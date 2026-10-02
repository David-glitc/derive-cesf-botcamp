# Options paper execution and live readiness — 2026-10-01

Options have a separate runnable paper replay and chart line. **Live Condor
options execution remains blocked.** The installed Hummingbot connectors skip
option instrument rules, and the installed API has no paired/RFQ execution
route. No real orders, RFQs, funding or bot loops were started.

## What was implemented

- [Paper engine](../src/options/paper.py): call/put spread selection via the
  existing shared policy, both-leg cash flows, size reduction for fixed fees,
  entry/exit fee estimates, net-profit exits and explicit unmatched exposure.
- [Public capture](../backtest/capture_options.py): bounded public v3 ETH/BTC
  L1 snapshots, active instrument metadata and causal Binance proxy features.
- [Replay/plot CLI](../backtest/options_paper.py): immutable result directories,
  traces, input hashes, missing-mark gaps and deterministic restart checkpoints.
- [Execution tests](../tests/test_options_paper.py): 1,000 synthetic fault
  iterations plus targeted fee, stale/crossed/zero book, future-data,
  unmatched-fill, duplicate and restart cases.
- Canonical controller exposes `processed_data.options_execution` in normal
  and halted states. The portable Condor Flyby identity instructs the operator
  not to interpret paper fills as live exchange execution.

## Separate result lanes

| Lane | Data | Result | Meaning |
|---|---|---|---|
| Existing 15M campaign | Binance proxy candles; modeled perp execution | Negative aggregate perp results | Unchanged; no option trades added retroactively |
| Options smoke | Six synthetic snapshots | Two matched spreads close after net fees | Accounting/execution fixture, not demonstrated alpha |
| Public ETH capture | Two current snapshots; 114 eligible definitions | Zero usable quoted contracts; zero fills | Insufficient executable data for an options performance claim |
| Public BTC capture | Two current snapshots; 68 eligible definitions | Zero usable quoted contracts; zero fills | Same limitation; not evidence that the strategy is profitable or safe |

Counts are point-in-time observations for the specified 2–5 DTE window and
v3 capture, not claims that all Derive options markets lack liquidity. The
four public snapshots are a bounded probe, not a 48h soak or historical
options backtest. The capture didn't relax expiry or quote guards to force
trades. It stores raw public-chain inputs locally under ignored `data/`.

Open the [synthetic execution chart](options-fixture-check/options_line.png),
[ETH capture replay](options-eth-capture/options_line.png) and
[BTC capture replay](options-btc-capture/options_line.png).
Synthetic chart gains must not be quoted as real options performance.

These linked outputs use the final checkpoint-capable replay. Its latest
ETH capture rejected one stale index sample; BTC rejected both. All four
samples still had zero usable quoted contracts. The earlier dated captures
and outputs remain preserved separately.

## Verification results

- Host suite: **1,092 passed, 1 skipped**.
- Pinned Hummingbot 2.17.0 suite: **1,119 passed**, with seven upstream
  deprecation warnings.
- Focused paper suite: **1,015 passed**, including 1,000 synthetic fault
  iterations, not historical trading trials.
- Runnable smoke replay: one call and one put spread completed modeled
  entry and net-fee close; both public capture replays completed with zero fills.

The skipped host test requires Hummingbot; the pinned-image suite exercises
the actual connector/controller contracts. Passing these tests doesn't prove
live exchange placement, account margin or real matched fills.

## What “execute” means here

The primary paper fill assumes simultaneous paired execution at fresh
depth-backed limits. That is a simulator assumption, not an installed venue
capability. Explicit unequal-leg faults record actual simulated quantities,
cash and fees, retain the unmatched exposure, halt new entries and attempt
a simulated depth-priced recovery when quotes exist. Such recovery never
counts as a matched successful spread. Missing closing quotes leave the
position open and its equity unavailable rather than inventing a close.

All modeled fees use instrument-supplied standard taker/base/premium-cap
inputs; RFQ fee discounts and account tiers aren't assumed. These defaults
need fill-level validation before a live risk estimate. Quantity convention
is underlying units with multiplier 1; alternative units are rejected.
[Published fee model](https://docs.derive.xyz/integrators/trading/trading-fees.md).

## Verified live blocker

In the pinned Hummingbot image, a contract test passes a valid option-type
record into both connector rule parsers. `derive_perpetual` and `derive` both
return no supported rules. Another test proves the canonical controller
emits an advisory option plan while keeping `options_enabled` false.
Condor routes trading through Hummingbot API; a prompt or status flag cannot
add unsupported instruments or atomic matching.
[Official connector boundary](https://hummingbot.org/exchanges/derive/),
[Condor architecture](https://github.com/hummingbot/condor).

The existing running Condor deployment wasn't replaced, restarted or launched
as a Flyby autonomous loop. The updated identity/controller are repository
artifacts, not a claim that a live options executor was deployed. Building
a Hummingbot-owned paired options/RFQ adapter is a separate implementation
decision; using a private side-channel would violate the existing boundary.

## Remaining work

Obtain synchronized historical two-leg executable quotes, or record a longer
forward shadow dataset, before measuring option strategy performance. Add a
verified Hummingbot paired adapter and prove placement, partial-fill recovery,
exact margin/fill reconciliation, restart and matched close before enabling
live options. Keep the live pause meanwhile. See the
[paper runbook](../backtest/OPTIONS_PAPER.md) for commands.
