"""Causality, accounting and conservative-fill checks for the offline harness."""
import asyncio
from decimal import Decimal
import numpy as np
import pandas as pd
import pytest

from backtest.public_history import coverage
from backtest.rfq_simulation import Surface, ModelTransport, MemoryJournal, SimLifecycle, model_price
from backtest.two_year_flyby import causal_iv, barrier_fill, Replay
from src.risk.competition import risk_view


def rule(minimum=".1", base=".5"):
    return dict(minimum_amount=minimum, amount_step=".001", tick_size=".01", maximum_amount="100000",
                taker_fee_rate=".0003", maker_fee_rate=".0001", base_fee=base, mark_price_fee_rate_cap=".125")


def test_iv_hour_is_only_visible_after_it_closes():
    iv = pd.DataFrame(dict(timestamp=[0, 3600, 7200], close=[50, 60, 90]))
    values = causal_iv(np.array([0, 3599, 3600, 7199, 7200, 10800, 18001]), iv)
    assert np.isnan(values[:2]).all()
    assert values[2:6].tolist() == [.5, .5, .6, .9]
    assert np.isnan(values[-1])


def test_coverage_never_interpolates_missing_rows():
    view = coverage(pd.DataFrame(dict(timestamp=[0, 300, 900])), 0, 1200, 300)
    assert view["missing_rows"] == 1 and view["missing_first_20"] == [600]
    with pytest.raises(ValueError, match="duplicate"):
        coverage(pd.DataFrame(dict(timestamp=[0, 0])), 0, 600, 300)


@pytest.mark.parametrize("side", [1, -1])
def test_ambiguous_bar_is_stop_first(side):
    p = dict(side=side, entry=100, stop=.01, target=.02)
    price, reason = barrier_fill(p, dict(open=100, high=104, low=96), .001)
    assert reason == "stop_loss"
    assert price == pytest.approx(100 * (1 - side * .01) * (1 - side * .001))


def test_gap_stop_uses_worse_open_not_the_trigger():
    assert barrier_fill(dict(side=1, entry=100, stop=.01, target=.02),
                        dict(open=90, high=94, low=89), 0) == (90, "stop_gap")


def test_price_and_signed_delta_match_call_put_parity():
    call, cd = model_price(3000, 3000, 259200, 0, .6, "call")
    put, pd = model_price(3000, 3000, 259200, 0, .6, "put")
    assert call == pytest.approx(put)
    assert cd - pd == pytest.approx(1)


def test_venue_minimum_is_rejected_not_rounded_up():
    surface = Surface({"ETH-option": rule()})
    surface.now = 1800000000
    surface.spots, surface.ivs = {"ETH": 3000}, {"ETH": .6}
    risk = dict(risk_trade_budget=4, risk_scale=1)
    plan, reason = surface.plan("ETH", "call", surface.now, 800, risk, .9)
    assert plan is None and reason == "option_minimum_gross_exceeds_cap"


def test_finer_lots_never_remove_fixed_venue_fees():
    surface = Surface({"ETH-option": rule()}, finer_lots=True)
    surface.now = 1800000000
    surface.spots, surface.ivs = {"ETH": 3000}, {"ETH": .6}
    plan, reason = surface.plan("ETH", "call", surface.now, 800,
                                dict(risk_trade_budget=1, risk_scale=1), .9)
    assert plan is None and reason == "option_fixed_fees_exhaust_risk_budget"
    assert surface.fees("ETH").base == .5


def test_combined_is_one_800_account_and_drawdown_latches_survive_recovery():
    replay = Replay({}, {"ETH-option": rule()}, "combined-ETH", "base")
    assert replay.account["cash"] == 800 and replay.transport.account_state is replay.account
    replay.account["cash"] = 680
    replay.observe()
    assert replay.state["restricted"] and not replay.state["hard_stop"]
    replay.now += 300
    replay.account["cash"] = 600
    replay.observe()
    assert replay.state["hard_stop"]
    replay.now += 86400
    replay.account["cash"] = 800
    replay.observe()
    assert risk_view(replay.state, 800)["risk_mode"] == "hard_stop"


