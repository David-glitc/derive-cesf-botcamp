# Condor runtime oversight reference

Flyby can publish private market, position and portfolio state on each controller
update and accept bounded Condor adjustments. The shipped profiles keep this
feature **off** and trading paused. Adding agent discretion does not establish
profitability, mainnet fills or production readiness.

## Data and action boundary

```text
Existing HB candles/books + authenticated account/user stream
                          |
                          v
             Controller allowlisted snapshot/event tail
                          |
                          v
             Condor core provider + private stdio tools
                          |
                    bounded request
                          |
                          v
             Controller revalidation + existing risk gates
                          |
                          v
              Owned perp actions / atomic paired RFQ lifecycle
```

The controller owns execution. Condor cannot directly submit an order, create
option legs, clear a halt, rewrite a risk checkpoint or alter an active executor's
barriers. The agent may request an owned close, but a validated receipt does not
mean the venue filled it. Existing protective exits run without an agent lease.

## Modes

| `runtime_oversight_mode` | Behavior |
|---|---|
| `off` | Default; baseline behavior, no runtime publication or control requirement |
| `observe` | Refresh private state/event tail; no adjustments accepted |
| `bounded` | Require a fresh valid adjustment lease before entry; controller validates every action |

Select modes only in a separately reviewed, paused operator profile. Do not
modify the fixed submitted samples or treat an offline test as activation approval.
The adaptive extension is separate from measured fixed-baseline performance.

## Private state

The owned directory is `data/flyby-runtime-<controller-id>/`. Mount it privately
between Hummingbot and Condor. Never publish it through the public dashboard.
The snapshot includes controller/account binding, session, sequence, timestamps,
signal/gates, full venue equity separately from the $800 allocation, fresh margin
status, position/order/executor views, a bounded execution-book slice, option
context/lifecycle and request receipts. Venue-wide inventory is separate from
connector-local tracking. Each venue array is capped at 50 rows; truncation or
malformed/incomplete inventory blocks adjustment submission and consumption.
Unknown values remain unknown.

The publisher reuses existing connector state; it does not open another private
exchange connection. Publication cadence follows controller updates, not an
exchange-event delivery guarantee. Condor sees the core-provider summary on each
tick and can read the latest snapshot and event tail through tools. The tail
retains 128 events; cursor gaps require refreshing the snapshot.

Authenticated account snapshots do not prove exact fill/fee/funding ledger
reconciliation. Those flags remain unverified. A missing native option chain or
short book slice cannot establish executable option prices or market-making fills.

## Tools

| Tool | Contract |
|---|---|
| `flyby_get_runtime_state` | Read current allowlisted state with age/freshness |
| `flyby_read_events` | Read events after a sequence; report retention gaps |
| `flyby_submit_adjustment` | Queue a typed, expiring adjustment; absent in read-only/dry-run servers |
| `flyby_get_adjustment_status` | Read queued/validated/superseded/unknown receipt and current lease activity; never infer fills |

Requests use `request_id`, the current `session`, `basis_sequence`, `patch` and
`expires_in_seconds` (1–60). Refresh state immediately before submitting. State
older than five seconds, future sequences, wrong ownership, conflicting IDs,
foreign executors and unsupported fields are rejected. Every receipt persists;
at 4,096 requests the mailbox rejects new requests instead of silently evicting
idempotency history. Operator review is required to extend a run beyond that bound.

## Adjustment bounds

| Patch field | Reviewed range / effect |
|---|---|
| `veto_entry` | Boolean; block new entries |
| `size_multiplier` | 0–1 of deterministic size/risk budget; never enlarge it |
| `confidence_floor` | 0.70–0.95; effective floor cannot fall below the current risk-mode floor |
| `cost_multiple` | 3–6; effective floor cannot fall below the current 3x/4x requirement |
| `stop_multiplier` | 0.5–1; tighten stops on new perps, size against original stop |
| `take_profit_multiplier` | 1–2; new perps only; original cost gate still applies |
| `hold_multiplier` | 0.5–1.5; new perps only, maximum six hours |
| `close_executor_id` | Request a close only for an active executor owned by this controller |
| `close_options` | Request a paired close only through the enabled owned RFQ lifecycle |

