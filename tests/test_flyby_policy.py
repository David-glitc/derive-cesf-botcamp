from dataclasses import replace
from decimal import Decimal
import numpy as np
import pandas as pd
import pytest

from agents.condor_agent import decide, decide_active
from src.signal.flyby import feature_frame, INTERVAL_SECONDS
from src.risk.position_sizing import risk_size, depth_quote, cost_allows_entry
from src.options.spread_builder import OptionQuote, build_spread, spread_exit
from src.accounting.ledger import AccountingLedger
from src.accounting.reconciliation import reconcile


def snapshot(**overrides):
    return dict(price=3000, trend_z=1.9, efficiency=.8, volume_ratio=1.8, atr_pct=.004,
                stale_secs=0, daily_pnl_pct=0, peak_dd=0, valid=True, reconciled=True, ccy="ETH",
                previous_trend_z=1.8, previous_volume_ratio=1.8, previous_efficiency=.8, **overrides)


def candles(n=200):
    rng = np.random.default_rng(52)
    close = 3000 * np.exp(np.cumsum(rng.normal(.0003, .001, n)))
    opening = np.r_[close[0], close[:-1]]
    return pd.DataFrame(dict(open=opening, high=np.maximum(close, opening) * 1.001,
                             low=np.minimum(close, opening) * .999, close=close,
                             volume=rng.uniform(100, 250, n)))


@pytest.mark.parametrize("field", ["price", "trend_z", "efficiency", "volume_ratio", "atr_pct", "stale_secs", "daily_pnl_pct", "peak_dd",
                                   "previous_trend_z", "previous_volume_ratio", "previous_efficiency"])
@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), "bad"])
def test_policy_fails_closed_for_invalid_numeric_fields(field, bad):
    data = snapshot()
    data[field] = bad
    assert decide(data).halt


def test_same_agent_policy_routes_only_shadow_spreads():
    assert decide(snapshot()).signal == 1
    data = snapshot(option_iv_edge=.04)
    assert decide(data).option_direction == "call"
    data["trend_z"] = -1.9
    data["previous_trend_z"] = -1.8
    assert decide(data).option_direction == "put"
    assert decide(data).execution_venue == "spread-plan"
    data["volume_ratio"] = 0.7
    assert decide(data).signal == 0
    assert decide({}).halt


@pytest.mark.parametrize("active", [False, True])
def test_active_mode_never_loosens_loss_guards(active):
    for key, value in (("daily_pnl_pct", -.02), ("peak_dd", -.04)):
        data = snapshot()
        data[key] = value
        assert decide(data, active=active).halt


@pytest.mark.parametrize("interval", list(INTERVAL_SECONDS))
def test_features_are_causal_and_match_live_window(interval):
    frame = candles(400)
    full = feature_frame(frame, interval)
    pd.testing.assert_series_equal(full.iloc[250], feature_frame(frame.iloc[:251], interval).iloc[-1])
    pd.testing.assert_series_equal(full.iloc[250], feature_frame(frame.iloc[101:251], interval).iloc[-1])
    frame.loc[251:, "close"] *= 2
    pd.testing.assert_series_equal(full.iloc[250], feature_frame(frame, interval).iloc[250])


def test_corrupt_bar_poisons_window_instead_of_bridging_gap():
    frame = candles(400)
    frame.loc[200, "close"] = np.nan
    features = feature_frame(frame, "5m")
    assert not features.valid.iloc[200:301].any()
    assert features.valid.iloc[350]


def test_preset_scalp_features_are_causal_and_not_baseline_alias():
    frame = candles(400)
    candidate = feature_frame(frame, "5m", trend_horizon_seconds=1800)
    assert not candidate.trend_z.equals(feature_frame(frame, "5m").trend_z)
    pd.testing.assert_series_equal(candidate.iloc[250], feature_frame(frame.iloc[:251], "5m",
                                   trend_horizon_seconds=1800).iloc[-1])
    frame.loc[251:, "close"] *= 2
    pd.testing.assert_series_equal(candidate.iloc[250], feature_frame(frame, "5m",
                                   trend_horizon_seconds=1800).iloc[250])
    with pytest.raises(ValueError): feature_frame(frame, "5m", trend_horizon_seconds=60)