def test_modeled_atomic_fills_use_production_reducer_and_reconcile_lost_ack():
    surface = Surface({"ETH-option": rule(".01", ".01")})
    now = 1800000000
    surface.now = now
    surface.spots, surface.ivs = {"ETH": 3000}, {"ETH": .6}
    expiry = now + 259200
    surface.contracts = {"ETH-A": ("ETH", 3000, expiry, "call"), "ETH-B": ("ETH", 3200, expiry, "call")}
    bid_a, ask_a, _ = surface.quote("ETH-A")
    bid_b, ask_b, _ = surface.quote("ETH-B")
    debit = round((ask_a - bid_b) * .01, 8)
    fees = 2 * (surface.fees("ETH").charge(.01, ask_a, 3000) + surface.fees("ETH").charge(.01, bid_b, 3000))
    plan = dict(buy="ETH-A", sell="ETH-B", kind="call", underlying="ETH", amount=.01, expiry=expiry,
        debit=debit, max_loss=debit + fees + 1e-8, max_payoff=2., round_trip_fees=fees,
        valid_until=now + 5, fees_verified=True, delta_verified=True, buy_limit=ask_a, sell_limit=bid_b,
        net_delta_quote=10., net_cap_quote=160., gross_reference_quote=60., gross_cap_quote=240.,
        take_profit=.30, stop_loss=.18, max_hold_seconds=21600)
    account = {"cash": 800.}
    transport = ModelTransport(surface, account, faults=True)
    transport.now, transport.execute_count = now, 10
    lifecycle = SimLifecycle(transport, MemoryJournal(), 42)
    async def run():
        await lifecycle.step(plan=plan, budget=4, allow_entry=True, consume_entry=lambda a, t: True)
        with pytest.raises(TimeoutError):
            await lifecycle.step(plan=plan, budget=4, allow_entry=True)
        assert lifecycle.journal.state["phase"] == "settling" and len(transport.positions) == 2
        await lifecycle.step(plan=plan, budget=4, allow_entry=True)
        assert lifecycle.journal.state["phase"] == "open" and transport.execute_count == 11
        assert account["cash"] == pytest.approx(800 - debit - fees / 2)
        assert transport.lost_acks == 1
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["call", "put"])
@pytest.mark.parametrize("winning", [True, False])
def test_modeled_call_put_pair_closes_and_cash_matches_realized_ledger(kind, winning):
    # Chosen low fixed fees and fine lots: execution fixture, NOT venue history.
    surface = Surface({"ETH-option": rule(".01", ".01")})
    now = 1800000000
    surface.now = now
    surface.spots, surface.ivs = {"ETH": 3000}, {"ETH": .6}
    expiry = now + 259200
    strike = 3200 if kind == "call" else 2800
    surface.contracts = {"ETH-A": ("ETH", 3000, expiry, kind), "ETH-B": ("ETH", strike, expiry, kind)}
    ask, bid = surface.quote("ETH-A")[1], surface.quote("ETH-B")[0]
    debit = float((Decimal(str(ask)) - Decimal(str(bid))) * Decimal(".01"))
    plan = dict(buy="ETH-A", sell="ETH-B", kind=kind, underlying="ETH", amount=.01, expiry=expiry,
        debit=debit, max_loss=debit + .20000001, max_payoff=2., round_trip_fees=.2,
        valid_until=now + 5, fees_verified=True, delta_verified=True, buy_limit=ask, sell_limit=bid,
        net_delta_quote=10., net_cap_quote=160., gross_reference_quote=60., gross_cap_quote=240.,
        take_profit=.30, stop_loss=.18, max_hold_seconds=21600)
    account = {"cash": 800.}
    transport = ModelTransport(surface, account)
    transport.now = now
    lifecycle = SimLifecycle(transport, MemoryJournal(), 42)
    async def run():
        for _ in range(3):
            await lifecycle.step(plan=plan, budget=4, allow_entry=True, consume_entry=lambda a, t: True)
        assert lifecycle.journal.state["phase"] == "open" and len(transport.positions) == 2
        direction = (1 if kind == "call" else -1) * (1 if winning else -1)
        surface.spots["ETH"] *= 1 + direction * .03
        transport.now += 300
        surface.now = transport.now
        for _ in range(3):
            await lifecycle.step(budget=4)
        assert lifecycle.journal.state["phase"] == "idle" and not transport.positions
        trade = lifecycle.journal.state["trades"][-1]
        pnl = float(trade["net_pnl"])
        assert (pnl > 0) == winning
        assert account["cash"] == pytest.approx(800 + pnl)
        assert transport.execute_count == 2
        assert transport.fees_total == pytest.approx(float(trade["fees"]))
    asyncio.run(run())
