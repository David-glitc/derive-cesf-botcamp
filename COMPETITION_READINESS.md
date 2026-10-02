# Live readiness — NO-GO (2026-10-02)

The Condor packaging blocker is fixed: explicit identity/loop, fixed baseline
profile and no-overwrite installer. The latest pass includes 2,683 host and
2,775 pinned tests, actual Condor registry/config/mocked-tick checks, both formal
models and extracted-archive installations. See the
[final Condor report](reports/CONDOR_FINAL_VERIFICATION.md). Real provider/API,
private execution/restart and positive-edge gates remain unverified.

Latest milestone: the user-approved −10% restricted / −15% hard-stop policy
has account-bound persistent latches, completed-signal/cooldown protection and
actual pinned action tests. The optional 30m scalp candidate raises turnover
but worsens net P&L, so baseline samples remain paused and unchanged in signal
profile. Read the [risk/turnover evidence](reports/COMPETITION_RISK_TURNOVER_REPORT.md).
This doesn't clear private fill/restart recovery or profitability gates.

The [delta/options update](reports/DELTA_OPTIONS_REPORT.md) adds capped signed
delta, explicit strike moneyness and fee-aware shadow context. Dynamic paper
exits and algebraic delta-bound checks don't verify paired live execution.
Twenty 48-hour proxy cases remain economically negative or minimum-lot blocked;
150% return and $50k experiment-volume stretch targets are not achieved.

The corrected controller and explicit opt-in compatibility patch pass
pinned-image contract tests. Live execution isn't cleared: replay performance
remains negative and the adapter lifecycle
hasn't passed a live soak. Do not confuse model validation with exchange E2E.
The submitted runtime is now mainnet-only, not automatically live-enabled.
See [team mainnet setup](MAINNET_SETUP.md). Old local testnet snapshots don't
verify the team's mainnet account; installation doesn't migrate credentials.

| Gate | Evidence | Status |
|---|---|---|
| Validated client pin | v2.17.0 tag/digest downloaded; real model/controller tests | Passed |
| Perp connector/mode | `derive_perpetual`, `ONEWAY`, actual exit serialization | Passed |
| Mainnet-only configuration | Reject testnet/paper names and wrong runtime domains; installer checks stock legacy v2 endpoints and paused profiles | Contract-tested, not private connectivity |
| Team mainnet account | Team supplies encrypted credentials and selects its account/universe | Operator setup required |
| Approved instrument rules | Local API returned ETH/BTC/SOL/HYPE trading rules | Read-only discovery passed |
| Testnet exposure | Local API returned zero positions and working orders | Flat snapshot, not historical proof |
| Shared policy | Controller directly imports deterministic Condor policy | Passed |
| Native data and Condor context | Bounded legacy ETH/BTC index/volume/option capture, pricing and source-linked shadow replay; allowlisted status reporting | Verified slice only; no continuous feed or live switch |
| Defined-risk plans | Call/put planner and shadow exits tested | Planner only |
| Stress campaign | Three ×1,000 runs, 5m/15m/1h/4h, 15M evaluations with audited traces | Complete; economic gate failed |
| Private stream/reconnect | Prior WS1006; current local testnet diagnostic: tracker not ready, no connected book stream/books | Not cleared |
| Entry/partial fill/cancel/close | Fixture/model tests, not real adapter fills | Not cleared |
| Reduce-only close | Opt-in pinned patch sends CLOSE only for Derive; mocked payload is reduce-only IOC/market with a bounded tick price | Offline contract passed; private fills not cleared |
| Account margin/cache | Opt-in full authenticated SM snapshot parser, signed net-margin cushion, atomic full position replacement including empty lists | Fixture-tested; team account schema/refresh not cleared |
| Venue sizing | BASE-USDC mapping, exact lot/tick rules, explicit minimum-budget diagnostic, no cap increase | ETH/BTC currently incompatible with $160 cap |
| Fill/funding bridge and restart | Helpers tested; exact live reconciliation absent | Not cleared |
| Paired options lifecycle | No verified paired executor | Disabled |
| Formal paired safety model | Six exact-model SMT obligations, two detected unsafe mutations; 555 states/8,040 reducer transitions | Model verified, not exchange execution |

