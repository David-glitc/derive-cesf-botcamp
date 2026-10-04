"""Regression evidence for offline construction and the known exit-fee blocker."""
import asyncio

import pytest

from backtest.options_execution_audit import construct, construction_sweep, lifecycle_case, quotes, run


def rule():
    # Representative captured standard fees/minimums; scripted prices/Greeks.
    return dict(minimum_amount=".1", amount_step=".01", tick_size=".1",
                taker_fee_rate=".0003", base_fee=".5", mark_price_fee_rate_cap=".125")


def test_thousand_constructions_have_no_invalid_acceptance_or_payoff_violation():
    counts, trace = construction_sweep(rule(), 1000)
    assert counts == dict(accepted=39, rejected=961, invariant_failures=0, invalid_input_acceptances=0)
    assert len(trace) == 1000 and {row["kind"] for row in trace} == {"call", "put"}


@pytest.mark.parametrize("kind", ["call", "put"])
@pytest.mark.parametrize("scenario", ["profit", "loss", "time", "hard_stop", "lost_ack"])
def test_costed_current_lot_fixture_reaches_paired_entry_and_reconciled_exit(kind, scenario):
    result = asyncio.run(lifecycle_case(rule(), kind, scenario))
    assert result["remaining_legs"] == 0 and result["actual_fixture_executions"] == 2
    assert result["final_phase"] == "idle"
    assert result["ending_cash"] == pytest.approx(800 + result["net_pnl"])
    assert result["net_pnl"] >= -4
    if scenario == "lost_ack": assert result["lost_acknowledgements"] == 1


@pytest.mark.parametrize("kind", ["call", "put"])
def test_known_exit_fee_rise_retains_paired_inventory_and_blocks_live_readiness(kind):
    result = asyncio.run(lifecycle_case(rule(), kind, "exit_fee_rise"))
    assert result["exit_fee_required"] == pytest.approx(1.198)
    assert result["exit_fee_cap"] == pytest.approx(1.174001)
    assert result["final_phase"] == "settling" and result["remaining_legs"] == 2
    assert result["actual_fixture_executions"] == 1 and result["intent_attempts"] == 2
    assert result["net_pnl"] is None
    assert result["economic_or_recovery_gate"].startswith("FAIL:")


@pytest.mark.parametrize("kind", ["call", "put"])
def test_fee_budget_and_expiry_reward_are_separate_from_short_horizon_edge(kind):
    p = construct(quotes(kind, rule()))
    assert p.amount == .1 and p.debit == pytest.approx(1.1)
    assert p.round_trip_fees == pytest.approx(2.348)
    assert p.max_loss == pytest.approx(3.448) and p.reward_risk >= 1.5
    assert p.fees_verified and p.delta_verified and p.signal_only


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), -1])
def test_unknown_or_invalid_fees_never_become_zero(bad):
    raw = quotes("call", rule())
    raw[0]["fees"]["rate"] = bad
    with pytest.raises((TypeError, ValueError)):
        construct(raw)


def test_report_does_not_promote_discount_sensitivity_or_simulated_profits():
    result = run(rule(), 8)
    assert result["no_real_orders"] and not result["production_profiles_changed"]
    assert result["sample_fee_surface"]["rfq_discount_sensitivity_authorized"] is False
    assert result["sample_fee_surface"]["take_profit_close_credit"] == pytest.approx(4.1302)
    assert sum(row["remaining_legs"] > 0 for row in result["lifecycle_cases"]) == 2
