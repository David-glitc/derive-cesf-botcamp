"""Real lifecycle code with a scripted transport. No exchange orders or secrets."""
import asyncio
from copy import deepcopy
from decimal import Decimal

import pytest

from src.accounting.derive_margin import margin_snapshot
from src.execution.derive_rfq import fixed, leg_identity, quote_cost, validate_instruments
from src.execution.options_rfq import OptionsRFQ, RFQJournal, expected_positions, journal_busy
from tests.test_submission_hardening import account_result

NOW = 1800000000.0


def plan():
    return dict(buy="ETH-A", sell="ETH-B", kind="call", underlying="ETH", amount=.01,
                expiry=NOW + 259200, debit=2., max_loss=2.1, max_payoff=10., round_trip_fees=.1,
                valid_until=NOW + 5, fees_verified=True, delta_verified=True, buy_limit=300., sell_limit=100.,
                net_delta_quote=10., net_cap_quote=160., gross_reference_quote=60., gross_cap_quote=240.,
                take_profit=.30, stop_loss=.18, max_hold_seconds=21600)


class Transport:
    def __init__(self):
        self.now = NOW
        self.positions = {}
        self.rfq_rows = []
        self.quote_rows = []
        self.offer_rows = []
        self.writes = []
        self.fail_send = False
        self.fail_execute = False
        self.available = 800

    def clock(self):
        return self.now

    async def account(self):
        return dict(observed_at=self.now, equity=Decimal(800), available=Decimal(str(self.available)), open_orders=[],
                    positions=[dict(instrument_name=k, instrument_type="option", amount=str(v),
                                    delta=".5" if v > 0 else ".25", index_price="3000") for k, v in self.positions.items()])

    async def send(self, legs, label, max_cost):
        row = dict(subaccount_id=42, legs=deepcopy(legs), label=label, rfq_id="rfq-" + str(len(self.rfq_rows)),
                   status="open", valid_until=(self.now + 30) * 1000)
        self.rfq_rows.append(row)
        self.writes.append("send")
        if self.fail_send:
            raise asyncio.TimeoutError()
        return row

    async def rfqs(self, **filters):
        return [r for r in self.rfq_rows if "rfq_id" not in filters or r["rfq_id"] == filters["rfq_id"]]

    async def offers(self, rfq_id):
        return self.offer_rows

    async def cancel(self, rfq_id):
        self.writes.append("cancel")
        next(r for r in self.rfq_rows if r["rfq_id"] == rfq_id)["status"] = "cancelled"
        return "ok"

    async def execute(self, quote, max_fee, nonce, label, now, plan, intent):
        self.writes.append("execute")
        self.quote_rows.append({**deepcopy(quote), "direction": "buy", "liquidity_role": "taker", "nonce": nonce,
            "subaccount_id": 42, "fee": ".04", "status": "filled", "tx_status": "pending", "tx_hash": "tx-1"})
        if self.fail_execute:
            raise asyncio.TimeoutError()
        return self.quote_rows[-1]

    async def prepare(self, quote, max_fee, nonce, label, now, plan, intent):
        return deepcopy(quote), max_fee, nonce, label, now, deepcopy(plan), intent

    async def submit(self, prepared):
        return await self.execute(*prepared)

    async def executions(self, rfq_id, quote_id):
        return [r for r in self.quote_rows if r["rfq_id"] == rfq_id and r["quote_id"] == quote_id]

    def offer(self, lifecycle, buy_price="300", sell_price="100"):
        s = lifecycle.journal.state
        prices = {s["plan"]["buy"]: buy_price, s["plan"]["sell"]: sell_price}
        row = dict(rfq_id=s["rfq_id"], quote_id="quote-" + str(len(self.quote_rows)), status="open",
                   direction="sell", liquidity_role="maker", subaccount_id=999, tx_status=None,
                   creation_timestamp=self.now * 1000, last_update_timestamp=self.now * 1000,
                   legs_hash="0x" + "ab" * 32,
                   legs=[{**r, "price": prices[r["instrument_name"]]} for r in s["legs"]])
        self.offer_rows = [row]
        return row

    def settle(self, lifecycle):
        s = lifecycle.journal.state
        self.positions = expected_positions(s["plan"]) if s["intent"] == "entry" else {}
        row = self.quote_rows[-1]
        row.update(tx_status="settled", last_update_timestamp=self.now * 1000)
        next(r for r in self.rfq_rows if r["rfq_id"] == row["rfq_id"])["status"] = "filled"


