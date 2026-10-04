# Bounded Condor runtime verification — 2026-10-04

This report records the earlier bounded-handler milestone and its source hashes.
The [subsequent observation-loop pass](OBSERVATION_LOOP_VERIFICATION.md) adds
native-loop timing and read-only shutdown/adoption guards; its adapter hash
supersedes the adapter hash recorded below.

You can review the runtime extension offline. It passes the controller, bridge
and actual Condor/MCP integration checks below, but it remains disabled in shipped
profiles. No live bot, model provider or exchange order was activated. This report
is an evidence reference for the competition operator, not launch approval.

## Implemented boundary

The controller publishes private, allowlisted market, portfolio, inventory,
executor and options-lifecycle state on each update. A Condor core provider
injects that state into its tick; private stdio tools expose state, event tails,
adjustment submission and receipt lookup. The controller revalidates every lease
before using it. Receipts distinguish validation from exchange fills.

Condor can veto entries, reduce size, tighten confidence/cost requirements, tune
new perp exit parameters within reviewed bounds and request owned protective
closes. Options close requests use the existing paired RFQ lifecycle. The agent
cannot independently submit orders, widen stops, change caps/leverage/allocation,
clear risk latches or change an active executor's barriers.

The $800 allocation and −15% restricted / −25% latched halt remain unchanged.
Missing, stale, malformed, truncated or wrong-session state blocks discretionary
entry; existing protective exits don't depend on an agent lease. Other Condor
seats receive no runtime toolset. Original MCP tools are muted in the runtime
seat; ACP, dry-run and shutdown clients receive no adjustment tool.

## Results

These counts overlap. Don't add them together as independent scenarios.

| Check | Result | What it establishes |
|---|---|---|
| Final pinned HB regression, excluding the long virtual test | 3,061 passed; 2 skipped; 1 deselected; 248.08 s | Existing suite plus runtime controller contracts pass on the pinned image |
| Separate final 50-hour virtual sequence | 1 passed; 22 deselected; 277.94 s | 3,000 minute-spaced leases/publications, repeated sessions, persistent receipts and bounded event retention |
| Final focused host and submission checks | 99 passed; 1 deselected; 16.60 s | Bounds, bridge faults, context allowlisting and curated archive contents |
| Actual Condor + MCP environment | 3 passed; 16.75 s | Real stdio discovery/read denial, MCP write handler and real Condor tick/provider injection with mocked API/model |
| Focused pinned controller/RFQ/context pass | 53 passed; 10.16 s | Owned perp close, paired options exit, inventory truncation, session restart and publication-failure protection |
| Condor package checker | Passed | Agent structure, loop/profile identity and unchanged paused sample hashes |
| Both runtime module `--help` commands | Passed | CLI parameters resolve without launching a bot/server |
| Compilation and `git diff --check` | Passed | Runtime imports compile and patch whitespace is clean |
| Python wheel build | Passed | `src.runtime` modules ship with the shared package |

The pinned run reports seven upstream deprecation warnings. Its optional Condor
SDK and other optional checks can skip in that image; the separate Condor run
covers the runtime integration rather than treating those skips as evidence.
The 1,000 seeded bounded-patch check verifies size/stop/exit invariants, not 1,000
independent market simulations or a formal proof of the entire runtime.

The virtual test disables `fsync` to test clock/session/event behavior without
waiting for real disk durability. Separate bridge tests check permissions,
atomic replacement, missing components, ownership and symlinks with normal file
operations. Neither campaign establishes power-loss durability or 50 hours of
live exchange uptime.

## Reproduction environments

- Hummingbot image: `hummingbot/hummingbot@sha256:d8eb5675cdd37f84f8d132b79b932f012d755d97f21e2da3fd4fef955609079d`.
- Compatibility patch: `flyby-derive-2.17.0-r1`, applied only inside disposable test containers.
- Condor checkout: `/home/david/condor`, revision `07b4601b5a5060e3c7339696b0cd2f8236966fa2`.
- MCP SDK: `mcp==1.26.0` in Condor's Python; no SDK requirement in the controller environment.

The final regression command uses a network-disabled container and read-only source:

```bash
docker run --rm --network none --entrypoint /bin/bash --workdir /repo \
  --env PYTHONPATH=/repo:/home/hummingbot \
  --env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 --env OPENBLAS_NUM_THREADS=2 \
  --volume /home/david/derive-cesf-botcamp:/repo:ro \
  hummingbot/hummingbot@sha256:d8eb5675cdd37f84f8d132b79b932f012d755d97f21e2da3fd4fef955609079d \
  -c '/opt/conda/envs/hummingbot/bin/python scripts/hummingbot_compat.py --apply && /opt/conda/envs/hummingbot/bin/python -m pytest -q -p no:cacheprovider tests -k "not fifty_hour"'
# Expected: 3061 passed, 2 skipped, 1 deselected.
```

Run the virtual sequence separately from the repository root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OPENBLAS_NUM_THREADS=2 python3 -m pytest \
  -q -p no:cacheprovider tests/test_runtime_bridge.py -k fifty_hour
# Expected: 1 passed, 22 deselected.
```

The actual Condor check uses isolated test roots and fixture providers/model:

```bash
PYTHONPATH=/home/david/derive-cesf-botcamp:/home/david/condor \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/david/condor/.venv/bin/python -m pytest \
  -q -p no:cacheprovider tests/test_runtime_condor.py
# Expected: 3 passed. No real provider or exchange execution.
```

## Source identity

| File | SHA-256 |
|---|---|
| `src/runtime/bridge.py` | `4070bb74a27eff1dbb701739e7d4c2ed785acc78437056562294038b88b867f0` |
| `src/runtime/control.py` | `755761f024e35e20b80ae955823af5fad8d5ff6f0733afa1a039d0043560ba2b` |
| `src/runtime/condor_adapter.py` | `9474fc376b4d827dcb0ece5d52282b380e935b032e3ecafcf931945c32d09cee` |
| `src/runtime/mcp_server.py` | `f3d397ef3efff9b546da686c789f1e42a0e9df7eb61dcb2f5851b7d58ff74ef1` |
| `src/accounting/context.py` | `676492517a5c26f753fdce4224dbb821b124e9edcd03c5b3c114680834c0e231` |
| `controllers/directional_trading/flyby.py` | `dd301a9b346afd9114c48ccb8edbb3b8cf850c7b20f102d6be38fbceb4ed8af8` |

## Remaining gates

The shared feed is controller-update polling, not a guaranteed exchange-event
stream. A fresh authenticated inventory doesn't prove exact fee/funding/fill
ledger reconciliation; those flags remain unverified. Model latency, real API
connectivity and private fill/restart recovery still need operator-approved tests.

Leases expire after at most 60 seconds. Renewing every 60 seconds can leave
entry-blocked gaps; renewing every 20 seconds exhausts the 4,096-receipt history
in about 22.8 hours. Review cadence and capacity before claiming a 50-hour run.
Never delete receipt/risk state to regain entry permission.

This extension adds supervision, not demonstrated trading alpha. Adaptive-policy
performance needs a separate frozen-baseline comparison on unseen data. The
existing paired options exit-fee/recovery blocker and negative replay economics
remain unresolved. See the [runtime contract](../RUNTIME_OVERSIGHT.md) and
[launch gates](../COMPETITION_READINESS.md).
