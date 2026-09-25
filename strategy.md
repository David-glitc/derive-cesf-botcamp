# Flyby — Derive Volatility Agent

**Team:** Derive · **Agent:** Flyby · **Type:** Hummingbot V2 Controller + Condor Agent
**Capital:** $800 per agent · **Finals window:** October 6–9, 2026, with a 48h final run · **Scoring shown publicly:** P&L, volume, HBOT vote
**Core idea:** Buy volatility only when Derive implied volatility is cheap and CESF crash-mass says the move is operationally real.

Flyby is built as a Derive-native volatility specialist. The strategy uses Derive options math where it matters, Derive perps where the current venue/account supports execution, and a Condor decision layer that picks the regime while deterministic code handles sizing, guards, and orders.

## Submission Fit

| Botcamp / Derive requirement | Flyby evidence | Status |
|---|---|---|
| Hummingbot V2 Controller or Condor Agent | `controllers/directional_trading/flyby.py`, `agents/condor_agent.py` | Implemented |
| 100% unattended final run | Guarded controller, deterministic sizing, `scripts/start_flyby_v3_testnet.sh`, `scripts/flyby_v3_status.sh` | Implemented |
| $800 capital discipline | Backtests and configs use $800 starting capital; position caps are explicit | Implemented |
| Derive venue focus | SVI surface, Black76 options pricing, Derive public data, V2 mainnet adapter, v3 testnet proof | Implemented |
| Public proof path | `FLYBY_V3_TESTNET.md`, `run_flyby_v3_testnet.py`, `hb_backtest/flyby_v3_testnet.jsonl` | Running |

## How Flyby Stands Out

Most public builder descriptions cluster around market making, inventory control, LP/range management, funding loops, or generic Condor wrappers. Flyby is different: it is a volatility and options agent designed around Derive’s strongest surface.

| Differentiator | Why it matters for Derive |
|---|---|
| SVI + Black76 options stack | Uses the options surface directly instead of treating Derive like a generic perp venue. |
| CESF crash-mass filter | Avoids buying every cheap-vol print; it trades when downside/event structure is distinguishable. |
| Perps + options lanes | Perps provide robust execution fallback; options provide convex payoff when available. |
| Kelly + PortfolioGuard | Sizes from forecast confidence, then enforces hard gross, per-underlying, delta, vega, gamma, margin, daily loss, and peak loss limits. |
| v3 testnet proof without breaking v2 mainnet | Shows Derive v3 auth/order flow today while preserving the Hummingbot V2 controller path expected by Botcamp. |
| Honest unsupported-asset handling | Research proxies such as ARB/AVAX/OP stay as paper/backtest assets unless the venue lists them. The runner logs and skips instead of crashing. |

## Current Execution Lanes

| Lane | Venue | What it proves | Files |
|---|---|---|---|
| v3 testnet | Derive v3 testnet | Auth, live market data, Condor decisions, real testnet orders, safe unsupported-instrument handling | `run_flyby_v3_testnet.py`, `scripts/start_flyby_v3_testnet.sh` |
| v2 mainnet adapter | Hummingbot `derive` connector | Botcamp-compatible controller route for production Hummingbot | `controllers/directional_trading/flyby.py`, `conf/` |
| Research/backtest | Binance candles + Derive public options data | WFA, SVI, Black76, CESF and guard evidence | `backtest/`, `src/`, `agents/` |

The v3 testnet lane scans the native testnet universe by default:

```text
ETH-PERP,BTC-PERP,DOGE-PERP,ZEC-PERP,HYPE-PERP,SOL-PERP,BNB-PERP
```

On the current testnet subaccount, ETH/BTC are in risk universe 1 and can execute. DOGE/ZEC/SOL/BNB have been observed as risk universe 3 for that subaccount, so the runner disables them after the first venue rejection and continues. That behavior is intentional for a public demo: more universe coverage without process crashes.

The Derive v3 testnet book can be thin, so this proof should be judged as an integration and safety proof rather than a production-liquidity claim. The mainnet Hummingbot V2 adapter remains the production route.

## One-line Pitch

Buy cheap volatility when the forecast says realized vol should exceed the Derive SVI surface and the CESF event score says the move is operationally distinguishable.

- **Primary Derive trade:** long put/call options through Black76 and SVI when listed and supported.
- **Execution fallback:** Derive perps for testnet proof and unsupported option paths.
- **Decision layer:** Condor chooses regime and threshold; deterministic code prices, sizes, guards, and executes.

Perps are the conservative proof lane. Options are the convex Derive-native lane.

## Strategy Architecture

```text
Market data
  ├─ Derive public instruments, tickers, order books
  └─ Binance candles for research/proxy history

Forecast
  ├─ HAR-RV: 0.1·RV_month + 0.3·RV_week + 0.6·RV_day
  └─ EWMA λ=0.94

Vol surface
  └─ SVI per expiry: w(k)=a+b(ρ(k-m)+sqrt((k-m)^2+σ^2))

Event filter
  └─ CESF proxy score = tail + kurtosis + clustering + forecast disagreement

Condor decision
  ├─ OTM put when edge is high, crash-mass is high, and put skew is rich
  ├─ ATM put/call when edge is very high
  └─ Trend ride when momentum is strong and crash-mass is low

Execution
  ├─ Kelly sizing from edge and uncertainty
  ├─ PortfolioGuard hard limits
  └─ Derive perp or option order
```

## Signal Rules