def setup(tmp_path):
    t = Transport()
    j = RFQJournal(tmp_path / "rfq.json", "account-42", "owner")
    return t, OptionsRFQ(t, j, 42)


def tick(lifecycle, transport, **kwargs):
    asyncio.run(lifecycle.tick(transport.now, plan=plan(), budget=4, allow_entry=True, consume_entry=lambda account, now: True, **kwargs))


def open_spread(t, c):
    tick(c, t)
    assert c.journal.state["phase"] == "quoting_entry"
    t.offer(c)
    tick(c, t)
    assert c.journal.state["phase"] == "settling"
    t.settle(c)
    tick(c, t)
    assert c.journal.state["phase"] == "open"


def test_atomic_entry_paired_profit_exit_and_actual_fee_ledger(tmp_path):
    t, c = setup(tmp_path)
    open_spread(t, c)
    assert c.journal.state["entry_debit"] == "2.00"
    tick(c, t)  # request reversing BOTH legs; still no assumed exit fill
    assert c.journal.state["intent"] == "exit"
    assert leg_identity(c.journal.state["legs"]) == {"ETH-A": ("sell", Decimal(".01")), "ETH-B": ("buy", Decimal(".01"))}
    t.offer(c, "400", "100")  # $3 credit, >30% after fees
    tick(c, t)
    assert c.journal.state["phase"] == "settling" and t.positions
    t.settle(c)
    tick(c, t)
    assert c.journal.state["phase"] == "idle" and not t.positions
    assert Decimal(c.journal.state["realized_pnl"]) == Decimal(".92")
    assert c.status()["closed_spreads"] == 1
    assert t.writes == ["send", "execute", "send", "execute"]
    assert c.status()["live_execution_verified"] is False


@pytest.mark.parametrize("reason,credit", [("profit", "400"), ("loss", "250"), ("time", "310"), ("kill", "310")])
def test_exit_triggers_are_net_of_both_actual_entry_and_reserved_exit_fees(tmp_path, reason, credit):
    t, c = setup(tmp_path)
    open_spread(t, c)
    if reason == "time":
        t.now += 21601
    tick(c, t, force_exit=reason == "kill")
    t.offer(c, credit, "100")
    tick(c, t, force_exit=reason == "kill")
    assert c.journal.state["phase"] == "settling"


def test_no_exit_trigger_means_no_execution(tmp_path):
    t, c = setup(tmp_path)
    open_spread(t, c)
    tick(c, t)
    t.offer(c, "310", "100")
    tick(c, t)
    assert c.journal.state["phase"] == "quoting_exit"
    assert t.writes.count("execute") == 1


@pytest.mark.parametrize("change", [
    {"fill_pct": ".5"}, {"direction": "buy"}, {"liquidity_role": "taker"}, {"rfq_id": "foreign"},
    {"creation_timestamp": (NOW-6)*1000}, {"creation_timestamp": (NOW+1)*1000},
    {"last_update_timestamp": (NOW-6)*1000}, {"tx_status": "pending"}, {"legs_hash": "bad"},
])
def test_non_matching_or_stale_or_partial_quotes_never_execute(tmp_path, change):
    t, c = setup(tmp_path)
    tick(c, t)
    t.offer(c).update(change)
    tick(c, t)
    assert "execute" not in t.writes


