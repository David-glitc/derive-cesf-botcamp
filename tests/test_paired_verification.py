from copy import deepcopy
import json
import random

import pytest

from src.execution.paired import PairedModel, entry_guard, invariant, reserve_guard
from verification.check_safety import exhaustive


def prepare(**changes):
    return {"type": "prepare", "id": "start", "target": 3, "reserve": 8, "budget": 8,
            "guards": {"paused": False, "fresh": True, "reconciled": True, "daily_pnl": 0, "peak_dd": 0}, **changes}


def test_matched_partial_entry_close_and_restart():
    model = PairedModel()
    model.apply(prepare())
    model.apply({"type": "open_report", "id": "entry1", "buy": 1, "sell": 1})
    assert model.state.reserved == 8 and model.state.phase == "opening"
    model.apply({"type": "open_report", "id": "entry2", "buy": 2, "sell": 2, "terminal": True})
    model.apply({"type": "request_close", "id": "close"})
    model.apply({"type": "close_report", "id": "close1", "buy": 1, "sell": 1, "terminal": True})
    assert model.state.exposure == (1, 1) and model.state.reserved == 8
    restored = PairedModel.restore(json.loads(json.dumps(model.checkpoint())))
    assert restored.state == model.state
    restored.apply({"type": "request_close", "id": "close_again"})
    restored.apply({"type": "close_report", "id": "close2", "buy": 2, "sell": 2, "terminal": True})
    assert restored.state.phase == "flat" and restored.state.reserved == 0


@pytest.mark.parametrize("guard,value", [("paused", True), ("fresh", False), ("reconciled", False),
                                         ("daily_pnl", -.02), ("peak_dd", -.04)])
def test_entry_guards_cannot_be_bypassed(guard, value):
    event = prepare()
    event["guards"][guard] = value
    model = PairedModel()
    model.apply(event)
    assert model.state.phase == "flat"


@pytest.mark.parametrize("mode", ["live", "mainnet", "testnet"])
def test_no_live_transport_or_mode(mode):
    with pytest.raises(ValueError, match="not implemented"): PairedModel(mode)
    assert not hasattr(PairedModel(), "submit_order")


@pytest.mark.parametrize("report", [(0, 1), (4, 4), (0, 0)])
def test_invalid_or_reordered_reports_retain_reservation(report):
    model = PairedModel()
    model.apply(prepare())
    model.apply({"type": "open_report", "id": "one", "buy": 1, "sell": 1})
    model.apply({"type": "open_report", "id": "bad", "buy": report[0], "sell": report[1]})
    assert model.state.phase == "halted" and model.state.reserved == 8
    assert model.state.reported == report and invariant(model.state)
    assert PairedModel.restore(model.checkpoint()).state == model.state


def test_timeout_duplicate_and_conflict_survive_restart():
    model = PairedModel()
    model.apply(prepare())
    assert not model.apply(prepare())
    conflict = prepare(target=2)
    assert not model.apply(conflict)
    assert model.state.phase == "halted" and model.state.reserved == 8
    assert PairedModel.restore(model.checkpoint()).state == model.state
    fresh = PairedModel()
    fresh.apply(prepare())
    fresh.apply({"type": "timeout", "id": "timeout"})
    assert fresh.state.reserved == 8 and fresh.state.phase == "halted"
    changed = deepcopy(fresh.checkpoint())
    changed["state"]["reserved"] = 0
    with pytest.raises(ValueError): PairedModel.restore(changed)


def test_checkpoint_and_duplicate_do_not_alias_mutable_events():
    model, event = PairedModel(), prepare()
    model.apply(event)
    event["target"] = 1
    checkpoint = model.checkpoint()
    checkpoint["journal"].clear()
    assert model.journal[0]["target"] == 3
    with pytest.raises(ValueError): model.apply({"type": "prepare", "id": "secret", "private_key": "SECRET"})


def test_actual_reducer_exhaustive_model():
    result = exhaustive()
    assert result["reachable_states"] > 500 and result["transitions"] > 8000
    assert result["invariant_failures"] == 0


@pytest.mark.parametrize("seed", range(1000))
def test_thousand_adversarial_package_sequences(seed):
    rng, model = random.Random(seed), PairedModel()
    model.apply(prepare())
    for i in range(10):
        model.apply({"type": rng.choice(("open_report", "close_report", "timeout", "request_close")),
                     "id": f"{seed}-{i}", "buy": rng.randrange(5), "sell": rng.randrange(5),
                     "terminal": bool(rng.randrange(2))})
        assert invariant(model.state)
    assert PairedModel.restore(model.checkpoint()).state == model.state
