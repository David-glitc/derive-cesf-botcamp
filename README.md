# Flyby — Derive Volatility Agent

Flyby is a Hummingbot V2 Controller plus Condor Agent for Derive. It buys volatility when the forecast says realized volatility should exceed the Derive SVI surface and CESF crash-mass says the move is real enough to trade.

For Botcamp judging, the short version is simple: Flyby is a Derive-native vol/options agent built for Derive’s volatility surface. It combines SVI, Black76, HAR-RV/EWMA, CESF, Kelly sizing, and hard portfolio guards, with a v3 testnet proof lane and a V2 mainnet controller lane.

## Read First

| Doc | Use |
|---|---|
| [`strategy.md`](strategy.md) | Main Botcamp submission and strategy explanation |
| [`SUBMISSION_POSITIONING.md`](SUBMISSION_POSITIONING.md) | Rules, public landscape, and how Flyby stands out |
| [`FLYBY_V3_TESTNET.md`](FLYBY_V3_TESTNET.md) | Derive v3 testnet runbook |
| [`hb_backtest/testnet_proof.md`](hb_backtest/testnet_proof.md) | Testnet proof notes |
| [`hb_backtest/flyby_v3_testnet.jsonl`](hb_backtest/flyby_v3_testnet.jsonl) | Live/testnet decision and order trace |

## Current Lanes

| Lane | Venue | Purpose | Entry point |
|---|---|---|---|
| v3 testnet | Derive v3 testnet | Demonstrate auth, live data, Condor decisions, real testnet orders, and no-crash unsupported-symbol handling | `run_flyby_v3_testnet.py` |
| v2 mainnet adapter | Hummingbot `derive` connector | Keep the Botcamp-compatible Hummingbot controller path | `controllers/directional_trading/flyby.py` |
| Research/backtest | Binance candles + Derive public options data | Reproducible signal, SVI, Black76, WFA, and Guard evidence | `backtest/`, `src/` |

The v3 runner scans this native testnet universe by default:

```text
ETH-PERP,BTC-PERP,DOGE-PERP,ZEC-PERP,HYPE-PERP,SOL-PERP,BNB-PERP
```

The current testnet subaccount can execute risk-universe-1 instruments such as ETH/BTC. Some other symbols may be rejected by Derive for that subaccount’s risk universe; the runner disables those instruments after the first rejection and keeps running.

Derive testnet liquidity can be thin. Treat the v3 run as proof of authentication, market scanning, order creation, live status, and fault-tolerant execution; production liquidity remains the Hummingbot V2 mainnet lane.

## Quick Start — Derive v3 Testnet

```bash
cp .env.example .env
# fill DERIVE_SESSION_KEY, DERIVE_WALLET, DERIVE_SUBACCOUNT_ID, DERIVE_ETH_CHAIN
bash scripts/start_flyby_v3_testnet.sh
bash scripts/flyby_v3_status.sh
```

Useful overrides:

```bash
EXTRA_ARGS="--allow-default-orders" bash scripts/start_flyby_v3_testnet.sh
CONTAINER=hb-derive-py ENV_FILE=.env bash scripts/flyby_v3_status.sh
```

Artifacts:

```text
hb_backtest/flyby_v3_testnet.jsonl
/tmp/flyby_v3_testnet.log inside the container
```

## Quick Start — Research and Backtests

```bash
pip install -r requirements.txt

# Guarded perps proxy
python backtest/run_backtest.py --pair ETHUSDT --interval 1h --days 60 --thresh 2.5 --cesf_min 0.40 --plot

# Expanded universe, options pricing, and plots
PYTHONPATH=. python backtest/run_expanded.py

# Point-in-time WFA harness
PYTHONPATH=. python backtest/run_standard.py --pair ETHUSDT --interval 1h --days 60

# Derive public SVI snapshot
PYTHONPATH=. python src/venue/derive.py

# Condor decision demo
python -c "from agents.condor_agent import condor_options_demo; print(condor_options_demo())"
```

## Quick Start — Hummingbot V2 Mainnet Adapter

```bash
cp controllers/directional_trading/flyby.py <hummingbot>/controllers/directional_trading/
cp conf/controllers/*.yml <hummingbot>/conf/controllers/
cp conf/scripts/*.yml <hummingbot>/conf/scripts/
```

Then in Hummingbot:

```text
create --controller-config directional_trading.flyby
start --v2 conf_v2_flyby.yml
```

## Strategy Snapshot

| Layer | Implementation |
|---|---|
| Forecast | HAR-RV + EWMA λ=0.94 |
| Surface | SVI per expiry with no-arb checks |
| Pricing | Black76 options pricing |
| Event filter | CESF crash-mass proxy: tail, kurtosis, clustering, forecast disagreement |
| Decision | Condor `decide(snapshot)` selects OTM, ATM, trend, or strangle regime |
| Sizing | Half-Kelly from edge and uncertainty |
| Guard | Gross, per-underlying, delta, vega, gamma, margin, daily loss, and peak loss limits |
| Execution | Derive option where supported; Derive perp fallback/proof lane |

## Backtest Summary

Backtests use live Binance klines as proxy history, 1h candles, $800 start, fees and slippage, one-bar point-in-time lag, 60/40 WFA, and Guard enabled.

| Surface | Result |
|---|---|
| Perps proxy | ETH 1h 60d positive guarded run, low drawdown |
| Options model | Same signal becomes convex through Black76/SVI options pricing |
| WFA | OOS remains positive in the documented ETH 1h run |

The detailed table and plots are in [`strategy.md`](strategy.md).

## Repository Layout

```text
agents/                         Condor agent decision logic
controllers/directional_trading/ Hummingbot V2 controller
conf/                           Hummingbot controller and script configs
run_flyby_v3_testnet.py          Derive v3 testnet runner
scripts/                        Start/status scripts
src/svi/                        SVI surface fitting
src/forecast/                   HAR-RV + EWMA
src/pricing/                    Black76 pricing
src/risk/                       PortfolioGuard
src/collateral/                 Multi-collateral model
src/venue/                      Derive public data helpers
backtest/                       Backtest and WFA harnesses
hb_backtest/                    Testnet and proof artifacts
```

## Botcamp Context

Official/public material for the Agent Builders Cup describes $800 starting capital, Hummingbot V2 Controller or Condor Agent eligibility, sponsor teams including Derive, a 48h finals format, and public ranking surfaces including volume, P&L, and HBOT vote.

Flyby’s submission answer is: Derive-native volatility and options edge, deterministic risk controls, and a live v3 testnet proof path that does not disturb the V2 mainnet adapter.
