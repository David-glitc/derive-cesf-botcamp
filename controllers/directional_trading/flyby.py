"""Flyby V2 controller: causal Condor policy, bounded perp and atomic RFQ execution.

Requires Hummingbot v2.17.0. RFQ execution is separately opt-in; this controller
never submits unmatched option legs through a perpetual position executor.
"""
from __future__ import annotations

from pathlib import Path
from decimal import Decimal
from dataclasses import asdict
from weakref import WeakSet
import re
import uuid

import numpy as np
from pydantic import Field, model_validator

from agents.condor_agent import decide
from agents.mainnet import MAINNET_CONNECTOR, execution_environment, require_mainnet_connector
from src.accounting.context import atomic_owned_json, controller_context, context_summary, context_path, load_market
from src.accounting.derive_margin import require_margin_state
from src.execution.derive_hb import COMPATIBILITY_VERSION
from src.risk.venue_sizing import venue_size
from src.risk.exposure import BASELINE_EXPOSURE, ETH_EXPOSURE_TEST, exposure_limits
from src.risk.competition import POLICY, HARD_STOP_DRAWDOWN, RiskCheckpoint, account_binding, scalp_exits, exit_signal_reason
from src.signal.flyby import INTERVAL_SECONDS, feature_frame
from src.risk.position_sizing import depth_quote, dynamic_exits, risk_size, cost_allows_entry
from src.options.spread_builder import build_spread
from src.options.paper import live_options_status, normalize_quote
from src.options.ranking import costed_plan
from src.options.delta import account_policy, delta_context
from src.runtime.bridge import RuntimeBridge, root_path
from src.runtime.control import entry_allowed as runtime_entry_allowed, tune_exits
from src.execution.derive_rfq import DeriveRFQTransport
from src.execution.options_rfq import OptionsRFQ, RFQJournal, expected_positions, journal_busy
from hummingbot.core.data_type.common import TradeType, PositionMode, OrderType
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy_v2.controllers.directional_trading_controller_base import (
    DirectionalTradingControllerBase, DirectionalTradingControllerConfigBase,
)
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig, TripleBarrierConfig
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction, StopExecutorAction


