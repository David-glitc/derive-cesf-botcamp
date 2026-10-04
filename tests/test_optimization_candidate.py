from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.execution.fill_journal import FillJournal
from src.options.valuation_candidate import tenor_variance_edges, weighted_spread_value
from src.signal.flyby import feature_frame
from src.signal.optimization import expected_edge_allows, fixed_risk_size, holding_exit
from src.signal.return_model import ReturnEstimate, fit_return_model, predict_return, validate_model


def journal(tmp_path):
    return FillJournal(tmp_path / "fills.sqlite", "fixture-account", "SOL-USDC", "executor-1")


def entry(j, quantity="2", side=1):
    j.intent("entry-intent", "entry", side, quantity, 1)
    j.acknowledge("entry-intent", "entry-1")


def snapshot(position="0", when=10, orders=None):
    return {"source": "authenticated_private", "complete": True, "pair": "SOL-USDC",
            "account_binding": "fixture-account",
            "observed_at": when, "position_base": position, "open_order_ids": orders or []}


def reconcile(j, snap, now=10):
    return j.reconcile(snap, now, minimum_amount=".1", amount_step=".01")


def test_journal_duplicate_conflict_and_late_fill(tmp_path):
    j = journal(tmp_path)
    entry(j)
    j.status("entry-1", "canceled", 2)
    assert reconcile(j, snapshot())["entry_allowed"]
    assert j.fill("trade-1", "entry-1", ".5", "100", ".04", 3)
    assert not j.fill("trade-1", "entry-1", ".5", "100", ".04", 3)
    with pytest.raises(ValueError, match="conflicting"):
        j.fill("trade-1", "entry-1", ".6", "100", ".04", 3)
    assert reconcile(j, snapshot(".5"))["reason"] == "reduce_only_recovery_required"
    assert j.totals()["fees_quote"] == Decimal(".04")


@pytest.mark.parametrize("side", [-1, 1])
def test_journal_partial_close_survives_restart(tmp_path, side):
    j = journal(tmp_path)
    entry(j, side=side)
    j.fill("a", "entry-1", "1", "100", ".1", 2)
    j.status("entry-1", "canceled", 3)
    j.intent("close-intent", "close", -side, "1", 4)
    j.acknowledge("close-intent", "close-1")
    j.fill("b", "close-1", ".4", "101", ".05", 5)
    j.status("close-1", "canceled", 6)
    j.close()
    j = journal(tmp_path)
    assert reconcile(j, snapshot(str(side * .6)))["close_amount"] == "0.6"
    assert j.totals()["fees_quote"] == Decimal(".15")


@pytest.mark.parametrize("quantity,reason", [(".01", "residual_below_minimum"), (".101", "residual_not_whole_lot")])
def test_dust_is_not_flat(tmp_path, quantity, reason):
    j = journal(tmp_path)
    entry(j)
    j.fill("a", "entry-1", quantity, "100", "0", 2)
    j.status("entry-1", "canceled", 3)
    result = reconcile(j, snapshot(quantity))
    assert not result["entry_allowed"] and result["close_amount"] == "0" and result["reason"] == reason


def test_unknown_exposure_and_intent_block_restart(tmp_path):
    j = journal(tmp_path)
    assert reconcile(j, snapshot(".5"))["reason"] == "position_mismatch"
    j.intent("crash-before-ack", "entry", 1, "1", 2)
    j.close()
    assert reconcile(journal(tmp_path), snapshot())["reason"] == "ambiguous_transport_intent"


@pytest.mark.parametrize("update", [{"source": "public"}, {"complete": False}, {"pair": "ETH-USDC"},
                                    {"account_binding": "another-account"}, {"observed_at": 11}, {"observed_at": -1}])
def test_invalid_snapshot_rejected(tmp_path, update):
    j = journal(tmp_path)
    with pytest.raises(ValueError):
        reconcile(j, {**snapshot(), **update})


def test_stale_backwards_and_unresolved_order_snapshots(tmp_path):
    j = journal(tmp_path)
    entry(j)
    assert reconcile(j, snapshot())["reason"] == "working_or_unresolved_orders"
    with pytest.raises(ValueError):
        reconcile(j, snapshot(), now=71)
    j.status("entry-1", "canceled", 12)
    with pytest.raises(ValueError, match="precedes"):
        reconcile(j, snapshot(), now=12)
    assert reconcile(j, snapshot(when=12), now=12)["entry_allowed"]
    with pytest.raises(ValueError, match="precedes"):
        reconcile(j, snapshot(when=11), now=12)


