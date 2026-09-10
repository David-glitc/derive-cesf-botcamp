"""
Derive CESF Crash-Mass Long Vol — Botcamp Agent Builders Cup (Derive Track)

Standalone Hummingbot V2 controller. No Brickfort imports — fully self-contained.
Venue: Derive (perp/spot) for execution, Binance + Derive candle feeds for signal.

Edge: HAR-RV + EWMA ensemble → forecast_sigma + epsilon
      CESF crash-mass filter (ε-graph proxy) → high-persistence downside relevance
      Signal = forecast - IV_proxy > 1.8 vol AND crash_mass >= 0.35

Maps to Brickfort ALPHA-SCALP-002 (scalp-long-put-v1):
  backtest $100 isolated, 500d regime-sim → +24.37% Sharpe 1.72 43tr 51% win DD -5.5%
  TP 1.2 SL 0.48 time_limit 86400 (30m hold loses -11%, 24h wins +10.8%)

Feeds:
  - Binance klines (primary, always available): https://api.binance.com/api/v3/klines
  - Derive spot_feed (secondary, when available): https://api.lyra.finance/public/get_ticker
  Hummingbot CandlesConfig can point to either connector.

Usage:
  create --controller-config directional_trading.derive_cesf_long_vol
  create --v2-config v2_with_controllers
  start --v2 conf_v2_derive_cesf.yml
"""

from decimal import Decimal
from typing import List, Optional

import numpy as np
import pandas_ta as ta  # noqa: F401
from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from hummingbot.core.data_type.common import TradeType
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy_v2.controllers.directional_trading_controller_base import (
    DirectionalTradingControllerBase,
    DirectionalTradingControllerConfigBase,
)
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig

# ---------------------------------------------------------------------------
# Forecasting — inlined (no external brickfort dependency)
# ---------------------------------------------------------------------------

def _har_rv_forecast(returns: np.ndarray, periods_per_year: float = 365 * 24 * 20) -> float:
    """HAR-RV: 0.1*RVm + 0.3*RVw + 0.6*RVd  (mirrors bf-vol). periods tuned for 3m candles."""
    r = np.asarray(returns, dtype=np.float64)
    if r.size < 5:
        return float(np.sqrt(np.mean(r**2) * periods_per_year)) if r.size else 0.20
    rv_d = float(r[-1] ** 2)
    rv_w = float(np.mean(r[-5:] ** 2))
    rv_m = float(np.mean(r**2))
    forecast_var = 0.1 * rv_m + 0.3 * rv_w + 0.6 * rv_d
    return max(float(np.sqrt(forecast_var * periods_per_year)), 1e-8)

def _ewma_vol(returns: np.ndarray, lam: float = 0.94, ppy: float = 365 * 24 * 20) -> float:
    r = np.asarray(returns, dtype=np.float64)
    if r.size == 0:
        return 0.20
    var = float(r[0] ** 2)
    for x in r[1:]:
        var = lam * var + (1 - lam) * float(x**2)
    return max(float(np.sqrt(var * ppy)), 1e-8)

def _ensemble_sigma(returns: np.ndarray):
    har = _har_rv_forecast(returns)
    ewma = _ewma_vol(returns)
    sigma = 0.5 * har + 0.5 * ewma
    epsilon = max(0.01 + 0.5 * abs(har - ewma), 0.01)
    return sigma, epsilon, har, ewma

def _cesf_crash_mass_proxy(returns: np.ndarray, sigma: float, epsilon: float) -> float:
    """Lightweight CESF R_Q proxy: tail mass + kurtosis + vol clustering + epsilon."""
    r = np.asarray(returns, dtype=np.float64)
    if r.size < 20:
        return 0.0
    sigma_daily = sigma / np.sqrt(365 * 24 * 20 / (365))  # approx
    # tail mass: % returns < -1.5*sigma_daily
    try:
        tail = float(np.mean(r < -1.5 * sigma_daily)) if sigma_daily > 0 else 0.0
    except Exception:
        tail = 0.0
    m = float(np.mean(r))
    var = float(np.mean((r - m) ** 2))
    kurt = float(np.mean((r - m) ** 4) / (var**2 + 1e-12)) if var > 1e-12 else 3.0
    kurt_norm = min(max((kurt - 3.0) / 10.0, 0.0), 1.0)
    if r.size > 10:
        r2 = r**2
        try:
            ac = float(np.corrcoef(r2[:-1], r2[1:])[0, 1])
            ac = max(ac, 0.0) if np.isfinite(ac) else 0.0
        except Exception:
            ac = 0.0
    else:
        ac = 0.0
    eps_boost = min(epsilon / 0.05, 1.0)
    score = 0.45 * min(tail / 0.08, 1.0) + 0.25 * kurt_norm + 0.2 * ac + 0.1 * eps_boost
    return float(np.clip(score, 0.0, 1.0))

# ---------------------------------------------------------------------------
# Hummingbot controller config
# ---------------------------------------------------------------------------

