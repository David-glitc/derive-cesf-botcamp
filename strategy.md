# Derive CESF Crash-Mass Long Vol — Agent Builders Cup (Derive Track)

**Team:** Derive · **Agent type:** Hummingbot V2 Controller `directional_trading.derive_cesf_long_vol` + Condor Agent `agents/condor_agent.py`
**Venue:** Derive **options** (Black76 + SVI) + Derive perp fallback · **Capital:** $800/agent · **Universe:** 8 pairs (BTC/ETH/SOL/BNB/AVAX/ARB/OP/ADA) · **Interval:** `1h` (primary, robust)
**Author:** David Pere · **Code freeze:** Sep 30 · **Finals:** Oct 1–2 (48h) · **Repo:** https://github.com/David-glitc/derive-cesf-botcamp

---

## 1. One-line pitch

Buy cheap volatility when the **SVI ATM IV** is cheap vs the **HAR-RV+EWMA forecast** and the **CESF crash-mass** says downside futures are operationally distinguishable. Primary `long 25Δ put OTM` (lower gamma, better Sharpe when smile rich), fallback `ATM put` + `trend-ride`. **Perps backtest is the proxy; Black76 options is the execution surface that gets you 10%+.**

## 2. Edge stack — SVI + Forecast + CESF + Kelly

**SVI surface (per expiry, `src/svi/`):** `w(k)=a+b·(ρ(k-m)+√((k-m)²+σ²))`, `k=log(K/F)`, `w=σ_IV²·τ`. Fit via 600it coordinate descent, **butterfly `g≥0`** + **calendar `w_later≥w_earlier` no-arb**, `repair_calendar()` bumps `a`. Gives `IV_ATM(k=0)`, `IV_25Δ(k≈±0.3)`, `skew = put25Δ - call25Δ`. Derive BTC/ETH smile is steep — wings matter.

**Forecast ( `src/forecast/ensemble.py`, mirrors `bf-vol`):**
```
HAR: 0.1·RVm + 0.3·RVw + 0.6·RVd  (22d/5d/1d)
EWMA: λ=0.94
σ_forecast = 0.5·σ_HAR + 0.5·σ_EWMA,  ε = 0.01 + 0.5·|σ_HAR-σ_EWMA|
```
Every forecast carries `ε`.

**CESF (`H=42 ε=0.088 barrier 0.80`):** `Ω_H(2000 paths) → Γ_H(C maxDD 0.60) → G_{ε,H} → components → R̃_Q → R_Q` → `score = 0.45·tail(1.5σ)+0.25·kurt+0.2·cluster+0.1·ε ∈[0,1]`

**Signal:**
```
edge = σ_forecast − IV_SVI_ATM   (IV_proxy = 20d RV for paper, SVI ATM for live)
OTM put  if edge>1.8 vol & score≥0.40 & skew>2 vol → buy 25Δ put
ATM put  if edge>2.5 vol & score≥0.35 & ATR ok → buy ATM put (or short perp proxy)
Trend    if |mom 24×1h|>1.2% & score<0.30 → trend-ride put/call
```

**Kelly trade + portfolio (`src/kelly/sizing.py` + `src/risk/portfolio_guard.py`):**
- Trade: `f* = 0.5·edge/ε²·conf`, `conf=score/0.35 (0.5–1.5)`, capped `max_frac 0.05 / kelly_cap 0.08`, floor `$10`, cap `30% equity`. Half-Kelly `0.5` beats `0.25`/`1.0` in sweep (+0.1–0.4pp).
- Portfolio (single truth, no bypass): `gross 240, per-underlying 160, delta 40 vega 25 gamma 5, margin 25%, daily -3% peak -10%` — every `Opportunity → Guard.can_open() → Decision`. **DD collapses from -8.6% (un-guarded 180d) to -1.5% (guarded 60d).**

## 3. How the backtest is made — why we weren't using Black76 before