def test_foreign_corrupt_and_unowned_journal(tmp_path):
    j = journal(tmp_path)
    with pytest.raises(ValueError, match="foreign"):
        FillJournal(j.path, "other-account", "SOL-USDC", "executor-1")
    with pytest.raises(ValueError, match="unowned"):
        j.fill("a", "unknown", 1, 100, 0, 1)


def test_journal_disk_corruption_is_not_a_new_account(tmp_path):
    import sqlite3
    path = tmp_path / "corrupt.sqlite"
    path.write_bytes(b"not a database")
    with pytest.raises(sqlite3.DatabaseError):
        FillJournal(path, "fixture-account", "SOL-USDC", "executor-1")


def test_seeded_fragment_and_duplicate_ledger_invariant(tmp_path):
    rng = np.random.default_rng(20261003)
    j = journal(tmp_path)
    entry(j, "100")
    total = Decimal(0)
    fees = Decimal(0)
    for i in range(1000):
        q = Decimal(int(rng.integers(1, 10))) / 1000
        fee = q * Decimal(".06")
        assert j.fill(str(i), "entry-1", q, "100", fee, i + 2)
        if i % 3 == 0:
            assert not j.fill(str(i), "entry-1", q, "100", fee, i + 2)
        total += q
        fees += fee
    assert j.totals()["signed_base"] == total and j.totals()["fees_quote"] == fees
    j.status("entry-1", "canceled", 1002)
    j.close()
    j = journal(tmp_path)
    assert j.totals()["signed_base"] == total
    assert not reconcile(j, snapshot(str(total), when=1003), now=1003)["entry_allowed"]


def test_close_fills_must_reconcile_exactly_not_round_to_flat(tmp_path):
    j = journal(tmp_path)
    entry(j, "1")
    j.fill("entry-fill", "entry-1", "1", "100", "0", 2)
    j.status("entry-1", "filled", 3)
    j.intent("close-intent", "close", -1, "1", 4)
    j.acknowledge("close-intent", "close-1")
    j.fill("close-fill", "close-1", ".999", "100", "0", 5)
    j.status("close-1", "canceled", 6)
    assert reconcile(j, snapshot(".001"))["reason"] == "residual_below_minimum"
    assert reconcile(j, snapshot())["reason"] == "position_mismatch"


def test_unowned_orders_are_never_cancellation_proposals(tmp_path):
    j = journal(tmp_path)
    result = reconcile(j, snapshot(orders=["someone-elses-order"]))
    assert result["reason"] == "unowned_venue_orders"
    assert result["cancel_order_ids"] == [] and not result["entry_allowed"]


def frame():
    rng = np.random.default_rng(9)
    close = 100 * np.exp(np.cumsum(rng.normal(0, .002, 1000)))
    return pd.DataFrame({"timestamp": np.arange(1000) * 300 + 10000, "open": close,
                         "high": close * 1.001, "low": close * .999, "close": close,
                         "volume": rng.uniform(1, 100, 1000)})


def test_model_training_is_purged_and_future_independent():
    f = frame()
    features = feature_frame(f, "5m")
    m = fit_return_model(f, features, 750, market="SOL")
    future = f.copy()
    future.loc[750:, ["open", "close", "high", "low"]] *= 20
    assert m == fit_return_model(future, feature_frame(future, "5m"), 750, market="SOL")
    assert m["max_training_label_time"] < m["evaluation_not_before"]
    with pytest.raises(ValueError, match="precedes"):
        predict_return(m, features.iloc[749].to_dict(), m["evaluation_not_before"] - 1)
    before = deepcopy(m)
    estimate = predict_return(m, features.iloc[751].to_dict(), float(f.timestamp.iloc[752]))
    assert m == before and np.isfinite(estimate.gross_return)


@pytest.mark.parametrize("update", [{"coefficients": [1, 2]}, {"scale": [0, 1, 1]}, {"intercept": float("nan")}, {"live_authorized": True}, {"horizon_bars": 12}])
def test_invalid_model_rejected(update):
    f = frame()
    m = fit_return_model(f, feature_frame(f, "5m"), 750, market="SOL")
    with pytest.raises(ValueError):
        validate_model({**m, **update})


