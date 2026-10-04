# Atomic options execution — offline verification (2026-10-03)

The missing options execution code is now implemented in the canonical Flyby
controller. You can configure a separate paused ETH/BTC RFQ lane without routing
options through Hummingbot's perpetual executor. Mainnet option orders, accepted
RFQs and real premium fills remain unverified; no live activation or push occurred.

## Implemented surface

| Component | Responsibility |
|---|---|
| `src/execution/derive_rfq.py` | Legacy v2 request/poll/cancel/execute transport; native instrument checks; maker-leg hash; existing HB signer/auth |
| `src/execution/options_rfq.py` | Paired lifecycle, exclusive durable account/owner journal, unknown-ack recovery and exact inventory/settlement checks |
| `controllers/directional_trading/flyby.py` | Explicit RFQ mode, shared entry exclusion, fresh risk rechecks and protective servicing during stale entry data |
| Full account compatibility delegates | Preserve option positions/Greeks in authenticated SM snapshots; don't map them to perps |
| Condor context and playbook | Report lifecycle phase, owned option inventory, attempted versus acknowledged submissions, uncertainty, fees and paired closes |
| `conf_flyby_options_{eth,btc}.yml` | Separate paused profiles; unchanged budget/risk caps; at most one RFQ controller per account |

The four original registered samples keep their fixed settings. Only their
comments changed. Previous optimization candidates remain isolated and unpromoted.
The default launcher doesn't select either RFQ profile.

## Safety properties exercised

- Reject stale/partial/foreign or changed-leg quotes and native contract/tenor,
  lot, tick, payoff or maker-hash mismatches before submitting orders.
- Prepare/sign a quote in memory before persisting its execution intent;
  a rejected signature/hash cannot create a phantom pending order.
- Refresh account/risk after preparation, account for clocks advancing during
  network waits, and reject quotes that expire before submission.
- Persist the consumed signal and full execution intent before a private write.
  Lost acknowledgements trigger read-only discovery/reconciliation, not a retry.
- Require an owned settled taker transaction, actual bounded fees and exact full
  authenticated inventory before recording a spread entry or close.
- Reverse both legs in one RFQ for +30%/−18% net-value, six-hour, signal, expiry,
  current Greek/exposure or hard-stop exits. No independent short-option repair.
- Preserve the account-bound −10% restricted / −15% hard-stop latches. A recovery
  in equity doesn't reset the hard stop. Protective servicing doesn't require
  healthy entry candles or an LLM tick.
- Report open option gross reference exposure and Greeks to Condor rather than
  showing an empty perpetual map as a flat account.

## Evidence boundaries

Final pinned run: **2,881 passed**, seven upstream deprecation warnings,
142.78 seconds, with networking disabled and the repository mounted read-only.
This includes 49 lifecycle/fault/virtual-clock cases and 15 real-Hummingbot
RFQ signer/controller/context cases. The separate upstream Condor check verified
agent/loop discovery, typed configuration, a real tick/prompt/persistence cycle
with mocked providers, and zero network attempts or submitted orders.
Condor still permits some design-time saved-config writes in dry run; the
playbook forbids them, but isn't a configuration sandbox.

The fault-injected lifecycle test advances a 50-hour virtual clock through 600
paired spreads and 1,200 execution requests, including rejected partial quotes,
restarts and lost send/execute acknowledgements. Its scripted prices and account
are fixtures. It is NOT a 50-hour wall-clock production soak, market backtest,
profitability result, minimum-lot proof or live capital/turnover measurement.

Pinned Hummingbot tests use the actual v2.17.0 controller/models, session signer,
RFQ ABI and auth serializer in a network-disabled disposable container. The signer
uses a public deterministic fixture identity, not any credential store. API/schema
and mainnet RFQ contract addresses are source-pinned in the adapter module.

Public unsigned legacy mainnet reads returned ETH option instruments and native
metadata, including `ETH-20261030-3000-C` with amount step 0.01 and minimum amount
0.1. Public discovery doesn't establish session permission, margin, RFQ maker
liquidity or accepted private execution. Minimum lots can still violate the
existing $800 delta/gross/debit caps; this implementation doesn't widen them.

Remaining operator gates: a dedicated mainnet SM account with an admin-level
registered v2 session, fresh native context, verified private RFQ/fill/close/restart,
the team's v2/v3 migration schedule, approved activation and production endurance.
The strategy's cost-adjusted edge remains unproven. No source or test change here
authorizes live trading, credential reuse or submission of the dirty worktree.

Use [options setup](../OPTIONS_EXECUTION.md) and the updated
[field-by-field Botcamp answers](../BOTCAMP_STRATEGY_DESCRIPTION.md) for handoff.
