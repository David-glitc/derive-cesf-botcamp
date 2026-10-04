"""Pinned Hummingbot proposals only; no order transport."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
import yaml

pytest.importorskip("hummingbot", reason="Requires pinned actual controller models")
from hummingbot.core.data_type.common import TradeType
from controllers.directional_trading.flyby import DeriveCesfLongVolController, DeriveCesfLongVolConfig
from tests.test_condor_hummingbot import controller, executor_info


@pytest.fixture(autouse=True)
def isolate_owned_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def set_equity(ctl, provider, value):
    provider.connector._flyby_account_state.update(equity=Decimal(str(value)), available=Decimal(str(value)),
                                                observed_at=provider.now)
    account = ctl._account(provider.connector, provider.now)
    ctl.processed_data.update(account)
    return account


def arm(ctl, atr=.006):
    ctl.processed_data.update(signal=1, halt=False, confidence=.9, atr_pct=atr,
        trend_z=1.9, previous_trend_z=1.8, efficiency=.8, previous_efficiency=.8,
        volume_ratio=1.8, previous_volume_ratio=1.8)


def test_restricted_high_quality_entry_is_smaller_and_weak_signal_blocked(tmp_path):
    ctl, provider = controller(tmp_path)
    account = set_equity(ctl, provider, 680)
    assert account["risk_mode"] == "restricted" and account["risk_scale"] == .25
    arm(ctl)
    ctl.processed_data["volume_ratio"] = 1.4
    assert ctl.create_actions_proposal() == []
    arm(ctl)
    action = ctl.create_actions_proposal()
    assert len(action) == 1, ctl.processed_data
    config = action[0].executor_config
    assert config.entry_price * config.amount <= Decimal("34")
    assert ctl.processed_data["cost_multiple"] == 4


def test_loss_between_tick_and_proposal_rechecks_restricted_gate(tmp_path):
    ctl, provider = controller(tmp_path)
    arm(ctl)
    ctl.processed_data["volume_ratio"] = 1.4
    # The cached decision is normal, but actual full-account equity fell.
    provider.connector._flyby_account_state["equity"] = Decimal("680")
    assert ctl.create_actions_proposal() == []
    assert ctl.processed_data["entry_block"] == "volume_gate"


def test_hard_stop_cancels_pending_and_closes_owned_executors(tmp_path):
    ctl, provider = controller(tmp_path)
    cfg = ctl.get_executor_config(TradeType.BUY, Decimal("3000"), Decimal(".01"))
    ctl.executors_info = [executor_info(cfg), executor_info(cfg, id="pending", is_trading=False)]
    set_equity(ctl, provider, 600)
    assert len(ctl.stop_actions_proposal()) == 2
    assert ctl.processed_data["reason"] == "competition_hard_stop"
    assert ctl.create_actions_proposal() == []
    provider.now += 86400
    set_equity(ctl, provider, 850)
    assert ctl._risk["hard_stop"]


def test_stale_margin_and_failed_risk_write_never_suppress_owned_stops(tmp_path, monkeypatch):
    ctl, provider = controller(tmp_path)
    cfg = ctl.get_executor_config(TradeType.BUY, Decimal("3000"), Decimal(".01"))
    ctl.executors_info = [executor_info(cfg)]
    provider.connector._flyby_account_state = None
    assert len(ctl.stop_actions_proposal()) == 1
    assert ctl.create_actions_proposal() == []


def test_risk_disk_failure_blocks_entry_but_still_proposes_protective_close(tmp_path, monkeypatch):
    ctl, provider = controller(tmp_path)
    cfg = ctl.get_executor_config(TradeType.BUY, Decimal("3000"), Decimal(".01"))
    arm(ctl)
    def fail(*args): raise OSError("disk unavailable")
    monkeypatch.setattr("src.risk.competition.RiskCheckpoint._write", fail)
    assert ctl.create_actions_proposal() == []
    ctl.executors_info = [executor_info(cfg)]
    assert len(ctl.stop_actions_proposal()) == 1


def test_restart_new_profile_cannot_reset_hard_stop(tmp_path):
    ctl, provider = controller(tmp_path)
    set_equity(ctl, provider, 600)
    cfg = DeriveCesfLongVolConfig(id="another-profile", trading_pair="ETH-USDC")
    other = DeriveCesfLongVolController(cfg, provider, asyncio.Queue())
    other._risk_path = ctl._risk_path
    assert other._account(provider.connector, provider.now)["risk_mode"] == "hard_stop"
    assert other.create_actions_proposal() == []


def test_same_bar_restart_and_cooldown_cannot_duplicate_entry(tmp_path):
    ctl, provider = controller(tmp_path)
    ctl.config.cooldown_time = 60
    arm(ctl)
    assert len(ctl.create_actions_proposal()) == 1
    ctl._reservations.pop(id(provider.connector), None)
    provider.now += 61
    ctl._last_entry = 0
    provider.connector._user_stream_tracker.last_recv_time = provider.now
    provider.connector._flyby_account_state["observed_at"] = provider.now
    ctl._last_book_time = provider.now
    ctl.processed_data["updated_at"] = provider.now
    assert ctl.create_actions_proposal() == []
    assert ctl.processed_data["entry_block"] == "signal_already_consumed_or_cooldown"
    ctl.processed_data["signal_time"] += 300
    # Advancing the signal into the future is rejected, not consumed.
    assert ctl.create_actions_proposal() == []


def test_unknown_restart_position_is_halted_not_adopted(tmp_path):
    ctl, provider = controller(tmp_path)
    provider.connector.account_positions["unknown"] = SimpleNamespace(
        trading_pair="ETH-USDC", amount=Decimal(".01"), entry_price=Decimal("3000"))
    account = ctl._account(provider.connector, provider.now)
    assert not account["reconciled"] and not account["entry_allowed"]
    arm(ctl)
    assert ctl.create_actions_proposal() == []


def test_scalp_candidate_duration_and_hold_hysteresis(tmp_path):
    ctl, provider = controller(tmp_path)
    ctl.config.strategy_profile = "competition_scalp"
    ctl.config.cooldown_time = 60
    arm(ctl)
    action = ctl.create_actions_proposal()
    assert len(action) == 1, ctl.processed_data
    assert 600 <= action[0].executor_config.triple_barrier_config.time_limit <= 1800
    ctl.executors_info = [executor_info(action[0].executor_config)]
    ctl.processed_data.update(signal=0, volume_ratio=.5)
    assert ctl.stop_actions_proposal() == []
    ctl.processed_data["trend_z"] = -.5
    assert len(ctl.stop_actions_proposal()) == 1


def test_conflicting_peer_budget_rejected(tmp_path):
    ctl, provider = controller(tmp_path)
    other = DeriveCesfLongVolController(DeriveCesfLongVolConfig(id="peer", trading_pair="ETH-USDC",
        total_amount_quote=Decimal("900")), provider, asyncio.Queue())
    with pytest.raises(ValueError, match="shared_account"):
        ctl._account(provider.connector, provider.now)
    assert other.config.total_amount_quote == 900


@pytest.mark.parametrize("change", [dict(risk_policy="looser"), dict(risk_state_id="../bad"),
    dict(cooldown_time=10), dict(strategy_profile="unbounded"),
    dict(strategy_profile="competition_scalp", interval="15m")])
def test_risk_and_candidate_configuration_contract(change):
    with pytest.raises(ValueError):
        DeriveCesfLongVolConfig(id="candidate-config", trading_pair="ETH-USDC", **change)


@pytest.mark.parametrize("market", ["ETH", "BTC", "SOL", "HYPE"])
def test_prepared_scalp_profile_validates_with_real_hummingbot(tmp_path, market):
    from scripts.prepare_competition_profile import prepare
    output = tmp_path / "new-profile.yml"
    prepare(market, "competition_scalp", output)
    config = DeriveCesfLongVolConfig(**yaml.safe_load(output.read_text()))
    assert config.manual_kill_switch and config.cooldown_time == 60 and config.risk_policy == "flyby-dd15-dd25-v1"