@pytest.mark.parametrize("field,value", [("amount", ".005"), ("direction", "sell"), ("instrument_name", "BTC-C"), ("price", "301")])
def test_modified_leg_cannot_execute(tmp_path, field, value):
    t, c = setup(tmp_path)
    tick(c, t)
    quote = t.offer(c)
    quote["legs"][0][field] = value
    tick(c, t)
    assert "execute" not in t.writes


def test_lost_send_ack_restart_discovers_label_without_resending(tmp_path):
    t, c = setup(tmp_path)
    t.fail_send = True
    tick(c, t)
    assert c.journal.state["phase"] == "requesting"
    restarted = OptionsRFQ(t, RFQJournal(c.journal.path, "account-42", "owner"), 42)
    tick(restarted, t)
    assert restarted.journal.state["phase"] == "quoting_entry" and t.writes == ["send"]


def test_absent_send_or_execution_ack_does_not_cause_a_retry(tmp_path):
    t, c = setup(tmp_path)
    t.fail_send = True
    tick(c, t)
    t.rfq_rows = []
    for _ in range(10):
        tick(c, t)
    assert t.writes == ["send"] and c.busy


def test_unexpected_transport_failure_does_not_break_tick_or_replay_intent(tmp_path):
    t, c = setup(tmp_path)
    original = t.send
    async def send(*args):
        await original(*args)
        raise RuntimeError("fixture third-party failure")
    t.send = send
    tick(c, t)
    assert c.status()["reason"] == "rfq_unavailable:RuntimeError"
    tick(c, t)
    assert c.journal.state["phase"] == "quoting_entry" and t.writes == ["send"]


def test_failed_quote_preparation_does_not_create_a_phantom_execution_intent(tmp_path):
    t, c = setup(tmp_path)
    tick(c, t)
    t.offer(c)
    original = t.prepare
    async def bad_quote(*args):
        raise ValueError("rfq_legs_hash_mismatch")
    t.prepare = bad_quote
    tick(c, t)
    assert c.journal.state["phase"] == "quoting_entry"
    assert c.status()["execution_attempts"] == 0 and "execute" not in t.writes
    t.prepare = original
    tick(c, t)
    assert c.journal.state["phase"] == "settling" and t.writes == ["send", "execute"]


def test_clock_advancing_during_account_requests_does_not_break_freshness_or_consumption(tmp_path):
    t, c = setup(tmp_path)
    original = t.account
    async def advancing_account():
        t.now += 1
        return await original()
    t.account = advancing_account
    consumed = []
    asyncio.run(c.tick(NOW, plan=plan(), budget=4, allow_entry=True,
                      consume_entry=lambda account, now: consumed.append((account["observed_at"], now)) or True))
    assert consumed == [(NOW+1, NOW+1)]
    t.offer(c)
    tick(c, t)
    assert c.journal.state["phase"] == "settling" and "execute" in t.writes


def test_slow_preparation_rejects_quote_before_submission_not_after(tmp_path):
    t, c = setup(tmp_path)
    tick(c, t)
    t.offer(c)
    original = t.prepare
    async def slow_prepare(*args):
        t.now += 6
        return await original(*args)
    t.prepare = slow_prepare
    tick(c, t)
    assert c.journal.state["phase"] == "cancelling" and "execute" not in t.writes
    assert c.status()["execution_attempts"] == 0


def test_lost_execute_ack_restart_reconciles_settled_pair_once(tmp_path):
    t, c = setup(tmp_path)
    tick(c, t)
    t.offer(c)
    t.fail_execute = True
    tick(c, t)
    assert c.journal.state["phase"] == "settling"
    restarted = OptionsRFQ(t, RFQJournal(c.journal.path, "account-42", "owner"), 42)
    tick(restarted, t)
    assert restarted.journal.state["phase"] == "settling"
    t.settle(restarted)
    tick(restarted, t)
    assert restarted.journal.state["phase"] == "open"
    assert t.writes.count("execute") == 1


