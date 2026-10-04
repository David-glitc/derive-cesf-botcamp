# Native Condor observation-loop verification — 2026-10-04

The 48-hour observation preparation and native-loop guards pass offline checks.
The real provider-backed run has not started. The model/server selection and
private observe-feed mount remain operator setup requirements. No exchange
orders, adjustments, live activation or automatic restart occurred.

## Results

| Check | Result | Scope |
|---|---|---|
| Host observation/package/archive tests | 68 passed, 4.87 s | Config bounds, monotonic deadline, paused preparation and no-overwrite |
| Actual Condor and MCP environment | 10 passed, 28.55 s | Seven observation tests plus three existing runtime/MCP checks |
| Pinned Hummingbot focused regression | 121 passed, 33.69 s | Observation config, unchanged actions/RFQs, private context, package/archive checks |
| Preparation command | Passed | Local SOL example; paused, setup incomplete, not started |
| CLI help, compilation, package checker | Passed | New flag resolves and fixed samples/default discovery remain unchanged |

Counts overlap. The focused pinned run has seven upstream deprecation warnings.
This update did not rerun the entire prior 3,061-test pinned regression or its
3,000-control-renewal virtual bridge campaign; neither is represented as a new
observation uptime result.

## Native-loop evidence

Tests use the actual installed Condor TickEngine, journal and supervisor in
isolated roots. One test drives its real `_loop` and actual `_tick` with mocked
API/core providers/model, accelerating scheduler sleep to cover 48 virtual hours
in three successful model ticks. It verifies journal persistence, terminal
`COMPLETED` state, provider injection, empty ownership ledger and no adjustment
receipts. This tests deadline behavior, not 2,880 successful model calls.

Further tests exercise repeated tick errors, cancellation of a hung gather,
missing/unsupported model setup, write-control refusal, unrelated-seat behavior,
and both direct and gather-triggered emergency shutdown paths. The observation
guard calls normal session completion rather than the upstream deterministic
exchange winddown. Tests verify the original winddown/adoption handlers aren't
called for the observer.

The adapter uses a monotonic first-tick deadline. Native loop cadence is a sleep
after model/provider execution, not a fixed-rate timer. Idle sleep can delay
deadline completion by one cadence; cooperative cancellation/client cleanup can
add teardown latency. There is no process-level hard-kill guarantee.

## Environment and source identity

Condor revision: `07b4601b5a5060e3c7339696b0cd2f8236966fa2` at `/home/david/condor`.
The integration tests use its Python with `mcp==1.26.0` and mocked transports.
Hummingbot uses the previously validated image digest
`d8eb5675cdd37f84f8d132b79b932f012d755d97f21e2da3fd4fef955609079d`,
network disabled and source mounted read-only. No running service was modified.

| File | SHA-256 |
|---|---|
| `src/runtime/observation.py` | `a4902b469a4f3a215398c1e73a9577444c2f9a1e18f387aa96062437fed85d16` |
| `src/runtime/condor_adapter.py` | `6ad78fe434b4e5186ec5396826bfe3a351be6ab939153056d30842ba5b34d4af` |
| `condor/profiles/flyby_observe_48h.yml` | `745b479030c1af1521b9a6c86b90b4d277090dbd0f2e727fbf8eacddd79cc6b7` |
| `scripts/prepare_observation_profile.py` | `7f4daf5fb517d029311d9c7ff02845806e7be94dc25948a8ae1b942961631238` |

## Launch conditions

Use the explicit observation launcher, a real accessible API/model seat and the
owned private controller snapshot. Keep controls disabled, the controller paused,
and restart-on-boot false. The template is a separate operator override, not a
change to the fixed submission defaults. A crash ends continuous-uptime evidence;
explicitly relaunching the observation process creates a new window. Starting
another native loop session in that same process doesn't reset the deadline.

The read-only loop consumes no adjustment receipts; bounded-control cadence and
the 4,096-request history limit remain separate constraints. Observer journals
with no adopted bot are not source-of-truth strategy PnL. Unknown state remains
unknown, and profitable trading/exchange recovery are not established.

Follow the [observation procedure](../condor/OBSERVATION_RUN.md) and preserve
the [live readiness gates](../COMPETITION_READINESS.md).
