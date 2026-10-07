"""Two durable atomic-spread slots sharing one authenticated account.

No independent option legs. Background inventory is accepted only when an
operator-owned perp executor or another durable spread slot proves ownership.
Disjoint option instruments keep settlement/recovery unambiguous.
"""
import asyncio
import os
from pathlib import Path

from src.accounting.derive_margin import decimal
from src.execution.options_rfq import OptionsRFQ, RFQJournal, expected_positions


def inventories(state):
    phase = state["phase"]
    if phase == "idle":
        return [{}]
    if phase == "halted" or "plan" not in state:
        raise ValueError("rfq_slot_requires_reconciliation")
    owned = expected_positions(state["plan"])
    if phase == "settling":
        return [{}, owned]
    return [owned] if phase == "open" or state.get("intent") == "exit" else [{}]


class SlotTransport:
    def __init__(self, book, index):
        self.book, self.index = book, index
        self.api_generation = getattr(book.transport, "api_generation", "offline")

    def __getattr__(self, name):
        return getattr(self.book.transport, name)

    async def account(self):
        account = await self.book.transport.account()
        if not self.book.background_owned(account):
            raise ValueError("rfq_unowned_background_inventory")
        options, perps = {}, []
        for row in account["positions"]:
            name, amount = row["instrument_name"], decimal(row["amount"])
            if not amount:
                continue
            if row["instrument_type"] == "perp":
                perps.append(row)
            elif row["instrument_type"] == "option" and name not in options:
                options[name] = row
            else:
                raise ValueError("rfq_unrecognized_background_position")
        background = set()
        for i, slot in enumerate(self.book.slots):
            if i == self.index:
                continue
            state = slot.journal.state
            names = set(expected_positions(state["plan"])) if state["phase"] != "idle" and "plan" in state else set()
            actual = {n: decimal(options[n]["amount"]) for n in names if n in options}
            if actual not in inventories(state):
                raise ValueError("rfq_background_spread_inventory_mismatch")
            background.update(names)
        own = self.book.slots[self.index].journal.state
        owned_names = set(expected_positions(own["plan"])) if own["phase"] != "idle" and "plan" in own else set()
        if set(options) - background - owned_names:
            raise ValueError("rfq_unowned_option_inventory")
        other_rows = [r for n, r in options.items() if n in background]
        net = sum((decimal(r["amount"]) * decimal(r["delta"]) * decimal(r["index_price"])
                   for r in other_rows + perps if self.book.underlying is None or
                   r["instrument_name"].startswith(self.book.underlying + "-")), decimal(0))
        gross = sum((abs(decimal(r["amount"])) * decimal(r["index_price"]) for r in other_rows + perps), decimal(0))
        # Keep full option Greeks for account-wide exposure exits, but expose
        # only this slot's exact legs to the single-spread lifecycle reconciler.
        return {**account, "positions": [r for n, r in options.items() if n not in background],
                "open_orders": [], "_rfq_other_net": net, "_rfq_other_gross": gross,
                "_option_exposure_positions": list(options.values()) + perps}


class OptionsBook:
    def __init__(self, transport, path, binding, owner, subaccount, *, max_spreads=2,
                 background_owned=None, exposure_profile="baseline", underlying=None):
        if isinstance(max_spreads, bool) or max_spreads not in (1, 2):
            raise ValueError("rfq_spread_slot_limit")
        self.transport, self.max_spreads = transport, max_spreads
        self.background_owned = background_owned or (lambda a: not a["open_orders"] and
            not any(decimal(r["amount"]) for r in a["positions"] if r["instrument_type"] != "option"))
        self._lock = asyncio.Lock()
        self.last_error = None
        self.exposure_profile, self.underlying = exposure_profile, underlying
        path = Path(path)
        self.lock_journal = RFQJournal(path.with_name(path.stem + "-book.json"), binding, owner)
        self.slots = []
        for i in range(max_spreads):
            slot_path = path if i == 0 else path.with_name(path.stem + f"-slot-{i + 1}" + path.suffix)
            journal = RFQJournal(slot_path, binding, owner)
            self.slots.append(OptionsRFQ(SlotTransport(self, i), journal, subaccount,
                exposure_profile=exposure_profile, underlying=underlying))

    @property
    def busy(self):
        return any(s.busy for s in self.slots)

    @property
    def blocked(self):
        return any(s.journal.state["phase"] not in ("idle", "open") or
            (s.busy and getattr(self.transport, "api_generation", None) == "v3" and
             s.journal.state.get("api_generation") != "v3") for s in self.slots)

    @property
    def open_count(self):
        return sum(s.busy for s in self.slots)

    @property
    def planning_exclusions(self):
        return {n for s in self.slots if s.busy and "plan" in s.journal.state and
                (s.journal.state["phase"] == "open" or s.journal.state.get("intent") == "exit")
                for n in expected_positions(s.journal.state["plan"])}

    def owns(self, actual):
        possibilities = [{}]
        try:
            for slot in self.slots:
                next_values = []
                for prior in possibilities:
                    for candidate in inventories(slot.journal.state):
                        if set(prior) & set(candidate):
                            return False
                        next_values.append({**prior, **candidate})
                possibilities = next_values
        except (ValueError, KeyError):
            return False
        return actual in possibilities

    def status(self):
        rows = [s.status() for s in self.slots]
        return {"adapter": "derive_v3_atomic_rfq_book", "live_options_enabled": True,
                "live_execution_verified": False, "max_spreads": self.max_spreads,
                "open_spreads": self.open_count, "entry_blocked": self.blocked,
                "phase": "idle" if not self.busy else "active", "slots": rows,
                "reason": self.last_error,
                "orders_submitted": sum(r["orders_submitted"] for r in rows),
                "closed_spreads": sum(r["closed_spreads"] for r in rows)}

    async def tick(self, now, *, plan=None, budget=0, allow_entry=False, force_exit=False,
                   consume_entry=None, entry_budget=None, exit_required=None):
        async with self._lock:
            try:
                fd = self.lock_journal.lock()
            except BlockingIOError:
                self.last_error = "rfq_book_owned_by_other_process"
                return
            try:
                for slot in self.slots:
                    slot.journal.state = slot.journal.load()
                occupied = {n for s in self.slots if s.busy and "plan" in s.journal.state
                            for n in expected_positions(s.journal.state["plan"])}
                eligible = (allow_entry and not self.blocked and plan is not None and
                            not occupied.intersection((plan["buy"], plan["sell"])))
                candidate = next((s for s in self.slots if not s.busy), None) if eligible else None
                # Reserve at most one entry per tick; never resubmit a pending
                # intent. Existing slots still receive protective exit service.
                ordered = ([candidate] if candidate else []) + [s for s in self.slots if s is not candidate and s.busy]
                for slot in ordered:
                    own_plan = slot.journal.state.get("plan", plan)
                    forced = force_exit(own_plan) if callable(force_exit) else force_exit
                    await slot.tick(now, plan=plan, budget=budget,
                        allow_entry=allow_entry if slot.busy else slot is candidate,
                        force_exit=forced, consume_entry=consume_entry, entry_budget=entry_budget,
                        exit_required=exit_required)
                self.last_error = None
            except (ValueError, KeyError, TypeError, OSError) as exc:
                self.last_error = "rfq_book_unavailable:" + type(exc).__name__
            finally:
                os.close(fd)
