"""Controlled checks for offline policy isolation; fixtures are not alpha proof."""
import asyncio
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from agents.condor_agent import AgentDecision
from backtest.simple_edge import (FIXED, SimpleReplay, range_decision, range_features,
                                  slice_window, trade_statistics)
from backtest.two_year_flyby import barrier_fill


def row(**changes):
    return dict(valid=True, mean=103., z=-2.1, efficiency=.2, atr_pct=.004, price=98., **changes)


def test_symmetric_reversion_and_fixed_risk_weights_not_probabilities():
    assert range_decision(row(), "normal").signal == 1
    short = row(); short.update(z=2.1, mean=97., price=102.)
    assert range_decision(short, "normal").signal == -1
    assert range_decision(row(), "normal").confidence == FIXED.risk_weight
    assert range_decision(row(), "restricted").signal == 0
    restricted = row(); restricted["z"] = -3.1
    assert range_decision(restricted, "restricted").confidence == .85


@pytest.mark.parametrize("fault", ["invalid", "nan", "zero_price", "trend", "extreme_atr", "bad_mode", "hard_stop"])
def test_bad_inputs_and_risk_modes_block_entries(fault):
    r, mode = row(), "normal"
    if fault == "invalid": r["valid"] = False
    if fault == "nan": r["z"] = float("nan")
    if fault == "zero_price": r["price"] = 0
    if fault == "trend": r["efficiency"] = .9
    if fault == "extreme_atr": r["atr_pct"] = .1
    if fault == "bad_mode": mode = "unknown"
    if fault == "hard_stop": mode = "hard_stop"
    assert range_decision(r, mode).signal == 0


def fixture():
    start = 1759276800
    candles = [dict(timestamp=start + i * 300, open=100., close=100., high=100.5, low=99.5, volume=10.)
               for i in range(140)]
    feature = dict(valid=True, atr_pct=.004, trend_z=2., efficiency=.8, volume_ratio=2.)
    d = AgentDecision("fixture", signal=1, confidence=.9)
    history = {a: dict(candles=deepcopy(candles), features=[deepcopy(feature) for _ in candles],
               decisions={m: [d] * len(candles) for m in ("normal", "restricted")},
               iv=np.full(len(candles), .6)) for a in ("ETH", "BTC", "SOL")}
    rule = dict(minimum_amount=".1", amount_step=".001", tick_size=".01", maximum_amount="10000",
                taker_fee_rate=".0003", maker_fee_rate=".0001", base_fee=".01")
    return history, {a + "-perp": deepcopy(rule) for a in history}


def ready(variant="range_sol", scenario="base"):
    history, rules = fixture()
    replay = SimpleReplay(history, rules, scenario, variant)
    replay.range_rows = [row() for _ in history["SOL"]["candles"]]
    replay.index = 101
    replay.now = history["SOL"]["candles"][101]["timestamp"]
    replay.surface.spots = {a: 100. for a in history}
    return replay


def test_future_data_cannot_change_closed_features():
    h, _ = fixture()
    candles = h["SOL"]["candles"]
    for i, c in enumerate(candles):
        c.update(open=100 + np.sin(i), close=100 + np.sin(i), high=102., low=98.)
    before = pd.DataFrame(range_features(candles))
    changed = deepcopy(candles)
    for c in changed[125:]: c.update(open=200., close=200., high=202., low=198.)
    after = pd.DataFrame(range_features(changed))
    pd.testing.assert_frame_equal(before.iloc[:125], after.iloc[:125])


def test_aligned_slice_and_missing_or_wrong_market_bar_rejected():
    h, _ = fixture()
    begin = h["ETH"]["candles"][110]["timestamp"]
    end = h["ETH"]["candles"][-1]["timestamp"] + 300
    local = slice_window(h, begin, end)
    assert local["ETH"]["candles"][101]["timestamp"] == begin
    h["SOL"]["candles"][120]["timestamp"] += 1
    with pytest.raises(ValueError, match="unaligned"): slice_window(h, begin, end)