Cost-multiple tuning applies to perps; original option fee/edge rules and options
TP/holding rules do not change. Reduced option entry budgets can block
minimum lots; no split-leg workaround is allowed. Perp entry tuning never changes
the signal direction, underlying universe, cooldown, leverage, allocation or
exposure caps. The −15% restricted and −25% halt latches remain authoritative.

## Failure and restart behavior

Missing/expired/corrupt leases and publication failures block bounded entries.
They do not suppress deterministic protective exits. A new controller session
rejects old leases; receipts survive restart. Missing owned state is not repaired
by deleting files, choosing a new namespace or resetting the drawdown checkpoint.
Partial publication failures require review rather than silent reinitialization.

Private files use atomic replacement and restrictive permissions. These checks
are not a sandbox against arbitrary filesystem/code access by the same OS user.
Keep the agent in its reviewed tool seat; do not expose shell/config-upsert tools
to bypass the bridge.

## Condor integration interface

The optional runtime dependency is `mcp==1.26.0`; it belongs in Condor's Python,
not in Hummingbot's controller environment. The extension uses the local official
Condor provider registry and gated-client builder, without editing upstream files.
It scopes tool injection to the Flyby tick seat and an explicit operator user ID.
Dry-run/shutdown clients mount no adjustment-write tool even if the launcher has
controls enabled. ACP/code-capable model seats remain read-only; only a Condor
PydanticAI tool-only model seat may receive the adjustment tool. All original
MCP tools are muted in the runtime seat, including saved-config/direct-order
tools, so it cannot route around the bounded mailbox. Other users and agent
seats get no runtime toolset. Core providers keep their trusted read-only API calls.

These commands show the interfaces without starting a server or bot:

```bash
python3 -m src.runtime.mcp_server --help
python3 -m src.runtime.condor_adapter --help
```

The explicit launcher requires `--condor-root`, `--root`, `--controller-id`,
`--account-binding` and `--operator-user-id`. Without `--enable-controls`, it
mounts read-only tools. It replaces the operator's stock Condor startup command;
installing the Flyby agent alone does not register this extension. The team must
mount the private volume, select its real API/model, clear launch gates and
explicitly choose sustained loop operation. No startup/deployment occurred here.
Run with this package installed in Condor's Python (including the `runtime` extra),
or a persistent absolute `PYTHONPATH` visible to its subprocesses. The launcher
uses the official checkout as its working directory. The shared-volume root is
resolved before that directory change; pass an absolute root for clarity.

The 60-second lease is a safety timeout, not a scheduling guarantee. Model/network
latency can create intentional entry-blocked gaps even when loop frequency is
60 seconds. More frequent renewals exhaust 4,096 receipts sooner (about 22.8 hours
at 20-second intervals); do not promise a continuous 50-hour bounded run at that
cadence or delete the journal to regain capacity. Review cadence, history capacity
and latency before promotion. The virtual test is not a real-time uptime soak.

## Native 48-hour observation

The explicit launcher now accepts `--observation-hours 48` for a separate
read-only native loop. It forbids control writes, skips bot adoption and
intercepts upstream emergency winddown so completion ends only the observer.
The monotonic deadline starts at its first selected tick; no automatic restart
is enabled. Read-only observation consumes no adjustment receipts.
Follow the [observation run procedure](condor/OBSERVATION_RUN.md). The shipped
default is a continuous native controller loop with runtime oversight off;
the optional adapter remains a separate oversight-only seat. No real-time run
has started here.

See [mainnet launch gates](COMPETITION_READINESS.md) and
[planning/control boundary](condor/flyby/loops/flyby_operator/loop.md).
The [verification report](reports/RUNTIME_OVERSIGHT_VERIFICATION.md) records the
offline results, source hashes and remaining rollout limits.
