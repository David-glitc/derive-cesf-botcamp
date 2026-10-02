# Run the options paper lane

You can replay normalized option snapshots with both-leg cash accounting and
plot a separate options equity line. This local harness doesn't submit orders,
and the installed Hummingbot connectors do not support option instruments.
See the [results](../reports/OPTIONS_PAPER_REPORT.md).

From the repository root, first inspect the live capability verdict:

```bash
python3 -m backtest.options_paper --capabilities
```

Expected: `live_execution_verified: false` and
`installed_hummingbot_has_no_paired_options_adapter`. This is the reviewed
capability boundary, not a real-time private account/connection diagnostic.

## Collect bounded public snapshots

Use a new filename: the collector refuses to overwrite prior captures.

```bash
python3 -m backtest.capture_options --currency ETH --samples 2 --output data/options-paper/eth-capture.jsonl
python3 -m backtest.capture_options --currency BTC --samples 2 --output data/options-paper/btc-capture.jsonl
```

These are public v3, forward-observed L1 quotes, instrument fee/lot metadata
and closed Binance 5m proxy features. The signal uses a labeled, uncalibrated
HAR-like/EWMA-minus-mark-IV diagnostic. Missing IV means no options entry;
there is no default IV edge. Only active 2–5 DTE contracts qualify. A capture
can validly contain no usable quotes or no qualifying signals.

## Replay and plot

Choose a new output directory for each replay:

```bash
python3 -m backtest.options_paper --input data/options-paper/eth-capture.jsonl --output reports/options-eth-capture
python3 -m backtest.options_paper --input data/options-paper/btc-capture.jsonl --output reports/options-btc-capture
```

Each directory contains `summary.json`, `trace.jsonl`, `curve.json`, a replayable
`checkpoint.json` and `options_line.png`. Null equity marks represent missing
executable closing quotes, not zero losses. Premium volume counts both leg
sides and fees use supplied standard instrument metadata, without account
discounts or RFQ assumptions. This isn't exchange queue/matching proof.

## Test execution plumbing separately

```bash
python3 -m backtest.options_paper --synthetic-smoke --output reports/options-fixture-check
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests/test_options_paper.py
bash scripts/test_hummingbot.sh
```

The smoke case completes one call and one put spread with synthetic prices.
Its chart is explicitly marked **not strategy performance**. The unit suite
includes 1,000 synthetic execution-fault iterations, not 1,000 market backtests.
Inputs from synthetic and public sources cannot share a replay output.

For inspection without changing output, rerun the tests or capability command.
To rerun a capture/replay, use another name; don't delete or overwrite evidence.

The prior 15M campaign remains perp-only. Combining its overlapping scenario
accounts with this forward option capture would misstate portfolio returns.

## Check delta sizing and the stretch targets

The delta suite tests signed call/put exposure, pending fills, explicit
moneyness, minimum lots, changing Greeks, fee-aware exits and missing-book
recovery. Paper checkpoint schema 2 retains the selection settings by replay;
schema 1 checkpoints are rejected rather than silently reinterpreted.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests/test_options_delta.py
python3 -m backtest.delta_performance --perps-data data/stress-candles --venue-rules data/validation/competition-risk-turnover-20261002/venue-rules-current.json --output data/validation/delta-options-review
```

Use a new output name. The first summary contains 20 public option feasibility
cases; `perps-48h/summary.json` contains 20 fixed 48-hour proxy cases using
current lot rules. Each starts with a separate $800 account. Sum turnover only
as experiment volume; don't sum returns or claim a combined account curve.
Neither suite authorizes live trading or calibrates a profitable edge.
The current observed outcomes are in the [delta report](../reports/DELTA_OPTIONS_REPORT.md).
