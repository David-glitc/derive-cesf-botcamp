# Derive CESF Crash-Mass Long Vol — Agent Builders Cup (Derive Track)

**Team:** Derive · **Agent type:** Hummingbot V2 Controller (`directional_trading.derive_cesf_long_vol`)
**Venue:** Derive (execution) + Binance/Derive candle feeds (signal) · **Capital:** $800 · **Interval:** 1h (primary) / 3m (secondary)
**Author:** David Pere · **Code freeze:** Sep 30 · **Finals:** Oct 1-2 (48h)

---

## 1. One-line pitch

Buy cheap volatility when the forecast (HAR-RV + EWMA) exceeds implied vol **and** the CESF crash-mass score says downside futures are operationally distinguishable. Primary trade is **long put / short perp** (crash), secondary is **long call** (expansion). No LLM in the loop.

## 2. Edge

**SVI surface (per expiry):** `w(k)=a+b*(ρ(k-m)+sqrt((k-m)²+σ²))` → IV_ATM, IV_25Δ wing, skew. Fit via coordinate descent, butterfly `g≥0` + calendar `w_later≥w_earlier` no-arb, `repair_calendar` bumps `a`. ATM vs OTM 25Δ: OTM lower gamma, better Sharpe when skew steep (put IV > call IV by 2 vol) → TP 1.8 SL 0.55 hold 48h; ATM TP 1.2 SL 0.48 hold 24h.

**Volatility ensemble (forecast):**
```
HAR: 0.1·RV_m + 0.3·RV_w + 0.6·RV_d  (1d/5d/22d realized variance)
EWMA: λ=0.94
σ_forecast = 0.5·σ_HAR + 0.5·σ_EWMA,   ε = 0.01 + 0.5·|σ_HAR - σ_EWMA|
```
Every forecast carries its own uncertainty ε.

**CESF filter (relevance):**
```
Ω_H (2000 paths) → Γ_H(C, maxDD 0.60) → G_{ε,H} (ε=0.088) → components
→ R̃_Q proxy (barrier 0.80) → R_Q persistence → score ∈[0,1]

score = 0.45·tail(1.5σ) + 0.25·kurtosis_norm + 0.2·vol_cluster + 0.1·ε_boost
```
Calibrated to CESF defaults (H=42, ε=0.088, barrier 0.80, proxy 40th pct, event 30th pct).

**Signal:**
```
edge = σ_forecast − IV_proxy   (IV_proxy = 20-period RV; replace with Derive IV when live)
long_put  if edge > thresh/100  && score ≥ cesf_min  && ATR regime ok   → short perp
long_call if edge > (thresh+0.4)/100 && score < 0.30 && ATR regime ok   → long perp
thresh = 1.8–2.5 vol pts (tuned), cesf_min = 0.35–0.40
```

**Execution:** `PositionExecutor`, 1 position at a time, `TP 1.2× SL 0.48× time_limit 86400s` (24h). 30m hold loses ~11% at every equity tier; 24h hold is required. Risk: 5% equity, half-Kelly capped 8%, notional $10–$240, leverage 3×.

## 3. Why this beats the alternatives

Live Binance backtest (public, reproducible: `python backtest/run_backtest.py`):

| Pair | Interval | Days | Thresh | CESF | Return | Trades | Win | DD |
|---|---|---|---|---|---|---|---|---|
| **ETHUSDT** | **1h** | **60** | **2.5** | **0.40** | **+4.59%** | 41 | 58.5% | **-1.5%** |
| ETHUSDT | 1h | 60 | 2.0 | 0.45 | +3.55% | 42 | 52% | -1.5% |
| BTCUSDT | 3m | 60 | 1.8 | 0.35 | +1.57% | 28 | 50% | -1.9% |
| ETHUSDT | 1h | 180 | 1.8 | 0.35 | -1.95% | 146 | 44% | -8.1% |
| ETHUSDT | 3m | 60 | 1.8 | 0.35 | -7.83% | 42 | 45% | -8.6% |
| BTCUSDT | 1h | 180 | 1.5 | 0.35 | -10.8% | 144 | 45% | -11.8% |

Private regime-sim (500d, $100 isolated, same payoff, TP/SL 1.2/0.48): `scalp-long-put-v1 +24.37% Sharpe 1.72 43tr 51% win DD -5.5%` — the only regime that clears the 30-obs Bayesian promote gate. `VRP straddle` is -3.29% at 3 trades (halt-constrained), `arb-pcp` is 1 trade/500d (zero volume → loses Volume rank).

**For a 48h finals, you need both P&L and Volume.** Long-vol is the only bucket with positive expectancy *and* turnover. ETH 1h is the sweet spot: high win rate, tiny drawdown, ~0.7 trades/day.

## 4. Venue specificity (Derive)

- **Execution:** Derive perp (`derive` connector). For paper, `binance_perpetual` is drop-in (same signal, same leve 3×).
- **Candle feed:** `candles_connector` = `binance_perpetual` (always available) or `derive` (when its WS is live). Controller is feed-agnostic — Hummingbot `CandlesConfig` handles both.
- **Options angle:** Signal originates from options IV forecasting (Derive is an options venue). Synthetic long put = short perp; when Derive options connector is live, replace perp with `buy ATM put`.

## 5. Run it

```bash
# Backtest (public Binance klines, no keys needed)
pip install -r requirements.txt
python backtest/run_backtest.py --pair ETHUSDT --interval 1h --days 60 --thresh 2.5 --cesf_min 0.40 --plot

# Hummingbot V2 (copy into your Hummingbot instance)
cp controllers/directional_trading/derive_cesf_long_vol.py <hummingbot>/controllers/directional_trading/
cp conf/controllers/*.yml <hummingbot>/conf/controllers/
cp conf/scripts/*.yml <hummingbot>/conf/scripts/
# In Hummingbot CLI:
# create --controller-config directional_trading.derive_cesf_long_vol  (or use the ymls)
# start --v2 conf_v2_derive_cesf.yml
# status --live
```

Configs:
- `conf/controllers/conf_derive_cesf_eth.yml` — ETH-USDT (primary, 1h, thresh 2.5)
- `conf/controllers/conf_derive_cesf_btc.yml` — BTC-USDT (secondary, 1h, thresh 1.8)
- `conf/scripts/conf_v2_derive_cesf.yml` — loads both (2 agents = Derive team size)

## 6. Risk

- One position, 24h max, hard TP/SL, daily halt -3% peak -10% (Botcamp allows more, we stay tighter).
- Deterministic only — LLM (Condor) may propose `thresh`/`cesf_min` but never prices options or places orders.

## 7. Roadmap if selected

Week 1: paper on Derive testnet, 48h dry run, tune `cesf_min` 0.35→0.40 on live tail.
Week 2: wire true Derive IV (orderbook mid IV) to replace `IV_proxy = 20d RV`.
Finals: ETH + BTC as Derive’s two seats — combined Volume + P&L.

---
*CESF: ε=0.088 H=42 barrier 0.80 — causal event space reduction to operational, persistence-filtered futures.*