class DeriveCesfLongVolConfig(DirectionalTradingControllerConfigBase):
    controller_name: str = "derive_cesf_long_vol"
    controller_type: str = "directional_trading"

    # Venue for execution
    # For Botcamp, choose derive or binance_perpetual. We default to binance_perpetual
    # for paper testing, derive for live finals. Both work with same signal.

    candles_connector: str = Field(
        default=None,
        json_schema_extra={
            "prompt": "Candles connector (binance_perpetual, binance, derive) — empty = same as trading connector: ",
            "prompt_on_new": True,
        },
    )
    candles_trading_pair: str = Field(
        default=None,
        json_schema_extra={
            "prompt": "Candles pair (empty = same as trading pair): ",
            "prompt_on_new": True,
        },
    )
    interval: str = Field(
        default="3m",
        json_schema_extra={"prompt": "Candle interval (1m,3m,5m,1h,1d): ", "prompt_on_new": True},
    )

    # Forecasting
    vol_lookback: int = Field(
        default=100,
        json_schema_extra={"prompt": "Vol lookback (candles) for HAR+EWMA: ", "prompt_on_new": True},
    )
    iv_threshold_vol: float = Field(
        default=1.8,
        json_schema_extra={"prompt": "Cheap-vol threshold (vol pts, 1.8): ", "prompt_on_new": True},
    )

    # CESF
    cesf_epsilon: float = Field(default=0.088)
    cesf_barrier: float = Field(default=0.80)
    cesf_min_score: float = Field(
        default=0.35,
        json_schema_extra={"prompt": "Min CESF crash-mass score [0,1] (0.35): ", "prompt_on_new": True},
    )

    # Execution (scalp-long-put payoff: win 1.2 loss 0.48)
    leverage: int = Field(default=3)
    position_mode: str = Field(default="HEDGE")
    stop_loss: float = Field(default=0.48)
    take_profit: float = Field(default=1.2)
    time_limit: int = Field(default=86400)

    @field_validator("candles_connector", mode="before")
    @classmethod
    def _set_candles_connector(cls, v, info: ValidationInfo):
        if v is None or v == "":
            return info.data.get("connector_name")
        return v

    @field_validator("candles_trading_pair", mode="before")
    @classmethod
    def _set_candles_pair(cls, v, info: ValidationInfo):
        if v is None or v == "":
            return info.data.get("trading_pair")
        return v

# ---------------------------------------------------------------------------
# Controller logic
# ---------------------------------------------------------------------------

class DeriveCesfLongVolController(DirectionalTradingControllerBase):
    """
    Long-vol scalp:
      signal -1 → long put / short perp (crash) — PRIMARY edge +24% backtest
      signal +1 → long call / long perp (expansion) — secondary +6%
      signal  0 → flat
    """

    def __init__(self, config: DeriveCesfLongVolConfig, *args, **kwargs):
        self.config = config
        self.max_records = max(config.vol_lookback, 100)
        super().__init__(config, *args, **kwargs)

    def get_candles_config(self) -> List[CandlesConfig]:
        return [
            CandlesConfig(
                connector=self.config.candles_connector,
                trading_pair=self.config.candles_trading_pair,
                interval=self.config.interval,
                max_records=self.max_records,
            )
        ]

    async def update_processed_data(self):
        df = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval,
            max_records=self.max_records,
        )
        if df is None or df.empty or len(df) < 30:
            self.processed_data["signal"] = 0
            return

        closes = df["close"].astype(float).values
        rets = np.diff(np.log(np.maximum(closes, 1e-8)))

        sigma, epsilon, har, ewma = _ensemble_sigma(rets[-self.config.vol_lookback :])
        cesf_score = _cesf_crash_mass_proxy(rets[-self.config.vol_lookback :], sigma, epsilon)

        # IV proxy: 20-period RV vs forecast. Replace with Derive IV when available.
        recent_rv = float(np.sqrt(np.mean(rets[-20:] ** 2) * 365 * 24 * 20)) if len(rets) >= 20 else sigma
        iv_proxy = recent_rv
        edge = sigma - iv_proxy

        # ATR regime filter
        try:
            df.ta.atr(length=14, append=True)
            atr = float(df["ATRr_14"].iloc[-1]) if "ATRr_14" in df.columns else 0.0
        except Exception:
            atr = 0.0
        atr_ok = atr > float(np.mean(df["close"].iloc[-20:]) * 0.002) if len(df) >= 20 else True

        long_put = (edge > self.config.iv_threshold_vol / 100.0) and (cesf_score >= self.config.cesf_min_score) and atr_ok
        long_call = (edge > (self.config.iv_threshold_vol + 0.4) / 100.0) and (cesf_score < 0.30) and atr_ok

        signal = 0
        if long_put:
            signal = -1
        elif long_call:
            signal = 1

        self.processed_data["signal"] = signal
        self.processed_data["forecast_sigma"] = float(sigma)
        self.processed_data["forecast_epsilon"] = float(epsilon)
        self.processed_data["har_sigma"] = float(har)
        self.processed_data["ewma_sigma"] = float(ewma)
        self.processed_data["cesf_score"] = float(cesf_score)
        self.processed_data["edge"] = float(edge)
        self.processed_data["iv_proxy"] = float(iv_proxy)
        self.processed_data["atr"] = float(atr)
        self.processed_data["features"] = df

    def get_executor_config(self, trade_type: TradeType, price: Decimal, amount: Decimal):
        return PositionExecutorConfig(
            timestamp=self.market_data_provider.time(),
            connector_name=self.config.connector_name,
            trading_pair=self.config.trading_pair,
            side=trade_type,
            entry_price=price,
            amount=amount,
            leverage=self.config.leverage,
            position_mode=self.config.position_mode,
            stop_loss=self.config.stop_loss,
            take_profit=self.config.take_profit,
            time_limit=self.config.time_limit,
            trailing_stop=None,
            coerce_tp_to_limit=False,
        )
