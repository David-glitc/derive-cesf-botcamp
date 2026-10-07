"""Durable, account-bound atomic spread lifecycle. Never place separate legs.

Every write intent is fsynced before its HTTP request. Unknown requests are
reconciled read-only, never blindly resent. Settled quotes AND exact authenticated
positions are required; unmatched positions halt instead of opening another leg.
"""
import asyncio
import fcntl
import json
import os
from pathlib import Path
import tempfile
import uuid
from decimal import Decimal

from src.accounting.derive_margin import decimal
from src.execution.derive_rfq import leg_identity, quote_cost
from src.risk.exposure import BASELINE_EXPOSURE, exposure_limits

ACTIVE = {"requesting", "quoting_entry", "quoting_exit", "settling", "cancelling", "open", "halted"}


class RFQJournal:
    def __init__(self, path, binding, owner):
        self.path, self.binding, self.owner = Path(path), binding, owner
        self.lock_path = self.path.with_suffix(".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self.load()

    def load(self):
        if self.path.is_symlink():
            raise ValueError("rfq_journal_symlink")
        if not self.path.exists():
            return {"kind": "flyby_rfq_journal", "schema": 1, "binding": self.binding,
                    "owner": self.owner, "phase": "idle", "nonce": 0, "executions_submitted": 0, "trades": []}
        with self.path.open() as stream:
            raw = stream.read(512001)
        state = json.loads(raw)
        if (len(raw) > 512000 or state.get("kind") != "flyby_rfq_journal" or state.get("schema") != 1
                or state.get("binding") != self.binding or state.get("owner") != self.owner
                or state.get("phase") not in ACTIVE | {"idle"}):
            raise ValueError("rfq_journal_identity_or_state_mismatch")
        return state

    def save(self, **changes):
        state = {**self.state, **changes}
        data = json.dumps(state, sort_keys=True, allow_nan=False)
        if len(data) > 512000:
            raise ValueError("rfq_journal_capacity_requires_archive")
        # Never store signatures or session keys, even in an execution intent.
        with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, prefix=self.path.name + ".",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            temporary.replace(self.path)
            fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)
        self.state = state

    def lock(self):
        if self.lock_path.is_symlink():
            raise ValueError("rfq_lock_symlink")
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(fd)
            raise
        return fd


def position_amounts(account):
    rows = account["positions"]
    if not isinstance(rows, list) or account["open_orders"]:
        raise ValueError("rfq_account_orders_or_snapshot_invalid")
    result = {}
    for row in rows:
        name, amount = row["instrument_name"], decimal(row["amount"])
        if name in result:
            raise ValueError("rfq_duplicate_account_position")
        if amount:
            if row["instrument_type"] != "option":
                raise ValueError("rfq_foreign_position")
            result[name] = amount
    return result


def expected_positions(plan):
    amount = decimal(plan["amount"])
    return {plan["buy"]: amount, plan["sell"]: -amount}


def exposure_requires_exit(account, plan, *, exposure_profile=BASELINE_EXPOSURE):
    """Authenticated current Greeks, not entry Greeks or assumed hedge fills."""
    try:
        limits = exposure_limits(exposure_profile, plan.get("underlying"))
        net, gross = Decimal(0), Decimal(0)
        for row in account.get("_option_exposure_positions", account["positions"]):
            amount = decimal(row["amount"])
            if not amount:
                continue
            delta, index = decimal(row["delta"]), decimal(row["index_price"])
            if not -1 <= delta <= 1 or index <= 0:
                return True
            if row["instrument_name"].startswith(plan["underlying"] + "-"):
                net += amount * delta * index
            gross += abs(amount) * index
        return (abs(net) > min(decimal(plan["net_cap_quote"]), decimal(account["equity"]) * decimal(limits["option_net"]))
                or gross > min(decimal(plan["gross_cap_quote"]), decimal(account["equity"]) * decimal(limits["option_gross"])))
    except (ValueError, KeyError, TypeError):
        return True  # unknown risk is not zero; only an owned paired exit is allowed


