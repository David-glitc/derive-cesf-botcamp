# Competition risk and turnover evidence — 2026-10-02

The approved −10% restricted / −15% hard-stop policy is implemented in the
mainnet-only controller and shared Condor policy. Offline tests pass; live
readiness remains **NO-GO**. The faster scalp candidate increases modeled
turnover but worsens net P&L, so it isn't promoted into paused baseline samples.

## Implemented risk contract

| State | Trigger | Entry behavior |
|---|---|---|
| Normal | Above −10%, no previous restricted latch | Existing confirmed signal, confidence >=0.70, modeled 3x cost cushion |
| Restricted | Equity <=90% of observed peak | Persistent latch; confidence >=0.85, trend >=1.5, efficiency >=0.45, current/previous volume >=1.5; 4x modeled cost cushion |
| Hard stop | Equity <=85% of observed peak | Persistent latch; zero trade budget/size, no new entries; cancel/close proposals for owned executors |

The peak starts at at least the approved competition budget, then rises with
authenticated full-account equity. $800 peak -> $720 restricted -> $680 hard
stop. Threshold comparisons use Decimal before signal/sizing float conversion.
Daily P&L is diagnostic; the previous independent −2% daily veto no longer
governs competition runtime. Legacy baseline replay retains its old limits as
a comparison; `competition_baseline` models the new boundaries.

Restricted size is at most 25% of normal, declining linearly through the final
five percentage points. Modeled trade-risk dollars cannot exceed 10% of the
remaining loss buffer. Lot/minimum rules can therefore block every candidate
near the hard boundary. Never enlarge to fit a lot, force trades or increase
unchanged 20% notional/30% gross/leverage caps to generate volume.

The checkpoint is shared across selected profiles, bound to a digest of the
connector subaccount, policy and starting budget. It tracks peak/day diagnostics,
both latches and per-pair consumed signals/cooldowns. File locking, exclusive
temporary files, fsynced atomic replacement and an initialization marker reject
corrupt/foreign/lost state. Profile changes, recovery, UTC rollover and restart
don't clear latches or consumed signals. A fresh flat dedicated account can
bootstrap; unknown existing orders/positions cannot. Legacy per-controller
checkpoints require operator review and aren't overwritten or discarded.

State files require an owned persistent data volume and one dedicated client;
deleting the whole volume/namespace defeats its history and is prohibited.
Entry consumes its completed-candle signal before emitting a proposal: a crash
may miss a trade, not deliberately duplicate it. Pending entries still expire
after 30s. Entry rechecks actual risk, signal and confidence, candle completion,
private/book freshness, exact venue sizing and conservative modeled fees/base
fees/exit slippage/funding. Stale margin or checkpoint failure blocks entries
but doesn't suppress owned-executor protective stop proposals.

## Fixed strategy experiment

`competition_scalp` is an opt-in 5m candidate, not a market-making strategy:
fixed 30m trend window, unchanged confirmed-entry quality formula, 10–30m holding
cap, 60s cooldown, one new completed-candle signal per entry, and hold hysteresis
on trend deterioration/opposite confirmation rather than volume-only exit.
Normal Hummingbot limit entries may take liquidity; no maker fee or queue-fill
claim is made. Stops are software managed and bounded reduce-only market closes,
not native exchange protection or guaranteed full fills.

The first short-hold experiment kept the 4h trend window and remained sparse,
roughly 1–2 trades/day on 5m test slices. The single preset 30m revision raises
this to roughly 7–8 trades/day at public-taker assumptions without venue lots.
There was no parameter grid, automatic threshold search or promotion. All
history was already inspected; none of these partitions is an unseen holdout.

Public-taker/current-lot diagnostic, SOL 5m test slice (908 bars, about 3.15 days):