| Regime | Condition | Action |
|---|---|---|
| OTM put | `edge > 1.8 vol`, `score >= 0.40`, `skew > 2` | Buy 25Δ put, `TP 1.8`, `SL 0.55`, `48h` max hold |
| ATM put/call | `edge > 2.5 vol`, `score >= 0.35`, ATR ok | Buy ATM option or perp proxy, `TP 1.2`, `SL 0.48`, `24h` max hold |
| Trend | `abs(24h momentum) > 1.2%`, `score < 0.30` | Directional put/call or perp, `TP 1.0`, `12h` max hold |
| Strangle, active mode | Vol expansion uncertainty is high | Lower thresholds for 48h finals volume while guards stay on |

Sizing: `f* = 0.5 · edge / uncertainty^2 · confidence`, capped by strategy and portfolio guard. The guard blocks orders that breach gross exposure, per-underlying exposure, delta, vega, gamma, margin, daily loss, or peak loss limits.

## Backtest Evidence

Live Binance klines, 1h candles, 60d, $800 start, fee 0.06%, spread/slippage assumptions, point-in-time one-bar lag, WFA 60/40, and Guard enabled.

| Pair | Perps best | Return | Trades | Win | DD | Options best | Return | DD |
|---|---|---:|---:|---:|---:|---|---:|---:|
| ARBUSDT | `2.0 / 0.35` | +4.23% | 43 | 47% | -4.3% | `2.5 / 0.40` | +106% | -8% |
| AVAXUSDT | `2.5 / 0.40` | +2.66% | 42 | 50% | -0.83% | `2.0 / 0.40` | +439% | -7% |
| ETHUSDT | `2.0 / 0.40` | +3.53% | 42 | 45% | -1.3% | `2.0 / 0.40` | +152% | -10% |
| SOLUSDT | `2.5 / 0.40` | +2.33% | 44 | 52% | -1.4% | `2.5 / 0.40` | +118% | -10% |
| Universe avg | — | +1.73% | — | — | — | — | +159% | — |

WFA ETH 1h 60d `2.5 / 0.40`: `IS 13.2% Sh 1.92 DD -1.4% → OOS 20.9% Sh 3.79 DD -0.4% → ALL 15.8% Sh 2.45`.

Visual evidence:

![Confusion](https://raw.githubusercontent.com/David-glitc/derive-cesf-botcamp/master/backtest/confusion.png)
![Heatmap](https://raw.githubusercontent.com/David-glitc/derive-cesf-botcamp/master/backtest/heatmap.png)
![Equity](https://raw.githubusercontent.com/David-glitc/derive-cesf-botcamp/master/backtest/equity.png)
![Options vs Perps](https://raw.githubusercontent.com/David-glitc/derive-cesf-botcamp/master/backtest/options_vs_perps.png)
![WFA](https://raw.githubusercontent.com/David-glitc/derive-cesf-botcamp/master/backtest/standard_wfa.png)

## Runbook

Install dependencies and run research checks:

```bash
pip install -r requirements.txt
python backtest/run_backtest.py --pair ETHUSDT --interval 1h --days 60 --thresh 2.5 --cesf_min 0.40 --plot
PYTHONPATH=. python backtest/run_expanded.py
PYTHONPATH=. python backtest/run_standard.py --pair ETHUSDT --interval 1h --days 60
PYTHONPATH=. python src/venue/derive.py
python -c "from agents.condor_agent import condor_options_demo; print(condor_options_demo())"
```

Run the Derive v3 testnet demo:

```bash
cp .env.example .env
# fill DERIVE_SESSION_KEY, DERIVE_WALLET, DERIVE_SUBACCOUNT_ID, DERIVE_ETH_CHAIN
bash scripts/start_flyby_v3_testnet.sh
bash scripts/flyby_v3_status.sh
```

Install into Hummingbot V2 for the mainnet controller lane:

```bash
cp controllers/directional_trading/flyby.py <hummingbot>/controllers/directional_trading/
cp conf/controllers/*.yml <hummingbot>/conf/controllers/
cp conf/scripts/*.yml <hummingbot>/conf/scripts/
# Hummingbot CLI:
# create --controller-config directional_trading.flyby
# start --v2 conf_v2_flyby.yml
```

## Key Files

| File | Purpose |
|---|---|
| `agents/condor_agent.py` | Condor `decide(snapshot) -> AgentDecision` regime router |
| `controllers/directional_trading/flyby.py` | Hummingbot V2 controller |
| `run_flyby_v3_testnet.py` | Derive v3 testnet runner with real orders and status mode |
| `scripts/start_flyby_v3_testnet.sh` | One-command testnet startup |
| `scripts/flyby_v3_status.sh` | Process, order, position, and log status |
| `src/svi/` | SVI fit and no-arb checks |
| `src/pricing/black76.py` | Options pricing |
| `src/risk/portfolio_guard.py` | Portfolio risk limits |
| `src/collateral/multi_collateral.py` | Multi-collateral model |
| `backtest/` | Research harness and plots |
| `FLYBY_V3_TESTNET.md` | Testnet runbook |
| `SUBMISSION_POSITIONING.md` | Rules, public landscape, and pitch notes |

## Source Notes

- Hummingbot release notes describe Agent Builders Cup rules, sponsor format, prize pool, V2 Controller or Condor Agent eligibility, and 48h finals: <https://hummingbot.org/release-notes/2.16.0/>
- Botcamp public pages list $800 starting capital, ranking surfaces, eligible exchanges, and Derive team context: <https://www.botcamp.xyz/hackathons/agent-builders-cup-1>
- Hummingbot September 2026 newsletter lists finalist format, finals window, Derive workshop context, and v2.17 Derive config changes: <https://hummingbot.substack.com/p/hummingbot-newsletter-september-2026>
- Hummingbot Condor docs describe Condor as an LLM decision harness with deterministic execution: <https://hummingbot.org/installation/condor/>
