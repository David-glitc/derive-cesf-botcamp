from copy import deepcopy
from dataclasses import asdict, replace
import json

import pytest

from agents.condor_agent import options_context
from backtest.options_paper import smoke_rows
from backtest.delta_performance import run_cases, target_assessment
from src.options.delta import DeltaPolicy, account_policy, amount_limit, exposure, moneyness, delta_context
from src.options.paper import PaperOptions
from src.options.spread_builder import build_spread, spread_exit
from tests.test_flyby_policy import chain


@pytest.mark.parametrize("kind,strike,expected", [("call", 2900, "ITM"), ("call", 3000, "ATM"),
                         ("call", 3100, "OTM"), ("put", 2900, "OTM"), ("put", 3000, "ATM"), ("put", 3100, "ITM")])
def test_moneyness_is_strike_based(kind, strike, expected):
    assert moneyness(kind, strike, 3000) == expected


@pytest.mark.parametrize("field", ["spot", "net_cap_quote", "gross_cap_quote", "existing_units", "pending_buy_units",
                                  "pending_sell_units", "committed_gross_quote", "buy_target", "sell_target"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True])
def test_bad_policy_fails_closed(field, bad):
    params = account_policy(3000, 800).to_dict()
    params[field] = bad
    with pytest.raises((ValueError, ArithmeticError)):
        DeltaPolicy(**params)


@pytest.mark.parametrize("kind", ["call", "put"])
def test_signed_delta_and_partial_fill_bounds(kind):
    sign = 1 if kind == "call" else -1
    policy = account_policy(3000, 800)
    amount = amount_limit(policy, sign * .5, sign * .25, 1, .01)
    assert amount == .04
    for bq, sq in ((amount, amount), (amount, 0), (0, amount)):
        assert exposure(policy, sign * .5, sign * .25, bq, sq)["within_caps"]
    assert exposure(policy, sign * .5, sign * .25, amount, amount)["net_delta"] == pytest.approx(sign * .01)
    assert not exposure(policy, sign * .5, sign * .25, .05, .05)["within_caps"]


def test_pending_orders_cannot_be_credited_as_guaranteed_hedges():
    policy = account_policy(3000, 800, existing_units=.04, pending_sell_units=.04)
    # Sell order might never fill: capacity is .01, not .04.
    assert amount_limit(policy, .5, .25, 1, .01) == .02
    v = exposure(policy, .5, .25, .02, .02)
    assert v["portfolio_delta_low"] == .005 and v["portfolio_delta_high"] == .045
    assert amount_limit(replace(policy, pending_buy_units=.02), .5, .25, 1, .01) == 0


def test_cross_asset_policy_and_duplicate_instruments_are_rejected():
    kwargs = dict(kind="call", underlying="ETH", now=0, debit_budget=8, confidence=.9)
    assert build_spread(chain(), delta_policy=account_policy(3000, 800, underlying="BTC"), **kwargs) is None
    qs = chain()
    assert build_spread(qs + [replace(qs[0], strike=2990)], **kwargs) is None


@pytest.mark.parametrize("kind", ["call", "put"])
def test_plans_size_to_delta_and_gross_without_rounding_up(kind):
    policy = account_policy(3000, 800, net_fraction=.01)
    plan = build_spread(chain(kind), kind=kind, underlying="ETH", now=0, debit_budget=8,
                        confidence=.9, delta_policy=policy)
    assert plan is None  # Minimum .01 exceeds either-leg directional cap.
    policy = account_policy(3000, 800)
    plan = build_spread(chain(kind), kind=kind, underlying="ETH", now=0, debit_budget=8,
                        confidence=.9, delta_policy=policy)
    assert plan and plan.delta_verified and plan.amount == .04
    assert plan.gross_reference_quote <= 240 and abs(plan.net_delta_quote) <= 160
    assert plan.buy_moneyness == "ATM" and plan.sell_moneyness == "OTM"


def test_itm_and_otm_selection_are_explicit_not_a_delta_probability():
    quotes = chain()
    itm = [replace(quotes[0], strike=2900, delta=.65), replace(quotes[1], strike=3100, delta=.25)]
    policy = account_policy(3000, 800, buy_moneyness="ITM", buy_target=.65)
    assert build_spread(itm, kind="call", underlying="ETH", now=0, debit_budget=8, confidence=.9,
                        delta_policy=policy).buy_moneyness == "ITM"
    assert build_spread(itm, kind="call", underlying="ETH", now=0, debit_budget=8, confidence=.9,
                        delta_policy=replace(policy, buy_moneyness="OTM")) is None
    assert build_spread(quotes, kind="call", underlying="ETH", now=0, debit_budget=8, confidence=.9).delta_verified is False


