# Submission positioning

Flyby submits one Hummingbot V2 Derive perpetual controller with a shared
deterministic policy and an explicit Condor operator agent/loop. The fixed
profile is `flyby-baseline-dd15-dd25-v1`; its loop is `flyby.flyby_operator`. It
combines consecutive-bar price/volume confirmation, capped risk and
depth-aware marketable-limit entries. ETH/BTC are primary candidates;
SOL/HYPE remain fallback profiles chosen by the judging team.

The options component constructs defined-risk call/put debit-spread plans.
Default samples do not execute options. The separately configured atomic v2
RFQ lane now implements paired entry/exit and persistent reconciliation, but
mainnet fills remain unverified. It doesn't infer paired execution from two
independent orders or claim a profitable SVI/Black76 strategy. Current stress results
remain negative. Present the [measured report](reports/STRESS_REPORT.md) and
[readiness limits](COMPETITION_READINESS.md), not legacy research returns.

The [paste-ready Botcamp form answers](BOTCAMP_STRATEGY_DESCRIPTION.md)
provide separate blocks for each field in the screenshot-matched editor.
It replaces the historical seven-day-put description without
promoting offline candidates. The public listing hasn't been edited; review
and publish the description through the author's Botcamp account separately.