def test_model_ood_and_insufficient_data():
    f = frame()
    features = feature_frame(f, "5m")
    with pytest.raises(ValueError, match="insufficient"):
        fit_return_model(f, features, 200, market="SOL")
    m = fit_return_model(f, features, 750, market="SOL")
    estimate = predict_return(m, {"trend_z": 10000, "efficiency": 1, "volume_ratio": 1000}, float(f.timestamp.iloc[800]))
    assert not estimate.in_distribution
    assert not expected_edge_allows(estimate, 1, .001)


@pytest.mark.parametrize("side", [-1, 1])
def test_expected_edge_boundary_and_restricted_margin(side):
    assert not expected_edge_allows(ReturnEstimate(side * .003, .001, True), side, .002)
    e = ReturnEstimate(side * .004, .001, True)
    assert expected_edge_allows(e, side, .002)
    assert not expected_edge_allows(e, side, .002, True)


def test_hold_does_not_reapply_entry_volume_filter():
    d = SimpleNamespace(halt=False, signal=0)
    f = {"valid": True, "trend_z": 1, "efficiency": .5, "volume_ratio": .01}
    assert holding_exit(d, f, 1) is None
    assert holding_exit(d, {**f, "trend_z": -.1}, 1) == "trend_reversal"
    assert holding_exit(d, f, 1, ReturnEstimate(-.01, .001, True)) == "adverse_return_forecast"


def test_fixed_sizing_preserves_caps_and_hard_stop():
    for scale in (1, .25, .1, 0):
        v = {"peak_dd": -.11 if scale < 1 else 0, "risk_scale": scale, "risk_trade_budget": 4 * scale}
        n = fixed_risk_size(equity=800, available=800, committed=0, stop_pct=.01, view=v)
        assert n <= 160 * scale and n * .01 <= v["risk_trade_budget"] * .7 + 1e-9
    assert fixed_risk_size(equity=800, available=800, committed=0, stop_pct=.01,
                           view={"peak_dd": -.25, "risk_scale": 0, "risk_trade_budget": 0}) == 0


def option(kind, strike, expiry=1000000):
    return {"instrument": f"ETH-{expiry}-{strike}-{kind}", "kind": kind, "strike": strike, "expiry": expiry,
            "timestamp": 100000, "quoted": True, "bids": [[100 if strike == 3000 else 50, 2]],
            "asks": [[102 if strike == 3000 else 52, 2]],
            "pricing": {"forward": 3000, "discount": 1, "iv": .6}}


def test_tenor_matching_and_variance_units():
    now = 100000
    forecast = {"expiry": 1000000, "variance_rate": .49, "horizon_seconds": 900000, "as_of": now}
    quotes = [option("call", 3000), option("put", 3000, 1100000)]
    assert tenor_variance_edges(quotes, [forecast], now, 3000) == []
    quotes.append(option("put", 3000))
    assert tenor_variance_edges(quotes, [forecast], now, 3000)[0]["observed_iv_variance_rate"] == .36
    with pytest.raises(ValueError, match="tenor_matched"):
        tenor_variance_edges(quotes, [{**forecast, "horizon_seconds": 1800}], now, 3000)


def test_weighted_options_prices_fees_and_probability_provenance():
    scenarios = [{"probability": .5, "spot_return": .01, "iv_change": -.05},
                 {"probability": .5, "spot_return": -.01, "iv_change": .05}]
    args = (option("call", 3000), option("call", 3100), 100000, .1, 3600, scenarios)
    result = weighted_spread_value(*args, entry_fees_quote=.1, exit_fees_quote=.1, probability_provenance="hypothetical_test")
    assert not result["entry_authorized"] and not result["calibrated"]
    assert result["expected_net_quote"] == sum(r["net_quote"] * .5 for r in result["scenarios"])
    expensive = weighted_spread_value(*args, entry_fees_quote=.2, exit_fees_quote=.2, probability_provenance="hypothetical_test")
    assert expensive["expected_net_quote"] == pytest.approx(result["expected_net_quote"] - .2)
    with pytest.raises(ValueError, match="sum_to_one"):
        weighted_spread_value(*args[:-1], scenarios[:1], entry_fees_quote=0, exit_fees_quote=0, probability_provenance="test")


def test_weighted_options_require_depth_not_just_top_price():
    with pytest.raises(ValueError, match="depth"):
        weighted_spread_value(option("call", 3000), option("call", 3100), 100000, 3, 3600,
                              [{"probability": 1, "spot_return": 0, "iv_change": 0}],
                              entry_fees_quote=0, exit_fees_quote=0, probability_provenance="hypothetical_test")
