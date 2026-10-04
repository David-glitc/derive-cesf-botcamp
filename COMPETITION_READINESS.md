# Live readiness — NO-GO (2026-10-03)

The new [bounded Condor runtime extension](RUNTIME_OVERSIGHT.md) refreshes private
controller/account state, exposes read-only tools and accepts reviewed veto,
size-reduction, new-entry tuning and owned-close requests. It remains off in all
shipped profiles. Its offline verification does not clear mainnet, profitability,
provider latency, history-capacity or exchange-soak gates; the existing paired
exit fee/recovery blocker remains unresolved. No bot was activated.
See the [runtime verification evidence](reports/RUNTIME_OVERSIGHT_VERIFICATION.md).

Current drawdown policy: `flyby-dd15-dd25-v1` enters restricted trading at
−15% of peak equity and latches a hard stop at −25%. At an $800 peak, these
are $680 and $600. Position caps, signals and the $800 allocation are unchanged;
production profiles remain paused. Old-policy checkpoints fail closed and
require operator review; no runtime state was migrated or reset. Historical
performance below predates this change and does not establish a positive edge
under the wider limits. See [operator state rules](MAINNET_SETUP.md#preserve-competition-drawdown-state).

The [chronological alpha pass](reports/ALPHA_WALKFORWARD_REPORT.md) evaluates
16 bounded model configurations and 12 final-year execution ablations. No model
beats the zero-return validation benchmark; the least-bad frozen choice vetoes
all entries, not a profitable active strategy. Baseline final-year perps/combined
lose $53.49 base / $66.86 cost stress, and historical options still execute zero
trades. Greek computations and lean fee/theta checks are offline research only;
fresh public API Greeks don't establish executable or private fills.

The [five-million-path portfolio screen](reports/PORTFOLIO_5M_PATHS_REPORT.md)
rejects baseline, wider ETH and hypothetical combined profiles from the research
shortlist under the requested $500 intra-path loss/drawdown rule. Ordinary
empirical cases have no $500 breach but negative mean P&L; the declared extreme
gap/fee stresses breach the limit. This is conditional Monte Carlo evidence,
not a live-market loss probability or a controller/Condor execution soak.
Production profiles and persistent risk state were not changed.

The latest [options construction/fee audit](reports/OPTIONS_EXECUTION_FEE_AUDIT.md)
reproduces an exit-fee-cap rejection with both paired legs retained and an
unresolved execution intent. Normal controlled closes pass, but this fee/recovery
blocker must be fixed and revalidated before activation. No production strategy
or risk-budget change was made by the diagnostic pass.

The separate [approved ETH exposure test](reports/ETH_EXPOSURE_TEST_REPORT.md)
is implemented and paused. Its six-case replay still executes zero options and
loses $80.04 base / $80.10 cost stress in perps/combined. The ten-case baseline
regression matches prior results exactly; wider caps are not a live promotion.

Latest two-year evaluation: 18 fixed-policy cases on checksummed free public
underlying/IV history. Current-lot options execute zero trades; perps and combined
cases lose $80.83 base / $81.45 cost stress from a shared $800 account. Conservative
venue minimums and fee-adjusted spread gates remain binding; finer-lot diagnostics
don't fix them. No candidate is promoted. Read the
[two-year measured report](reports/TWO_YEAR_OPTIONS_PERPS_REPORT.md).

Latest implementation: [atomic option RFQs](OPTIONS_EXECUTION.md) now have a
real v2 transport/signer, canonical controller wiring, paired exits and durable
restart reconciliation. Two separate profiles install paused. Network-disabled
tests exercise the actual Hummingbot classes; no mainnet option order was sent.
This fixes the missing-code gap, not the private-fill or profitability gates.
The final options pass recorded 2,881 pinned tests, the 600-spread virtual
fault campaign and a real Condor mocked-provider tick; see the
[atomic options evidence](reports/ATOMIC_OPTIONS_EXECUTION_REPORT.md).

The Condor packaging blocker is fixed: explicit identity/loop, fixed baseline
profile and no-overwrite installer. The latest pass includes 2,683 host and
2,775 pinned tests, actual Condor registry/config/mocked-tick checks, both formal
models and extracted-archive installations. See the
[final Condor report](reports/CONDOR_FINAL_VERIFICATION.md). Real provider/API,
private execution/restart and positive-edge gates remain unverified.

Earlier milestone: the user-approved −10% restricted / −15% hard-stop policy
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
| Paired options lifecycle | Atomic v2 RFQ entry/exit/restart implemented; scripted exchange and real HB signer tested offline | Opt-in paused; mainnet fills unverified |
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