def test_gross_exit_profit_is_not_net_profit():
    plan = build_spread(chain(), kind="call", underlying="ETH", now=0, debit_budget=8, confidence=.9)
    assert spread_exit(plan, plan.debit * 1.4, 60, 60) == "take_profit"
    assert spread_exit(plan, plan.debit * 1.4, 60, 60, entry_fees=2, exit_fees=2) != "take_profit"
    assert spread_exit(plan, plan.debit, 60, 60, exit_fees=float("nan")) == "unpriceable"


def test_condor_context_is_bounded_fresh_and_advisory():
    plan = build_spread(chain(), kind="call", underlying="ETH", now=0, debit_budget=8, confidence=.9,
                        delta_policy=account_policy(3000, 800))
    raw = {**plan.to_dict(), "api_secret": "SECRET", "buy": "x" * 100000}
    view = options_context({"spread_plan": raw, "risk_mode": "normal"}, 0)
    assert view["status"] == "fresh_shadow_plan" and not view["live_options"]
    assert not view["hedge_orders_enabled"] and "SECRET" not in json.dumps(view)
    assert len(json.dumps(view)) < 1200
    assert delta_context(raw, 6)["status"] == "stale_or_unverified"
    assert delta_context(raw, -1)["delta_verified"] is False
    assert not delta_context({"delta_verified": True, "valid_until": 5}, 0)["delta_verified"]


def test_high_fixed_fees_fixture_rejected_not_silently_discounted():
    engine = PaperOptions()
    engine.step(smoke_rows(base_fee=.5)[0])
    assert engine.position is None and engine.events[-1]["reason"] == "all_in_fee_budget"


def test_dynamic_delta_breach_closes_actual_filled_quantity():
    rows = smoke_rows()[:2]
    engine = PaperOptions()
    engine.step(rows[0])
    assert engine.position
    rows[1]["spot"] = 5000  # Gross reference notional breaches existing cap.
    engine.step(rows[1])
    close = [e for e in engine.events if e["type"] == "close_fill"][-1]
    assert close["reason"] == "delta_limit" and engine.halted and engine.position is None
    assert close["delta"]["gross_reference_quote"] > close["delta"]["gross_cap_quote"]


def test_invalid_greek_can_close_when_books_are_executable():
    rows = smoke_rows()[:2]
    engine = PaperOptions()
    engine.step(rows[0])
    rows[1]["chain"][0]["delta"] = -.4
    engine.step(rows[1])
    assert engine.position is None and engine.halted
    assert engine.events[-1]["reason"] == "invalid_delta"


def test_delta_drift_without_spot_movement_triggers_exit():
    rows = smoke_rows()[:2]
    engine = PaperOptions(delta_net_fraction=.02)
    engine.step(rows[0])
    assert engine.position
    rows[1]["chain"][0]["delta"] = .95
    engine.step(rows[1])
    assert engine.events[-1]["reason"] == "delta_limit"
    assert engine.events[-1]["delta"]["worst_delta_quote"] > engine.events[-1]["delta"]["net_cap_quote"]


def test_unpriceable_exposure_halts_without_fictitious_fill_and_restores():
    rows = smoke_rows()[:2]
    rows[1]["chain"] = []
    engine = PaperOptions()
    for row in rows:
        engine.step(row)
    assert engine.halted and engine.position and engine.summary()["equity"] is None
    restored = PaperOptions.restore(engine.export_state())
    assert restored.summary() == engine.summary()


def test_paper_uses_shared_competition_risk_not_old_four_percent_guard():
    engine = PaperOptions()
    engine.cash = 680
    row = smoke_rows()[0]
    engine.step(row)
    assert engine.summary()["risk_policy"]["risk_mode"] == "restricted"
    engine.cash = 600
    row = deepcopy(row)
    row["time"] += 1
    engine.step(row)
    assert engine.summary()["risk_policy"]["risk_mode"] == "hard_stop"
    assert engine.position is None


@pytest.mark.parametrize("seed", range(200))
def test_delta_lot_properties(seed):
    import random
    rng = random.Random(seed)
    policy = account_policy(rng.uniform(1000, 100000), 800, existing_units=rng.uniform(-.0001, .0001))
    b, s = rng.uniform(.35, .7), rng.uniform(.1, .3)
    amount = amount_limit(policy, b, s, 1, .0001)
    for bq, sq in ((amount, amount), (amount, 0), (0, amount)):
        assert exposure(policy, b, s, bq, sq)["within_caps"]


def test_target_report_does_not_claim_return_or_forecast_from_volume():
    report = target_assessment([dict(premium_volume_quote=50000, observed_hours=1, closed_matched_spreads=1)])
    assert report["volume_target_met"] and not report["return_target_supported"]
    assert report["competitor_return_forecast"] is None and not report["optimisation_floor_enforced"]


def test_public_case_runner_rejects_synthetic_data(tmp_path):
    path = tmp_path / "synthetic.jsonl"
    path.write_text(json.dumps(smoke_rows()[0]) + "\n")
    with pytest.raises(ValueError, match="not_synthetic"):
        run_cases([("ETH", path), ("BTC", path)], tmp_path / "output")
