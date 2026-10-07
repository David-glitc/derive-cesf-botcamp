"""False-startup-blocker regressions in real HB; no exchange or model calls."""
import asyncio
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

pytest.importorskip("hummingbot", reason="Requires the pinned Hummingbot image")
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_row import OrderBookRow
from derive_cesf_long_vol import DeriveCesfLongVolConfig, DeriveCesfLongVolController
from tests.test_condor_hummingbot import Provider, ROOT


def snapshot_controller(tmp_path):
    provider = Provider()
    price = float(provider.frame.close.iloc[-1])
    provider.book = OrderBook()
    provider.book.apply_snapshot([OrderBookRow(price * .9999, 10, 11)],
                                 [OrderBookRow(price * 1.0001, 10, 11)], 11)
    publication = SimpleNamespace(update_id=11, timestamp=provider.now)
    provider.connector.order_book_tracker = SimpleNamespace(data_source=SimpleNamespace(
        _snapshot_messages={"ETH-USDC": publication}))
    cfg = DeriveCesfLongVolConfig(id="snapshot-contract", trading_pair="ETH-USDC")
    ctl = DeriveCesfLongVolController(cfg, provider, asyncio.Queue())
    ctl._risk_path = tmp_path / "risk.json"
    return ctl, provider, publication


def test_first_fresh_native_full_snapshot_does_not_need_a_diff(tmp_path):
    ctl, provider, _ = snapshot_controller(tmp_path)
    assert provider.book.snapshot_uid == 11 and provider.book.last_diff_uid == 0
    asyncio.run(ctl.update_processed_data())
    assert not ctl.processed_data["halt"]


def test_valid_snapshot_and_signal_can_propose_a_bounded_executor(tmp_path):
    ctl, provider, _ = snapshot_controller(tmp_path)
    asyncio.run(ctl.update_processed_data())
    # Explicit offline signal fixture, not a profitability or fill assertion.
    ctl.processed_data.update(signal=1, confidence=.8, atr_pct=.004, trend_z=1.9,
        previous_trend_z=1.8, efficiency=.8, previous_efficiency=.8,
        volume_ratio=1.8, previous_volume_ratio=1.8)
    actions = ctl.create_actions_proposal()
    assert len(actions) == 1
    executor = actions[0].executor_config
    assert executor.amount * executor.entry_price <= 160
    assert executor.leverage == 2 and executor.triple_barrier_config.stop_loss > 0
    assert not provider.connector.in_flight_orders  # proposals do not send orders


def test_full_snapshot_updates_remain_fresh_without_diff_updates(tmp_path):
    ctl, provider, publication = snapshot_controller(tmp_path)
    asyncio.run(ctl.update_processed_data())
    provider.now += 31
    provider.connector._user_stream_tracker.last_recv_time = provider.now
    provider.connector._flyby_account_state["observed_at"] = provider.now
    price = float(provider.frame.close.iloc[-1])
    provider.book.apply_snapshot([OrderBookRow(price * .9999, 10, 12)],
                                 [OrderBookRow(price * 1.0001, 10, 12)], 12)
    publication.update_id, publication.timestamp = 12, provider.now
    assert provider.book.last_diff_uid == 0
    asyncio.run(ctl.update_processed_data())
    assert not ctl.processed_data["halt"]


def test_fresh_same_id_native_publication_is_not_mistaken_for_stale_book(tmp_path):
    ctl, provider, publication = snapshot_controller(tmp_path)
    asyncio.run(ctl.update_processed_data())
    provider.now += 31
    provider.connector._user_stream_tracker.last_recv_time = provider.now
    provider.connector._flyby_account_state["observed_at"] = provider.now
    publication.timestamp = provider.now
    asyncio.run(ctl.update_processed_data())
    assert not ctl.processed_data["halt"]


@pytest.mark.parametrize("fault", ["old", "future", "mismatch", "nan", "missing"])
def test_native_publication_is_not_blindly_trusted(tmp_path, fault):
    ctl, provider, publication = snapshot_controller(tmp_path)
    if fault == "old": publication.timestamp = provider.now - 31
    if fault == "future": publication.timestamp = provider.now + 1
    if fault == "mismatch": publication.update_id += 1
    if fault == "nan": publication.timestamp = float("nan")
    if fault == "missing":
        provider.connector.order_book_tracker.data_source._snapshot_messages.clear()
    asyncio.run(ctl.update_processed_data())
    assert ctl.processed_data["reason"] == "stale_order_book"
    assert ctl.create_actions_proposal() == []


def test_rereading_old_native_snapshot_does_not_refresh_its_age(tmp_path):
    ctl, provider, _ = snapshot_controller(tmp_path)
    asyncio.run(ctl.update_processed_data())
    provider.now += 31
    provider.connector._user_stream_tracker.last_recv_time = provider.now
    provider.connector._flyby_account_state["observed_at"] = provider.now
    asyncio.run(ctl.update_processed_data())
    assert ctl.processed_data["reason"] == "stale_order_book"
    assert ctl.create_actions_proposal() == []


@pytest.mark.parametrize("market", ["eth", "sol"])
def test_active_samples_pass_actual_condor_template_validator(market):
    condor_root = os.environ.get("FLYBY_CONDOR_ROOT")
    if not condor_root:
        pytest.skip("Set FLYBY_CONDOR_ROOT to an offline official Condor checkout")
    source = Path(condor_root) / "mcp_servers/hummingbot_api/tools/controllers.py"
    spec = importlib.util.spec_from_file_location("condor_controller_template_fixture", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    template = {name: {"default": field.default, "type": str(field.annotation)}
                for name, field in DeriveCesfLongVolConfig.model_fields.items()}
    sample = yaml.safe_load((ROOT / f"conf/controllers/conf_flyby_{market}_active.yml").read_text())
    # Demonstrate upstream's false required-field check, then exercise the fix.
    missing = {k: v for k, v in sample.items() if k != "trailing_stop"}
    with pytest.raises(ValueError, match="trailing_stop"):
        module._validate_config_against_template(missing, template)
    module._validate_config_against_template(sample, template)
    assert DeriveCesfLongVolConfig(**sample).trailing_stop is None
