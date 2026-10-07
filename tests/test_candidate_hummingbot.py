"""Candidate controller integration in pinned HB; fixture data, no transport."""
import asyncio
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

pytest.importorskip("hummingbot", reason="Requires pinned Hummingbot models")
from backtest.flyby_candidate import FlybyCandidateController
from hummingbot.core.data_type.common import TradeType
from src.signal.return_model import FEATURES, ReturnEstimate
from tests.test_condor_hummingbot import controller, executor_info


def model(provider):
    return {"schema": 1, "kind": "flyby_linear_return_candidate", "features": list(FEATURES),
            "market": "ETH",
            "interval_seconds": 300, "horizon_bars": 6, "penalty": 100., "mean": [0, 0, 0],
            "scale": [10, 10, 10], "coefficients": [0, 0, 0], "intercept": .03,
            "residual_rmse": .001, "train_rows": 500, "max_training_label_time": provider.now - 10000,
            "evaluation_not_before": provider.now - 9000, "live_authorized": False}


@pytest.fixture(autouse=True)
def isolation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    FlybyCandidateController._reservations.clear()


def candidate(tmp_path, variant="combined"):
    baseline, provider = controller(tmp_path)
    provider.flyby_offline_replay = True
    source = model(provider)
    ctl = FlybyCandidateController(baseline.config, provider, asyncio.Queue(), model=source, variant=variant)
    ctl._risk_path = baseline._risk_path
    ctl.processed_data = deepcopy(baseline.processed_data)
    ctl._last_book_time = provider.now
    ctl.processed_data.update(signal=1, halt=False, atr_pct=.006, confidence=.9, updated_at=provider.now)
    ctl.return_estimate = ReturnEstimate(.03, .00025, True)
    return ctl, provider, source


def test_live_provider_cannot_construct_candidate(tmp_path):
    baseline, provider = controller(tmp_path)
    with pytest.raises(ValueError, match="offline_fixture"):
        FlybyCandidateController(baseline.config, provider, asyncio.Queue(), model=model(provider))


def test_wrong_market_model_is_rejected(tmp_path):
    baseline, provider = controller(tmp_path)
    provider.flyby_offline_replay = True
    with pytest.raises(ValueError, match="market_mismatch"):
        FlybyCandidateController(baseline.config, provider, asyncio.Queue(), model={**model(provider), "market": "SOL"})


def test_candidate_model_is_copied_and_cost_gate_rechecked(tmp_path):
    ctl, provider, source = candidate(tmp_path)
    source["intercept"] = 1000
    assert ctl.return_model["intercept"] == .03
    ctl.return_estimate = ReturnEstimate(.0001, .001, True)
    assert ctl.create_actions_proposal() == []
    assert ctl.processed_data["entry_block"] == "candidate_expected_edge_gate"
    ctl.return_estimate = ReturnEstimate(.03, .00025, True)
    actions = ctl.create_actions_proposal()
    assert len(actions) == 1
    assert actions[0].executor_config.amount * actions[0].executor_config.entry_price <= Decimal(160)
    assert ctl.entry_risk_weight(ctl.processed_data) == .7


def test_candidate_prediction_enters_operator_context(tmp_path):
    ctl, provider, _ = candidate(tmp_path)
    ctl._last_book_uid = provider.book.last_diff_uid
    asyncio.run(ctl.update_processed_data())
    assert ctl.processed_data["candidate_alpha"]["expected_gross_return"] == .03
    from src.accounting.context import controller_context
    context = controller_context(ctl, provider.now)
    assert context["candidate_alpha"]["live_authorized"] is False
    assert context["candidate_alpha"]["confidence_is_probability"] is False


def test_hold_only_keeps_volume_fade_but_never_hard_stop(tmp_path):
    ctl, provider, _ = candidate(tmp_path, "hold_only")
    cfg = ctl.get_executor_config(TradeType.BUY, Decimal(3000), Decimal(".01"))
    ctl.executors_info = [executor_info(cfg)]
    ctl.processed_data.update(signal=0, volume_ratio=.5)
    assert ctl.stop_actions_proposal() == []
    provider.connector._flyby_account_state.update(equity=Decimal(600), available=Decimal(600))
    assert len(ctl.stop_actions_proposal()) == 1
    assert ctl.processed_data["halt"]


def test_model_absence_blocks_entries_not_protective_exits(tmp_path):
    ctl, provider, _ = candidate(tmp_path)
    ctl.return_estimate = None
    assert ctl.create_actions_proposal() == []
    cfg = ctl.get_executor_config(TradeType.BUY, Decimal(3000), Decimal(".01"))
    ctl.executors_info = [executor_info(cfg)]
    ctl.processed_data["trend_z"] = -.1
    assert len(ctl.stop_actions_proposal()) == 1
