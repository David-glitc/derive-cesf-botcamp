import asyncio
from decimal import Decimal
import pytest

pytest.importorskip("hummingbot", reason="Requires pinned Hummingbot action models")
from hummingbot.core.data_type.common import TradeType
from src.runtime.bridge import RuntimeBridge
from tests.test_condor_hummingbot import controller, executor_info
from tests.test_competition_hummingbot import arm, set_equity
from tests.test_runtime_bridge import request


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def runtime_controller(tmp_path, mode="bounded"):
    ctl, provider = controller(tmp_path)
    ctl.config.runtime_oversight_mode = mode
    provider.connector._flyby_account_state.update(positions=[], initial_margin=Decimal(800), maintenance_margin=Decimal(800))
    arm(ctl)
    ctl._publish_runtime()
    return ctl, provider


def submit(ctl, provider, patch):
    state = ctl._publish_runtime()
    bridge = RuntimeBridge(ctl._runtime_bridge.root, ctl.config.id, ctl._runtime_bridge.owner["account_binding"], writable=True)
    return bridge.submit(request(state, patch, provider.now), provider.now)


def test_bounded_missing_lease_blocks_entry_but_observe_preserves_baseline(tmp_path):
    ctl, provider = runtime_controller(tmp_path)
    assert ctl.create_actions_proposal() == []
    assert ctl.processed_data["entry_block"] == "runtime_lease_required"
    ctl.config.runtime_oversight_mode = "observe"
    assert len(ctl.create_actions_proposal()) == 1


def test_size_reduction_and_new_entry_exits_are_applied(tmp_path):
    ctl, provider = runtime_controller(tmp_path)
    submit(ctl, provider, {"size_multiplier": .5, "stop_multiplier": .75,
                           "take_profit_multiplier": 1.5, "hold_multiplier": .5})
    action = ctl.create_actions_proposal()
    assert len(action) == 1, ctl.processed_data
    config = action[0].executor_config
    assert config.amount * config.entry_price <= Decimal(80)
    from src.risk.position_sizing import dynamic_exits
    stop, target, hold = dynamic_exits(.006, ctl.processed_data["confidence"], 300)
    assert float(config.triple_barrier_config.stop_loss) == pytest.approx(stop * .75)
    assert float(config.triple_barrier_config.take_profit) == pytest.approx(target * 1.5)
    assert config.triple_barrier_config.time_limit == int(hold * .5)


@pytest.mark.parametrize("patch", [{"veto_entry": True}, {"confidence_floor": .95}, {"size_multiplier": 0}])
def test_agent_can_only_tighten_entries(tmp_path, patch):
    ctl, provider = runtime_controller(tmp_path)
    submit(ctl, provider, patch)
    assert ctl.create_actions_proposal() == []
    assert ctl.processed_data["entry_block"] == "runtime_entry_veto"


def test_close_request_uses_owned_executor_action(tmp_path):
    ctl, provider = runtime_controller(tmp_path)
    ctl.executors_info = [executor_info(ctl.get_executor_config(TradeType.BUY, Decimal(3000), Decimal(".01")))]
    submit(ctl, provider, {"close_executor_id": "executor-one"})
    actions = ctl.stop_actions_proposal()
    assert len(actions) == 1 and actions[0].executor_id == "executor-one"


def test_expired_lease_and_publish_failure_never_suppress_protective_stops(tmp_path, monkeypatch):
    ctl, provider = runtime_controller(tmp_path)
    submit(ctl, provider, {"size_multiplier": 1})
    provider.now += 61
    ctl.processed_data["updated_at"] = provider.now
    provider.connector._user_stream_tracker.last_recv_time = provider.now
    provider.connector._flyby_account_state["observed_at"] = provider.now
    ctl._last_book_time = provider.now
    assert ctl.create_actions_proposal() == []
    ctl.executors_info = [executor_info(ctl.get_executor_config(TradeType.BUY, Decimal(3000), Decimal(".01")))]
    set_equity(ctl, provider, 600)
    monkeypatch.setattr(ctl._runtime_bridge, "publish", lambda *args: (_ for _ in ()).throw(OSError("disk")))
    assert len(ctl.stop_actions_proposal()) == 1
    assert ctl.processed_data["reason"] == "competition_hard_stop"


def test_state_is_published_without_status_report_and_has_no_secrets(tmp_path):
    ctl, provider = runtime_controller(tmp_path, "observe")
    provider.connector.api_secret = "SECRET_MARKER"
    provider.book.last_diff_uid += 1
    asyncio.run(ctl.update_processed_data())
    state = ctl._runtime_bridge.read_state(provider.now)
    import json
    assert "SECRET_MARKER" not in json.dumps(state)
    assert state["context"]["runtime_health"]["account_verified"]
    assert state["context"]["portfolio"]["equity"] == 800


def test_restart_session_and_truncated_inventory_block_entry(tmp_path):
    ctl, provider = runtime_controller(tmp_path)
    submit(ctl, provider, {"size_multiplier": 1})
    ctl._runtime_session = "restarted"
    assert ctl.create_actions_proposal() == []
    assert "session" in ctl.processed_data["entry_block"]
    account = provider.connector._flyby_account_state
    account["positions"] = [{"instrument_type": "perp", "instrument_name": "ETH-PERP", "amount": "0"}] * 51
    state = ctl._publish_runtime()
    health = state["context"]["runtime_health"]
    assert health["account_verified"] and not health["inventory_complete"]
    assert health["inventory_truncated"] and len(state["context"]["venue_positions"]) == 50
    with pytest.raises(ValueError, match="inventory"):
        submit(ctl, provider, {"size_multiplier": 1})


def test_unexpected_observability_failure_blocks_entries_not_manual_protection(tmp_path, monkeypatch):
    ctl, provider = runtime_controller(tmp_path)
    submit(ctl, provider, {"size_multiplier": 1})
    monkeypatch.setattr(ctl._runtime_bridge, "publish", lambda *a: (_ for _ in ()).throw(RuntimeError("fixture")))
    assert ctl.create_actions_proposal() == []
    assert ctl.processed_data["entry_block"] == "runtime_publication_unavailable"
    ctl.config.manual_kill_switch = True
    ctl.executors_info = [executor_info(ctl.get_executor_config(TradeType.BUY, Decimal(3000), Decimal(".01")))]
    assert len(ctl.stop_actions_proposal()) == 1


def test_agent_option_close_routes_existing_paired_lifecycle(tmp_path):
    from tests.test_options_rfq_hummingbot import wired_controller
    ctl, provider, transport = wired_controller(tmp_path)
    # Open a paired fixture through the normal controller before observing it.
    asyncio.run(ctl._service_options())
    transport.offer(ctl._options)
    asyncio.run(ctl._service_options())
    transport.settle(ctl._options)
    asyncio.run(ctl._service_options())
    assert ctl._options.journal.state["phase"] == "open"
    provider.connector._flyby_account_state.update(positions=asyncio.run(transport.account())["positions"])
    ctl.config.runtime_oversight_mode = "bounded"
    submit(ctl, provider, {"close_options": True, "veto_entry": True})
    asyncio.run(ctl._service_options())
    assert ctl._options.journal.state["intent"] == "exit"
    transport.offer(ctl._options, "310", "100")
    asyncio.run(ctl._service_options())
    assert ctl._options.journal.state["phase"] == "settling"
    assert transport.writes.count("execute") == 2
