# Flyby specification

The implemented contract is [strategy.md](strategy.md), the runtime artifact
index is [SUBMISSION_ARTIFACT.md](SUBMISSION_ARTIFACT.md), and launch status is
[COMPETITION_READINESS.md](COMPETITION_READINESS.md).

This replaces the earlier long-vol desk draft. Collateral vaults, portfolio
margin and autonomous LLM private order routines from that
draft are not part of the submitted V2 execution path.

The canonical controller now has a separately gated [atomic v2 RFQ options
lane](OPTIONS_EXECUTION.md). It isn't the old independent option-ticket design;
default samples remain paused/shadow-only and mainnet fills remain unverified.