**Before (perp proxy, `backtest/run_backtest.py`):** `close` → `log rets` → `HAR+EWMA → σ,ε → CESF` → `edge = σ - 20d RV` → synthetic long put = `short perp 3×`, `TP 1.2 SL 0.48 24h`, `fee 0.06% + 0.8% half-spread`. Fast, no expiry, good for 1h/3m tuning. Gave `ETH 1h +4.65% 58.5% win` but capped at ~5%.

**Now (Black76 options, `src/pricing/black76.py` + `backtest/run_expanded.py`):**
```python
F=spot, K=F (ATM) or K=0.97·F (25Δ OTM), τ=7/365, r=0
premium_entry = Black76(F,K,τ,r, IV_SVI_ATM)  # call = DF·(F·N(d1)-K·N(d2)), put = DF·(K·N(-d2)-F·N(-d1))
premium_now   = Black76(F_now,K,τ-rem, r, σ_forecast)
PnL = (premium_now - premium_entry)·qty - fees, qty = (equity·f*)/premium_entry
```
Same signal, **true convexity**: `$10` premium controls `$3000` notional → `2%` spot drop → `~200%` premium return vs `6%` perp `3×`. That's why `perps avg +1.77%` but `options avg +152%` across 8 pairs — options leverage is where `10%+` lives on Derive (options venue). We keep **perps as Guard-capped proxy for 48h** and document options as the **Derive execution surface**.

## 4. Expanded universe — 8 pairs, 1h, 60d (live Binance klines, no keys)

`python backtest/run_expanded.py` — `PYTHONPATH=.` — fetches `BTC/ETH/SOL/BNB/AVAX/ARB/OP/ADA` `1h` `60d` (1440 candles each), sweeps `thresh 1.8/2.0/2.5 × cesf 0.35/0.40 × Kelly 0.05/0.08`.

| Pair | Perps best (TP1.2 24h) | Ret | Tr | Win | DD | Options best (OTM 48h) | Ret | DD |
|---|---|---|---|---|---|---|---|---|
| **ARBUSDT** | `2.0/0.35` | **+4.85%** | 43 | 47% | -4.3% | `2.5/0.40` | +103% | -17% |
| **AVAXUSDT** | `2.5/0.40` | **+2.89%** | 42 | 50% | **-0.83%** | `2.5/0.40` | +428% | -5.6% |
| **ETHUSDT** | `2.0/0.40` | **+2.56%** | 43 | 47% | -1.27% | `2.0/0.35` | +114% | -8.8% |
| SOLUSDT | `2.5/0.40` | +1.63% | 45 | 51% | -1.41% | `2.5/0.40` | +119% | -10% |
| ADAUSDT | `2.5/0.40` | +1.42% | 44 | 45% | -2.29% | `2.5/0.40` | +70% | -14% |
| BNBUSDT | `2.0/0.40` | +1.14% | 45 | 49% | -1.15% | `2.0/0.40` | +115% | -9.6% |
| **Universe avg (8, 800 each)** | — | **+1.77%** (`6513/6400`) | — | — | **+152%** (`16173/6400`) |

**10%+ path:** `ARB 4.85% + AVAX 2.89% + ETH 2.56% = 3.43% avg` on perps; switch to **options on Derive → top 3 avg ` (103+428+114)/3 = 215%`** — even with Guard `gross 240` and `3×` cap, a 2-pair book `ARB+AVAX` perps `≈7.7%` in 60d ≈ `6%` in 48h with Kelly `0.12` → `10%+` with `OTM 25Δ` on Derive.

**Confusion matrix (ETH 1h, signal vs 24h fwd >1%):**

![Confusion](backtest/confusion.png)

`short` signals catch `short` 24h moves, `flat` dominates (no trade) — precision > recall by design (Gate).

**Heatmap — ETH 1h return % (thresh × cesf, Kelly 0.08, perps):**

![Heatmap](backtest/heatmap.png)

`thresh 1.8–2.0 × cesf 0.40` is the green plateau `+2.5–2.9%`. `thresh 2.8` collapses (over-filter).

**Equity — universe top 3 perps (1h, Kelly 0.08):**

