# Flyby — Derive CESF Long Vol (Agent Builders Cup — Derive)

**Team:** Derive · **Agent:** Flyby · **Type:** Hummingbot V2 Controller + Condor Agent  
**Venue:** Derive **spot + perps (ETH-PERP, BTC-PERP, SOL-PERP, AVAX-PERP)** + **options (Black76 + SVI)** — *all Derive native*  
**Capital:** $800 / agent · **Universe:** 8 pairs (BTC / ETH / SOL / BNB / AVAX / ARB / OP / ADA) · **Interval:** `1h` (primary)  

> **Derive scoring — all 4 bonuses hit**

| Criterion | Flyby implementation | File | Status |
|---|---|---|---|
| **Spot / Perp on Derive** | `connector_name: derive` · `ETH-PERP / BTC-PERP / SOL-PERP / AVAX-PERP` (USDC-settled) · Candles `derive` WS `spot_feed.{CCY}` + `orderbook.{inst}.1.10` `wss://api.lyra.finance/ws` · Binance klines only backtest proxy | `conf_flyby_*.yml` `controllers/directional_trading/flyby.py` | ✅ |
| **Options via Condor (bonus)** | `agents/condor_agent.py:decide()` OTM 25Δ alongside perps · `POST /public/get_ticker` → `k=log(K/F)` `w=iv²τ` → `fit_svi_slice()` → `iv_from_svi()` → `Black76(F,K,τ7d)` `TP1.8 SL0.55 48h` · `options +159% avg` | `agents/condor_agent.py` `src/svi/` `src/pricing/black76.py` | ✅ |
| **Multi-collateral (bonus)** | `CollateralVault` `USDC 40% + ETH 30% + BTC 15% + HYPE 10% + kHYPE 5%` haircuts `0 / 10 / 10 / 15 / 15%` → `effective` vs USDC-only `+60%` headroom · spot rebalance `ETH-USDC` | `src/collateral/multi_collateral.py` | ✅ |
| **Portfolio margin (bonus)** | `GuardConfig 10% gross + 2% vega` on **NET** `Δ / ν / Γ` vs `50%` isolated · `long spot +0.3 + short PERP -0.5 + long put +0.25 → net -0.25 vs gross 1.05` → `60%` less margin | `src/risk/portfolio_guard.py` | ✅ |

**Author:** David Pere · **Repo:** https://github.com/David-glitc/flyby · **Freeze:** Sep 30 · **Finals:** Oct 1–2 (48h, 800$, P&L+Volume+HBOT)

---

## One-line pitch

Buy cheap volatility — when vol is cheap *and* downside is real, we buy puts. Else we sit.

- **Primary:** `long 25Δ put OTM` when smile rich (best Sharpe)
- **Fallback:** `ATM put` + `trend-ride` when edge large

> **Perps = proxy. Options = execution.** Same signal, true convexity: `$10` premium controls `$3k` notional → `2%` drop → `~200%` premium vs `6%` perp 3×.

---

## Architecture

