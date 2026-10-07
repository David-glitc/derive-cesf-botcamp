# Prepare Flyby on Derive V3 with Hummingbot V2

Prepare a stopped, dedicated Flyby client image. Installation starts no bot and
sends no exchange requests. The team supplies its encrypted mainnet account and
starts the selected loop using [the handoff](condor/SYNC_HANDOFF.md).

## Supported environment

The tested framework base is Hummingbot 2.17.0 at the digest in
[hummingbot-version.json](hummingbot-version.json), plus Flyby's package, the
pinned V3 connector and the Derive-only executor close fix. Stock 2.17.0 alone
is insufficient. Other 2.x fleet builds need compatibility verification;
the patcher refuses unknown source hashes.

The overlay is pinned to Hummingbot PR #8491 commit
`817cf2b42822e720d6074392c90e53d43f3c6264`. Its source and legacy hashes are in
[vendor/derive_v3/manifest.json](vendor/derive_v3/manifest.json).
Hummingbot V2 is the controller framework; Derive V3 is the venue API.

Mainnet endpoints are `https://api.derive.xyz/v3` and
`wss://api.derive.xyz/v3/ws`. The migration includes V3 auth headers, Ethereum
mainnet EIP-712 domain, string nanosecond nonces, slim tickers and private schemas.
Do not change just URLs. The owner is the EOA/multisig, not the old intermediate
Derive Wallet or the session key's address.

## Check and install offline

Mount the repository at `/repo` and use the client's Hummingbot Python environment.
Check-only commands make no client changes:

```bash
python /repo/scripts/check_mainnet.py --profiles-only
python /repo/scripts/install_derive_v3.py --hb-dir /home/hummingbot
```

After reviewing the hashes, install explicitly into the stopped dedicated image:

```bash
bash /repo/scripts/install_hummingbot.sh /home/hummingbot --with-compatibility
python /repo/scripts/check_mainnet.py
python /repo/scripts/hummingbot_compat.py --hb-dir /home/hummingbot
```

Expected: `api_generation: v3`, compatibility `flyby-derive-v3-r2`, no account
verification and zero submitted orders. Exact reapplication is idempotent;
edited sources and invalid backups fail. Original files remain recoverable.

Package version 0.3.0 still uses generic `agents`/`src` imports. Compare installed
package/source hashes before updating an API import environment. Do not
pip-upgrade a shared fleet or patch a running bot as a Flyby source-sync step.
Use an isolated prepared image and the team's reviewed API import environment.
Source sync alone does not install Python dependencies.

## Selected execution lane

The launcher selects ETH and SOL, stable IDs and one shared $800 risk checkpoint.
ETH atomic options are enabled; SOL options are disabled. Native quotes are
fetched inside the ETH controller without a manual quote-capture sidecar.

Account limits are two perps and two disjoint two-leg debit spreads. Same-market
perp stacking and naked option legs are forbidden. Concurrency does not widen
allocation, leverage, aggregate exposure, the $4 normal trade-loss budget or
−15%/−25% latches. Minimum size, costs or lack of signals can still mean no fills.

Full authenticated `get_subaccount` snapshots retain option positions without
mapping them to perp executors. V3 positions may omit display leverage; sizing
still enforces the configured cap. Perp closes use IOC/reduce-only and a signed
15bp price bound, which can leave partial or unfilled closes in fast markets.

V3 RFQ signatures use nanosecond string nonces and a one-hour expiry constrained
by the key's expiry and RFQ's 31-minute minimum. Filled taker quotes plus fresh
exact paired inventory confirm sequencer execution; L1 settlement is separate.
Lost acknowledgements are reconciled, never blindly resent. Non-idle V2 RFQ
journals require operator reconciliation and are never replayed on V3.
Preserve all risk and RFQ journals.

## Verify and recover

`scripts/test_hummingbot.sh` runs isolated client tests, not live activation.
The team separately verifies authentication, perp/RFQ scopes, account margin,
private streams and actual fills. Public HTTP success proves none of those.

For connector rollback, restore the team's pre-change prepared image after
position/order reconciliation. `hummingbot_compat.py --restore` removes only
Flyby delegates/close fix, not the V3 overlay, and leaves entry disabled.
Authored Condor rollback is separate and described in the handoff.

## Preserve competition drawdown state

Keep the account-bound `flyby-competition` checkpoint and RFQ journals across
syncs and attended restarts. The controller owns −15% restricted / −25% hard-stop
latches. Unknown, old-policy or differently bound state requires operator
reconciliation; do not reset it, change IDs or delete journals to resume trading.