def test_size_subtracts_committed_and_never_multiplies_by_leverage():
    args = dict(equity=800, available=800, committed=0, confidence=.9, stop_pct=.004, gross_cap=240)
    assert risk_size(**args) == 160
    args["committed"] = 220
    assert risk_size(**args) == 20
    args["available"] = 10
    assert risk_size(**args) == 10
    args["equity"] = float("nan")
    assert risk_size(**args) == 0
    assert depth_quote(((3000, .01), (3001, .02)), .04) is None
    assert depth_quote(((3000, .01), (3001, .02)), .02).worst_price == 3001


def test_cost_confirmation_and_drawdown_mitigations():
    assert not cost_allows_entry(.005, .003)
    assert cost_allows_entry(.01, .002)
    data = snapshot()
    data["previous_trend_z"] = -1
    assert decide(data).reason == "confirmation_gate"
    args = dict(equity=800, available=800, committed=0, confidence=.9, stop_pct=.004, gross_cap=240)
    assert risk_size(**args, peak_dd=-.02) == 80
    assert risk_size(**args, peak_dd=-.04) == 0


def chain(kind="call"):
    strikes = (3000, 3100) if kind == "call" else (3000, 2900)
    return [OptionQuote(str(k), "ETH", kind, k, 3 * 86400, 1, .01, .01, 0,
                        ((bid, 10),), ((ask, 10),), delta)
            for k, bid, ask, delta in zip(strikes, (29, 9), (30, 10),
                                         (.4, .2) if kind == "call" else (-.4, -.2))]


@pytest.mark.parametrize("kind", ["call", "put"])
def test_defined_risk_depth_matched_spread_and_otm_profit(kind):
    plan = build_spread(chain(kind), kind=kind, underlying="ETH", now=0, debit_budget=8, confidence=.9)
    assert plan and plan.max_loss <= 8 and plan.max_profit == plan.max_payoff - plan.max_loss
    assert plan.signal_only and plan.reward_risk >= 1.5
    # No ITM predicate: executable bid/ask credit alone can realize profit.
    assert spread_exit(plan, plan.debit * 1.4, 60, 60) == "take_profit"
    assert spread_exit(plan, plan.debit * .7, 60, 60) == "stop_loss"
    assert spread_exit(plan, plan.debit, 21600, 60) == "time_limit"


@pytest.mark.parametrize("change", [dict(timestamp=-6), dict(expiry=86400), dict(multiplier=2),
                                   dict(step=.03), dict(bids=((31, 10),)), dict(asks=((30, .001),))])
def test_spread_rejects_incompatible_or_unexecutable_leg(change):
    quotes = chain()
    quotes[0] = replace(quotes[0], **change)
    assert build_spread(quotes, kind="call", underlying="ETH", now=0, debit_budget=8, confidence=.9) is None


def test_ledger_conflict_nonfinite_and_replay():
    ledger = AccountingLedger()
    fill = dict(trade_id="one", instrument="ETH-PERP", side="buy", amount=".1", price="3000", fee=".18")
    ledger.apply_fill(fill)
    assert not ledger.apply_fill(fill)
    with pytest.raises(ValueError):
        ledger.apply_fill({**fill, "price": "3100"})
    with pytest.raises(ValueError):
        ledger.apply_fill({**fill, "trade_id": "two", "amount": "NaN"})
    restored = AccountingLedger()
    state = ledger.export_state()
    restored.replay(state["fills"], state["funding_events"])
    assert restored.snapshot() == ledger.snapshot()
    assert not reconcile({}, {}).ok


def test_bad_deep_books_delta_and_tick_limits_fail_closed():
    quotes = chain()
    for change in (dict(asks=((30, 10), (29, 10))), dict(bids=((29, 10), (float("nan"), 10))),
                   dict(delta=-.4), dict(tick=float("nan"))):
        bad = [replace(quotes[0], **change), quotes[1]]
        assert build_spread(bad, kind="call", underlying="ETH", now=0, debit_budget=8, confidence=.9) is None
    quotes[0] = replace(quotes[0], tick=7)
    plan = build_spread(quotes, kind="call", underlying="ETH", now=0, debit_budget=8, confidence=.9)
    assert plan is None or plan.max_loss <= 8
