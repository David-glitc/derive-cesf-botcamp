# Derive CESF Crash-Mass — Botcamp Agent Builders Cup (Derive)

**Hummingbot V2 controller + Condor agent + SVI + Kelly** for Derive. Max-upside, robust, 48h-tuned.

- `ETH 1h 60d +4.59% 58.5% win -1.5% DD` (live Binance klines)
- `500d regime-sim +24.37% Sharpe 1.72 43tr` (same TP 1.2/1.8 SL 0.48/0.55, half-Kelly 0.08)
- Supports **ATM** (primary, gamma) and **OTM 25Δ** (scalps when smile rich, lower gamma = better Sharpe), **Trend** momentum, **SVI** surfaces per expiry.

## Architecture

```
Binance klines (or Derive WS) → HAR-RV+EWMA → σ_forecast, ε
        → SVI fit per expiry: w(k)=a+b*(ρ(k-m)+sqrt((k-m)²+σ²)) → IV_ATM, IV_25Δ wing, skew
        → CESF crash-mass: tail + kurtosis + vol_cluster + ε → score [0,1]
        → Regime router (agents/condor_agent.py):
            CESF≥0.40 & skew>2 → OTM 25Δ put (TP 1.8 SL 0.55 hold 48h)
            CESF≥0.35 & edge>2.5 vol → ATM put (TP 1.2 SL 0.48 hold 24h)  ← primary
            |mom|>1.2% & CESF low → trend-ride call/put (TP 1.0)
        → Kelly trade sizing: f*=½·edge/ε² capped 0.05/0.08, conf·CESF, $10 min lot
        → PortfolioGuard: gross 240, per-underlying 160, delta 40 vega 25 gamma 5, margin 25%, daily -3% peak -10% (no bypass)
        → PositionExecutor (Hummingbot) 3× leverage
```

## Feeds (Hummingbot-native)

- `candles_connector: binance_perpetual` (default, always available) or `derive`
- `interval: 1h` (ETH primary, best live) or `3m` (BTC secondary)
- Derive WS: `wss://api.lyra.finance/ws` + `spot_feed` → Parquet (see `src/svi` for surface persistence)

## Quick start

```bash
pip install -r requirements.txt

# 1. Backtest (no keys)
python backtest/run_backtest.py --pair ETHUSDT --interval 1h --days 60 --thresh 2.5 --cesf_min 0.40 --plot
# Full stack:
python -c "from src.svi.params import SviParams, iv_from_svi; print(iv_from_svi(0, 0.08, SviParams(0.04,0.12,-0.3,0,0.18)))"
python agents/condor_agent.py  # regime router demo

# 2. Hummingbot V2
cp controllers/directional_trading/derive_cesf_long_vol.py <hummingbot>/controllers/directional_trading/
cp conf/controllers/*.yml <hummingbot>/conf/controllers/
cp conf/scripts/*.yml <hummingbot>/conf/scripts/
# In Hummingbot CLI: create --controller-config directional_trading.derive_cesf_long_vol; start --v2 conf_v2_derive_cesf.yml

# 3. Condor Agent lane (LLM harness)
# agents/condor_agent.py wraps the same controller — LLM picks regime/thresh within bands, never prices.
# See https://condor.hummingbot.org — copy agents/condor_agent.py into your Condor workspace.
```

## Layout

```
controllers/directional_trading/derive_cesf_long_vol.py  # V2 controller (SVI+OTM/ATM+Kelly+Guard)
src/svi/            # SVI params, fit, calendar/butterfly no-arb
src/forecast/       # HAR-RV + EWMA ensemble
src/kelly/          # trade Kelly + portfolio sizing
src/regimes/        # catalog: ATM/OTM/trend/VRP
src/risk/           # PortfolioGuard (single source of truth)
agents/condor_agent.py  # Condor harness — regime router + dual-control bands
backtest/           # Binance kline backtests + sweep
conf/               # ETH 1h primary + BTC 1h secondary + v2 script
strategy.md         # Botcamp submission
```

## Botcamp application

Team **Derive** — https://www.botcamp.xyz/dashboard/hackathons/agent-builders-cup-1
Link repo + `strategy.md`. Code freeze Sep 30, finals Oct 1-2 (48h, $800/agent, P&L+Volume+HBOT).

## Backtest proof

`backtest/result_*.json` — live Binance, reproducible. 1h > 3m for this regime. OTM wings beat ATM when skew steep (put IV > call IV by 2 vol).

