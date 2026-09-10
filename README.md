# Derive CESF Crash-Mass — Botcamp Agent Builders Cup (Derive)

**Hummingbot V2 controller** that trades Derive (and Binance perp as drop-in) on an IV-forecast + CESF crash-mass signal.

- `+4.59% / 58.5% win / -1.5% DD` on ETH 1h 60d (public Binance backtest)
- `+24.37% Sharpe 1.72` on 500d regime-sim (same payoff, TP 1.2 SL 0.48, 24h hold)

Self-contained — no private deps. Candle feed is Hummingbot-native (Binance + Derive WS).

## Quick start

```bash
pip install -r requirements.txt

# Backtest (Binance public klines, no API keys)
python backtest/run_backtest.py --pair ETHUSDT --interval 1h --days 60 --thresh 2.5 --cesf_min 0.40 --plot
python backtest/run_backtest.py --pair BTCUSDT --interval 3m --days 60

# Hummingbot V2
cp controllers/directional_trading/derive_cesf_long_vol.py <hummingbot>/controllers/directional_trading/
cp conf/controllers/*.yml <hummingbot>/conf/controllers/
cp conf/scripts/*.yml <hummingbot>/conf/scripts/
# then in Hummingbot:
# start --v2 conf_v2_derive_cesf.yml
```

## Layout

```
controllers/directional_trading/derive_cesf_long_vol.py  # V2 controller (Binance + Derive feeds)
conf/controllers/conf_derive_cesf_eth.yml                # ETH primary
conf/controllers/conf_derive_cesf_btc.yml                # BTC secondary
conf/scripts/conf_v2_derive_cesf.yml                     # loads both
backtest/run_backtest.py                                 # standalone Binance backtest (Binance WS klines)
strategy.md                                              # Botcamp submission writeup
```

## Botcamp

Apply to **Derive** team at https://www.botcamp.xyz/dashboard/hackathons/agent-builders-cup-1 — link this repo + `strategy.md`. Code freeze Sep 30, finals Oct 1-2 (48h, $800/agent).

## Backtest proof

See `backtest/result_*.json` — generated live from Binance. Re-run with `run_backtest.py` (handles `api.binance.com` 451 via `data-api.binance.vision` fallback).
