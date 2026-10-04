# Drawdown policy update — 2026-10-03

Policy: `flyby-dd15-dd25-v1`. Condor profile:
`flyby-baseline-dd15-dd25-v1`.

| Mode | Drawdown from peak | Equity at an $800 peak | Action |
|---|---|---|---|
| Normal | Above −15% | Above $680 | Existing entry and sizing rules |
| Restricted | −15% through above −25% | $680 through above $600 | Stricter signals; size at most 25%, tapering to zero |
| Hard stop | −25% or lower | $600 or lower | Block new entries; request protection/closure of owned positions |

Profits raise the equity peak. Recovery, midnight, restart and profile changes
do not clear a latched restriction or halt. The $800 allocation, exposure caps,
per-trade risk fraction, concurrency and signal strategy are unchanged.

The shared reducer, Condor decision guard, Hummingbot controller, replay sizing
and package/profile validation use the new limits. Operator and submission
documentation are aligned. Historical performance reports remain historical;
they do not validate profitability with these wider limits.

Old `flyby-dd10-dd15-v1` checkpoints or initialization markers fail closed with
`risk_checkpoint_contract_mismatch`. Regression tests verify rejection without
rewriting either file, even with bootstrap enabled. No runtime checkpoint was
migrated, reset or deleted. Review is required before an explicit migration;
preserve the account binding, peak, entry history and existing stop latches.

Verification: 451 focused host tests passed. The complete pinned Hummingbot
regression passed: 3,009 passed, one skipped, seven upstream deprecation warnings
in 177.53 seconds. Three stale old-boundary fixtures were updated before this
successful rerun. Condor package structure checks and `git diff --check` passed.

The Hummingbot run used a disposable container, a read-only repository mount
and disabled networking, pinned to
`hummingbot/hummingbot@sha256:d8eb5675cdd37f84f8d132b79b932f012d755d97f21e2da3fd4fef955609079d`.
These are offline contract/property tests, not proof of mainnet fills or a live soak.

Production remains paused. No exchange order, activation, deployment, commit or
push was performed for this update. A hard-stop request is not a guaranteed
fill or realized-loss ceiling during gaps or venue failures.
