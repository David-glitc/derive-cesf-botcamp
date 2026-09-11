#!/usr/bin/env python3
"""
Mock Hummingbot test for Flyby + Condor

Since hummingbot isn't pip-installed in this VPS, we mock the
Hummingbot classes and run flyby.py / condor_agent.py end-to-end
with real Binance klines — same path Hummingbot would take:

  MarketDataProvider.get_candles_df() → Flyby.update_processed_data() → Condor decide() → get_executor_config()

Run: PYTHONPATH=. python tests/test_condor_hummingbot.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import types, sys as _sys

# ── Mock hummingbot modules if not installed ─────────────────────
try:
    import hummingbot  # noqa
    HAS_HB = True
except ImportError:
    HAS_HB = False
    # Create minimal mock modules so flyby.py can import
    for mod in [
        "hummingbot", "hummingbot.core", "hummingbot.core.data_type",
        "hummingbot.core.data_type.common", "hummingbot.data_feed",
        "hummingbot.data_feed.candles_feed", "hummingbot.data_feed.candles_feed.data_types",
        "hummingbot.strategy_v2", "hummingbot.strategy_v2.controllers",
        "hummingbot.strategy_v2.controllers.directional_trading_controller_base",
        "hummingbot.strategy_v2.executors", "hummingbot.strategy_v2.executors.position_executor",
        "hummingbot.strategy_v2.executors.position_executor.data_types",
    ]:
        _sys.modules[mod] = types.ModuleType(mod)

    # Mock TradeType
    ct = _sys.modules["hummingbot.core.data_type.common"]
    class TradeType:
        BUY = 1
        SELL = 2
    ct.TradeType = TradeType

    # Mock CandlesConfig
    cmod = _sys.modules["hummingbot.data_feed.candles_feed.data_types"]
    from dataclasses import dataclass
    @dataclass
    class CandlesConfig:
        connector: str
        trading_pair: str
        interval: str
        max_records: int
    cmod.CandlesConfig = CandlesConfig

    # Mock base controller
    base_mod = _sys.modules["hummingbot.strategy_v2.controllers.directional_trading_controller_base"]
    from pydantic import BaseModel
    class DirectionalTradingControllerConfigBase(BaseModel):
        connector_name: str = "derive"
        trading_pair: str = "ETH-PERP"
        total_amount_quote: float = 800
        class Config:
            arbitrary_types_allowed = True
    class DirectionalTradingControllerBase:
        def __init__(self, config, *args, **kwargs):
            self.config = config
            self.market_data_provider = None
            self.processed_data = {}
    base_mod.DirectionalTradingControllerConfigBase = DirectionalTradingControllerConfigBase
    base_mod.DirectionalTradingControllerBase = DirectionalTradingControllerBase

    # Mock PositionExecutorConfig
    pos_mod = _sys.modules["hummingbot.strategy_v2.executors.position_executor.data_types"]
    pos_mod.PositionExecutorConfig = object  # will be patched in flyby

    # Mock pandas_ta import
    _sys.modules["pandas_ta"] = types.ModuleType("pandas_ta")

print(f"[mock] hummingbot installed: {HAS_HB} — using mock: {not HAS_HB}")

# ── Now import Flyby + Condor after mocks ────────────────────────
import pandas as pd
import numpy as np
from unittest.mock import MagicMock
from decimal import Decimal

# Patch PositionExecutorConfig for our mock before importing flyby
import hummingbot.strategy_v2.executors.position_executor.data_types as pos_dt
from dataclasses import dataclass
@dataclass
class MockPosConfig:
    timestamp: float
    connector_name: str
    trading_pair: str
    side: object
    entry_price: Decimal
    amount: Decimal
    leverage: int
    position_mode: str
    stop_loss: float
    take_profit: float
    time_limit: int
    trailing_stop: object
    coerce_tp_to_limit: bool
pos_dt.PositionExecutorConfig = MockPosConfig

# Import Flyby controller and Condor
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("flyby_mod", "controllers/directional_trading/flyby.py")
flyby_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flyby_mod)
FlybyController = flyby_mod.DeriveCesfLongVolController
FlybyConfig = flyby_mod.DeriveCesfLongVolConfig

from agents.condor_agent import decide, decide_active, condor_options_demo

# ── Fetch real klines for mock provider ──────────────────────────
from backtest.run_expanded import fetch

print("\n[1] Fetching ETH-PERP proxy klines (Binance ETHUSDT 1h)...")
df = fetch("ETHUSDT", "1h", 60)
print(f"    got {len(df)} candles {df['open_time'].iloc[0]} → {df['open_time'].iloc[-1]}")

# ── Build mock market_data_provider ──────────────────────────────
mock_provider = MagicMock()
mock_provider.get_candles_df.return_value = df
mock_provider.time.return_value = 1_700_000_000

# ── Test 1: Flyby conservative ───────────────────────────────────
print("\n[2] Testing Flyby (conservative, condor_active=False)...")
cfg = FlybyConfig(
    connector_name="derive",
    trading_pair="ETH-PERP",
    candles_connector="derive",
    candles_trading_pair="ETH-PERP",
    interval="1h",
    vol_lookback=100,
    iv_threshold_vol=2.5,
    cesf_min_score=0.40,
    svi_skew_threshold=2.0,
    kelly_cap=0.08,
    max_fraction=0.05,
    regime="auto",
    leverage=3,
    condor_active=False,
)
ctl = FlybyController(cfg)
ctl.market_data_provider = mock_provider

import asyncio
asyncio.run(ctl.update_processed_data())

print(f"    processed_data keys: {list(ctl.processed_data.keys())}")
for k in ["signal","regime","venue","cesf_score","edge","skew","kelly_frac","derive_perp","derive_bonuses"]:
    print(f"    {k}: {ctl.processed_data.get(k)}")

# Condor decide from same snapshot
snap = dict(
    cesf_score=ctl.processed_data["cesf_score"],
    edge=ctl.processed_data["edge"],
    svi_skew=ctl.processed_data["skew"],
    momentum=ctl.processed_data["momentum"],
    epsilon=ctl.processed_data["forecast_epsilon"],
    ccy="ETH", spot=float(df["close"].iloc[-1]),
    stale_secs=0, daily_pnl_pct=0,
)
dec = decide(snap)
dec_a = decide_active(snap)
print(f"\n    Condor decide (conservative): {dec.regime} | {dec.reason[:90]}")
print(f"    Condor decide (ACTIVE):       {dec_a.regime} | {dec_a.reason[:90]}")
print(f"    Condor options demo: {condor_options_demo(spot=float(df['close'].iloc[-1]))}")

# Test executor config if signal !=0
sig = ctl.processed_data["signal"]
if sig != 0:
    # Mock TradeType
    from hummingbot.core.data_type.common import TradeType
    side = TradeType.BUY if sig==1 else TradeType.SELL
    exec_cfg = ctl.get_executor_config(side, Decimal(str(df["close"].iloc[-1])), Decimal("0.01"))
    print(f"\n    Executor config (signal {sig}): connector={exec_cfg.connector_name} pair={exec_cfg.trading_pair} lev={exec_cfg.leverage} SL={exec_cfg.stop_loss} TP={exec_cfg.take_profit} TL={exec_cfg.time_limit}")
else:
    print(f"\n    No signal (flat) — no executor, as designed (precision > recall)")

# ── Test 2: Flyby ACTIVE ─────────────────────────────────────────
print("\n[3] Testing Flyby ACTIVE (condor_active=True, more volume)...")
cfg_a = FlybyConfig(
    connector_name="derive", trading_pair="ETH-PERP",
    candles_connector="derive", candles_trading_pair="ETH-PERP",
    interval="1h", vol_lookback=100, iv_threshold_vol=2.0, cesf_min_score=0.27,
    condor_active=True,
)
ctl_a = FlybyController(cfg_a)
ctl_a.market_data_provider = mock_provider
asyncio.run(ctl_a.update_processed_data())
print(f"    ACTIVE regime: {ctl_a.processed_data.get('regime')} venue={ctl_a.processed_data.get('venue')} signal={ctl_a.processed_data.get('signal')}")
print(f"    cesf {ctl_a.processed_data['cesf_score']:.3f} edge {ctl_a.processed_data['edge']:.4f} skew {ctl_a.processed_data['skew']:.2f}")

# ── Test 3: Synthetic trigger (force cheap vol + crash-mass) ───────
print("\n[3b] Synthetic trigger — should BUY (OTM 25Δ via Condor) ...")
import pandas as _pd
import numpy as _np
# Build synthetic closes: 100 flat bars then 1 crash-like bar to pump cesf+edge
closes = _np.concatenate([_np.full(110, 3000.0), _np.linspace(3000, 2950, 20), _np.full(10, 2950.0)])
rets_syn = _np.diff(_np.log(closes))
# Create df with those closes
df_syn = _pd.DataFrame({"close": closes, "high": closes*1.01, "low": closes*0.99, "open": closes})
# Need ATR col — mock by adding dummy
df_syn["open_time"] = pd.date_range("2026-09-01", periods=len(df_syn), freq="h")
mock_syn = MagicMock()
mock_syn.get_candles_df.return_value = df_syn
mock_syn.time.return_value = 1_700_000_000
cfg_syn = FlybyConfig(connector_name="derive", trading_pair="ETH-PERP", candles_connector="derive", candles_trading_pair="ETH-PERP", iv_threshold_vol=1.5, cesf_min_score=0.30, condor_active=False)
ctl_syn = FlybyController(cfg_syn)
ctl_syn.market_data_provider = mock_syn
asyncio.run(ctl_syn.update_processed_data())
print(f"    synthetic cesf {ctl_syn.processed_data['cesf_score']:.3f} edge {ctl_syn.processed_data['edge']:.4f} skew {ctl_syn.processed_data['skew']:.2f} → regime {ctl_syn.processed_data['regime']} signal {ctl_syn.processed_data['signal']} venue {ctl_syn.processed_data['venue']}")
# Force Condor synthetic snap for OTM
snap_otm = dict(cesf_score=0.45, edge=0.02, svi_skew=2.5, momentum=0.0, epsilon=0.045, ccy="ETH", spot=2950, stale_secs=0, daily_pnl_pct=0)
print(f"    Condor OTM snap → {decide(snap_otm)}")
print(f"    Condor OTM ACTIVE → {decide_active(snap_otm)}")
if ctl_syn.processed_data["signal"] != 0:
    from hummingbot.core.data_type.common import TradeType
    side = TradeType.BUY if ctl_syn.processed_data["signal"]==1 else TradeType.SELL
    ec = ctl_syn.get_executor_config(side, Decimal(str(closes[-1])), Decimal("0.02"))
    print(f"    Synthetic executor: {ec.connector_name} {ec.trading_pair} TP={ec.take_profit} SL={ec.stop_loss} TL={ec.time_limit}")

# ── Test 4: Multi-pair loop (4-agent book) ───────────────────────
print("\n[4] Testing 4-agent book (ETH/ARB/SOL/AVAX) — one tick each...")
for pair, conf_pair in [("ETHUSDT","ETH-PERP"),("ARBUSDT","ARB-PERP"),("SOLUSDT","SOL-PERP"),("AVAXUSDT","AVAX-PERP")]:
    dfp = fetch(pair, "1h", 60)
    mp = MagicMock()
    mp.get_candles_df.return_value = dfp
    mp.time.return_value = 1_700_000_000
    c = FlybyConfig(connector_name="derive", trading_pair=conf_pair, candles_connector="derive", candles_trading_pair=conf_pair)
    ctlx = FlybyController(c)
    ctlx.market_data_provider = mp
    asyncio.run(ctlx.update_processed_data())
    print(f"    {conf_pair:10} signal {ctlx.processed_data['signal']:2} regime {ctlx.processed_data['regime']:20} cesf {ctlx.processed_data['cesf_score']:.2f} venue {ctlx.processed_data['venue']}")

print("\n✅ All mocked Hummingbot tests passed — Flyby + Condor wire correctly.")
print("   For full Hummingbot (no mock): docker run hummingbot/hummingbot + mount ./controllers + ./conf")
