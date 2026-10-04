# Flyby optimization candidate results — 2026-10-03

**Offline implementation verified; no strategy promotion or live activation.**
The recovery candidate retains ownership through additional failure modes. The
tested model/holding candidates do not demonstrate an improved tradable edge.
No deploy, restart, venue order, git commit, push or organizer upload occurred.

## Changes and boundaries

| Component | Implementation | Scope |
|---|---|---|
| Fill ownership | `src/execution/fill_journal.py` | Account/pair/executor-bound SQLite FULL transactions, pre-transport intents, Decimal fill/fee sums, duplicate conflict checks, retained terminal orders |
| Recovery | `src/execution/recovery_candidate.py` | Actual pinned HB executor wrapper, explicit fixture-only constructor; restart reconciliation, exact residuals, lifetime close-attempt ceiling |
| Return model | `src/signal/return_model.py` | Three signed features, fixed ridge penalty 100, 30m next-open return, purged labels, training-only scaling, market-bound JSON artifact |
| Economics/holding | `src/signal/optimization.py` | Expected-return veto after costs/noise, separate holding thresholds, conservative fixed .70 risk weight |
| HB candidate | `controllers/directional_trading/flyby_candidate.py` | Baseline/hold-only/alpha-only/combined; requires an explicit offline provider; no production config or runtime registration |
| Options | `src/options/valuation_candidate.py` | Exact-tenor variance comparison, same-expiry weighted spot/IV/time repricing, observed depth/VWAP and fees; diagnostic-only |
| Oversight | `src/accounting/context.py` | Bounded candidate forecast context; never calls confidence a probability or serializes an executable model |

The canonical controller has two default-preserving candidate hooks: baseline
risk weight still equals its original score and its additional entry gate is
always true. Baseline entry/exit thresholds, paused configs and Condor identity
are unchanged. The new recovery executor is not registered in the orchestrator.
The options utilities are separate shadow diagnostics; they do not replace the
baseline's legacy IV diagnostic automatically or enable options execution.

Keep $800, 20% normal entry notional ($160), 30% gross cap, one position,
persistent −10% restricted mode and −15% hard-stop action trigger. Fixed .70
sizing is 70% of the approved risk budget, not estimated win probability.

## Verification