class DeriveCesfLongVolConfig(DirectionalTradingControllerConfigBase):
    controller_name: str = "derive_cesf_long_vol"
    connector_name: str = "derive_perpetual"
    candles_connector: str = "binance_perpetual"
    candles_trading_pair: str = "ETH-USDT"
    interval: str = "5m"
    signal_source: str = "binance_proxy"
    vol_lookback: int = Field(default=100, ge=30, le=1000)
    leverage: int = Field(default=2, ge=1, le=3)
    position_mode: PositionMode = PositionMode.ONEWAY
    max_executors_per_side: int = 1
    cooldown_time: int = Field(default=300, ge=60)
    strategy_profile: str = "baseline"
    risk_state_id: str = "flyby-competition"
    risk_policy: str = POLICY
    total_amount_quote: Decimal = Field(default=Decimal("800"), gt=0)
    risk_fraction: float = Field(default=0.005, gt=0, le=0.02)
    exposure_profile: str = BASELINE_EXPOSURE
    max_notional_fraction: float = Field(default=0.20, gt=0, le=0.40)
    max_gross_exposure_fraction: float = Field(default=0.30, gt=0, le=0.40)
    option_gross_fraction: float = Field(default=0.30, gt=0, le=0.75)
    max_slippage: float = Field(default=0.0015, gt=0, le=0.01)
    estimated_fee_per_side: float = Field(default=0.0006, ge=0, le=0.01)
    max_basis: float = Field(default=0.03, gt=0, le=0.05)
    max_book_age: int = Field(default=30, gt=0, le=60)
    max_user_stream_age: int = Field(default=60, gt=0, le=120)
    condor_active: bool = False
    runtime_oversight_mode: str = "off"
    options_enabled: bool = False
    options_execution_mode: str = "shadow"
    options_signal_enabled: bool = True
    option_buy_moneyness: str = "any"
    option_buy_delta_target: float = Field(default=.50, ge=.25, le=.70)
    option_sell_delta_target: float = Field(default=.25, ge=.10, le=.35)
    portfolio_margin: bool = False
    spot_hedge_enabled: bool = False
    trailing_stop: object = None
    stop_loss: Decimal = Decimal("0.005")
    take_profit: Decimal = Decimal("0.01")
    time_limit: int = 10800

    @model_validator(mode="after")
    def competition_contract(self):
        if self.runtime_oversight_mode not in ("off", "observe", "bounded"):
            raise ValueError("unknown_runtime_oversight_mode")
        limits = exposure_limits(self.exposure_profile, self.trading_pair.split("-")[0])
        if (self.max_notional_fraction > limits["perp_notional"]
                or self.max_gross_exposure_fraction > limits["perp_gross"]
                or self.option_gross_fraction > limits["option_gross"]):
            raise ValueError("exposure_caps_require_approved_profile")
        if self.exposure_profile == ETH_EXPOSURE_TEST and (
                self.total_amount_quote != 800 or self.risk_fraction != .005 or self.strategy_profile != "baseline"
                or self.max_notional_fraction != .40 or self.max_gross_exposure_fraction != .40
                or self.option_gross_fraction != .75):
            raise ValueError("fixed_eth_exposure_test_settings_required")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.id):
            raise ValueError("controller id must be a stable filename-safe identifier")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.risk_state_id) or self.risk_policy != POLICY:
            raise ValueError("competition risk contract required")
        if self.strategy_profile not in ("baseline", "competition_scalp"):
            raise ValueError("unknown strategy profile")
        if self.strategy_profile == "competition_scalp" and self.interval != "5m":
            raise ValueError("competition scalp candidate supports 5m only")
        if self.interval not in INTERVAL_SECONDS:
            raise ValueError("interval must be 5m, 15m, 1h or 4h")
        if self.signal_source not in ("binance_proxy", "derive_native"):
            raise ValueError("signal_source must be binance_proxy or derive_native")
        if self.signal_source == "derive_native" and self.interval != "5m":
            raise ValueError("native controller slice supports 5m only; no timeframe fallback")
        if self.connector_name != MAINNET_CONNECTOR:
            raise ValueError("Competition Flyby requires mainnet derive_perpetual; testnet/paper connectors are not allowed")
        if self.position_mode != PositionMode.ONEWAY:
            raise ValueError("Derive supports ONEWAY positions")
        if self.options_execution_mode not in ("shadow", "rfq_v2"):
            raise ValueError("unknown_options_execution_mode")
        if self.options_enabled != (self.options_execution_mode == "rfq_v2"):
            raise ValueError("options_enabled requires explicit rfq_v2 execution mode")
        if self.portfolio_margin or self.spot_hedge_enabled:
            raise ValueError("portfolio margin and spot hedges are not supported")
        if self.options_enabled and (self.trading_pair not in ("ETH-USDC", "BTC-USDC") or not self.options_signal_enabled):
            raise ValueError("RFQ execution requires ETH/BTC native option signals")
        if self.option_buy_moneyness not in ("any", "ATM", "OTM", "ITM"):
            raise ValueError("unknown option moneyness selection")
        if self.trading_pair not in ("ETH-USDC", "BTC-USDC", "SOL-USDC", "HYPE-USDC"):
            raise ValueError("Choose an approved Derive perpetual profile")
        if self.candles_connector != "binance_perpetual" or self.candles_trading_pair != self.trading_pair.split("-")[0] + "-USDT":
            raise ValueError("Use the matching approved Binance perpetual candle proxy")
        return self