Before live enablement, complete a 24–36h adapter soak on the final image:
startup, private-stream health, stale-book halt, cancellation, partial-fill
recovery, bounded close, fees/funding and restart reconciliation. This requires
an operator-approved validation procedure for the target mainnet connector.
Forward shadow observation doesn't submit orders. Real fill testing requires
separate explicit operator approval; this configuration update submits none.
If isolated testnet adapter testing is needed, use a separate upstream harness,
not overrides to the mainnet-only competition controller.
Prove a cost-adjusted edge on unseen data or forward shadow execution before
risking competition capital. A smaller loss is not a profitable strategy.

Sample profiles remain paused. Re-connect credentials after the v2.17 field
rename, persist `data/`, use stable IDs/budget, and don't share the account with
other trading processes. An operator—not an LLM—clears these gates.

Source inspection found that unpatched `_update_positions()` returns without
clearing cached positions when the adapter receives an empty position list.
That can leave stale account exposure after closing. These adapter behaviors
have reviewed offline fixes in `scripts/hummingbot_compat.py` and
`src/execution/derive_hb.py`. The team must approve the explicit installation
and validate its own private lifecycle before enabling samples. The patcher
refuses unknown source hashes and preserves originals; it doesn't patch running
containers here. Reduce-only dust closes below venue minimums, fast-market
partial closes, signing, fills and restart recovery remain launch blockers.

The unpatched adapter reports USDC collateral amount as both total and available
balance; that isn't independently verified free margin. This controller
now requires the fresh full authenticated net-margin boundary and blocks entry
on the stock connector or missing/expired state. This is source/fixture evidence,
not a claim that the team's credentials or production account were verified.

## Mainnet configuration verification — 2026-10-02

The host suite passed 1,114 tests with one Hummingbot-only skip; the pinned
image passed 1,149 tests with seven upstream deprecation warnings. The
installer also completed in a separate disposable pinned container: all four
installed profiles validated as mainnet/paused, and the installed controller
rejected testnet configuration. Failed preflight tests left targets untouched.
The preflight reports account and live execution as unverified.

The legacy mainnet `public/get_time` endpoint returned HTTP 200 with a result;
this is public reachability, not private-stream or order-lifecycle proof.
No persistent runtime installation, credential migration, live Condor restart,
bot activation or exchange order occurred. Strategy parameters are unchanged.

## Native data verification — 2026-10-02

The subsequent data/context milestone passed 1,190 host tests (one skip) and
1,228 pinned Hummingbot tests (seven upstream warnings). Both native ETH/BTC
captures returned option prices/IV/OI and complete 180-bar index/perp-volume
windows. Replay produced no option trades, so it adds no profitability evidence.
The installer imported the new modules in a disposable container without
activating the paused ETH profile. See the
[native coverage and verification report](reports/NATIVE_DATA_REPORT.md).

The native path is shadow-only. Detailed context files require an owned shared
volume and an explicitly mounted Condor workspace; source-level API transport
checks aren't proof of a deployed live agent. All live launch gates remain.

## Expanded shadow validation — 2026-10-02

The eight-stage local bundle passed 2,299 host tests (one skip) and 2,341 pinned
tests (seven upstream warnings), model proofs, 48 fixed policy comparisons and
bounded public capture/replay. Native 5m input is now explicit opt-in; submitted
profiles retain the paused baseline source. Bounded L2/tape/IV/skew/OI/spread
analytics don't prove synchronization, a complete tape or dealer GEX.

Hold hysteresis's mean test-partition result remained negative (−0.3242% versus
baseline −0.4777%) on previously inspected proxy data. No policy was promoted.
Pure account/close contracts and the paired simulator don't patch the installed
connector or provide live transport. Actual close/margin/cache/paired execution
and unseen-edge gates remain NO-GO. See the
[expanded evidence report](reports/SHADOW_VALIDATION_REPORT.md).

## Final submission hardening — 2026-10-02

The local candidate passed 2,340 host tests (two Hummingbot-only skips), 2,410
pinned tests (seven upstream warnings), the bounded model checker and three
48-case cost/capacity replay matrices. A fresh disposable installer/recovery
cycle imported all four paused profiles from installed modules. Condor's own
filesystem parser discovered the identity, wrapper and four paused samples.

Explicit pinned compatibility addresses close flags, signed market bounds and
full account/margin/cache replacement offline. The team still must approve
that patch and validate private fills, partial/dust exits, fees/funding and
restart/reconnect on its final image. Public-taker replay remains negative;
ETH/BTC minimums currently exceed unchanged caps. No bot was activated, no
order submitted and no source pushed/uploaded. Read the
[final report](reports/FINAL_SUBMISSION_REPORT.md).
