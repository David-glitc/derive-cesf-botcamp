import asyncio
import copy

import numpy as np
import pandas as pd
import pytest

from agents.condor_agent import AgentDecision
from backtest.alpha_walkforward import AlphaReplay, LeanSurface, metrics, slice_history
from backtest.public_history import START
from backtest.rfq_simulation import Surface
from backtest.two_year_flyby import causal_iv
from src.signal.alpha_research import features, labels, fit, predict, entry_gate
from src.options.greeks_research import greeks, quote_diagnostic, lean_gate, YEAR
from src.options.pricing import black_price


@pytest.fixture
def frame():
    rng = np.random.default_rng(72)
    close = 100 * np.exp(np.cumsum(rng.normal(0, .001, 1200)))
    opened = np.r_[close[0], close[:-1]]
    return pd.DataFrame(dict(timestamp=np.arange(1200) * 300,
        open=opened, close=close, high=np.maximum(opened, close) * 1.002,
        low=np.minimum(opened, close) * .998, volume=rng.uniform(1, 100, 1200)))


def test_causal_features_and_fit_ignore_future_prices_and_iv(frame):
    iv = np.full(len(frame), .5)
    x = features(frame, iv)
    np.testing.assert_allclose(features(frame.iloc[:900], iv[:900]), x.iloc[:900], equal_nan=True)
    original = fit(frame, x, 900)
    changed = frame.copy()
    changed.loc[900:, ["open", "high", "low", "close"]] *= 3
    changed_iv = iv.copy(); changed_iv[900:] = 2
    assert original == fit(changed, features(changed, changed_iv), 900)
    assert original["max_label_time"] < original["evaluation_not_before"]


def test_labels_are_next_open_and_endpoint_is_purged(frame):
    y = labels(frame, 12)
    assert y[100] == pytest.approx(np.log(frame.open.iloc[113] / frame.open.iloc[101]))
    assert np.isnan(y[-13:]).all()


def test_future_prediction_rejected_and_model_not_live(frame):
    x = features(frame)
    m = fit(frame, x, 900)
    with pytest.raises(ValueError, match="boundary"):
        predict(m, x.iloc[899:], frame.timestamp.iloc[899:])
    bad = copy.deepcopy(m); bad["live_authorized"] = True
    with pytest.raises(ValueError): predict(bad, x.iloc[900:], frame.timestamp.iloc[900:])
    p, ood = predict(m, x.iloc[900:], frame.timestamp.iloc[900:])
    assert p.shape == ood.shape == (300,)


def test_degree_two_matches_sklearn_artifact(frame):
    sklearn = pytest.importorskip("sklearn")
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import PolynomialFeatures, StandardScaler
    x = features(frame)
    m = fit(frame, x, 900)
    y = labels(frame, 12)
    mask = (np.arange(len(frame)) + 13 < 900) & np.isfinite(y) & np.isfinite(x).all(axis=1)
    train = x.to_numpy()[mask]
    s = StandardScaler().fit(train)
    poly = PolynomialFeatures(2, include_bias=False).fit(s.transform(train))
    expanded = poly.transform(s.transform(train)); ps = StandardScaler().fit(expanded)
    reg = Ridge(alpha=10000., solver="cholesky").fit(ps.transform(expanded), y[mask])
    expected = reg.predict(ps.transform(poly.transform(s.transform(x.iloc[900:].to_numpy()))))
    actual, _ = predict(m, x.iloc[900:], frame.timestamp.iloc[900:])
    np.testing.assert_allclose(actual, expected, atol=1e-12)


def test_iv_missing_is_explicit_and_close_not_available_early(frame):
    iv = causal_iv(frame.timestamp.to_numpy(), pd.DataFrame(dict(timestamp=[0, 3600], close=[50, 80])))
    assert np.isnan(iv[:12]).all() and iv[12] == .5 and iv[24] == .8
    x = features(frame, np.full(len(frame), np.nan))
    assert x.iv_available.eq(0).all() and x.iv_level.eq(0).all()


def test_cost_gate_not_weakened_by_polynomial_or_restricted_mode():
    assert not entry_gate(.001, False, .001, 1, .0043)
    assert not entry_gate(.1, True, .001, 1, .0043)
    assert not entry_gate(.1, False, .001, -1, .0043)
    assert entry_gate(.016, False, .001, 1, .0043)
    assert not entry_gate(.016, False, .001, 1, .0043, True)


@pytest.mark.parametrize("kind", ["call", "put"])
def test_greeks_match_finite_differences_and_units(kind):
    f, k, t, df, iv = 3000., 3100., 3 / 365, .999, .6
    g = greeks(f, k, t, df, iv, kind)
    price = lambda F=f, T=t, IV=iv: black_price(F, k, T, df, IV, kind)
    h = .01
    assert g["delta_forward"] == pytest.approx((price(F=f+h)-price(F=f-h))/(2*h), rel=1e-6)
    assert g["gamma_forward"] == pytest.approx((price(F=f+h)-2*price()+price(F=f-h))/h**2, rel=1e-4)
    v = 1e-5
    assert g["vega_per_unit_iv"] == pytest.approx((price(IV=iv+v)-price(IV=iv-v))/(2*v), rel=1e-6)
    dt = 1 / YEAR
    assert g["theta_per_calendar_day_fixed_discount"] == pytest.approx((price(T=t-dt)-price(T=t+dt))/(2*dt*365), rel=1e-6)
    assert g["vega_per_vol_point"] == pytest.approx(g["vega_per_unit_iv"] / 100)


