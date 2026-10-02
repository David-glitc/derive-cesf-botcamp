# Demo outline

Show the [artifact index](SUBMISSION_ARTIFACT.md), the single canonical
controller, shared Condor policy and opt-in profiles. Show an actual
Hummingbot v2.17 test run with serialized stop/profit/time exits.

Show call/put plans with matched legs and explicit `signal_only: true`.
Explain why unmatched option legs are prohibited and live options are off.

Show the [stress report](reports/STRESS_REPORT.md), including negative returns,
fee sensitivity and reduced drawdown after mitigations. End with the live
NO-GO gates. Don't describe a synthetic replay or paused dashboard as live
trading proof.