| Metric | Competition baseline | 30m scalp candidate |
|---|---|---|
| Closed trades | 4 | 23 |
| Trades/day | 1.27 | 7.30 |
| Traded quote volume | $1,281.79 | $7,323.13 |
| Net return on separate $800 account | +0.0247% | −0.8521% |
| Gross quote P&L after modeled slippage, before fees/funding | +$0.66 | −$4.15 |
| Fees | $0.46 | $2.66 |
| Net quote per $10,000 traded | +$1.54 | −$9.31 |

These values aren't a shared multi-market portfolio or exactly a 48h contest.
Applying current instrument rules to old proxy prices is only a capacity
diagnostic. ETH/BTC produce zero 5m trades in this current-rule scenario under
unchanged caps; SOL's sparse baseline gain isn't proof of profitability.
HYPE has no historical replay coverage here and remains an operator fallback.

Three final 90-case matrices cover ETH/BTC/SOL, 5m/15m/1h/4h and disjoint
train/validation/test evaluation windows. Original baseline/hold diagnostics
run on all timeframes; competition baseline/scalp run only at supported 5m.
Stressed and public-taker fees, plus public-taker/current-rule sizing, are
separate scenarios. Symmetric 3bp replay slippage is not validation of the
runtime's 15bp close bound or private fill behavior. Fixed fees/funding, OHLC
ambiguity and no historical Derive depth/queue model remain limitations.
Net P&L/fees/funding reconcile to terminal cash. Traces include risk mode,
decisions, equity and exits; manifests hash source, history and optional rules.

## Validation evidence

The final source suite passes **2,387 host tests** (three Hummingbot-only skips)
and **2,476 pinned Hummingbot tests** (seven upstream deprecation warnings).
New tests include exact boundary values, recovery/midnight/restart/profile
switches, corrupt/foreign/lost checkpoints, disk failure, duplicate and unfinished
signals, restricted quality/sizing, hard-stop cancellation/close proposals,
unknown positions, preset causality and 1,000 seeded governor transitions.

Negative tests found and fixed an unfinished-bar proposal gap and nonzero
hard-stop budget reporting. Failed first validation logs are retained. Existing
paired-option formal model checks also pass, but don't prove this new governor,
real transport, margin refresh, fills or profit. Options remain disabled.
Condor's local upstream filesystem parser still discovers the identity, wrapper
and four byte-identical paused samples; it doesn't validate a deployed agent loop.

Ignored evidence is under `data/validation/competition-risk-turnover-20261002/`:
initial/revised fixed comparisons, source-hashed `final-*` matrices, final
validation logs and a refreshed credential-free public rule snapshot. No private
account calls, live orders, restart/deployment, commit, push or submission occurred.
The earlier review archive remains intact; any new archive is another local
review candidate, not an organizer submission.

## Competition objective and next strategy direction

The [official contest page](https://www.botcamp.xyz/hackathons/agent-builders-cup-1)
weights P&L rank 40%, volume rank 40% and HBOT vote rank 20%, with rank points
from 14 to 1. It specifies $800 per agent and 48 hours. Extra volume only improves
points if it changes rank; local replay without competitor outcomes cannot
compute that. Don't treat turnover as permission to burn capital or self-trade.

The tested fast momentum candidate loses before fees as well as after them.
Reducing fees alone cannot establish an edge. Next investigate a separate,
cost-aware short-horizon range/reversion hypothesis with a trend/volatility veto,
then compare against the baseline. Maker-first execution is a separate hypothesis
that requires timestamped native L2/tape, post-only lifecycle and conservative
queue/adverse-selection validation; candles cannot prove maker fills. No such
replacement strategy or private validation is delivered in this milestone.

Launch still requires operator-approved account/universe/minimum sizing,
private stream/signing, actual partial and dust close handling, exact fill/funding
reconciliation, restart adoption and a 24–36h final-image soak. Stops can gap,
partially fill or fail; −15% is an action trigger, not a guaranteed loss ceiling.
Keep all samples paused. Read [team setup](../MAINNET_SETUP.md) and
[readiness gates](../COMPETITION_READINESS.md).
