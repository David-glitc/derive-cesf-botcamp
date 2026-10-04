# Configure atomic option spreads

You can now route Flyby's fee- and delta-checked call/put debit spreads through
Derive's legacy v2 atomic RFQ interface. The code is implemented and tested offline;
no mainnet option fill has been verified. This guide is for the competition operator.

## Before you select the lane

Keep trading paused until you have a dedicated mainnet SM subaccount, the pinned
Hummingbot v2.17.0 client, the reviewed compatibility patch, and a fresh authenticated
full margin snapshot. Provide credentials through Hummingbot's encrypted setup,
not files in this repository. The v2 RFQ execution method requires an admin-level
registered session key; ordinary order permission alone isn't sufficient.
Confirm with the team that the legacy v2 API remains
available on their competition infrastructure; this adapter doesn't fall back to v3.

The $800 budget, 0.5% risk budget, signed delta/gross caps, −10% restricted mode
and −15% hard stop remain unchanged. Venue minimums or missing liquidity can still
produce zero trades. The IV-edge diagnostic is uncalibrated; execution support
doesn't establish profitability.

A separate [approved ETH exposure test](reports/ETH_EXPOSURE_TEST_REPORT.md)
raises only its exposure ceilings to 40% perp notional/gross and 75% option gross.
It installs paused, is not selected by the default launcher, and does not change
the baseline profiles, 20% option-delta ceiling or $4 initial loss budget.

## Select one paused profile

1. Install the repository through the existing [mainnet setup](MAINNET_SETUP.md).
   The installer includes the two new RFQ profiles without selecting or starting them.
2. Select `conf/controllers/conf_flyby_options_eth.yml` OR
   `conf/controllers/conf_flyby_options_btc.yml` in the operator's launcher configuration.
   Don't select both, or the perp and RFQ variants of the same controller ID.
3. Keep `manual_kill_switch: true` while you verify the account, profile and native data.
   The required option settings are `options_enabled: true` and
   `options_execution_mode: rfq_v2`; neither changes the API generation.
4. Supply fresh owned `data/flyby-market-ETH.json` or `data/flyby-market-BTC.json`
   captures using [the native data setup](backtest/NATIVE_DATA.md). RFQ entry requires
   a fee-verified, delta-verified plan no older than five seconds.
5. Inspect `processed_data.options_execution` and the allowlisted Condor context.
   Approve launch separately after checking the team's migration schedule and private
   account connectivity. This repository has not unpaused or started your bot.

## Inspect the lifecycle

Entry requests contain two matched option legs. Flyby signs and submits one
`private/execute_quote` request only for a fresh, full, matching maker quote within
its premium, fee and risk bounds. It verifies the native instrument rules and
maker-leg hash before signing with Hummingbot's existing session signer.
It never routes an option through a perpetual `PositionExecutor`.

| Phase | Entry behaviour | Recovery/exit behaviour |
|---|---|---|
| `requesting` | Block competing entries | Discover a lost RFQ acknowledgement by unique owned label; never blindly resend |
| `quoting_entry` | Accept only the planned full spread | Cancel on stale plan or failed current risk/signal gate |
| `settling` | Block all new entries | Require the owned settled transaction and exact full authenticated inventory |
| `open` / `quoting_exit` | Block all new entries | Request both reversed legs; evaluate +30% TP / −18% SL after fees, six-hour hold, expiry, signal failure or hard stop |
| `cancelling` | Block new entries | Await terminal RFQ status; a cancel acknowledgement isn't a flat-position proof |
| `halted` | Block new entries | Require operator reconciliation; don't place a naked repair leg |

`orders_submitted` counts identified exchange acknowledgements;
`execution_attempts` counts durable execution intents. If an acknowledgement is
lost, `submission_count_incomplete` remains true until read-only reconciliation
finds that owned request. A prepared/signing-failed intent isn't a confirmed order.

Quotes may be absent, expire or fail venue margin/fee checks. Exit triggers aren't
guaranteed fills or guaranteed loss ceilings. Failed or ambiguous settlement doesn't
authorize a retry, journal deletion, namespace change or risk-cap increase.

## Preserve recovery state

Persist `data/flyby-rfq-flyby-competition.json` and its lock alongside the existing
risk checkpoint when the bot restarts. Each write intent reaches disk before its
request. Keep the same account and controller owner; don't share the state directory
between different accounts. The journal stores transaction identifiers, paired trade
P&L and fees, but no private key or signed payload. Its bounded size fails closed
instead of silently discarding history.

The default four Condor samples remain paused and shadow-only. The Condor agent
observes the controller's RFQ state; it doesn't recreate signals, sign requests,
submit private orders or bypass the operator's launch gate.

## Verify without sending orders

From the repository root, run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -p no:cacheprovider tests/test_options_rfq.py
```

The lifecycle tests use a scripted transport. The pinned-container tests in
`tests/test_options_rfq_hummingbot.py` exercise the actual RFQ serializer, signer,
controller and compatibility delegates with network access disabled. Neither is
evidence of an accepted mainnet RFQ or a live option fill.

Protocol references: [legacy RFQ schema](https://github.com/derivexyz/orderbook-stubs/blob/db6b172d5e10553738c74ccab775ef2e7258e955/typescript/private.execute_quote.ts),
[signing layout](https://github.com/derivexyz/v2-action-signing-python/blob/d1914d61985e33559244da242892c7255b6fd0ca/derive_action_signing/module_data/rfq.py),
and [atomic RFQ contract](https://github.com/derivexyz/v2-matching/blob/f6c20f46e346151e0969777c5119c92ec21b3be8/src/modules/RfqModule.sol).