class OptionsRFQ:
    def __init__(self, transport, journal, subaccount, *, exposure_profile=BASELINE_EXPOSURE, underlying=None):
        exposure_limits(exposure_profile, underlying)
        self.exposure_profile, self.underlying = exposure_profile, underlying
        self.transport, self.journal, self.subaccount = transport, journal, subaccount
        self._lock = asyncio.Lock()
        self.last_error = None

    @property
    def busy(self):
        return self.journal.state["phase"] != "idle"

    def status(self):
        s = self.journal.state
        return {"adapter": "derive_v3_atomic_rfq", "live_options_enabled": True,
                "exposure_profile": self.exposure_profile,
                "live_execution_verified": False, "phase": s["phase"], "reason": s.get("reason") or self.last_error,
                "orders_submitted": s.get("execution_acknowledgements", 0),
                "execution_attempts": s["executions_submitted"],
                "submission_count_incomplete": s["phase"] == "settling" and not s.get("execution_acknowledged"),
                "rfq_id": s.get("rfq_id"),
                "entry_debit": s.get("entry_debit"), "entry_fee": s.get("entry_fee"),
                "realized_pnl": s.get("realized_pnl"), "closed_spreads": len(s["trades"])}

    def halt(self, reason):
        self.journal.save(phase="halted", reason=reason)

    def _clock(self, now):
        return max(now, float(decimal(self.transport.clock())))

    async def tick(self, now, *, plan=None, budget=0, allow_entry=False, force_exit=False,
                   consume_entry=None, entry_budget=None, exit_required=None):
        async with self._lock:
            try:
                fd = self.journal.lock()
            except BlockingIOError:
                self.last_error = "rfq_owned_by_other_process"
                return
            try:
                self.journal.state = self.journal.load()
                if (getattr(self.transport, "api_generation", None) == "v3" and self.busy
                        and self.journal.state.get("api_generation") != "v3"):
                    self.last_error = "legacy_rfq_requires_operator_reconciliation"
                    return  # preserve the old intent; never re-sign/replay it on V3
                await self._tick(now, plan, decimal(budget), allow_entry, force_exit, consume_entry, entry_budget, exit_required)
                self.last_error = None
            except Exception as exc:
                # Do not erase the pre-request intent or replay a write. Avoid
                # exception text: third-party errors may contain signed payloads.
                # Cancellation/SystemExit still propagate (BaseException).
                self.last_error = "rfq_unavailable:" + type(exc).__name__
            finally:
                os.close(fd)

    async def _tick(self, now, plan, budget, allow_entry, force_exit, consume_entry, entry_budget, exit_required):
        s = self.journal.state
        if s["phase"] == "halted":
            return
        account = await self.transport.account()
        now = self._clock(now)
        if not 0 <= now - account["observed_at"] <= 5:
            raise ValueError("rfq_stale_account")
        positions = position_amounts(account)
        if exit_required is not None:
            risk_exit = exit_required(account, now)
            force_exit = bool(force_exit or risk_exit)
        phase = s["phase"]
        if phase == "idle":
            if positions:
                return self.halt("rfq_unowned_positions")
            if not allow_entry or plan is None:
                return
            if entry_budget is not None:
                budget = min(budget, decimal(entry_budget(account, now)))
            self._validate_plan(plan, now, budget, account)
            fee_bound = decimal(plan["round_trip_fees"]) + Decimal(".000002")
            if decimal(plan["debit"]) + fee_bound > budget:
                return
            if consume_entry is None or not consume_entry(account, now):
                return
            self.journal.save(plan=plan, budget=str(budget), entry_debit=None, entry_fee=None,
                              api_generation=getattr(self.transport, "api_generation", "offline"),
                              opened_at=None, force_exit=False, realized_pnl=None)
            return await self._request(now, "entry")
        if phase == "settling":
            return await self._settle(now, account, positions)
        # Before execution the only acceptable inventory is exactly the owned
        # spread (exits) or flat (entries). No partial-fill repair by legging in.
        target = expected_positions(s["plan"]) if s.get("intent") == "exit" or phase == "open" else {}
        if positions != target:
            return self.halt("rfq_unmatched_or_foreign_inventory")
        if positions:
            force_exit = bool(force_exit or exposure_requires_exit(account, s["plan"], exposure_profile=self.exposure_profile))
        if phase == "open":
            if now < s.get("next_quote_at", 0):
                return
            self.journal.save(force_exit=bool(force_exit))
            return await self._request(now, "exit")
        if phase == "requesting":
            # Lost send acknowledgement: match unique account-owned label.
            rows = await self.transport.rfqs(from_timestamp=int(s["requested_at"] * 1000))
            matches = [r for r in rows if r.get("label") == s["label"]]
            if len(matches) != 1:
                return  # absence is NOT proof the write failed; no resubmission
            return self._accept_rfq(matches[0], now)
        rows = await self.transport.rfqs(rfq_id=s["rfq_id"])
        if len(rows) != 1:
            raise ValueError("rfq_ambiguous_status")
        rfq = rows[0]
        self._check_rfq(rfq)
        if rfq["status"] == "filled":
            return self.halt("rfq_filled_without_owned_execution_intent")
        if rfq["status"] in ("cancelled", "expired"):
            return self.journal.save(phase="open" if s["intent"] == "exit" else "idle",
                                     next_quote_at=now + 30, reason="rfq_no_execution")
        if rfq["status"] != "open":
            raise ValueError("rfq_unknown_status")
        if phase == "cancelling":
            return  # uncertain cancel acknowledgement: read-only until terminal
        force_exit = bool(force_exit or s.get("force_exit") or
                          (s["intent"] == "exit" and (now - s["opened_at"] >= s["plan"]["max_hold_seconds"]
                           or now >= s["plan"]["expiry"] - 21600)))
        if s["intent"] == "exit" and force_exit and not s.get("force_exit"):
            self.journal.save(force_exit=True)
        if s["intent"] == "entry" and (not allow_entry or now > s["plan"]["valid_until"]):
            return await self._cancel()
        offers = await self.transport.offers(s["rfq_id"])
        now = self._clock(now)
        qualified = []
        for quote in offers:
            try:
                cost = self._check_offer(quote, now)
            except (ValueError, KeyError, TypeError):
                continue
            qualified.append((cost, str(quote["quote_id"]), quote))
        if qualified:
            cost, _, quote = min(qualified, key=lambda item: item[:2])
            if s["intent"] == "exit":
                debit, fee = decimal(s["entry_debit"]), decimal(s["entry_fee"])
                pnl_fraction = (-cost - decimal(s["max_fee"]) - debit - fee) / (debit + fee)
                if not (force_exit or pnl_fraction >= decimal(s["plan"]["take_profit"])
                        or pnl_fraction <= -decimal(s["plan"]["stop_loss"])):
                    if now - s["requested_at"] >= 20:
                        return await self._cancel()
                    return
            generator = getattr(self.transport, "next_nonce", None)
            nonce = max(generator() if generator else int(decimal(now) * 10 ** 9), int(s["nonce"]) + 1)
            # Bad native metadata/hash/signature fails BEFORE any write intent:
            # no private request exists to recover. Signed payload stays in memory.
            prepared = await self.transport.prepare(quote, s["max_fee"], nonce, s["label"], now, s["plan"], s["intent"])
            # Refresh account after metadata/signing, immediately before submission.
            refreshed = await self.transport.account()
            now = self._clock(now)
            try:
                self._check_offer(quote, now)
            except (ValueError, KeyError, TypeError):
                return await self._cancel()  # quote expired during preparation/account refresh
            if now >= float(rfq["valid_until"]) / 1000:
                return await self._cancel()
            if (position_amounts(refreshed) != target or not 0 <= now - refreshed["observed_at"] <= 5
                    or decimal(refreshed["available"]) < max(Decimal(0), cost + decimal(s["max_fee"]))):
                return self.halt("rfq_pre_execute_account_changed")
            if s["intent"] == "entry":
                if entry_budget is not None:
                    budget = min(budget, decimal(entry_budget(refreshed, now)))
                if now > s["plan"]["valid_until"] or cost + 2 * decimal(s["max_fee"]) > budget:
                    return await self._cancel()
            self.journal.save(phase="settling", quote_id=quote["quote_id"], nonce=nonce,
                execution_legs=quote["legs"], execution_cost=str(cost), execution_hash=quote["legs_hash"],
                submitted_at=now, executions_submitted=s["executions_submitted"] + 1, execution_acknowledged=False)
            # Result is only an acknowledgement; reconciliation below is the
            # sole path to recording an opened or closed position.
            ack = await self.transport.submit(prepared)
            if (ack.get("subaccount_id") == self.subaccount
                    and ack.get("rfq_id") == s["rfq_id"] and str(ack.get("nonce")) == str(nonce)):
                self._acknowledge()
            return
        if now >= min(s["requested_at"] + 20, float(rfq["valid_until"]) / 1000):
            await self._cancel()

    def _validate_plan(self, p, now, budget, account):
        limits = exposure_limits(self.exposure_profile, p.get("underlying"))
        if self.underlying is not None and p.get("underlying") != self.underlying:
            raise ValueError("rfq_exposure_underlying_mismatch")
        if (p.get("fees_verified") is not True or p.get("delta_verified") is not True
                or p["underlying"] not in ("ETH", "BTC") or p["kind"] not in ("call", "put")
                or not now <= p["valid_until"] <= now + 5 or not 172800 <= p["expiry"] - now <= 432000
                or p["buy"] == p["sell"]):
            raise ValueError("rfq_unverified_plan")
        nums = {k: decimal(p[k]) for k in ("amount", "debit", "max_loss", "max_payoff", "round_trip_fees",
                "buy_limit", "sell_limit", "net_delta_quote", "net_cap_quote", "gross_reference_quote", "gross_cap_quote")}
        if not 0 <= decimal(p.get("committed_gross_quote", 0)) <= nums["gross_reference_quote"]:
            raise ValueError("rfq_invalid_committed_gross")
        if (abs(nums["net_delta_quote"] + decimal(account.get("_rfq_other_net", 0))) >
                min(nums["net_cap_quote"], decimal(account["equity"]) * decimal(limits["option_net"])) or
                nums["gross_reference_quote"] - decimal(p.get("committed_gross_quote", 0)) + decimal(account.get("_rfq_other_gross", 0)) >
                min(nums["gross_cap_quote"], decimal(account["equity"]) * decimal(limits["option_gross"]))):
            raise ValueError("rfq_plan_exceeds_configured_exposure")
        # A declared plan cap isn't permission to widen configured current-equity
        # limits. Legacy baseline journals retain their narrower stored caps.
        if (abs(nums["net_delta_quote"]) > min(nums["net_cap_quote"], decimal(account["equity"]) * decimal(limits["option_net"]))
                or nums["gross_reference_quote"] > min(nums["gross_cap_quote"], decimal(account["equity"]) * decimal(limits["option_gross"]))):
            raise ValueError("rfq_plan_exceeds_configured_exposure")
        if (min(nums["amount"], nums["debit"], nums["round_trip_fees"], nums["sell_limit"]) <= 0
                or nums["buy_limit"] <= nums["sell_limit"]
                or nums["max_loss"] < nums["debit"] + nums["round_trip_fees"]
                or nums["max_payoff"] < nums["max_loss"] * Decimal("2.5")
                or nums["max_loss"] > min(budget, decimal(account["available"]))
                or abs(nums["net_delta_quote"]) > nums["net_cap_quote"]
                or nums["gross_reference_quote"] > nums["gross_cap_quote"]):
            raise ValueError("rfq_plan_exceeds_caps")
        if (decimal(p["take_profit"]) != Decimal(".30") or decimal(p["stop_loss"]) != Decimal(".18")
                or p["max_hold_seconds"] != 21600):
            raise ValueError("rfq_unreviewed_exit_policy")

    async def _request(self, now, intent):
        p = self.journal.state["plan"]
        sides = ("buy", "sell") if intent == "entry" else ("sell", "buy")
        legs = sorted([{"instrument_name": p["buy"], "direction": sides[0], "amount": str(p["amount"])},
                       {"instrument_name": p["sell"], "direction": sides[1], "amount": str(p["amount"])}],
                      key=lambda row: row["instrument_name"])
        # Bound total fee per atomic transaction. A low cap causes a venue
        # rejection, never permission to exceed the risk budget.
        max_fee = decimal(p["round_trip_fees"]) / 2 + Decimal(".000001")
        max_cost = decimal(p["debit"]) if intent == "entry" else Decimal(0)
        label = "flyby-rfq-" + uuid.uuid4().hex
        self.journal.save(phase="requesting", intent=intent, legs=legs, label=label, rfq_id=None,
                          requested_at=now, max_fee=str(max_fee), max_cost=str(max_cost), reason=None)
        row = await self.transport.send(legs, label, max_cost)
        self._accept_rfq(row, now)

    def _check_rfq(self, row):
        s = self.journal.state
        if (row["subaccount_id"] != self.subaccount or row["label"] != s["label"]
                or leg_identity(row["legs"]) != leg_identity(s["legs"])
                or (s.get("rfq_id") is not None and row["rfq_id"] != s["rfq_id"])):
            raise ValueError("rfq_identity_mismatch")

    def _accept_rfq(self, row, now):
        self._check_rfq(row)
        if not isinstance(row["rfq_id"], str) or not row["rfq_id"]:
            raise ValueError("rfq_missing_id")
        self.journal.save(rfq_id=row["rfq_id"], phase="quoting_" + self.journal.state["intent"])

    def _check_offer(self, quote, now):
        s = self.journal.state
        if (quote["rfq_id"] != s["rfq_id"] or quote["status"] != "open" or quote["direction"] != "sell"
                or quote["liquidity_role"] != "maker" or quote.get("tx_status") is not None
                or quote.get("batch_status") is not None
                or decimal(quote.get("fill_pct", "1")) != 1
                or not 0 <= now - quote["creation_timestamp"] / 1000 <= 5
                or not 0 <= now - quote["last_update_timestamp"] / 1000 <= 5
                or leg_identity(quote["legs"]) != leg_identity(s["legs"])
                or not isinstance(quote["legs_hash"], str) or len(quote["legs_hash"]) != 66):
            raise ValueError("rfq_not_full_fresh_matching_quote")
        cost = quote_cost(quote["legs"])
        if cost > decimal(s["max_cost"]):
            raise ValueError("rfq_quote_exceeds_cost_bound")
        if s["intent"] == "entry":
            p = s["plan"]
            prices = {r["instrument_name"]: decimal(r["price"]) for r in quote["legs"]}
            if (cost <= 0 or prices[p["buy"]] > decimal(p["buy_limit"])
                    or prices[p["sell"]] < decimal(p["sell_limit"])):
                raise ValueError("rfq_entry_price_outside_plan")
        return cost

    async def _cancel(self):
        self.journal.save(phase="cancelling")
        await self.transport.cancel(self.journal.state["rfq_id"])

    def _acknowledge(self):
        s = self.journal.state
        if not s.get("execution_acknowledged"):
            self.journal.save(execution_acknowledged=True,
                              execution_acknowledgements=s.get("execution_acknowledgements", 0) + 1)

    async def _settle(self, now, account, positions):
        s = self.journal.state
        rows = await self.transport.executions(s["rfq_id"], s["quote_id"])
        matches = [r for r in rows if r.get("liquidity_role") == "taker" and str(r.get("nonce")) == str(s["nonce"])]
        if len(matches) != 1:
            return  # no acknowledgement is NOT proof of rejection; never replay
        row = matches[0]
        if (row["subaccount_id"] != self.subaccount or row["rfq_id"] != s["rfq_id"]
                or row["direction"] != "buy"
                or leg_identity(row["legs"]) != leg_identity(s["execution_legs"])
                or quote_cost(row["legs"]) != decimal(s["execution_cost"])
                or row["legs_hash"].lower() != s["execution_hash"].lower()
                or decimal(row.get("fill_pct", "1")) != 1):
            return self.halt("rfq_execution_identity_mismatch")
        self._acknowledge()
        target = expected_positions(s["plan"]) if s["intent"] == "entry" else {}
        before = {} if s["intent"] == "entry" else expected_positions(s["plan"])
        v3 = getattr(self.transport, "api_generation", None) == "v3"
        batch = row.get("batch_status")
        if v3 and (batch not in (None, "Batching", "Executing", "Da", "Proving", "Settling", "Settled")):
            return self.halt("rfq_batch_failed_requires_operator_reconciliation")
        if (not v3 and row["tx_status"] in ("requested", "pending", None)) or (v3 and positions != target):
            if positions not in (target, before):
                self.halt("rfq_unmatched_inventory_during_settlement")
            return
        if not v3 and row["tx_status"] in ("reverted", "ignored", "timed_out"):
            # A terminal backend status alone is insufficient to assume flat.
            return self.halt("rfq_execution_failed_requires_operator_reconciliation")
        if ((not v3 and (row["tx_status"] != "settled" or not row["tx_hash"])) or row["status"] != "filled"
                or account["observed_at"] < row["last_update_timestamp"] / 1000):
            return
        if positions != target:
            return self.halt("rfq_settled_inventory_mismatch")
        fee = decimal(row["fee"])
        if not 0 <= fee <= decimal(s["max_fee"]):
            return self.halt("rfq_settled_fee_exceeds_bound")
        # V3 execution is atomic at the sequencer; L1 batches settle later.
        # Filled taker quote + fresh exact inventory permits protective exits
        # without pretending an absent L1 transaction has already settled.
        reference = row.get("tx_hash") or "rfq:" + row["quote_id"] + ":" + str(row["nonce"])
        if s["intent"] == "entry":
            self.journal.save(phase="open", entry_debit=s["execution_cost"], entry_fee=str(fee),
                              opened_at=row["last_update_timestamp"] / 1000, next_quote_at=now,
                              entry_tx=reference, batch_status=batch,
                              settlement_confirmation="matched_inventory" if v3 else "chain_settled")
        else:
            pnl = -decimal(s["execution_cost"]) - fee - decimal(s["entry_debit"]) - decimal(s["entry_fee"])
            trade = {"opened_at": s["opened_at"], "closed_at": row["last_update_timestamp"] / 1000,
                     "entry_tx": s["entry_tx"], "exit_tx": reference, "net_pnl": str(pnl),
                     "batch_status": batch, "l1_settled": batch == "Settled" if v3 else True,
                     "entry_debit": s["entry_debit"], "exit_credit": str(-decimal(s["execution_cost"])),
                     "fees": str(fee + decimal(s["entry_fee"])), "buy": s["plan"]["buy"],
                     "sell": s["plan"]["sell"], "amount": str(s["plan"]["amount"])}
            self.journal.save(phase="idle", realized_pnl=str(pnl), trades=s["trades"] + [trade], reason="paired_exit_settled")


def journal_busy(path, binding):
    """Read-only inter-controller entry gate, including after a restart."""
    path = Path(path)
    if not path.exists():
        return False
    if path.is_symlink():
        return True
    try:
        with path.open() as stream:
            raw = stream.read(512001)
        s = json.loads(raw)
        return (len(raw) > 512000 or s.get("kind") != "flyby_rfq_journal" or s.get("binding") != binding
                or s.get("phase") != "idle")
    except (OSError, ValueError, TypeError, AttributeError):
        return True