def test_lean_gate_keeps_four_dollar_budget_and_full_fees():
    assert not lean_gate(debit=1.1, fee_reserve=2.348, max_loss=3.448, budget=4,
                         expected_credit=4.59, theta_drag=.01)
    assert lean_gate(debit=1, fee_reserve=.5, max_loss=1.5, budget=4,
                     expected_credit=2, theta_drag=.2)
    assert not lean_gate(debit=1, fee_reserve=.5, max_loss=1.5, budget=4,
                         expected_credit=1.4, theta_drag=.2)
    assert not lean_gate(debit=1, fee_reserve=.5, max_loss=1.5, budget=4,
                         expected_credit=2, theta_drag=1.1)


def test_api_missing_greeks_are_not_manufactured():
    q = dict(instrument="ETH-X", expiry=3*86400, strike=3000, kind="call",
             pricing=dict(forward=3000, discount=1, iv=.6, delta=None, gamma=None))
    d = quote_diagnostic(q, 0)
    assert d["api_greeks"]["delta"] is None and d["model_greeks"] is not None
    assert not d["api_vega_theta_units_verified"] and not d["entry_authorized"]


def test_slice_keeps_signal_warmup_and_test_open():
    h = {a: dict(candles=list(range(1200)), features=list(range(1200)),
        decisions={"normal":list(range(1200)), "restricted":list(range(1200))}, iv=np.arange(1200))
        for a in ("ETH", "BTC", "SOL")}
    sliced = slice_history(h, 900)
    assert sliced["ETH"]["candles"][101] == 900
    assert sliced["ETH"]["features"][100] == 899


def test_forecast_metric_reports_zero_benchmark():
    m = metrics(np.array([.01, -.01]), np.array([.0, .0]), np.array([False, False]))
    assert m["relative_mse"] == 1 and m["correlation"] is None


@pytest.mark.parametrize("alpha_passes", [False, True])
def test_candidate_veto_and_real_replay_ledger_integrate(frame, alpha_passes):
    frame = frame.iloc[:160].copy(); frame.timestamp += START
    # Deliberate barrier touches exercise protective stops and cash accounting;
    # these are controlled fixtures, not historical performance observations.
    frame.high = np.maximum(frame.open, frame.close) * 1.05
    frame.low = np.minimum(frame.open, frame.close) * .95
    rows = frame.to_dict("records")
    feature_rows = [dict(atr_pct=.004) for _ in rows]
    history = {a: dict(candles=rows, features=feature_rows,
        decisions={mode: [AgentDecision("forced_fixture", signal=1, confidence=.9)] * len(rows)
                   for mode in ("normal", "restricted")}, iv=np.full(len(rows), .6))
               for a in ("ETH", "BTC", "SOL")}
    rule = dict(minimum_amount=".1", amount_step=".001", tick_size=".01", maximum_amount="100000",
                taker_fee_rate=".0003", maker_fee_rate=".0001", base_fee=".01", mark_price_fee_rate_cap=".125")
    rules = {a+"-perp":{**rule, "minimum_amount":"1000" if a != "SOL" else ".1"}
             for a in history}
    models = {a:dict(residual_rmse=.001, horizon=6) for a in history}
    forecasts = {a:(np.full(len(rows), .1 if alpha_passes else 0), np.zeros(len(rows), dtype=bool))
                 for a in history}
    replay = AlphaReplay(history, rules, "perps", "base", models, forecasts, 101)
    result = asyncio.run(replay.run())
    assert bool(result["trades"]) == alpha_passes
    assert not result["residual_perp"]
    assert result["net_pnl"] == pytest.approx(sum(t["net_pnl"] for t in replay.trades))
    assert all(t["amount"] * t["entry_price"] <= 160 + 1e-8 for t in replay.trades)
    if alpha_passes:
        assert "stop_loss" in result["exit_reasons"]


def test_lean_surface_wraps_construction_without_fee_waiver(monkeypatch):
    now = START + 101 * 300
    rule = dict(tick_size=".01")
    models = {"ETH":dict(horizon=6, residual_rmse=.001)}
    forecasts = {"ETH":(np.full(200, .1), np.zeros(200, dtype=bool))}
    surface = LeanSurface({"ETH-option":rule}, .02, models, forecasts, 100)
    surface.spots, surface.ivs = {"ETH":3000}, {"ETH":.6}
    surface.contracts = {"BUY":("ETH",3000,now+3*86400,"call"),
                         "SELL":("ETH",3100,now+3*86400,"call")}
    plan = dict(buy="BUY", sell="SELL", amount=.01, debit=.1, round_trip_fees=2.348, max_loss=2.448)
    monkeypatch.setattr(Surface,"plan",lambda *a, **kw:(plan,"qualified"))
    value, reason = surface.plan("ETH","call",now,800,dict(risk_trade_budget=4),.9)
    assert value is None and reason == "lean_fee_theta_or_net_edge_veto"
    assert plan["round_trip_fees"] == 2.348
    # A selected cheap-fee fixture can pass; the veto isn't hard-coded false.
    plan.update(round_trip_fees=.5, max_loss=.6)
    value, reason = surface.plan("ETH","call",now,800,dict(risk_trade_budget=4),.9)
    assert value == plan and reason == "qualified_lean_model_only"