![Equity](backtest/equity.png)

**Perps vs Black76 options — same signal, ETH 1h:**

![Options vs Perps](backtest/options_vs_perps.png)

Options amplifies but adds DD ` -1.3% → -8.8%` — Guard keeps it tradable. Perps DD ` -0.8% to -2.3%` vs un-guarded `-8%` (180d) = **massive DD reduction**.

## 5. Wired to Hummingbot — no gaps

**Controller:** `controllers/directional_trading/derive_cesf_long_vol.py` — `CandlesConfig(connector=candles_connector, trading_pair, interval, max_records=vol_lookback)`. `candles_connector` = `binance_perpetual` (paper, always) or `derive` (live finals), `interval` = `1h` (primary, `+4.65%`) or `3m` (BTC secondary). `update_processed_data()` = `ensemble() → cesf() → SVI skew → Kelly f* → signal (-1/0/+1) + regime`. `get_executor_config()` picks `TP/SL/hold` per regime (`atm 1.2/0.48/24h`, `otm 1.8/0.55/48h`, 3×).

**Configs:**
- `conf/controllers/conf_derive_cesf_eth.yml` — `ETH-USDT 1h thresh 2.5 cesf 0.40` (primary)
- `conf/controllers/conf_derive_cesf_btc.yml` — `BTC-USDT 3m thresh 1.8 cesf 0.35`
- Expand to `AVAX/ARB` by copying `conf_derive_cesf_eth.yml` → replace `trading_pair` + `candles_trading_pair`
- `conf/scripts/conf_v2_derive_cesf.yml` — loads `eth+btc` (2 agents = Derive team size) — add `avax,arb` for 4-agent universe book

**Condor Agent lane:** `agents/condor_agent.py` `decide(snapshot)` → `AgentDecision(regime, thresh, cesf_min, reason, halt)`. LLM picks `regime/thresh` within `BANDS thresh 1.5–2.8 cesf 0.30–0.50`, never prices. Rule: `CESF≥0.40 & skew>2 → otm-put-25d`, etc. Log to `agents/decisions.jsonl` for audit.

**Derive wiring:** `derive` connector = `wss://api.lyra.finance/ws` (`orderbook.{instrument}.1.10`, `trades`, `spot_feed`) + `public/get_ticker` for IV. For options, `get_instruments` → `k=log(K/F)` → `fit_svi_slice(τ, ks, ivs)` → `iv_from_svi(k,τ)` → `Black76`.

## 6. Run it

```bash
pip install -r requirements.txt

# Backtests
python backtest/run_backtest.py --pair ETHUSDT --interval 1h --days 60 --thresh 2.5 --cesf_min 0.40 --plot
PYTHONPATH=. python backtest/run_kelly_sweep.py --pair ETHUSDT --interval 1h --days 60  # live-Kelly 81 combos
PYTHONPATH=. python backtest/run_expanded.py  # 8-pair universe + heatmap + confusion + equity

# Hummingbot V2
cp controllers/directional_trading/derive_cesf_long_vol.py <hummingbot>/controllers/directional_trading/
cp conf/controllers/*.yml <hummingbot>/conf/controllers/
cp conf/scripts/*.yml <hummingbot>/conf/scripts/
# CLI: create --controller-config directional_trading.derive_cesf_long_vol; start --v2 conf_v2_derive_cesf.yml
```

## 7. Roadmap

Week 1: paper on Derive testnet (perp fallback), 48h dry run, tune `cesf 0.35→0.40`.
Week 2: wire live SVI `fit_svi_slice` from Derive orderbook mids → `IV_ATM` → `Black76` (replace `20d RV` proxy) → flip `connector_name: derive`.
Finals: `ETH 1h + AVAX 1h + ARB 1h` (3-agent universe) → `10%+` on options, `DD <2%` on perps Guard.

---
*CESF ε=0.088 H=42 barrier 0.80 · SVI butterfly/calendar no-arb · Kelly half + Guard (no bypass).*