def test_partial_inventory_never_repaired_by_placing_a_naked_leg(tmp_path):
    t, c = setup(tmp_path)
    tick(c, t)
    t.offer(c)
    tick(c, t)
    t.quote_rows[-1]["tx_status"] = "pending"
    t.positions = {"ETH-A": Decimal(".01")}
    tick(c, t)
    assert c.journal.state["phase"] == "halted"
    assert t.writes == ["send", "execute"]


@pytest.mark.parametrize("status", ["reverted", "ignored", "timed_out"])
def test_terminal_failed_execution_requires_operator_reconciliation(tmp_path, status):
    t, c = setup(tmp_path)
    tick(c, t)
    t.offer(c)
    tick(c, t)
    t.quote_rows[-1]["tx_status"] = status
    tick(c, t)
    assert c.journal.state["phase"] == "halted"


@pytest.mark.parametrize("mutation", ["foreign", "partial", "overfee", "wrongnonce", "oldaccount"])
def test_settlement_must_match_owned_transaction_and_inventory(tmp_path, mutation):
    t, c = setup(tmp_path)
    tick(c, t)
    t.offer(c)
    tick(c, t)
    t.settle(c)
    if mutation == "foreign": t.quote_rows[-1]["subaccount_id"] = 99
    if mutation == "partial": t.positions["ETH-A"] = Decimal(".005")
    if mutation == "overfee": t.quote_rows[-1]["fee"] = "1"
    if mutation == "wrongnonce": t.quote_rows[-1]["nonce"] += 1
    if mutation == "oldaccount": t.quote_rows[-1]["last_update_timestamp"] += 1000
    tick(c, t)
    assert c.journal.state["phase"] != "open"


def test_restricted_or_hard_stop_budget_recheck_cancels_entry(tmp_path):
    t, c = setup(tmp_path)
    tick(c, t)
    t.offer(c)
    tick(c, t, entry_budget=lambda account, now: .5)
    assert c.journal.state["phase"] == "cancelling" and "execute" not in t.writes
    tick(c, t)
    assert c.journal.state["phase"] == "idle"


def test_hard_stop_on_fresh_equity_forces_a_paired_exit(tmp_path):
    t, c = setup(tmp_path)
    open_spread(t, c)
    tick(c, t, exit_required=lambda account, now: True)
    t.offer(c, "310", "100")
    tick(c, t)
    assert c.journal.state["phase"] == "settling"


@pytest.mark.parametrize("mutation", ["missing_delta", "high_index", "invalid_delta"])
def test_live_delta_or_gross_cap_or_unknown_greeks_force_only_a_paired_close(tmp_path, mutation):
    t, c = setup(tmp_path)
    open_spread(t, c)
    original = t.account
    async def account():
        result = await original()
        if mutation == "missing_delta": result["positions"][0].pop("delta")
        if mutation == "high_index":
            for row in result["positions"]: row["index_price"] = "20000"
        if mutation == "invalid_delta": result["positions"][0]["delta"] = "2"
        return result
    t.account = account
    tick(c, t)
    t.offer(c, "310", "100")
    tick(c, t)
    assert c.journal.state["phase"] == "settling" and t.writes.count("execute") == 2


def test_journal_account_owner_and_lock_are_enforced(tmp_path):
    t, c = setup(tmp_path)
    tick(c, t)
    assert journal_busy(c.journal.path, "account-42")
    for binding, owner in [("other-account", "owner"), ("account-42", "other-owner")]:
        with pytest.raises(ValueError): RFQJournal(c.journal.path, binding, owner)
    fd = c.journal.lock()
    try:
        tick(c, t)
        assert c.last_error == "rfq_owned_by_other_process" and t.writes == ["send"]
    finally:
        import os
        os.close(fd)


def test_corrupt_and_symlink_journal_fail_closed(tmp_path):
    t, c = setup(tmp_path)
    c.journal.path.write_text("not-json")
    assert journal_busy(c.journal.path, "account-42")
    with pytest.raises(ValueError): RFQJournal(c.journal.path, "account-42", "owner")
    linked = tmp_path / "linked.json"
    linked.symlink_to(c.journal.path)
    with pytest.raises(ValueError): RFQJournal(linked, "account-42", "owner")