def test_scope_cap_costs_hold_and_owned_exit_independent_of_new_entry():
    replay = ready()
    risk = replay.observe()
    assert not replay.entry_perp("ETH", risk)
    assert replay.entry_perp("SOL", risk)
    assert replay.perp["amount"] * replay.perp["entry"] <= 160
    assert replay.perp["hold"] == 1800 and replay.perp["frozen_mean"] == 103
    replay.range_rows[100]["z"] = 0
    assert replay.decision("SOL").signal == 1  # Not an entry-filter-based close.
    replay.surface.spots["SOL"] = 103.1
    replay.close_perp(103.1, "signal_invalid", replay.now + 300)
    assert replay.trades[-1]["reason"] == "mean_reversion"
    assert replay.account["cash"] - 800 == pytest.approx(replay.trades[-1]["net_pnl"])
    assert replay.perp_turnover == pytest.approx(sum(e["notional"] for e in replay.fill_events))


def test_insufficient_mean_distance_stale_signal_and_minimum_lot_block():
    replay = ready()
    replay.range_rows[100]["mean"] = 100.1
    assert not replay.entry_perp("SOL", replay.observe())
    assert replay.blocks["SOL:mean_inside_original_target"] == 1
    replay.range_rows[100]["mean"] = 103
    replay.now += 1
    assert not replay.entry_perp("SOL", replay.observe())
    # Do not rewind a persisted risk clock when testing a separate minimum gate.
    replay = ready()
    replay.rules["SOL-perp"]["minimum_amount"] = "1000"
    assert not replay.entry_perp("SOL", replay.observe())
    assert replay.account["cash"] == 800 and replay.fill_events == []


def test_fee_hurdle_and_hard_stop_remain_binding():
    replay = ready(scenario="stress")
    assert not replay.entry_perp("SOL", replay.observe())
    assert replay.blocks["SOL:cost_gate"] == 1
    replay = ready()
    replay.account["cash"] = 599
    risk = replay.observe()
    assert risk["risk_mode"] == "hard_stop"
    assert not replay.entry_perp("SOL", risk)


def test_restricted_latch_requires_stronger_entry_and_capped_risk():
    replay = ready()
    replay.account["cash"] = 679
    risk = replay.observe()
    assert risk["risk_mode"] == "restricted"
    assert not replay.entry_perp("SOL", risk)
    replay.range_rows[100]["z"] = -3.2
    assert replay.decision("SOL").signal == 1
    assert risk["risk_scale"] <= .25
    replay.account["cash"] = 800
    assert replay.observe()["risk_mode"] == "restricted"


def test_actual_barrier_loss_stays_enabled_and_costs_are_counted_once():
    replay = ready()
    assert replay.entry_perp("SOL", replay.observe())
    fill = barrier_fill(replay.perp, dict(open=100., high=110., low=90.), replay.scenario["perp_slip"])
    assert fill[1] == "stop_loss"
    replay.close_perp(*fill, replay.now + 300)
    stats = trade_statistics(replay.trades)
    assert stats["net_expectancy"] < 0
    assert replay.account["cash"] - 800 == pytest.approx(stats["net_expectancy"])
    assert stats["net_win_rate"] == 0


@pytest.mark.parametrize("variant", ["baseline_sol", "range_sol"])
def test_integrated_replay_has_one_owned_position_and_reconciled_ledger(variant):
    replay = ready(variant)
    for candle in replay.history["SOL"]["candles"]:
        candle.update(high=110., low=90.)
    result = asyncio.run(replay.run())
    assert result["trades"] > 0 and not result["residual_perp"]
    assert result["net_pnl"] == pytest.approx(sum(t["net_pnl"] for t in replay.trades))
    assert {t["asset"] for t in replay.trades} == {"SOL"}
    assert result["option_trades"] == 0


def test_zero_trades_are_unknown_expectancy_not_profitable():
    stats = trade_statistics([])
    assert stats["net_win_rate"] is None and stats["net_expectancy"] is None
    assert stats["profit_factor"] is None
    with pytest.raises(ValueError): ready("unreviewed")
