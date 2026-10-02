from copy import deepcopy
import math

import pytest

from backtest.options_paper import smoke_rows
from src.options.paper import Fees, PaperOptions, live_options_status


def test_call_put_complete_four_side_cash_ledger():
    engine = PaperOptions()
    for row in smoke_rows():
        engine.step(row)
    summary = engine.summary()
    assert summary["closed_matched_spreads"] == 2
    assert not summary["open_position"]
    assert summary["live"]["orders_submitted"] == 0
    closes = [e for e in engine.events if e["type"] == "close_fill"]
    assert len(closes) == 2 and all(e["reason"] == "take_profit" for e in closes)
    assert summary["cash"] == pytest.approx(800 + sum(e["net"] for e in closes))
    assert engine.fees == pytest.approx(sum(e.get("fees", 0) for e in engine.events))
    assert summary["data_sources"] == ["synthetic_fixture"]


def test_gross_gain_is_not_net_take_profit():
    rows = smoke_rows(base_fee=.05)[:2]
    # Gross close credit rises, but cannot cover both-leg fixed fees.
    rows[1]["chain"][0]["bids"] = ((32, 10),)
    rows[1]["chain"][0]["asks"] = ((33, 10),)
    engine = PaperOptions()
    for row in rows:
        engine.step(row)
    close = [e for e in engine.events if e["type"] == "close_fill"][0]
    entry = engine.events[0]
    assert close["credit"] > entry["debit"]
    assert close["net"] < 0 and close["reason"] == "stop_loss"


def test_unmatched_short_is_retained_and_halts_not_success():
    row = smoke_rows()[0]
    row.update(buy_filled_amount=0, sell_filled_amount=.01)
    engine = PaperOptions()
    engine.step(row)
    assert engine.halted and engine.unmatched == 1
    assert engine.position["sell_qty"] == .01 and engine.position["buy_qty"] == 0
    assert engine.closed == 0 and engine.curve[-1]["unmatched_exposure"]
    missing = deepcopy(row)
    missing.update(time=row["time"] + 1, chain=[])
    engine.step(missing)
    assert engine.position is not None and engine.curve[-1]["equity"] is None
    recovery = deepcopy(row)
    recovery["time"] += 2
    for q in recovery["chain"]:
        q["timestamp"] = recovery["time"]
    engine.step(recovery)
    assert engine.position is None and engine.halted
    assert engine.closed == 0
    assert engine.events[-1]["type"] == "close_fill" and not engine.events[-1]["matched"]


def test_missing_close_quote_not_fictitious_profit():
    row = smoke_rows()[0]
    engine = PaperOptions()
    engine.step(row)
    row = deepcopy(row)
    row.update(time=row["time"] + 1, chain=[])
    engine.step(row)
    assert engine.summary()["equity"] is None and engine.summary()["return_pct"] is None
    assert engine.position is not None and engine.closed == 0


@pytest.mark.parametrize("fault", ["stale", "crossed", "zero", "missing_iv", "future", "fees", "duplicate", "time"])
def test_fail_closed_inputs(fault):
    row = smoke_rows()[0]
    engine = PaperOptions()
    if fault == "stale":
        for q in row["chain"]:
            q["timestamp"] -= 6
    elif fault == "crossed":
        row["chain"][0]["bids"] = ((35, 10),)
    elif fault == "zero":
        row["chain"][0]["asks"] = ((0, 10),)
    elif fault == "missing_iv":
        row["signal_snapshot"].pop("option_iv_edge")
    elif fault == "future":
        row["chain"][0]["timestamp"] += 1
    elif fault == "fees":
        row["chain"][0]["fees"]["base"] = float("nan")
    elif fault == "duplicate":
        row["chain"].append(row["chain"][0])
    else:
        engine.step(row)
        row["spot"] += 1  # Conflicting same-time record must be rejected.
    if fault in ("future", "fees", "duplicate", "time"):
        with pytest.raises(ValueError):
            engine.step(row)
    else:
        engine.step(row)
        assert engine.position is None and engine.cash == 800


def test_fee_cap_and_live_gate():
    assert Fees(.0003, .5, .125).charge(2, 1, 3000) == .75
    assert live_options_status()["live_options_enabled"] is False


def test_duplicate_and_checkpoint_are_idempotent():
    engine = PaperOptions()
    rows = smoke_rows()
    for row in rows:
        engine.step(row)
        engine.step(deepcopy(row))
    restored = PaperOptions.restore(engine.export_state())
    assert restored.summary() == engine.summary()
    assert restored.events == engine.events and restored.curve == engine.curve
    assert len(engine.curve) == len(rows)


@pytest.mark.parametrize("seed", range(1000))
def test_thousand_execution_fault_iterations(seed):
    # Synthetic fault/fee/exit arithmetic coverage, NOT 1,000 market backtests.
    import random
    rng = random.Random(seed)
    rows = smoke_rows()[:3]
    scenario = seed % 5
    if scenario == 0:
        rows[0]["matched_fill_fraction"] = rng.uniform(.5, 1)
    elif scenario == 1:
        rows[1]["chain"] = []
    elif scenario == 2:
        rows[0].update(buy_filled_amount=.01, sell_filled_amount=0)
    elif scenario == 3:
        for q in rows[0]["chain"]:
            q["fees"]["base"] = rng.uniform(4, 6)
    engine = PaperOptions()
    for row in rows:
        engine.step(row)
    assert math.isfinite(engine.cash) and engine.fees >= 0
    assert engine.closed <= 1
    assert engine.summary()["live"]["orders_submitted"] == 0
    if scenario == 2:
        assert engine.halted and engine.unmatched == 1 and engine.closed == 0


def test_public_collector_refuses_private_methods():
    from backtest.capture_options import PublicV3
    with pytest.raises(ValueError, match="allowlisted"):
        PublicV3().call("private/order", {})
