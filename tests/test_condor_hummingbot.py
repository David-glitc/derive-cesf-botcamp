"""Real v2.17 models + controller ticks; adapter data fixtures, no exchange orders."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace
from pathlib import Path
import tempfile
import json
import subprocess
import sys

import pandas as pd
import numpy as np
import pytest
import yaml

pytest.importorskip("hummingbot", reason="Run this suite in the pinned Hummingbot image")
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.models.executors_info import ExecutorInfo
from hummingbot.strategy_v2.models.base import RunnableStatus
from derive_cesf_long_vol import DeriveCesfLongVolConfig, DeriveCesfLongVolController
from tests.test_flyby_policy import candles

ROOT = Path(__file__).resolve().parents[1]


def test_pinned_connectors_do_not_accept_option_instrument_rules():
    from hummingbot.connector.derivative.derive_perpetual.derive_perpetual_derivative import DerivePerpetualDerivative
    from hummingbot.connector.exchange.derive.derive_exchange import DeriveExchange
    option = {"instrument_type": "option", "instrument_name": "ETH-20261004-3000-C", "is_active": True}
    for connector_class in (DerivePerpetualDerivative, DeriveExchange):
        instance = connector_class.__new__(connector_class)
        assert asyncio.run(instance._format_trading_rules([option])) == []


class Provider:
    ready = True
    def __init__(self):
        self.now = 1800000000.0
        self.frame = candles(180)
        self.frame["timestamp"] = self.now - (180 - pd.Series(range(180))) * 300
        price = float(self.frame.close.iloc[-1])
        self.book = SimpleNamespace(last_diff_uid=1, snapshot=(
            pd.DataFrame({"price": [price * .9999], "amount": [10]}),
            pd.DataFrame({"price": [price * 1.0001], "amount": [10]})))
        self.connector = SimpleNamespace(domain="derive_perpetual", _subacct_id=42, ready=True, _user_stream_tracker=SimpleNamespace(last_recv_time=self.now),
            _instrument_ticker=[{"instrument_name": "ETH-PERP", "taker_fee_rate": ".0003",
                                 "maker_fee_rate": ".0001", "base_fee": ".01"}],
            account_positions={}, in_flight_orders={}, get_balance=lambda _: Decimal("800"),
            get_available_balance=lambda _: Decimal("800"), get_order_book=lambda _: self.book,
            quantize_order_amount=lambda pair, amount: amount.quantize(Decimal(".001"), rounding="ROUND_DOWN"),
            trading_rules={"ETH-USDC": SimpleNamespace(min_order_size=Decimal(".001"), min_notional_size=Decimal("1"),
                min_base_amount_increment=Decimal(".001"), min_price_increment=Decimal(".01"), max_order_size=Decimal("Infinity"))},
            FLYBY_COMPATIBILITY_VERSION="flyby-derive-v3-r2",
            _flyby_account_state={"equity": Decimal("800"), "available": Decimal("800"), "open_orders": [],
                "source": "authenticated_v3_get_subaccount", "observed_at": self.now})

    def time(self): return self.now
    def get_connector(self, name): return self.connector
    def get_candles_df(self, **kwargs): return self.frame
    def initialize_rate_sources(self, pairs): pass
    def initialize_candles_feed(self, config): self.candle_config = config


def controller(tmp_path):
    provider = Provider()
    config = DeriveCesfLongVolConfig(id="contract-test", trading_pair="ETH-USDC")
    instance = DeriveCesfLongVolController(config, provider, asyncio.Queue())
    instance._risk_path = tmp_path / "risk.json"
    asyncio.run(instance.update_processed_data())
    assert instance.processed_data["reason"] == "stale_order_book"
    provider.book.last_diff_uid += 1
    asyncio.run(instance.update_processed_data())
    # Explicit high-quality adapter fixture. The separate candle/action test
    # below still derives its actual signal from raw causal candles.
    instance.processed_data.update(trend_z=1.9, previous_trend_z=1.8, efficiency=.8,
                                   previous_efficiency=.8, volume_ratio=1.8, previous_volume_ratio=1.8)
    return instance, provider


def executor_info(config, **overrides):
    values = dict(id="executor-one", timestamp=config.timestamp, type="position_executor", config=config,
                  status=RunnableStatus.RUNNING, net_pnl_pct=0, net_pnl_quote=0, cum_fees_quote=0,
                  filled_amount_quote=0, is_active=True, is_trading=True,
                  custom_info={"side": config.side, "order_ids": ["owned-order"]})
    return ExecutorInfo(**{**values, **overrides})


def test_actual_models_serialize_nonempty_exits(tmp_path):
    ctl, provider = controller(tmp_path)
    assert not ctl.processed_data["halt"]
    config = ctl.get_executor_config(TradeType.BUY, Decimal("3000"), Decimal(".01"))
    barrier = config.model_dump()["triple_barrier_config"]
    assert barrier["stop_loss"] > 0 and barrier["take_profit"] > 0 and barrier["time_limit"] > 0
    assert barrier["stop_loss_order_type"] == OrderType.MARKET
    assert barrier["open_order_type"] == OrderType.LIMIT
    assert ctl.processed_data["options_execution"]["live_execution_verified"] is False
    assert ctl.processed_data["execution_environment"]["network"] == "mainnet"


def test_custom_info_context_serialization_has_no_trading_side_effect(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctl, provider = controller(tmp_path)
    provider.connector.api_secret = "SECRET_CONNECTOR"
    ctl.processed_data["api_secret"] = "SECRET_DATA"
    ctl.config.manual_kill_switch = True
    before = dict(ctl.processed_data)
    report = ctl.get_custom_info()
    assert len(json.dumps(report)) < 1024 and report["flyby"]["paused"] is True
    assert report["flyby"]["live_options"] is False
    context = json.loads(Path(report["flyby"]["context_path"]).read_text())
    assert "SECRET" not in json.dumps(context)
    assert context["native_market"]["status"] == "unavailable_or_invalid"
    assert ctl.processed_data == before and ctl.create_actions_proposal() == []


def test_context_write_failure_does_not_block_protective_stops(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctl, provider = controller(tmp_path)
    cfg = ctl.get_executor_config(TradeType.BUY, Decimal("3000"), Decimal(".01"))
    ctl.executors_info = [executor_info(cfg)]
    ctl.config.manual_kill_switch = True
    def fail(*args): raise OSError("disk unavailable")
    monkeypatch.setattr("derive_cesf_long_vol.atomic_owned_json", fail)
    report = ctl.get_custom_info()
    assert report["flyby"]["context_file_status"] == "unavailable"
    assert len(ctl.stop_actions_proposal()) == 1


def test_unexpected_advisory_failure_is_contained(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctl, provider = controller(tmp_path)
    def fail(*args): raise RuntimeError("unexpected reporting failure")
    monkeypatch.setattr("derive_cesf_long_vol.controller_context", fail)
    assert ctl.get_custom_info()["flyby"]["context_status"] == "unavailable"


def test_native_controller_opt_in_never_calls_binance_or_falls_back(tmp_path, monkeypatch):
    from tests.test_native_data import snapshot, seal
    from src.accounting.context import atomic_owned_json
    monkeypatch.chdir(tmp_path)
    provider = Provider()
    native, _ = snapshot()
    native["candles"] = provider.frame.to_dict("records")
    native["features"]["valid"] = True
    atomic_owned_json(Path("data/flyby-market-ETH.json"), seal(native), "derive_market_context")
    cfg = DeriveCesfLongVolConfig(id="native-unit", trading_pair="ETH-USDC", signal_source="derive_native")
    ctl = DeriveCesfLongVolController(cfg, provider, asyncio.Queue())
    assert ctl.get_candles_config() == []
    provider.get_candles_df = lambda **kw: (_ for _ in ()).throw(AssertionError("Binance must not be queried"))
    asyncio.run(ctl.update_processed_data())
    provider.book.last_diff_uid += 1
    asyncio.run(ctl.update_processed_data())
    assert ctl.processed_data["signal_source"] == "derive_native" and not ctl.processed_data["halt"]
    provider.now += 6
    provider.book.last_diff_uid += 1
    asyncio.run(ctl.update_processed_data())
    assert ctl.processed_data["halt"] and ctl.processed_data["reason"] == "invalid_native_context"
    assert ctl.create_actions_proposal() == []


@pytest.mark.parametrize("source,interval", [("unknown", "5m"), ("derive_native", "15m"), ("derive_native", "4h")])
def test_native_input_contract_rejects_unsupported_modes(source, interval):
    with pytest.raises(ValueError): DeriveCesfLongVolConfig(id="source-contract", signal_source=source, interval=interval)


@pytest.mark.parametrize("domain", ["derive_perpetual_testnet", "derive_perpetual_paper_trade", None])
def test_wrong_runtime_domain_cannot_create_or_stop_executors(tmp_path, domain):
    ctl, provider = controller(tmp_path)
    config = ctl.get_executor_config(TradeType.BUY, Decimal("3000"), Decimal(".01"))
    ctl.executors_info = [executor_info(config)]
    provider.connector.domain = domain
    asyncio.run(ctl.update_processed_data())
    assert ctl.processed_data["halt"]
    assert ctl.processed_data["reason"] == "mainnet_connector_required"
    assert ctl.processed_data["execution_environment"]["network"] == "mainnet"
    assert ctl.stop_actions_proposal() == []
    ctl.executors_info = []
    ctl.processed_data.update(signal=1, halt=False, confidence=.8, atr_pct=.004)
    assert ctl.create_actions_proposal() == []
    with pytest.raises(ValueError, match="mainnet_connector_domain_required"):
        ctl.get_executor_config(TradeType.BUY, Decimal("3000"), Decimal(".01"))


def test_installed_mainnet_constants_match_submission_contract():
    from agents.mainnet import validate_installed_endpoints
    from hummingbot.connector.derivative.derive_perpetual import derive_perpetual_constants
    validate_installed_endpoints(derive_perpetual_constants)


def test_mainnet_preflight_cli_in_actual_hummingbot_environment():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/check_mainnet.py")],
                            check=True, capture_output=True, text=True, timeout=30)
    verdict = json.loads(result.stdout)
    assert verdict["network"] == "mainnet"
    assert verdict["connector"] == "derive_perpetual"
    assert verdict["api_generation"] == "v3"
    assert verdict["install_profiles_paused"] is True
    assert verdict["account_verified"] is False
    assert verdict["live_execution_verified"] is False
    assert verdict["orders_submitted"] == 0


def test_real_controller_shadow_options_are_not_live_execution(tmp_path):
    from backtest.options_paper import smoke_rows
    from src.options.paper import normalize_quote
    ctl, provider = controller(tmp_path)
    row = smoke_rows()[0]
    ctl.processed_data.update(row["signal_snapshot"], available=800, equity=800)
    quotes = []
    for raw in row["chain"]:
        raw["timestamp"] = provider.now
        raw["expiry"] = provider.now + 3 * 86400
        quotes.append(normalize_quote(raw)[0])
    plan = ctl.plan_options(quotes, provider.now, .04)
    assert plan is not None and plan.signal_only
    assert plan.delta_verified and not plan.fees_verified
    assert plan.gross_reference_quote <= 240 and abs(plan.net_delta_quote) <= 160
    assert ctl.processed_data["options_delta"]["status"] == "fresh_shadow_plan"
    assert ctl.config.options_enabled is False
    assert ctl.processed_data["options_execution"]["orders_submitted"] == 0


def test_option_plan_is_cleared_on_stale_or_unknown_account(tmp_path):
    from backtest.options_paper import smoke_rows
    from src.options.paper import normalize_quote
    ctl, provider = controller(tmp_path)
    row = smoke_rows()[0]
    ctl.processed_data.update(row["signal_snapshot"], available=800, equity=800)
    qs = []
    for raw in row["chain"]:
        raw.update(timestamp=provider.now, expiry=provider.now + 3 * 86400)
        qs.append(normalize_quote(raw)[0])
    assert ctl.plan_options(qs, provider.now, .04)
    provider.connector.in_flight_orders["unknown"] = SimpleNamespace(client_order_id="unknown", amount=.01, price=3000)
    assert ctl.plan_options(qs, provider.now, .04) is None
    assert ctl.processed_data["spread_plan"] is None
    provider.connector.in_flight_orders.clear()
    provider.now += 6
    assert ctl.plan_options(qs, provider.now, .04) is None


def test_option_plan_costs_use_supplied_metadata_not_premium_fee_guess(tmp_path):
    from backtest.options_paper import smoke_rows
    from src.options.paper import normalize_quote
    ctl, provider = controller(tmp_path)
    row = smoke_rows()[0]
    ctl.processed_data.update(row["signal_snapshot"], available=800, equity=800)
    qs, fees = [], {}
    for raw in row["chain"]:
        raw.update(timestamp=provider.now, expiry=provider.now + 3 * 86400)
        qs.append(normalize_quote(raw)[0])
        fees[raw["instrument"]] = raw["fees"]
    plan = ctl.plan_options(qs, provider.now, .04, fee_metadata=fees)
    assert plan and plan.fees_verified and plan.max_loss <= 4
    for metadata in fees.values():
        metadata["base"] = 10
    assert ctl.plan_options(qs, provider.now, .04, fee_metadata=fees) is None


def test_fresh_public_chain_automatically_produces_only_shadow_context(tmp_path, monkeypatch):
    from backtest.options_paper import smoke_rows
    ctl, provider = controller(tmp_path)
    row = smoke_rows()[0]
    ctl.processed_data.update(row["signal_snapshot"], forecast_sigma=.8)
    for q in row["chain"]:
        q.update(timestamp=provider.now, expiry=provider.now + 3 * 86400,
                 quoted=True, pricing={"iv": .5})
    monkeypatch.setattr("derive_cesf_long_vol.load_market", lambda *args:
                        {"perp": {"timestamp": provider.now, "index": ctl.processed_data["entry_mid"]}, "options": row["chain"]})
    ctl._update_options_shadow(provider.now)
    assert ctl.processed_data["spread_plan"]["fees_verified"]
    assert ctl.processed_data["options_delta"]["delta_verified"]
    assert not ctl.processed_data["options_delta"]["live_options"]
    assert ctl.processed_data["options_execution"]["orders_submitted"] == 0
    assert not provider.connector.in_flight_orders
    previous_signal = ctl.processed_data["signal"]
    monkeypatch.setattr("derive_cesf_long_vol.load_market", lambda *args: {})
    ctl._update_options_shadow(provider.now)
    assert ctl.processed_data["spread_plan"] is None
    assert ctl.processed_data["signal"] == previous_signal


def test_action_rechecks_state_and_shared_account_reservation(tmp_path):
    ctl, provider = controller(tmp_path)
    ctl.processed_data.update(signal=1, halt=False, confidence=.8, atr_pct=.004)
    actions = ctl.create_actions_proposal()
    assert len(actions) == 1
    config = actions[0].executor_config
    assert config.amount * config.entry_price <= Decimal("160")
    assert config.triple_barrier_config.stop_loss is not None
    assert ctl.create_actions_proposal() == []
    ctl._last_entry = 0
    ctl._reservations.pop(id(provider.connector), None)
    provider.connector.in_flight_orders["unknown"] = SimpleNamespace(client_order_id="unknown", amount=.01, price=3000)
    assert ctl.create_actions_proposal() == []


def test_owned_position_is_not_automatically_closed_as_unknown(tmp_path):
    ctl, provider = controller(tmp_path)
    config = ctl.get_executor_config(TradeType.BUY, Decimal("3000"), Decimal(".05"))
    ctl.executors_info = [executor_info(config)]
    provider.connector.account_positions["ETH"] = SimpleNamespace(trading_pair="ETH-USDC", amount=.025,
                                                                 entry_price=3000, unrealized_pnl=1)
    account = ctl._account(provider.connector, provider.now)
    assert account["reconciled"] and account["entry_allowed"] and account["perp_positions"] == 1
    ctl.processed_data.update(signal=1, halt=False)
    assert ctl.stop_actions_proposal() == []
    provider.connector.account_positions["ETH"].amount = .10
    assert not ctl._account(provider.connector, provider.now)["reconciled"]


def test_selected_two_perp_profiles_share_account_slots(tmp_path):
    from copy import deepcopy
    first, provider = controller(tmp_path)
    first.config = DeriveCesfLongVolConfig(**{**first.config.model_dump(),
        "max_perp_positions": 2, "max_option_spreads": 2})
    config = first.get_executor_config(TradeType.BUY, Decimal("3000"), Decimal(".02"))
    first.executors_info = [executor_info(config)]
    provider.connector.account_positions["ETH"] = SimpleNamespace(
        trading_pair="ETH-USDC", amount=Decimal(".02"), entry_price=Decimal("3000"), unrealized_pnl=0)
    raw = yaml.safe_load((ROOT / "conf/controllers/conf_flyby_sol_active.yml").read_text())
    second = DeriveCesfLongVolController(DeriveCesfLongVolConfig(**raw), provider, asyncio.Queue())
    second._risk_path = first._risk_path
    second._last_book_time = provider.now
    second.processed_data = deepcopy(first.processed_data)
    second.processed_data.update(signal=1, halt=False, confidence=.8, atr_pct=.004)
    provider.connector.trading_rules["SOL-USDC"] = provider.connector.trading_rules["ETH-USDC"]
    provider.connector._instrument_ticker.append({**provider.connector._instrument_ticker[0], "instrument_name": "SOL-PERP"})
    assert second._account(provider.connector, provider.now)["perp_positions"] == 1
    actions = second.create_actions_proposal()
    assert len(actions) == 1 and actions[0].executor_config.trading_pair == "SOL-USDC"
    second.executors_info = [executor_info(actions[0].executor_config, id="executor-sol")]
    assert second._account(provider.connector, provider.now)["perp_positions"] == 2
    assert second.create_actions_proposal() == []


@pytest.mark.parametrize("fault,reason", [("private", "stale_user_stream"), ("gap", "candle_gap"),
                                         ("crossed", "crossed_order_book"), ("empty", "empty_order_book"),
                                         ("basis", "proxy_basis")])
def test_real_controller_halts_for_feed_and_book_faults(tmp_path, fault, reason):
    ctl, provider = controller(tmp_path)
    if fault == "private": provider.connector._user_stream_tracker.last_recv_time -= 121
    if fault == "gap": provider.frame.loc[150, "timestamp"] -= 60
    if fault == "crossed": provider.book.snapshot[0].loc[0, "price"] *= 2
    if fault == "empty": provider.book.snapshot = (pd.DataFrame(), pd.DataFrame())
    if fault == "basis": provider.frame["close"] *= 2
    asyncio.run(ctl.update_processed_data())
    assert ctl.processed_data["reason"] == reason
    assert ctl.create_actions_proposal() == []


def test_pending_entry_timeout_and_invalid_signal_close(tmp_path):
    ctl, provider = controller(tmp_path)
    config = ctl.get_executor_config(TradeType.BUY, Decimal("3000"), Decimal(".05"))
    ctl.executors_info = [executor_info(config, timestamp=provider.now - 31, is_trading=False)]
    ctl.processed_data.update(signal=1, halt=False)
    assert len(ctl.stop_actions_proposal()) == 1
    ctl.executors_info[0].is_trading = True
    ctl.processed_data["signal"] = 0
    assert len(ctl.stop_actions_proposal()) == 1


@pytest.mark.parametrize("profile", ["eth", "btc", "sol", "hype"])
def test_all_submitted_profiles_validate_against_actual_hb(profile):
    config = yaml.safe_load((ROOT / f"conf/controllers/conf_flyby_{profile}.yml").read_text())
    DeriveCesfLongVolConfig(**config)


@pytest.mark.parametrize("change", [dict(connector_name="derive"), dict(position_mode="HEDGE"),
                                   dict(connector_name="derive_perpetual_testnet"),
                                   dict(connector_name="derive_perpetual_paper_trade"),
                                   dict(options_enabled=True), dict(interval="3m"), dict(leverage=20),
                                   dict(candles_connector="derive"), dict(candles_trading_pair="BTC-USDT")])
def test_incompatible_live_configuration_is_rejected(change):
    with pytest.raises(ValueError):
        DeriveCesfLongVolConfig(id="invalid", trading_pair="ETH-USDC", **change)


def test_mutated_config_cannot_bypass_mainnet_contract(tmp_path):
    ctl, provider = controller(tmp_path)
    with pytest.raises(ValueError, match="requires mainnet"):
        ctl.config.connector_name = "derive_perpetual_testnet"
    # Deliberate low-level corruption also cannot bypass the action boundary.
    object.__setattr__(ctl.config, "connector_name", "derive_perpetual_testnet")
    ctl.processed_data.update(signal=1, halt=False, confidence=.8, atr_pct=.004)
    assert ctl.create_actions_proposal() == []
    assert ctl.stop_actions_proposal() == []
    with pytest.raises(ValueError, match="mainnet_connector_name_required"):
        ctl.get_executor_config(TradeType.BUY, Decimal("3000"), Decimal(".01"))


def test_closed_candles_to_actual_controller_action_queue(tmp_path):
    ctl, provider = controller(tmp_path)
    # Causal high-confidence movement/volume fixture, not a manually forced decision.
    close = 3000 * np.exp(np.cumsum(.0005 + np.random.default_rng(77).normal(0, .0001, 180)))
    opening = np.r_[close[0], close[:-1]]
    provider.frame.loc[:, "open"] = opening
    provider.frame.loc[:, "close"] = close
    provider.frame.loc[:, "high"] = close * 1.002
    provider.frame.loc[:, "low"] = opening * .998
    provider.frame.loc[:, "volume"] = 100.0
    provider.frame.loc[176:, "volume"] = 300.0
    provider.book.snapshot[0].loc[0, "price"] = close[-1] * .9999
    provider.book.snapshot[1].loc[0, "price"] = close[-1] * 1.0001
    ctl.initialize_candles()
    assert provider.candle_config.connector == "binance_perpetual"
    ctl.executors_update_event.set()
    asyncio.run(ctl.control_task())
    assert ctl.processed_data["signal"] == 1, ctl.processed_data
    actions = ctl.actions_queue.get_nowait()
    assert len(actions) == 1 and actions[0].executor_config.side == TradeType.BUY
    assert actions[0].executor_config.triple_barrier_config.stop_loss > 0
    assert not ctl.executors_update_event.is_set()


def test_risk_checkpoint_reload_and_invalid_checkpoint_fail_closed(tmp_path):
    ctl, provider = controller(tmp_path)
    ctl._risk.update(day_equity="830", peak="840")
    import json
    ctl._risk_path.write_text(json.dumps(ctl._risk))
    other = DeriveCesfLongVolController(ctl.config, provider, asyncio.Queue())
    other._risk = json.loads(ctl._risk_path.read_text())
    other._risk_path = ctl._risk_path
    account = other._account(provider.connector, provider.now)
    assert account["daily_pnl_pct"] < -.02 and account["peak_dd"] < -.04
    other._risk_error = True
    with pytest.raises(ValueError, match="checkpoint"):
        other._account(provider.connector, provider.now)


def test_ordinary_interbar_age_does_not_invent_a_stale_feed(tmp_path):
    ctl, provider = controller(tmp_path)
    provider.now += 120
    provider.connector._user_stream_tracker.last_recv_time = provider.now
    provider.book.last_diff_uid += 1
    asyncio.run(ctl.update_processed_data())
    assert ctl.processed_data["reason"] != "stale_candles"


def test_paused_profile_never_creates_an_executor(tmp_path):
    ctl, provider = controller(tmp_path)
    ctl.config.manual_kill_switch = True
    ctl.processed_data.update(signal=1, halt=False, confidence=.9, atr_pct=.004)
    assert ctl.create_actions_proposal() == []


def test_bad_controller_id_is_rejected():
    with pytest.raises(ValueError, match="identifier"):
        DeriveCesfLongVolConfig(id="../../state", trading_pair="ETH-USDC")


def test_current_venue_minimum_blocks_without_raising_caps(tmp_path):
    ctl, provider = controller(tmp_path)
    provider.connector.trading_rules["ETH-USDC"].min_order_size = Decimal(".1")
    ctl.processed_data.update(signal=1, halt=False, confidence=.9, atr_pct=.004)
    assert ctl.create_actions_proposal() == []
    assert ctl.processed_data["entry_block"] == "venue_minimum_exceeds_budget"
    assert ctl.config.max_notional_fraction == .20
    assert ctl.processed_data["venue_minimum_notional"] > 160


def test_stock_connector_and_missing_margin_cannot_authorize_entries(tmp_path):
    ctl, provider = controller(tmp_path)
    del provider.connector.FLYBY_COMPATIBILITY_VERSION
    asyncio.run(ctl.update_processed_data())
    assert ctl.processed_data["reason"] == "reviewed_connector_compatibility_required"
    assert ctl.create_actions_proposal() == []
    provider.connector.FLYBY_COMPATIBILITY_VERSION = "flyby-derive-v3-r2"
    provider.connector._flyby_account_state = None
    provider.book.last_diff_uid += 1
    asyncio.run(ctl.update_processed_data())
    assert ctl.processed_data["reason"] == "verified_margin_unavailable"
    assert ctl.create_actions_proposal() == []
