from dataclasses import replace

import pandas as pd
import pytest

from agents.condor_agent import decide
from backtest.compare_policies import COST_PROFILES, exit_on_signal, simulate, split_ranges
from src.signal.flyby import feature_frame
from tests.test_flyby_policy import candles, snapshot


def test_hold_hysteresis_does_not_confuse_new_entry_with_hold():
    s = snapshot()
    s["volume_ratio"] = .5
    d = decide(s)
    assert not d.signal
    assert exit_on_signal("baseline", d, s, 1) == "signal_invalid"
    assert exit_on_signal("hold_hysteresis", d, s, 1) is None
    assert exit_on_signal("hold_hysteresis", replace(d, halt=True), s, 1) == "halt"
    assert exit_on_signal("hold_hysteresis", replace(d, signal=-1), s, 1) == "opposite_confirmation"
    s["trend_z"] = -.5
    assert exit_on_signal("hold_hysteresis", d, s, 1) == "trend_reversal"


@pytest.mark.parametrize("interval", ["5m", "15m", "1h", "4h"])
def test_chronological_embargo_has_disjoint_splits(interval):
    splits, embargo = split_ranges(5400, interval)
    assert embargo >= 102
    assert splits["validation"][0] - splits["train"][1] == embargo
    assert splits["test"][0] - splits["validation"][1] == embargo


@pytest.mark.parametrize("policy", ["baseline", "hold_hysteresis", "competition_baseline", "competition_scalp"])
def test_next_open_replay_is_causal_costed_and_deterministic(policy):
    frame = candles(400)
    frame["timestamp"] = pd.Series(range(400)) * 300
    horizon = 1800 if policy == "competition_scalp" else 14400
    features = feature_frame(frame, "5m", trend_horizon_seconds=horizon)
    a, trace = simulate(frame, features, "5m", policy, 150, 300, True)
    b, again = simulate(frame, features, "5m", policy, 150, 300, True)
    assert a == b and trace == again
    frame.loc[300:, "close"] *= 2
    c, altered = simulate(frame, feature_frame(frame, "5m", trend_horizon_seconds=horizon), "5m", policy, 150, 300, True)
    assert a == c and trace == altered
    assert a["fees_quote"] >= 0 and a["funding_quote"] <= 0
    assert trace[-1]["equity"] == pytest.approx(800 * (1 + a["net_return_pct"] / 100))


def test_realistic_fees_include_per_order_base_and_reconcile():
    frame = candles(400); frame["timestamp"] = pd.Series(range(400)) * 300
    features = feature_frame(frame, "5m")
    s, trace = simulate(frame, features, "5m", "baseline", 150, 300, True,
                        costs=COST_PROFILES["public_taker"])
    assert s["fees_quote"] == pytest.approx(s["volume_quote"] * .0003 + 2 * s["trades"] * .01)
    assert trace[-1]["equity"] == pytest.approx(800 * (1 + s["net_return_pct"] / 100))


def test_venue_minimum_scenario_blocks_unaffordable_entries():
    frame = candles(400); frame["timestamp"] = pd.Series(range(400)) * 300
    rule = dict(minimum_amount="10000", amount_step=".001", tick_size=".01", maximum_amount="10000")
    s, _ = simulate(frame, feature_frame(frame, "5m"), "5m", "baseline", 150, 300,
                    costs=COST_PROFILES["public_taker"], venue_rule=rule)
    assert s["trades"] == 0 and s["fees_quote"] == 0 and s["net_return_pct"] == 0
