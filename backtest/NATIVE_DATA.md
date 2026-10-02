# Capture and replay native Derive context

Collect public mainnet observations and replay them without placing orders.
This experimental shadow-data path doesn't switch the live strategy or provide
a historical options backtest. See the [capture report](../reports/NATIVE_DATA_REPORT.md).

## Prepare the environment

Run from the repository root with its Python dependencies installed. Use the
[team setup guide](../MAINNET_SETUP.md) for the pinned Hummingbot environment.
The collector needs outbound HTTPS, not credentials. It uses the stock
connector's legacy mainnet host and never falls back to v3 or testnet.

## Capture public observations

1. Choose a new output directory. Existing directories aren't overwritten.
2. Run one bounded ETH capture:

   ```bash
   python3 scripts/capture_derive_public.py --currency ETH --samples 2 \
     --output data/native-derive/eth-20261002-milestone1 --publish-shadow
   ```

   Expect two JSON summaries with `mode: advisory_only` and `live_options: false`.
   Quote counts and `native_signal_valid` depend on observed market data.
   If this example's directory exists, choose another name before running it.
   Use `--currency BTC` with a separate new directory for BTC.

3. Inspect `market.jsonl` and `raw.jsonl` in that directory. The first contains
   normalized snapshots; the second contains original public results, receipt
   times and content hashes. `--publish-shadow` also refreshes the owned
   `data/flyby-market-ETH.json` file in your working directory.

The collector takes 1–6 samples and exits. It doesn't start a daemon.
Add `--quant` for bounded public WS L2, deduplicated recent prints,
tenor IV/skew/OI and costed spread scenarios. `--interval-seconds` accepts
0–60 seconds between samples. Failed samples preserve raw responses already
obtained and produce a nonzero exit status. See the
[expanded validation workflow](../verification/VALIDATION.md).
If a request fails, keep any partial archive and choose a new directory for a
retry. A one-off shadow snapshot expires; it isn't an ongoing feed.

## Replay the archive

1. Choose a new replay output directory.
2. Run the replay against both archive files:

   ```bash
   python3 -m backtest.replay_derive \
     --input data/native-derive/eth-20261002-milestone1/market.jsonl \
     --raw data/native-derive/eth-20261002-milestone1/raw.jsonl \
     --output data/native-derive/eth-20261002-milestone1/replay
   ```

   Expect `mode: paper_only` and `orders_submitted: 0`. The verified first
   archive produced `performance_status: no_executed_spreads`.
   Choose a new output name if `replay/` already exists.

3. Inspect `summary.json`, `trace.jsonl`, `checkpoint.json` and `options_line.png`.
   Source IDs link replay observations to the public envelopes. Hash checks
   detect corruption, not authenticity or executable liquidity.

The replay applies existing decision and spread-accounting rules to native
inputs. It uses a simulated $800 account, standard instrument fees and assumed
matched fills. `reconciled: true` refers only to that simulated account.
Missing, future, reused or mixed-network sources fail validation.

## Inspect controller context

Keep the collector and controller on the same owned `data/` volume. Installing
the controller doesn't start collection or import a running Condor identity.
Read `custom_info.flyby` from normal Hummingbot controller status reports.
The installed API preserves that field on authenticated
`GET /bot-orchestration/status` and `GET /bot-orchestration/{bot_name}/status`
routes. This verifies a reporting contract, not an active Flyby deployment.

Use the summary's `context_path` to locate the detailed JSON file. Its filename
uses a hash of the stable controller ID. Follow `native_market_path` inside it
for the full observed chain and pricing diagnostics. Mount these files
read-only into Condor's workspace; don't expose them on an unauthenticated
public dashboard. Cached positions, orders and executors aren't proof of
private margin/fill reconciliation.

## Handle unavailable data

| Status or error | Meaning | Action |
|---|---|---|
| `stale_index` | Index tick is older than five seconds | Take a new sample; don't use stale books for entry |
| `unavailable_or_invalid` | Missing, malformed, wrong-network or >30-second-old file | Check the shared mount and capture a new sample |
| `native_trade_volume_missing` | Index bars lack matching perp volume | Keep native signals invalid; don't invent volume |
| `native_candle_gap` / `native_candle_warmup` | Feature window isn't continuous or long enough | Collect a complete window before evaluating entries |
| `context_file_status: unavailable` | The detailed context couldn't be saved | Check the owned directory; protective stops remain independent |
| `public HTTP status:429` | Service rejected request frequency | Stop and retry later in a new archive; don't loop requests |
| `output must be a new immutable capture directory` | Archive name already exists | Use a new directory; preserve earlier evidence |

Default profiles still use Binance candle confirmation and Derive books. The
controller accepts explicit `signal_source: derive_native` 5m opt-in for
fixture/shadow testing; stale/missing native context halts without fallback.
This isn't a cleared continuous-feed deployment. Keep profiles paused and live
options disabled until [launch gates](../COMPETITION_READINESS.md) are cleared.
