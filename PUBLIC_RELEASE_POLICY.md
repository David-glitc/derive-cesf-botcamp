# Public release policy

This repository is the competition-facing implementation and research record. It may contain the strategy thesis, high-level signal methodology, reproducible backtests, sanitized configuration examples, and instructions for running mocked or testnet checks.

The following stay outside GitHub:

- credentials, API keys, wallet addresses, session keys, signing material, and account identifiers;
- private deployment manifests, internal runbooks, incident notes, and operator contacts;
- raw live or testnet fills, account snapshots, equity history, and operational logs;
- private risk thresholds, execution heuristics, or venue-specific methodology that is not intended for publication;
- unredacted screenshots, dashboards, or exports containing account or order information.

Use local ignored paths such as `private/`, `runtime/`, `account_snapshots/`, `ledger_exports/`, `live_logs/`, and `testnet_logs/` for those artifacts. Store credentials in the deployment secret manager, not in repository files.

Before a public commit, verify that tracked files contain no secrets, account identifiers, raw fills, or internal-only operational documents. Public documentation must describe return ranges as scenarios, never as a promise or a launch criterion.