Final commands/results:

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -p no:cacheprovider --junitxml=data/validation/optimization-candidate-20261003/host-tests.xml tests`:
  **2,715 passed, 4 HB-only modules skipped**.
- Pinned `hummingbot/hummingbot@sha256:d8eb5675cdd37f84f8d132b79b932f012d755d97f21e2da3fd4fef955609079d`,
  ephemeral container with `--network none`, reviewed compatibility patch, then
  `python -m pytest -q -p no:cacheprovider --junitxml=/output/hummingbot-tests.xml tests`:
  **2,813 passed, 7 upstream deprecation warnings**.
- `python3 scripts/check_condor_package.py`: fixed paused identity/structure PASS;
  this does not verify a real model/MCP loop.
- Pinned-image `python scripts/check_mainnet.py`: endpoint/profile installation
  check only; account and live execution remain unverified.
- `git diff --check`: PASS.

An initial host pytest attempt failed before collection because an unrelated
auto-loaded web3 plugin was incompatible with eth_typing. Disabling plugin
autoload resolved it without modifying environment dependencies. Host mainnet
preflight cannot import Hummingbot; use the pinned image, not host output, for
installation verification.

The additional tests include 1,000 seeded fill fragments with duplicate callbacks,
corrupt/foreign journals, wrong-account snapshots, unknown venue orders (never
proposed for cancellation), exact dust residuals, market/clock/model validation,
future-data invariance, cost boundaries, protective exits and depth-aware options
valuation. Passing tests are not a security audit or endurance certification.

## Recovery evidence

`data/validation/optimization-candidate-20261003/recovery-reviewed.json` records
**six RECOVERED_FLAT outcomes, three BLOCKED residuals and eight regressions**:

- Four existing recoverable faults: partial entry protection, cancellation fill
  retention, delayed cancellation race and partial-close retry accounting.
- Restart after a partially filled/canceled entry: exact reduced close, fees and
  independent ledger reconcile.
- Late fill after terminal cancellation, duplicate callback, tracker eviction
  and restart: ownership survives and exact reduce-only close reconciles.
- Dust, exhausted retries and forced-stop residuals remain visible and blocked.
  Stopping an executor does not establish account flatness.

Authenticated snapshots here are **fixture schemas backed by an independent
modeled ledger**, not actual Derive private data. Missing/ambiguous transport
intent, unowned exposure, stale/incomplete/foreign snapshots and lot mismatch
do not authorize a new entry or an oversized recovery close.

## Performance: fixed 72-case ablation

`performance-reviewed/summary.json` contains three chronological windows for
ETH/BTC/SOL, four variants, two cost scenarios, nine separately funded cases per
aggregate. Each starts with $800. **These sums are not one portfolio or one 48h
contest result.** Current venue minimum rules exclude ETH/BTC; trades are SOL.

| Modeled cost scenario | Candidate | Trades | Turnover sum | Net P&L sum |
|---|---|---:|---:|---:|
| 3bp/side + 3bp/side slippage + base fees | Baseline | 9 | $2,880.18 | +$0.30 |
| Same | Hold-only | 9 | $2,877.30 | −$2.34 |
| Same | Alpha-only / combined, each | 0 | $0 | $0 |
| 6bp/side + 3bp entry/15bp exit reserve + base fees | Baseline | 7 | $2,231.06 | −$5.62 |
| Same | Hold-only | 7 | $2,226.79 | −$8.93 |
| Same | Alpha-only / combined, each | 0 | $0 | $0 |

The model rejected all otherwise-qualified entries, not because of a crashed
runner: SOL public-cost windows record 8, 11 and 7 explicit expected-edge gate
blocks. First SOL fit has residual RMSE about 43.52bp, hence a 10.88bp noise
margin in addition to costs. That margin is a fixed residual-error heuristic,
**not a calibrated confidence interval**. Do not lower it merely to force volume.

Holding-only worsened net P&L; do not promote it. The linear gate did not establish
a tradable edge or a superior active strategy; do not label zero trading profit
as a profitable strategy. Combined sizing cannot be judged empirically here
because no combined entries survived. More volume/return is not demonstrated.

Traces retain fills, modeled fees/funding, quantities, exits, holding times,
equity and risk mode; cash and turnover reconcile. Model/input/source hashes are
recorded. These are already-inspected proxy candles, not untouched forward data.
The 30m model is an entry veto, not a prediction of each variable-duration trade
or TP probability. OHLC cannot establish native depth, intrabar DD or queue fills;
stop-first ambiguity and gaps are modeled, not exchange-verified.

## Options diagnostics

`options-shadow-reviewed.json` exercises eight same-expiry call/put tenor
references and five quoted vertical price diagnostics from previously captured
chains. No spread passed the existing $4 risk-budget/delta/expiry eligibility
checks. Diagnostic-only examples do not waive those checks.

IV-persistence references deliberately have zero variance edge; they are not
future realized-variance forecasts. Scenario probabilities are explicitly
hypothetical equal weights, not estimated joint spot/IV probabilities. Future
depth, exit fees, hedges and funding remain unverified; no options order is
authorized. Separate tests cover pricing, fees, probability sums, expiry/horizon
mismatch and insufficient depth without pretending synthetic fixtures are
empirical performance.

## Decision

Retain the submitted baseline's identity and paused operation. Keep the new
models as rejected/unpromoted research candidates. Recovery is a better tested
offline ownership/reconciliation component, **not a production repair already
installed**. Mainnet private reconciliation, actual Condor model tick, production
adapter wiring, dust resolution and a final-image endurance run still gate launch.

The next useful research question is whether native order-flow or a distinct
range/reversion hypothesis has positive net edge on genuinely new data. That is
a separate experiment, not permission to weaken these gates or promise returns.
