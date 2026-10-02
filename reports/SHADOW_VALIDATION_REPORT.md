# Flyby shadow build and validation — 2026-10-02

Native analytics, short-horizon spread diagnostics, an opt-in native 5m input,
entry/hold comparisons and a simulation-only paired lifecycle are implemented.
Local safety checks pass; **live readiness and cost-adjusted trading edge are
not established**. Follow the [validation guide](../verification/VALIDATION.md).

## Implemented boundaries

| Layer | Implemented | Not established |
|---|---|---|
| Native data | Legacy REST, bounded public WS L2, query/receipt provenance, failed samples | Continuous coverage or synchronized quotes |
| Book/tape | L2 capacity/imbalance, deduplicated recent VWAP/POC | Complete tape, matching/queue proof or verified CVD |
| Options | Tenor ATM/skew, common-instrument OI changes, costed 1h/6h spread scenarios | Dealer GEX, calibrated expected returns or real option fills |
| Controller | Explicit native 5m opt-in, stale-data halt, no Binance fallback in native mode | Cleared production native/private lifecycle |
| Paired model | Matched cumulative events, fault reservations, idempotency/restart | Atomic exchange routing or real unmatched-fill prevention |
| Account/close | Whole-snapshot replacement, labeled verified-margin inputs, bounded reduce-only intents | Integrated authenticated free-margin/reduce-only enforcement |

Samples remain paused on the baseline source with live options disabled. The
pure execution model has no signing/transport and doesn't patch the connector.

## Bounded public observations

Six samples per currency ran about 03:15:50–03:18:19 UTC. All twelve returned
fresh native ticks, valid 180-bar features, L2, recent prints and surface
observations. ETH archived 54 public envelopes; BTC archived 48. Roughly 2.5
minutes of observations isn't a 48h soak or a historical options backtest.

| Observation | ETH | BTC |
|---|---|---|
| Qualified quotes per sample | 0, 1, 1, 0, 2, 41 | 10, 5, 15, 10, 17, 19 |
| Samples with qualified ATM IV | 1 | 3 |
| Samples with qualified 25-delta skew | 0 | 1 |
| Ranked spread counts | 0, 0, 0, 0, 0, 1 | 0, 0, 2, 2, 2, 2 |
| Duplicate counterparties excluded per sample | 50 | 50 |
| Replay trades / real orders | 0 / 0 | 0 / 0 |

Public history emits both counterparties under one trade ID. Conflicting
price/amount duplicates reject. Raw public envelopes stay ignored and may
contain public counterparty metadata; derived Condor context excludes those
identities. Surface availability doesn't imply qualified ATM/skew. Gamma×OI
is unsigned and unit-unverified, not dealer GEX.

The ETH candidate's favorable-direction 1h model net was about −$1.95. BTC
candidate scenarios ranged about −$0.38 to +$0.52. These aren't entry endorsements:
fixed-wedge scenarios have no calibrated probabilities or future-book guarantee.
They produced no confirmed strategy entries.

## Fixed entry/hold comparisons

Two fixed policies × ETH/BTC × 5m/15m/1h/4h × three chronological partitions
produced 48 comparisons. Features use closed bars; entries use the next open;
ambiguous bars resolve stop first. Embargo includes a 100-bar lookback and
maximum holding period. Fees/slippage/depth/funding are assumptions, and 4h
OHLC cannot resolve a six-hour timer exactly.

| Partition | Baseline mean net return | Hold-hysteresis mean net return |
|---|---:|---:|
| Train | −1.4287% | −1.5294% |
| Validation | −0.9004% | −0.8230% |
| Test | −0.4777% | −0.3242% |

Means span eight separate $800 runs per policy/partition, not one combined
portfolio. Test trades totaled 200 baseline versus 197 hold trades. The proxy
datasets were previously inspected: **this isn't genuinely unseen evidence**.
No parameter search or promotion occurred. Historical contemporaneous Derive
chain coverage is missing; no options result is retrofitted onto proxy candles.

## Formal scope

The actual pure reducer passed 555 reachable states and 8,040 transitions with
zero invariant failures. Z3 4.16.0 found no counterexample for six exact model
obligations: matched-fill bounds; matched close without reversal; budget
reservations; reduce-only intent without a position flip; entry pause/data/
account/loss guards; and idealized min-cap sizing.

Removing matching and committed-budget guards produced counterexamples: one
short lot without its long, and another reservation against a fully committed
budget. This checks detection of those modeled faults. Float rounding,
RPC/signing, process concurrency and real exchange guarantees remain outside
the proofs. Proofs aren't evidence of profitability.

## Evidence locations

The complete eight-stage validation bundle passed. Host tests: 2,299 passed
with one Hummingbot-only skip. Pinned Hummingbot 2.17.0: 2,341 passed with seven
upstream deprecation warnings. The new paired tests include 1,000 adversarial
sequences in addition to the earlier 1,000 paper fill-fault tests; these are
synthetic safety cases, not 2,000 historical strategy trials.

The bundle repeated all 48 fixed comparisons and captured another two samples
per currency. ETH qualified-quote counts were 48/40; BTC 21/20. Both repeated
replays remained flat with zero trades. The bundle records source hashes and
per-stage return codes; all eight were zero.

- `data/validation/full-build-20261002/`: stage logs/source hashes, formal report,
  another 48 comparisons and bounded capture/replay.
- `data/validation/entry-hold-20261002/`: initial comparisons and traces.
- `data/verification/paired-20261002-final.json`: standalone formal model report.
- `data/native-derive/{eth,btc}-quant-validation-20261002/`: six-sample archives,
  paper traces/checkpoints/charts. Runtime evidence remains ignored.

The disposable pinned installer imported analytics/execution modules, retained
the paused baseline ETH profile and accepted native input as explicit opt-in.
No persistent deployment, credential access, bot/agent activation, private RPC,
exchange order, commit or push occurred.

## Remaining gates

Stock Hummingbot still hard-codes `reduce_only: false` and leaves cached
positions untouched on empty responses. Reported collateral isn't verified
free margin, and no stock paired-options adapter is available. Pure contracts
identify required behavior but don't fix that installed integration. The team
must approve connector fixes/routing and real account validation.

Continuous collection, full-duration soak, truly unseen costed edge, real
paired entry/close/recovery and private fee/funding/restart reconciliation
remain unfinished. See [live gates](../COMPETITION_READINESS.md).