class DeriveCesfLongVolController(DirectionalTradingControllerBase):
    # A process-wide reservation prevents two profiles using the same
    # connector from allocating before its in-flight orders are visible.
    _reservations = {}
    _controllers = WeakSet()

    def __init__(self, config, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self.max_records = max(config.vol_lookback + 30, 150)
        self._last_book_uid = None
        self._last_book_time = 0.0
        self._last_entry = 0.0
        self._controllers.add(self)
        self._risk_path = Path("data") / f"flyby-risk-{config.risk_state_id}.json"
        self._risk = None
        self._risk_error = False
        self._options = None
        self._legacy_risk_path = Path("data") / f"flyby-risk-{config.id}.json"
        self._runtime_session = uuid.uuid4().hex
        self._runtime_bridge = None
        self._runtime_error = None

    def _publish_runtime(self):
        if self.config.runtime_oversight_mode == "off":
            return None
        try:
            connector = self._mainnet_connector()
            if self._runtime_bridge is None:
                self._runtime_bridge = RuntimeBridge(root_path(self.config.id), self.config.id, account_binding(connector))
            now = self.market_data_provider.time()
            context = controller_context(self, now)
            state = self._runtime_bridge.publish(context, self._runtime_session, self.config.runtime_oversight_mode, now)
            self._runtime_error = None
            self.processed_data["runtime_oversight"] = {"mode": self.config.runtime_oversight_mode,
                "sequence": state["sequence"], "session": self._runtime_session, "status": "published"}
            return state
        except Exception:
            self._runtime_error = "runtime_publication_unavailable"
            self.processed_data["runtime_oversight"] = {"status": self._runtime_error}
            return None

    def _runtime_adjustment(self):
        if self.config.runtime_oversight_mode != "bounded":
            return {}, None
        state = self._publish_runtime()
        if state is None:
            return {}, self._runtime_error
        try:
            return self._runtime_bridge.consume(state, self.market_data_provider.time()), None
        except Exception as exc:
            return {}, str(exc) if isinstance(exc, ValueError) else "runtime_lease_unavailable"

    def get_candles_config(self):
        if self.config.signal_source == "derive_native":
            return []
        return [CandlesConfig(connector=self.config.candles_connector,
                              trading_pair=self.config.candles_trading_pair,
                              interval=self.config.interval, max_records=self.max_records)]

    def _halt(self, reason):
        self.processed_data = {"signal": 0, "halt": True, "reason": reason,
                               "execution_environment": execution_environment(),
                               "options_execution": self._options.status() if self._options else live_options_status()}

    def _options_path(self):
        return self._risk_path.with_name(f"flyby-rfq-{self.config.risk_state_id}.json")

    def _ensure_options(self, connector):
        if not self.config.options_enabled:
            return
        if self._options is None:
            peers = [c for c in self._controllers if c is not self and c.config.options_enabled
                     and c.market_data_provider.get_connector(c.config.connector_name) is connector]
            if peers:
                raise ValueError("one_rfq_controller_per_account_required")
            journal = RFQJournal(self._options_path(), account_binding(connector), self.config.id)
            self._options = OptionsRFQ(DeriveRFQTransport(connector), journal, int(connector._subacct_id),
                exposure_profile=self.config.exposure_profile, underlying=self.config.trading_pair.split("-")[0])
        connector._flyby_rfq_enabled = True

    def _options_busy(self, connector):
        return journal_busy(self._options_path(), account_binding(connector))

    def _mainnet_connector(self):
        if self.config.connector_name != MAINNET_CONNECTOR:
            raise ValueError("mainnet_connector_name_required")
        connector = self.market_data_provider.get_connector(self.config.connector_name)
        require_mainnet_connector(connector)
        if getattr(connector, "FLYBY_COMPATIBILITY_VERSION", None) != COMPATIBILITY_VERSION:
            raise ValueError("reviewed_connector_compatibility_required")
        return connector

    def _account(self, connector, now):
        state = require_margin_state(connector, now)
        equity = float(state["equity"])
        available = float(state["available"])
        positions = list(connector.account_positions.values())
        option_positions = {r["instrument_name"]: Decimal(str(r["amount"])) for r in state.get("positions", [])
                            if r.get("instrument_type") == "option" and Decimal(str(r["amount"]))}
        # The venue's full subaccount valuation already includes position P&L.
        if not np.isfinite([equity, available]).all() or equity <= 0 or available < 0:
            raise ValueError("invalid_account")
        if self._risk_error:
            raise ValueError("invalid_risk_checkpoint")
        cap = float(self.config.total_amount_quote)
        orders = list(connector.in_flight_orders.values())
        if self._legacy_risk_path.exists() and self._legacy_risk_path != self._risk_path:
            raise ValueError("legacy_risk_checkpoint_requires_review")
        peers = [c for c in self._controllers
                 if c.market_data_provider.get_connector(c.config.connector_name) is connector]
        if any(c.config.risk_state_id != self.config.risk_state_id
               or c.config.total_amount_quote != self.config.total_amount_quote for c in peers):
            raise ValueError("shared_account_risk_contract_mismatch")
        self._risk_store = RiskCheckpoint(self._risk_path, account_binding(connector), self.config.total_amount_quote)
        self._risk, risk = self._risk_store.observe(state["equity"], now,
            allow_bootstrap=not orders and not state["open_orders"] and not any(p.amount for p in positions) and not option_positions)
        committed = sum(abs(float(p.amount) * float(p.entry_price)) for p in positions)
        for row in state.get("positions", []):
            if row.get("instrument_type") == "option" and Decimal(str(row["amount"])):
                index = Decimal(str(row["index_price"]))
                if not index.is_finite() or index <= 0:
                    raise ValueError("invalid_option_exposure_reference")
                committed += float(abs(Decimal(str(row["amount"]))) * index)
        committed += sum(abs(float(o.amount) * float(o.price)) for o in orders if o.price is not None)
        if not np.isfinite(committed):
            raise ValueError("invalid_account_exposure")
        active = [e for c in peers for e in c.executors_info if e.is_active]
        known_ids = {oid for e in active for oid in e.custom_info.get("order_ids", [])}
        known_orders = all(o.client_order_id in known_ids for o in orders)
        # HB's ExecutorInfo exposes order IDs but not net remaining base.
        # Match position sign and upper bound; exact fill reconciliation is
        # still an adapter preflight requirement, not a claimed ledger bridge.
        known_positions = all(any(
            e.config.trading_pair == p.trading_pair
            and (float(p.amount) > 0) == (e.config.side == TradeType.BUY)
            and abs(float(p.amount)) <= float(e.config.amount) + 1e-9
            for e in active) for p in positions if p.amount)
        known_options = not option_positions or any(c._options is not None and c._options.busy
            and option_positions == expected_positions(c._options.journal.state["plan"]) for c in peers)
        return {**risk, "equity": min(cap, equity), "venue_equity": state["equity"], "available": min(cap, available),
                "committed": committed,
                "entry_allowed": not orders and not state["open_orders"] and not any(p.amount for p in positions) and not option_positions,
                "margin_source": state["source"], "margin_age": now - state["observed_at"],
                "reconciled": known_orders and known_positions and known_options}

    async def update_processed_data(self):
        try:
            now = self.market_data_provider.time()
            try:
                connector = self._mainnet_connector()
                self._ensure_options(connector)
            except (ValueError, KeyError, AttributeError) as exc:
                return self._halt("reviewed_connector_compatibility_required"
                    if str(exc) == "reviewed_connector_compatibility_required" else "mainnet_connector_required")
            if not connector.ready:
                return self._halt("connector_not_ready")
            user_age = now - connector._user_stream_tracker.last_recv_time
            if not 0 <= user_age <= self.config.max_user_stream_age:
                return self._halt("stale_user_stream")
            book = connector.get_order_book(self.config.trading_pair)
            uid = book.last_diff_uid
            if self._last_book_uid is not None and uid != self._last_book_uid:
                self._last_book_time = now
            self._last_book_uid = uid
            if now - self._last_book_time > self.config.max_book_age:
                return self._halt("stale_order_book")
            if self.config.signal_source == "derive_native":
                ccy = self.config.trading_pair.split("-")[0]
                native = load_market(Path("data") / f"flyby-market-{ccy}.json", now, ccy)
                if (native["interval"] != "5m" or not native["features"].get("valid")
                        or not 0 <= now - native["perp"]["timestamp"] <= 5):
                    return self._halt("invalid_native_context")
                import pandas as pd
                frame = pd.DataFrame(native["candles"])
            else:
                frame = self.market_data_provider.get_candles_df(
                    connector_name=self.config.candles_connector, trading_pair=self.config.candles_trading_pair,
                    interval=self.config.interval, max_records=self.max_records)
            seconds = INTERVAL_SECONDS[self.config.interval]
            if frame is None or "timestamp" not in frame or len(frame) < self.config.vol_lookback + 2:
                return self._halt("missing_candles")
            completed = frame.loc[frame.timestamp.astype(float) + seconds <= now].copy()
            if len(completed) < self.config.vol_lookback + 1:
                return self._halt("candle_warmup")
            times = completed.timestamp.astype(float).to_numpy()
            if not np.allclose(np.diff(times[-self.config.vol_lookback - 1:]), seconds):
                return self._halt("candle_gap")
            age = now - (float(times[-1]) + seconds)
            if not 0 <= age <= seconds + 60:
                return self._halt("stale_candles")
            bids, asks = book.snapshot
            if bids.empty or asks.empty:
                return self._halt("empty_order_book")
            best_bid, best_ask = float(bids.price.iloc[0]), float(asks.price.iloc[0])
            if not 0 < best_bid < best_ask:
                return self._halt("crossed_order_book")
            mid = (best_bid + best_ask) / 2
            if abs(float(completed.close.iloc[-1]) / mid - 1) > self.config.max_basis:
                return self._halt("proxy_basis")
            account = self._account(connector, now)
            horizon = 1800 if self.config.strategy_profile == "competition_scalp" else 14400
            features = feature_frame(completed, self.config.interval, self.config.vol_lookback,
                                     trend_horizon_seconds=horizon).iloc[-1].to_dict()
            features.update(account, stale_secs=max(0, age - seconds), ccy=self.config.trading_pair.split("-")[0])
            features["valid"] = bool(features["valid"])
            decision = decide(features, active=self.config.condor_active)
            self.processed_data = {**features, "signal": decision.signal, "halt": decision.halt,
                                   "decision": asdict(decision), "regime": decision.regime,
                                   "reason": decision.reason, "confidence": decision.confidence,
                                   "entry_mid": mid, "bids": bids, "asks": asks, "updated_at": now,
                                   "signal_time": float(times[-1]),
                                   "signal_source": self.config.signal_source,
                                   "execution_environment": execution_environment(),
                                   "options_execution": self._options.status() if self._options else live_options_status()}
            self._update_options_shadow(now)
        except (ValueError, KeyError, TypeError, AttributeError, IndexError, OSError) as exc:
            self._halt(str(exc) if isinstance(exc, ValueError) else f"adapter_error:{type(exc).__name__}")
        finally:
            # Protective RFQ lifecycle runs even when entry candles/books fail.
            if self._options is not None:
                await self._service_options()
            self._publish_runtime()

    async def _service_options(self):
        try:
            connector = self._mainnet_connector()
            if not connector.ready:
                return
            now, data = self.market_data_provider.time(), self.processed_data
            fresh = 0 <= now - data.get("updated_at", 0) <= 5
            adjustment, runtime_error = self._runtime_adjustment()
            peers = [c for c in self._controllers
                     if c.market_data_provider.get_connector(c.config.connector_name) is connector]
            allow = bool(fresh and not data.get("halt", True) and not self.config.manual_kill_switch
                         and data.get("reconciled") and data.get("entry_allowed")
                         and not any(e.is_active for c in peers for e in c.executors_info)
                         and (self._options.busy or self._reservations.get(id(connector), 0) <= now))
            if self.config.runtime_oversight_mode == "bounded":
                allow = bool(allow and not runtime_error and runtime_entry_allowed(
                    adjustment, data.get("confidence", 0), data.get("confidence_floor", .70)))
            s = self._options.journal.state
            plan = data.get("spread_plan")
            expected_signal = 1 if s.get("plan", {}).get("kind") == "call" else -1
            force = bool(self.config.manual_kill_switch or data.get("halt", True) or not fresh
                         or data.get("signal", 0) != expected_signal or data.get("risk_mode") == "hard_stop")
            force = bool(force or adjustment.get("close_options", False))
            def entry_budget(account, timestamp):
                # Re-observe the FULL fresh account, not cached candle-tick equity.
                _, risk = self._risk_store.observe(account["equity"], timestamp)
                decision = decide({**data, **risk}, active=self.config.condor_active)
                latest, latest_error = self._runtime_adjustment()
                if (decision.halt or decision.signal != data.get("signal") or not decision.signal
                        or latest_error or (self.config.runtime_oversight_mode == "bounded" and
                            not runtime_entry_allowed(latest, decision.confidence, risk["confidence_floor"]))
                        or self.config.manual_kill_switch or not 0 <= timestamp - data.get("updated_at", 0) <= 5
                        or not 0 <= timestamp - connector._user_stream_tracker.last_recv_time <= self.config.max_user_stream_age
                        or timestamp - self._last_book_time > self.config.max_book_age
                        or any(e.is_active for c in peers for e in c.executors_info)):
                    return 0
                return min(float(account["available"]), float(self.config.total_amount_quote) * .01,
                           risk["risk_trade_budget"]) * latest.get("size_multiplier", 1)
            def consume(account, timestamp):
                return self._risk_store.consume_entry(account["equity"], timestamp, self.config.trading_pair,
                                                     data["signal_time"], self.config.cooldown_time)
            def exit_required(account, timestamp):
                # Existing checkpoint remains authoritative during stale entry data.
                if getattr(self, "_risk_store", None) is None:
                    if not self._options.busy:
                        return False
                    self._risk_store = RiskCheckpoint(self._risk_path, account_binding(connector), self.config.total_amount_quote)
                _, risk = self._risk_store.observe(account["equity"], timestamp)
                return risk["risk_mode"] == "hard_stop"
            reserved = allow and not self._options.busy
            if reserved:
                self._reservations[id(connector)] = now + 60
            await self._options.tick(now, plan=plan, budget=data.get("risk_trade_budget", 0) * adjustment.get("size_multiplier", 1), allow_entry=allow,
                                     force_exit=force, consume_entry=consume, entry_budget=entry_budget,
                                     exit_required=exit_required)
            if reserved and not self._options.busy:
                self._reservations.pop(id(connector), None)
            data["options_execution"] = self._options.status()
            if self._options.busy:
                data["entry_block"] = "atomic_options_lifecycle_active"
        except Exception:
            self._halt("rfq_lifecycle_unavailable")

    def create_actions_proposal(self):
        data = self.processed_data
        now = self.market_data_provider.time()
        if not data.get("signal") or data.get("halt") or self.config.manual_kill_switch:
            return []
        if any(e.is_active for e in self.executors_info) or now - self._last_entry < self.config.cooldown_time:
            return []
        try:
            signal_time = float(data["signal_time"])
        except (ValueError, KeyError, TypeError):
            self._halt("incomplete_or_stale_signal")
            return []
        if (not np.isfinite(signal_time)
                or not 0 <= now - (signal_time + INTERVAL_SECONDS[self.config.interval]) <= INTERVAL_SECONDS[self.config.interval] + 60):
            self._halt("incomplete_or_stale_signal")
            return []
        try:
            connector = self._mainnet_connector()
        except (ValueError, KeyError, AttributeError):
            self._halt("mainnet_connector_required")
            return []
        key = id(connector)
        if self._options_busy(connector):
            data["entry_block"] = "persistent_options_lifecycle_active"
            return []
        if self._reservations.get(key, 0) > now:
            return []
        try:
            account = self._account(connector, now)
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            self._halt("account_recheck_failed")
            return []
        if (not account["entry_allowed"] or not account["reconciled"] or not connector.ready
                or now - data.get("updated_at", 0) > 5
                or not 0 <= now - connector._user_stream_tracker.last_recv_time <= self.config.max_user_stream_age
                or now - self._last_book_time > self.config.max_book_age
                or account["risk_mode"] == "hard_stop"):
            return []
        # A loss between the signal tick and proposal cannot reuse the easier gate.
        current = decide({**data, **account}, active=self.config.condor_active)
        if current.halt or not current.signal or current.signal != data["signal"]:
            data["entry_block"] = current.reason
            return []
        data.update(account, confidence=current.confidence)
        adjustment, runtime_error = self._runtime_adjustment()
        if runtime_error or not runtime_entry_allowed(adjustment, current.confidence, account["confidence_floor"]):
            data["entry_block"] = runtime_error or "runtime_entry_veto"
            return []
        risk_weight = self.entry_risk_weight(data)
        exit_builder = scalp_exits if self.config.strategy_profile == "competition_scalp" else dynamic_exits
        stop, profit, hold = exit_builder(data["atr_pct"], data["confidence"], INTERVAL_SECONDS[self.config.interval])
        sizing_stop = stop
        stop, profit, hold = tune_exits(adjustment, stop, profit, hold)
        notional = risk_size(equity=account["equity"], available=account["available"],
                             committed=account["committed"], confidence=risk_weight,
                             stop_pct=sizing_stop + 2 * (self.config.estimated_fee_per_side + self.config.max_slippage) + .0001,
                             gross_cap=account["equity"] * self.config.max_gross_exposure_fraction, risk_fraction=self.config.risk_fraction,
                             notional_fraction=self.config.max_notional_fraction, peak_dd=account["peak_dd"],
                             drawdown_limit=float(HARD_STOP_DRAWDOWN), size_scale=account["risk_scale"],
                             trade_risk_budget=account["risk_trade_budget"], exposure_profile=self.config.exposure_profile,
                             underlying=self.config.trading_pair.split("-")[0])
        notional *= adjustment.get("size_multiplier", 1)
        if notional <= 0:
            return []
        price = data["entry_mid"]
        side = TradeType.BUY if data["signal"] > 0 else TradeType.SELL
        rule = connector.trading_rules.get(self.config.trading_pair)
        if rule is None:
            data["entry_block"] = "missing_venue_rules"
            return []
        def sized(at_price, budget=notional):
            return venue_size(budget=budget, price=at_price, side=1 if side == TradeType.BUY else -1,
                              min_amount=rule.min_order_size, amount_step=rule.min_base_amount_increment,
                              price_tick=rule.min_price_increment, min_notional=rule.min_notional_size,
                              max_amount=rule.max_order_size)
        try:
            initial = sized(price)
        except (ValueError, AttributeError):
            data["entry_block"] = "invalid_venue_rules"
            return []
        data["venue_minimum_notional"] = float(initial.minimum_notional)
        data["venue_minimum_equity_fraction"] = float(initial.minimum_notional) / account["equity"]
        if initial.amount <= 0:
            data["entry_block"] = initial.reason
            return []
        amount = initial.amount
        # Re-read depth immediately before proposing an executor.
        book = connector.get_order_book(self.config.trading_pair)
        bids, asks = book.snapshot
        if bids.empty or asks.empty or not 0 < float(bids.price.iloc[0]) < float(asks.price.iloc[0]):
            return []
        levels = asks if side == TradeType.BUY else bids
        quote = depth_quote(zip(levels.price, levels.amount), float(amount))
        if quote is None or abs(quote.worst_price / price - 1) > self.config.max_slippage:
            return []
        # The executable limit, not a cheaper mid, must respect the quote cap.
        try:
            executable = sized(quote.worst_price)
        except ValueError:
            data["entry_block"] = "invalid_venue_rules"
            return []
        if executable.amount <= 0:
            data["entry_block"] = executable.reason
            return []
        amount = min(amount, executable.amount)
        quote = depth_quote(zip(levels.price, levels.amount), float(amount))
        limit = executable.price
        if (quote is None or amount * max(Decimal(str(price)), limit) > Decimal(str(notional))
                or abs(float(limit) / price - 1) > self.config.max_slippage):
            return []
        instrument = next((r for r in getattr(connector, "_instrument_ticker", [])
                           if r.get("instrument_name") == self.config.trading_pair.split("-")[0] + "-PERP"), None)
        if not instrument:
            data["entry_block"] = "missing_public_fee_rules"
            return []
        try:
            rates = [self.config.estimated_fee_per_side, float(instrument["taker_fee_rate"]),
                     float(instrument["maker_fee_rate"])]
            fee_rate = max(rates)
            base_fee = float(instrument["base_fee"])
            if not np.isfinite([*rates, base_fee]).all() or min(*rates, base_fee) < 0:
                raise ValueError("invalid fees")
        except (KeyError, ValueError, TypeError):
            data["entry_block"] = "invalid_public_fee_rules"
            return []
        executable_notional = float(amount * max(Decimal(str(price)), limit))
        # Include an exit reserve, not just the cheap visible entry spread.
        costs = 2 * fee_rate + abs(quote.worst_price / price - 1) + self.config.max_slippage + 2 * base_fee / executable_notional + .0001
        if not cost_allows_entry(profit, costs, max(account["cost_multiple"], adjustment.get("cost_multiple", 3))):
            data["entry_block"] = "cost_gate"
            return []
        if not self.additional_entry_gate(data, costs):
            data["entry_block"] = "candidate_expected_edge_gate"
            return []
        if amount < rule.min_order_size or amount * limit < rule.min_notional_size:
            return []
        if executable_notional * (stop + costs) > account["risk_trade_budget"] * risk_weight:
            data["entry_block"] = "trade_risk_budget"
            return []
        data.update(stop_loss=stop, take_profit=profit, time_limit=hold)
        executor = self.get_executor_config(side, limit, amount)
        try:
            consumed = self._risk_store.consume_entry(account["venue_equity"], now, self.config.trading_pair,
                                                     data["signal_time"], self.config.cooldown_time)
        except (OSError, ValueError, KeyError, TypeError):
            self._halt("risk_entry_checkpoint_failed")
            return []
        if not consumed:
            data["entry_block"] = "signal_already_consumed_or_cooldown"
            return []
        self._reservations[key] = now + 30
        self._last_entry = now
        return [CreateExecutorAction(controller_id=self.config.id, executor_config=executor)]

    def entry_risk_weight(self, data):
        """Baseline sizing remains unchanged; isolated candidates may reduce it."""
        return data["confidence"]

    def additional_entry_gate(self, data, round_trip_cost):
        """No additional baseline gate. Candidate economics never widen caps."""
        return True

    def get_executor_config(self, trade_type, price: Decimal, amount: Decimal):
        self._mainnet_connector()
        data = self.processed_data
        return PositionExecutorConfig(
            controller_id=self.config.id, timestamp=self.market_data_provider.time(),
            connector_name=self.config.connector_name, trading_pair=self.config.trading_pair,
            side=trade_type, entry_price=price, amount=amount, leverage=self.config.leverage,
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal(str(data.get("stop_loss", self.config.stop_loss))),
                take_profit=Decimal(str(data.get("take_profit", self.config.take_profit))),
                time_limit=int(data.get("time_limit", self.config.time_limit)),
                open_order_type=OrderType.LIMIT, stop_loss_order_type=OrderType.MARKET,
                take_profit_order_type=OrderType.MARKET, time_limit_order_type=OrderType.MARKET),
        )

    def stop_actions_proposal(self):
        try:
            connector = self._mainnet_connector()
        except (ValueError, KeyError, AttributeError):
            self._halt("mainnet_connector_required")
            return []
        if any(e.is_active for e in self.executors_info):
            try:
                risk = self._account(connector, self.market_data_provider.time())
                if risk["risk_mode"] == "hard_stop":
                    self._halt("competition_hard_stop")
            except (ValueError, KeyError, TypeError, AttributeError, OSError):
                # Never require a healthy entry checkpoint to propose protective exits.
                self._halt("risk_or_account_unavailable")
        if self.processed_data.get("halt") or self.config.manual_kill_switch:
            return [StopExecutorAction(controller_id=self.config.id, executor_id=e.id)
                    for e in self.executors_info if e.is_active]
        adjustment, _ = self._runtime_adjustment()
        direction = self.processed_data.get("signal", 0)
        candidate_exit = None
        if self.config.strategy_profile == "competition_scalp":
            decision = decide(self.processed_data, active=self.config.condor_active)
            candidate_exit = lambda e: exit_signal_reason("competition_scalp", decision, self.processed_data,
                                               1 if e.config.side == TradeType.BUY else -1)
        return [StopExecutorAction(controller_id=self.config.id, executor_id=e.id)
                for e in self.executors_info if e.is_active and (
                    e.id == adjustment.get("close_executor_id")
                    or
                    (not e.is_trading and self.market_data_provider.time() - e.timestamp >= 30)
                    or (e.is_trading and (bool(candidate_exit(e)) if candidate_exit else (not direction or
                        ((direction > 0) != (e.config.side == TradeType.BUY))))))]

    def _update_options_shadow(self, now):
        """Consume only validated fresh public context; failure is advisory only."""
        self.processed_data["spread_plan"] = None
        self.processed_data["options_delta"] = {"status": "unavailable_public_chain", "live_options": False}
        if not self.config.options_signal_enabled:
            return
        try:
            ccy = self.config.trading_pair.split("-")[0]
            if ccy not in ("ETH", "BTC"):
                return
            market = load_market(Path("data") / f"flyby-market-{ccy}.json", now, ccy)
            if not 0 <= now - market["perp"]["timestamp"] <= 5:
                return
            spot = float(market["perp"]["index"])
            quotes, metadata, ivs = [], {}, []
            for raw in market["options"]:
                if not raw["quoted"] or raw.get("delta") is None or not 0 <= now - raw["timestamp"] <= 5:
                    continue
                q, fee = normalize_quote(raw)
                quotes.append(q)
                metadata[q.instrument] = asdict(fee)
            for kind in ("call", "put"):
                qualified = [q for q in market["options"] if q["instrument"] in metadata and q["kind"] == kind
                             and q["pricing"].get("iv") is not None]
                if qualified:
                    ivs.append(min(qualified, key=lambda q: (abs(q["strike"] / spot - 1), q["expiry"]))["pricing"]["iv"])
            forecast = self.processed_data.get("forecast_sigma")
            if not ivs or forecast is None:
                return
            # Uncalibrated IV edge remains a shadow diagnostic, not established alpha.
            self.plan_options(quotes, now, float(forecast) - sum(ivs) / len(ivs),
                              fee_metadata=metadata, option_spot=spot)
        except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError, OSError):
            self.processed_data["spread_plan"] = None
            self.processed_data["options_delta"] = {"status": "invalid_public_chain", "live_options": False}

    def plan_options(self, chain, now, option_iv_edge, *, fee_metadata=None, option_spot=None):
        # A previous plan must never survive a failed account/signal recheck.
        self.processed_data["spread_plan"] = None
        self.processed_data["options_delta"] = {"status": "no_plan", "live_options": False}
        if not self.config.options_signal_enabled:
            return None
        try:
            connector = self._mainnet_connector()
            account = self._account(connector, now)
            if (not account["entry_allowed"] or not account["reconciled"] or not connector.ready
                    or not 0 <= now - self.processed_data.get("updated_at", 0) <= 5
                    or not 0 <= now - connector._user_stream_tracker.last_recv_time <= self.config.max_user_stream_age
                    or now - self._last_book_time > self.config.max_book_age):
                return None
            snapshot = {**self.processed_data, **account, "option_iv_edge": option_iv_edge}
            decision = decide(snapshot, active=self.config.condor_active)
            if decision.option_direction is None or decision.halt:
                return None
            adjustment, runtime_error = self._runtime_adjustment()
            if runtime_error or not runtime_entry_allowed(adjustment, decision.confidence, account["confidence_floor"]):
                return None
            spot = float(snapshot["entry_mid"] if option_spot is None else option_spot)
            if not np.isfinite(spot) or spot <= 0 or abs(spot / float(snapshot["entry_mid"]) - 1) > self.config.max_basis:
                return None
            budget = min(snapshot["available"], snapshot["equity"] * .01, snapshot["risk_trade_budget"])
            budget *= adjustment.get("size_multiplier", 1)
            if budget <= 0:
                return None
            policy = account_policy(spot, max(.01, snapshot["equity"] - budget), scale=snapshot["risk_scale"],
                                    underlying=self.config.trading_pair.split("-")[0],
                                    net_fraction=min(.20, self.config.max_notional_fraction),
                                    gross_fraction=self.config.option_gross_fraction, exposure_profile=self.config.exposure_profile,
                                    committed_gross_quote=snapshot["committed"],
                                    buy_moneyness=self.config.option_buy_moneyness,
                                    buy_target=self.config.option_buy_delta_target,
                                    sell_target=self.config.option_sell_delta_target)
            plan = build_spread(chain, kind=decision.option_direction,
                                underlying=self.config.trading_pair.split("-")[0], now=now,
                                debit_budget=budget,
                                confidence=decision.confidence, delta_policy=policy,
                                fee_fraction=0 if fee_metadata is not None else .001)
            if plan and fee_metadata is not None:
                by_name = {q.instrument: q for q in chain}
                buy = {**asdict(by_name[plan.buy]), "fees": fee_metadata[plan.buy]}
                sell = {**asdict(by_name[plan.sell]), "fees": fee_metadata[plan.sell]}
                plan = costed_plan(buy, sell, now, spot, budget, decision.confidence, policy)
        except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError, OSError):
            self.processed_data["options_delta"]["status"] = "invalid_account_or_delta"
            return None
        self.processed_data["spread_plan"] = plan.to_dict() if plan else None
        self.processed_data["options_delta"] = delta_context(self.processed_data["spread_plan"], now)
        return plan

    def get_custom_info(self):
        """Existing MQTT/API reporting only; native context cannot place orders."""
        path = context_path(self.config.id)
        try:
            context = controller_context(self, self.market_data_provider.time())
            summary = context_summary(context, path)
            try:
                atomic_owned_json(path, context, "flyby_controller_context")
            except (OSError, ValueError, TypeError):
                summary["context_file_status"] = "unavailable"
            return {"flyby": summary}
        except Exception:
            # Advisory reporting must never interrupt execution or protective stops.
            return {"flyby": {"network": "mainnet", "context_status": "unavailable", "live_options": False}}
