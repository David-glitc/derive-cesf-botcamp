# Execute atomic option spreads on Derive V3

The selected ETH active profile enables fee- and delta-checked call/put debit
spreads through Derive V3 RFQs. SOL options stay disabled. This is execution
support, not verified live fills or a profitability promise.

## Prepare the execution environment

Use the reviewed Hummingbot V2 framework plus V3 connector/signing overlay in
[mainnet setup](MAINNET_SETUP.md). The team supplies encrypted mainnet credentials,
RFQ and instrument trade scopes, and a fresh authenticated SM/USDC subaccount.
Ordinary perp-order permission alone does not prove RFQ permission.

The selected `eth_active` sample has `options_enabled: true` and
`options_execution_mode: rfq_v3`. Native quotes are refreshed inside the
controller; a manual capture file is not required. Paused ETH/BTC RFQ reference
profiles remain separate. Do not select duplicate controller variants or two
options-enabled controllers for one account.

The shared allocation is $800, normal trade-loss budget $4, option net-delta cap
20%, ETH option gross cap 75%, with −15% restricted / −25% hard-stop latches.
At most two disjoint spread structures may be owned at once, alongside at most
two perps. Account-wide exposure and costs can permit fewer positions.

## Follow the lifecycle

Each entry or exit uses one atomic two-leg `private/execute_quote` call. Native
instrument rules, full-sized matched quotes, fees, premium budget, fresh Greeks
and maker-leg hash must pass before signing. Options never use perp executors.

| Phase | Behavior |
|---|---|
| Idle | Admit one verified disjoint structure within remaining account caps |
| Requesting/quoting entry | Persist intent; recover by label; no blind retry |
| Settling | Reconcile the exact taker nonce/legs and fresh paired inventory |
| Open | Preserve ownership; allow another sleeve within remaining caps |
| Quoting exit | Request both reversed legs; apply net-fee TP/SL/time/risk exits |
| Halted/unknown | Block new risk; require operator reconciliation, never naked repair |

V3 RFQ signatures use string nanosecond nonces from the shared Hummingbot nonce
generator. The one-hour signature is capped by key expiry and must cover the
31-minute RFQ signing minimum. Legacy active intents are never re-signed on V3.

A filled taker quote and exact fresh authenticated inventory confirm sequencer
execution. Batch status and optional L1 hash are separate settlement evidence;
Flyby does not wait for an L1 batch to permit a protective paired exit.
Errored batches halt for reconciliation. Maker and taker quote IDs can differ;
recovery uses the owned RFQ plus nonce and exact legs, not the maker ID alone.

TP is +30% and SL −18% of paid debit plus entry fee, with six-hour maximum hold
and expiry/signal/risk exits. Exit quotes include an exit-fee reserve. An exit
trigger is not a guaranteed fill or maximum-loss guarantee.

## Preserve state and verify

Persist the shared risk checkpoint and RFQ journals:
`flyby-rfq-flyby-competition.json`, its `-slot-2.json` journal, the book ownership
journal and lock files. Do not delete them, change ownership IDs or reuse one
state directory for another account. Signatures and session keys are not journaled.

Run offline fixtures from the repository root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -p no:cacheprovider tests/test_options_rfq.py tests/test_v3_upgrade.py
```

The pinned image tests additionally exercise real Hummingbot signing/serialization
with network disabled. Neither fixture tests nor a source sync prove mainnet
orders. Confirm actual authenticated state and exchange fills in the team's
environment using [the handoff](condor/SYNC_HANDOFF.md).

Protocol references: [V3 migration](https://docs.derive.xyz/migrating/breaking-changes.md),
[RFQ trading](https://docs.derive.xyz/trading/rfq.md) and
[official Python SDK](https://github.com/derivexyz/derive-py).
