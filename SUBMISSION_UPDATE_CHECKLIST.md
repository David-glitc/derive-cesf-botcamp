# Submission Update Checklist

Use this when updating the Botcamp submission from the last committed baseline.

## Reviewer-facing Update

Flyby now has a clearer Derive-native volatility pitch and a live v3 testnet proof lane. The update keeps the Hummingbot V2 mainnet controller path intact while adding a Derive v3 testnet runner that authenticates, scans the native perp universe, makes Condor decisions, places real testnet orders, reports positions/orders/notional exposure, and survives venue-level risk-universe rejections without crashing.

The testnet perp book can be thin, so the v3 run should be framed as integration and safety proof. Production liquidity remains the Hummingbot V2 mainnet route.

## Files to Include

```bash
git add README.md strategy.md SUBMISSION_POSITIONING.md FLYBY_V3_TESTNET.md .env.example .gitignore
git add run_flyby_v3_testnet.py scripts/start_flyby_v3_testnet.sh scripts/flyby_v3_status.sh
git add src/venue/derive.py hb_backtest/testnet_proof.md hb_backtest/flyby_v3_testnet.jsonl
```

## Files to Avoid

Do not add local secrets or scratch scaffolds:

```text
.env
/tmp/flyby-v3-testnet.env
testnet_scaffold/.env.testnet
testnet_scaffold/
place_one_trade.py
place_v3_order.py
```

Most temporary `hb_backtest/*.json` files are research artifacts. Add only the proof files unless we intentionally want the full research dump in the submission.

## Pre-submit Checks

```bash
python3 -m py_compile run_flyby_v3_testnet.py run_hb_v3_live.py
ENV_FILE=/tmp/flyby-v3-testnet.env bash scripts/flyby_v3_status.sh
git status --short
```

## Short Update Text

Flyby is now packaged as a Derive-native volatility agent: SVI + Black76 + CESF crash-mass + Kelly/PortfolioGuard, controlled by Condor and executable through Hummingbot. The new v3 testnet lane proves Derive authentication, market scanning, live order creation, status reporting, and no-crash handling for unsupported/risk-universe instruments. The V2 mainnet adapter remains the production Hummingbot route.
