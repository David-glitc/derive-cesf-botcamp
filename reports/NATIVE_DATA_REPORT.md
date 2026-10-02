# Native Derive data milestone — 2026-10-02

This records the first bounded milestone. The subsequent
[shadow build and validation report](SHADOW_VALIDATION_REPORT.md) covers added
L2/tape/surface/ranking, native opt-in and formal model work; it doesn't change
the observations recorded below.

The first bounded capture verifies native mainnet index candles, separate perp
volume, option quotes and venue pricing inputs. It does **not** establish a
profitable strategy or live options execution. Use the
[capture/replay guide](../backtest/NATIVE_DATA.md) to reproduce the workflow.

## Observed coverage

Captures ran at 02:24:04–02:24:10 UTC on 2026-10-02 through legacy mainnet public
REST. Each sample includes 180 closed five-minute index bars and matching Derive
perpetual `volume_contracts`: 15 hours of underlying history, not 15 hours of
historical option books.

| Observation | ETH | BTC |
|---|---|---|
| Independent option-chain samples | 2 | 2 |
| Option definitions/tickers per sample, 2–5 DTE | 114 | 68 |
| Quotes passing active/fresh/two-sided/≤15% spread checks | 4, then 44 | 21, then 9 |
| Available IV/pricing context and OI per sample | 114 | 68 |
| Closed index bars per sample | 180 | 180 |
| Bars with positive perp volume | 141 | 107 |
| Missing matched volume observations | 0 | 0 |
| Native feature validity | true, true | true, true |
| Native observation faults | none | none |
| Raw public response envelopes | 14 | 12 |
| Paper option trades / real orders submitted | 0 / 0 | 0 / 0 |

Zero-volume bars remain zero. The collector never invents index volume or
substitutes Binance data. Quote counts reflect HTTP samples across multiple
expiry requests, not synchronized depth or exchange fills. Local shadow files
are expired now unless explicitly refreshed.

## Pricing and replay

The normalizer exposes bid/ask prices and sizes, bid/ask IV, mark IV, forward,
discount, delta, gamma, theta, vega and OI. Greeks retain the venue's feed
convention; they aren't verified account exposures. Fees and amount conventions
remain explicit simulator assumptions pending private validation.

Black-76 uses venue forward, IV and discount, not just spot. Diagnostics show
model-versus-mark residuals and four one-hour repricing scenarios: underlying
up/down 1% and IV up/down five percentage points, holding discount fixed.
Maximum absolute model-versus-mark residuals were about $0.59 for ETH and $9.95
for BTC. These aren't arbitrage edges.

The underlying-volatility forecast is uncalibrated against option IV. Shadow
replay compares it with observed nearest-strike call/put IV before applying
existing spread rules. Both archives produced no option trades, $0 simulated
fees and $0 premium volume. A flat $800 paper line isn't profitability evidence.
No live candle source, strategy parameter or executor policy changed.

## Controller and Condor contract

`get_custom_info()` exposes compact `custom_info.flyby` through Hummingbot's
reporting mechanism. Detailed, allowlisted local files contain controller
decisions, risk metrics, cached positions/orders/executors, stream age and the
native snapshot path. Reporting failure doesn't change entry/stop proposals.
Controller IDs can't escape the owned data directory.

The installed API's status parser preserved the summary in a source-level
round-trip check. This isn't end-to-end live MQTT delivery: no Flyby bot or
autonomous Condor loop was deployed or activated. Condor requires the team's
agent import and read-only context-file mount.

## Evidence locations

Local archives remain ignored runtime data:

- `data/native-derive/eth-20261002-milestone1/{market,raw}.jsonl`
- `data/native-derive/btc-20261002-milestone1/{market,raw}.jsonl`
- Each archive's `replay/` holds summary, traces, checkpoint and paper chart.
- `data/flyby-market-{ETH,BTC}.json` holds the last published shadow snapshots.

| File | SHA-256 |
|---|---|
| ETH market archive | `1fcca6c142b932437cf58422da12300b6ec0b294979952f9c063b0ffe84b7985` |
| ETH raw archive | `300634d1b1d71fd1d477eb36f1739966393e016e3df90b078e8cf81dc85ba8cf` |
| BTC market archive | `daa9015a9ddec759e19f3d4b94d3452552e105b0a8abd2878da90e5bc6d864d0` |
| BTC raw archive | `fc009468198d5c9529bceacd2fc47738f7a043c756efa0d9b6da863bdf13a9e0` |

## Verification

The host suite passed 1,190 tests with one Hummingbot-only skip. The pinned
Hummingbot 2.17.0 suite passed 1,228 tests with seven upstream deprecation
warnings. This includes 76 new native-data/context cases and three reporting
cases using actual Hummingbot models; the existing 1,000 synthetic fill-fault
iterations remain arithmetic/safety tests, not market backtests.

The installer completed in a disposable pinned container. Installed native
modules and controller reporting imports resolved without relying on `/repo`
for shared-package imports, and the installed ETH profile stayed paused with
live options disabled. No persistent bot installation, credential access,
Cloudflare change, autonomous loop activation, commit or push occurred.

## Remaining gates

This slice has no continuous WebSocket collector, 48-hour soak, historical
option-chain holdout, L2 queue reconstruction, volume POC or calibrated
skew/GEX aggregation. OI isn't proof of dealer positioning or signed GEX.
Stock Hummingbot's paired-option execution, margin and restart blockers remain.
See [competition readiness](../COMPETITION_READINESS.md) and the
[earlier options report](OPTIONS_PAPER_REPORT.md) before making execution claims.