def test_options_margin_support_is_opt_in_and_not_cash_only_fallback():
    raw = account_result()
    raw["positions"] = [dict(instrument_type="option", instrument_name="ETH-A", amount=".01")]
    with pytest.raises(ValueError): margin_snapshot(raw, 7, NOW)
    state = margin_snapshot(raw, 7, NOW, allow_options=True)
    assert state["positions"] == raw["positions"] and state["available"] == 600


@pytest.mark.parametrize("value", ["NaN", "Infinity", ".0000000000000000001", True])
def test_exact_evm_precision_rejects_truncation(value):
    with pytest.raises(ValueError): fixed(value)


def instrument(name, strike):
    return dict(instrument_name=name, instrument_type="option", base_currency="ETH", quote_currency="USDC",
                is_active=True, amount_step=".01", tick_size="1", minimum_amount=".01", maximum_amount="10",
                base_asset_address="0x" + "12" * 20, base_asset_sub_id="1" if strike == 3000 else "2",
                option_details=dict(option_type="C", strike=str(strike), expiry=NOW+259200, index="ETH/USD"))


def test_native_instrument_contract_and_lot_rules():
    legs = [dict(instrument_name="ETH-A", direction="buy", amount=".01", price="300"),
            dict(instrument_name="ETH-B", direction="sell", amount=".01", price="100")]
    inst = {"ETH-A": instrument("ETH-A", 3000), "ETH-B": instrument("ETH-B", 4000)}
    validate_instruments(inst, legs, NOW)
    assert quote_cost(legs) == Decimal(2)
    for change in (dict(instrument_type="perp"), dict(is_active=False), dict(base_currency="SOL"),
                   dict(amount_step=".03"), dict(tick_size="7"), dict(minimum_amount=".02")):
        broken = deepcopy(inst)
        broken["ETH-A"].update(change)
        with pytest.raises(ValueError): validate_instruments(broken, legs, NOW)


def test_50_hour_virtual_lifecycle_with_600_spreads_restarts_and_lost_acks(tmp_path):
    """Fault-injected lifecycle clock, NOT a live soak or market/P&L backtest."""
    import random
    rng = random.Random(917)
    t, c = setup(tmp_path)
    for cycle in range(600):
        t.now = NOW + cycle * 300
        p = {**plan(), "valid_until": t.now + 5, "expiry": t.now + 259200}
        def step():
            asyncio.run(c.tick(t.now, plan=p, budget=4, allow_entry=True, consume_entry=lambda account, now: True))
        t.fail_send = rng.random() < .15
        t.fail_execute = rng.random() < .15
        step()
        if c.journal.state["phase"] == "requesting": step()
        assert c.journal.state["phase"] == "quoting_entry"
        quote = t.offer(c)
        if rng.random() < .2:
            quote["fill_pct"] = ".5"
            step()
            assert c.journal.state["phase"] == "quoting_entry"
            quote["fill_pct"] = "1"
        step()
        assert c.journal.state["phase"] == "settling"
        if cycle % 11 == 0:
            c = OptionsRFQ(t, RFQJournal(c.journal.path, "account-42", "owner"), 42)
        t.settle(c)
        step()
        assert c.journal.state["phase"] == "open"
        step()
        if c.journal.state["phase"] == "requesting": step()
        assert c.journal.state["phase"] == "quoting_exit"
        t.offer(c, "400" if rng.random() < .5 else "230", "100")
        step()
        assert c.journal.state["phase"] == "settling"
        t.settle(c)
        step()
        assert c.journal.state["phase"] == "idle" and not t.positions
    assert t.now + 300 - NOW == 50 * 3600
    assert len(c.journal.state["trades"]) == 600
    assert t.writes.count("execute") == 1200
    assert c.status()["orders_submitted"] == 1200
    assert c.status()["execution_attempts"] == 1200
    assert c.status()["live_execution_verified"] is False