![Flowchart](https://raw.githubusercontent.com/David-glitc/flyby/master/flowchart.png)

```
Binance klines ─┐
Derive WS       ─┤→ HAR 0.1·RVm+0.3·RVw+0.6·RVd + EWMA λ=0.94 → σ, ε
                → SVI w(k)=a+b(ρ(k-m)+√((k-m)²+σ²)) → IV_ATM, IV_25Δ, skew
                → CESF proxy score [0,1] → edge = σ - IV_SVI
                → Condor decide() → regime (OTM/ATM/trend/strangle) → Kelly f* → Guard → Derive perp 3× / options Black76 τ7d
```

**Derive wiring:** `https://api.lyra.finance` `POST /public/get_all_instruments` → `POST /public/get_ticker` → `k, w` → `fit_svi_slice` 600it `g≥0` + calendar → `iv_from_svi` → `Black76`. Live verified `ETH 20260911 τ0.003 n8 a0.0008`.

---

## Edge — three layers + sizing

### 1. SVI surface — per expiry
`src/svi/` Gatheral SVI `w(k)=a+b(ρ(k-m)+√((k-m)²+σ²))`, `k=log(K/F)`, `w=iv²τ`. 600it butterfly `g≥0` + calendar `w_later≥w_earlier`. Gives `IV_ATM (k=0)`, `IV_25Δ (k≈±0.3)`, `skew=put25-call25`.

### 2. Forecast — HAR-RV + EWMA
`src/forecast/ensemble.py` `HAR 0.1·RVm+0.3·RVw+0.6·RVd` (22/5/1d) + `EWMA λ=0.94` → `σ_forecast=0.5·HAR+0.5·EWMA`, `ε=0.01+0.5·|HAR-EWMA|`.

### 3. Signal
`edge = σ_forecast - IV_SVI_ATM`

| Regime | Condition | Action |
|---|---|---|
| **OTM put** | `edge>1.8 vol` & `score≥0.40` & `skew>2` | buy 25Δ put `TP1.8 SL0.55 48h` |
| **ATM put** | `edge>2.5 vol` & `score≥0.35` & `ATR ok` | buy ATM put `TP1.2 SL0.48 24h` (or short perp) |
| **Trend** | `|mom 24×1h|>1.2%` & `score<0.30` | trend-ride put/call `TP1.0 12h` |

ACTIVE mode (finals): `strangle` when vol expansion `ε>0.04` + lower thresholds for volume.

**Kelly + Guard** `f*=0.5·edge/ε²·conf` `conf=score/0.35` cap `0.05/0.08` $10 min. `PortfolioGuard gross240 per160 Δ40 ν25 Γ5 margin25% daily-3% peak-10%` — no bypass, 1 pos at a time, `3×` leverage.

> *Side note — CESF:* Flyby uses a fast **interpretation** of your **Causal Event Space Framework** (Pere, Aug 2026, `/CESF/CESF.pdf`) — not the full `G_{ε,H} → R_Q` pipeline, but its spirit. CESF compresses infinite futures `Ω_H` into finite operational `E_H(Q)` under `ε=0.088, H=42`; Flyby compresses before pricing — `score=0.45tail+0.25kurt+0.2cluster+0.1ε` filters noisy vol so the SVI/Black76 surface we price on is the *relevant, smoother* one. Keeps the glossary honest and the surface clean.

---

## Backtest — unseen holds

*Live Binance klines, 1h 60d 1440 bars, 800$ start, fee 0.06% + 0.8% half-spread + 5bps, PIT 1-bar lag `close i → fill open i+1`, WFA 60/40, Guard.*

| Pair | Perps best | Ret | Tr | Win | DD | Options best | Ret | DD |
|---|---|---|---|---|---|---|---|---|
| **ARBUSDT** | `2.0/0.35` | **+4.23%** | 43 | 47% | -4.3% | `2.5/0.40` | +106% | -8% |
| **AVAXUSDT** | `2.5/0.40` | **+2.66%** | 42 | 50% | **-0.83%** | `2.0/0.40` | **+439%** | -7% |
| **ETHUSDT** | `2.0/0.40` | **+3.53%** | 42 | 45% | -1.3% | `2.0/0.40` | +152% | -10% |
| SOLUSDT | `2.5/0.40` | +2.33% | 44 | 52% | -1.4% | `2.5/0.40` | +118% | -10% |
| **Universe avg (8)** | — | **+1.73%** | — | — | — | **+159%** | — | — |

**WFA ETH 1h 60d 2.5/0.40:** `IS 13.2% Sh1.92 DD-1.4% → OOS 20.9% Sh3.79 DD-0.4% → ALL 15.8% Sh2.45` — OOS > IS, not overfit.  
**Unseen checks:** `90d +1.97% avg / 450% AVAX` · `120d OOS +23% vs IS -8%` — same 60d window *was* OOS in the 120d cut.

**Visuals**

![Confusion](https://raw.githubusercontent.com/David-glitc/flyby/master/backtest/confusion.png)
![Heatmap](https://raw.githubusercontent.com/David-glitc/flyby/master/backtest/heatmap.png)
![Equity](https://raw.githubusercontent.com/David-glitc/flyby/master/backtest/equity.png)
![Options vs Perps](https://raw.githubusercontent.com/David-glitc/flyby/master/backtest/options_vs_perps.png)
![WFA](https://raw.githubusercontent.com/David-glitc/flyby/master/backtest/standard_wfa.png)

---

## Wired to Hummingbot — no gaps

```
controllers/directional_trading/flyby.py (alias derive_cesf_long_vol.py) — 255 lines, portable
  ├─ get_candles_config() → CandlesConfig(derive, ETH-PERP, 1h, 100)
  ├─ update_processed_data() → ensemble → cesf proxy → SVI skew → Kelly → signal+regime+venue
  └─ get_executor_config() → PositionExecutor 3× (TP/SL by regime, derive perp or options hint)
```

| File | What | Why |
|---|---|---|
| `controllers/directional_trading/flyby.py` | V2 controller (Flyby) | Hummingbot loads this |
| `conf_flyby_*.yml` | 4 configs `eth/arb/sol/avax 1h` | $800 each, WFA proven |
| `conf/scripts/conf_v2_flyby.yml` | `v2_with_controllers` | 4-agent book = `10%+` |
| `src/collateral/` `src/risk/` `src/svi/` `src/pricing/` | Vault, Guard, SVI, Black76 | Derive bonuses, no private deps |
| `agents/condor_agent.py` | Condor `decide()` | LLM picks regime, never prices |
| `backtest/` | `run_*` + `harness` + plots | Reproducible, PIT, WFA |
| `flowchart.png` | 12-step 300dpi | Video + docs |

---

## Run it

```bash
pip install -r requirements.txt

# Perps proxy (Guard-capped)
python backtest/run_backtest.py --pair ETHUSDT --interval 1h --days 60 --thresh 2.5 --cesf_min 0.40 --plot
# Expanded 8-pair + plots
PYTHONPATH=. python backtest/run_expanded.py
# WFA
PYTHONPATH=. python backtest/run_standard.py --pair ETHUSDT --interval 1h --days 60
# Live Derive SVI
PYTHONPATH=. python src/venue/derive.py
# Condor demo
python -c "from agents.condor_agent import condor_options_demo; print(condor_options_demo())"

# Hummingbot V2
cp controllers/directional_trading/flyby.py <hummingbot>/controllers/directional_trading/
cp conf/controllers/conf_flyby_*.yml <hummingbot>/conf/controllers/
cp conf/scripts/conf_v2_flyby.yml <hummingbot>/conf/scripts/
# CLI: create --controller-config directional_trading.flyby; start --v2 conf_v2_flyby.yml
```

*CESF ε=0.088 H=42 barrier 0.80 proxy40/event30 · SVI no-arb · Kelly half + Guard · PIT WFA 60/40*
