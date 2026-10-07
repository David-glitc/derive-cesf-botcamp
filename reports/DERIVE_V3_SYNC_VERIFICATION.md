# Derive V3 sync verification — 7 October 2026

This release prepares the team's Flyby sync. No trading service was activated,
no credential was copied, and no private order was submitted.

## Shipped scope

- Hummingbot V2 framework with hash-pinned Derive V3 connector/auth/signing overlay.
- Selected ETH+SOL profiles; ETH atomic options enabled, SOL options disabled.
- Account limits of two perps and two disjoint two-leg spread structures.
- Native V3 option quotes in a cancellable background task; no manual sidecar.
- Existing allocation, leverage, exposure caps and −15%/−25% latches retained.
- Backed-up authored-file Condor upgrade/rollback preserving team routines/state.
- Handoff specifies optional MCP origins, selected IDs and exact deployment caps.

## Evidence and limits

| Check | Result |
|---|---|
| Full pinned-image suite, network disabled | 3,098 passed / 2 failed / 3 skipped on initial run |
| Initial full-suite failures | One error-message compatibility mismatch; one stale WS-channel fixture |
| Corrected integration suite | 267 passed, including both corrected cases |
| Final changed-surface image suite | 215 passed after background-feed/expiry fixes |
| Complete installer in isolated pinned image | Passed; V3 overlay and delegates reapplication passed |
| Official Condor discovery/config | Passed against local official checkout |
| Native Condor engine | Two mocked live-mode ticks; deployment permission tested, not executed |
| Public mainnet V3 ETH feed | 846 definitions, 110 eligible options, 7 fresh quoted options, fresh perp index |
| Source artifact secret/hash checks | Passed; unrelated Cloudflare files excluded |

The full suite was not repeated after the two fixes; the affected cases and
integration surfaces were rerun successfully. The latest quote counts are a
single public observation, not liquidity guaranteed at deployment.

The public check caught the mandatory option `expiry_date` parameter absent
from an early fixture and a stale index captured before slow chain reads. The
collector now requests bounded expiry-specific chains, reads index last, and
does not block perp supervision. Its public check uses no credentials.

V3 RFQs use one-hour signatures covering the 31-minute minimum, nanosecond
string nonces shared with perp signing, RFQ/nonce/leg reconciliation rather
than maker-only IDs, and distinct sequencer-fill/L1-batch evidence. Existing
active legacy intents are preserved and require operator reconciliation.

Private authentication/scopes, real provider behavior, actual fills, 48-hour
uptime and positive net P&L remain unverified. Two-plus-two is a ceiling inside
aggregate caps, not a promise that venue minimums permit all four positions.
Do not update a fleet image or restart an exposed bot as a source-only sync.

Follow [the team handoff](../condor/SYNC_HANDOFF.md) and
[mainnet setup](../MAINNET_SETUP.md) for the attended rollout.

## Follow-up local controller-blocker fix — 7 October 2026

The operator confirmed there was no team-side error to diagnose. These findings
are reproduced local integration defects, not a diagnosis of a deployed account.

- A real HB `OrderBook` advances `snapshot_uid` on full snapshots while
  `last_diff_uid` remains zero. Flyby's diff-only freshness gate could therefore
  reject Derive's continuously updating full-book feed indefinitely. The fix
  accepts a matching native publication timestamp and full-snapshot ID; stale,
  future, missing and mismatched publications still block entries.
- Condor's actual `_validate_config_against_template` treats a None-default
  `trailing_stop` as required. Both active configs and their matching samples
  now explicitly supply `trailing_stop: null`, without enabling trailing stops.
- The playbook separates deployment prerequisites from controller-owned entry
  checks, removes contradictory paused-V2-options instructions and treats
  advisory reports/context mounts as nonblocking diagnostics.

Baseline regressions: 5 failed, 6 passed before the implementation. After the
fixes, the network-disabled pinned-image changed-surface suite passed 289 tests
with 7 upstream deprecation warnings. It includes the real Condor template check,
an offline bounded executor proposal from a valid snapshot/signal, options signer
and lifecycle tests, risk/checkpoint tests, runtime oversight, package parity,
mainnet preflight, and submission hash/secret checks. The full historical suite
was not rerun for this follow-up.

Official Condor discovery and two mocked live-mode engine ticks also passed;
deployment permission was checked but no deployment was executed. No exchange
or model network requests, real orders or service starts occurred. Exposure,
fees, signal thresholds, private-stream/book ages and −15%/−25% rules are unchanged.
The team still needs an attended source/config sync and reload to adopt this
local patch. This is not proof of production fills or positive returns.
