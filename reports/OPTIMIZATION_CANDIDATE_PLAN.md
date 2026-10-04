# Flyby optimization candidate — 2026-10-03

This records the user's approved six-change plan. Local implementation and
offline verification are authorized; live activation, deployment, push and
automatic promotion are not part of this change.

## Reviewed scope

1. Add a durable account-bound, Decimal fill journal with idempotent trade IDs,
   order intents persisted before transport, terminal-order retention and
   authoritative snapshot reconciliation. Late fills invalidate flatness.
   Dust, unknown exposure, unknown order status and exhausted retries block
   entry rather than rounding exposure to zero or enlarging a close.
2. Wrap the pinned Hummingbot PositionExecutor in an **offline-only** recovery
   candidate. Exercise real callbacks against the existing independent ledger;
   never register this executor in the production orchestrator.
3. Add a three-feature linear ridge return model using NumPy only. Target one
   fixed 30-minute forward return; standardize on training rows only and purge
   labels crossing the training cutoff. Freeze a JSON artifact, no pickle,
   refit, polynomial expansion or parameter sweep during evaluation.
4. Add a candidate entry gate for predicted return minus complete modeled
   round-trip costs and a residual-error margin. Preserve baseline quality,
   freshness, reconciliation, venue minimum, cost multiple and risk gates.
5. Isolate holding hysteresis and conservative fixed-risk sizing in a separate
   offline candidate. Baseline and its paused configs retain their identity.
6. Add same-expiry shadow options comparison and probability-weighted repricing
   with explicit scenario provenance and spot/IV/time changes. Scenarios are
   hypotheses, not a calibrated probability distribution or future fills.

## Tracer bullet and verification

First journal a partial entry, acknowledge cancellation, restart the journal,
reconcile an independent account snapshot and request only a bounded reduce-only
close. Then close and prove ledger/journal/fees agree. Never label a dust fixture
flat merely because its executor stopped.

Tests cover duplicate/conflicting/late fills, unknown orders, corrupt or foreign
journals, incomplete/stale/backward snapshots, unacknowledged transport intents,
both position signs, partial close retries, dust, forced stops, immutable trained
artifacts, future-label exclusion, feature causality, distribution shift, cost
gate boundary, volume-only holding behavior, fixed sizing caps, expiry mismatch
and option scenario probability/price bounds. Run host and pinned HB suites.

Compare unchanged baseline, hold-only, alpha-only and combined candidates on
identical historical windows and cost assumptions, with separate $800 ledgers.
Retain actual trade events, exit reasons, fees, funding, drawdowns, turnover and
model/input/source hashes. Inspected history is diagnostic, not untouched test
evidence. Validate unseen data later; do not claim historical selection is proof.

## Risk and rollback

Keep $800, maximum $160 normal entry notional, 30% gross exposure, one position,
the persistent −10% restriction and −15% hard stop. No leverage/cap expansion,
forced turnover, market universe change, automatic parameter selection or live
options. Candidate code rejects non-fixture execution; production samples and
runtime registry are unchanged. Rollback is simply not selecting the candidate;
never delete an ownership journal or risk checkpoint to resume trading.

Disk/model/journal errors fail closed for entries, without preventing protective
exit proposals. Public quotes cannot establish account flatness, fill priority,
complete tape, authenticated execution or a hard loss ceiling.

## Review notes

The plan-reviewer checks changed completeness/feasibility/testability from 3/4/3
to 5/5/5 by adding the tracer bullet, explicit error behavior and fixture-only
integration checks. Scope/risk/assumptions are 5/5 for **offline implementation**:
the unknowns are explicit rather than silently assumed solved. This is not a
production readiness, security or profitability score.

Verified inputs: submitted controller remains paused, existing local recovery
candidate recovers four of seven modeled faults and blocks three residuals,
and the faster scalp loses before fees. Mainnet credentials, private transport,
50-hour endurance and positive out-of-sample edge remain unverified. Production
wiring is deliberately outside this offline candidate's done criteria.
