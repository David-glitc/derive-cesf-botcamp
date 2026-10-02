# Submission positioning

Flyby submits one Hummingbot V2 Derive perpetual controller with a shared
deterministic policy and an explicit Condor operator agent/loop. The fixed
profile is `flyby-baseline-dd10-dd15-v1`; its loop is `flyby.flyby_operator`. It
combines consecutive-bar price/volume confirmation, capped risk and
depth-aware marketable-limit entries. ETH/BTC are primary candidates;
SOL/HYPE remain fallback profiles chosen by the judging team.

The options component constructs defined-risk call/put debit-spread plans.
It does not execute options, infer paired execution from two independent
orders, or claim a profitable SVI/Black76 strategy. Current stress results
remain negative. Present the [measured report](reports/STRESS_REPORT.md) and
[readiness limits](COMPETITION_READINESS.md), not legacy research returns.
