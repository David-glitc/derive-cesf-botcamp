# Condor scaffolding and fixed-profile verification — 2026-10-02

The missing Condor lane now has a discoverable agent and explicit loop. The
fixed submission profile is `flyby-baseline-dd10-dd15-v1`; the loop key is
`flyby.flyby_operator`. The V2 controller, shared `decide()` policy and four
market profiles are byte-identical to the previous delta/options review ZIP.
This fixes packaging and validates local contracts; it does not clear live
execution or establish a profitable strategy.

## Submitted entrypoints

```text
condor/flyby/
  AGENT.md
  PROFILE.yml
  loops/flyby_operator/loop.md
  controllers/derive_cesf_long_vol/
    CONTROLLER.md
    derive_cesf_long_vol.py
    sample_configs/{eth,btc,sol,hype}.yml
```

Follow [Condor installation](../condor/INSTALL.md). The installer copies authored
files into a new `flyby` agent home, refuses overwrite/links/runtime files and
doesn't start a loop. The Python policy alone isn't an agent upload. Registry
checks now exercise actual `AgentStore`, `StrategyStore` and `AgentConfig`, not
only frontmatter/controller parsers. Package and mainnet installation preflight
both reject changes to the fixed signal, sizing and risk settings.

## Verification results

| Check | Observed result | Boundary |
|---|---|---|
| Host tests | 2,683 passed, 3 Hummingbot-only skips | No exchange execution |
| Pinned Hummingbot | 2,775 passed, 7 upstream warnings | v2.17.0 digest, mocked connector contracts |
| Package regression | 73 targeted tests passed | Missing loop, changed profile/caps, sample drift, runtime files, links and overwrite refusal |
| Actual Condor discovery/config | Passed | Local official checkout, isolated agent roots |
| Actual Condor tick | Prompt assembly, one fixture model start/stop, dry-run snapshot persistence passed | API/providers/model mocked; network blocked |
| Dry-run permissions | 12 tested trade/running-bot/code requests refused; status/config/log reads allowed | Gate callbacks tested; no MCP transport invoked |
| Paired reducer model | 555 states, 8,040 transitions, zero invariant failures; six SMT obligations plus two detected unsafe mutations | Bounded integer/rational model only |
| Delta model | Call, put and gross checks `unsat` | Real-valued exposure inequalities, not Greeks/exchange safety proof |
| Fixed replay diagnostics | 60 comparisons; separate 90-case public-taker/current-rule matrix | Previously inspected proxy history, modeled execution |
| Extracted archive → Hummingbot | Installer succeeded in a network-disabled disposable pinned container; four paused profiles imported | Shared delta module loaded from installed site-packages, not source checkout |
| Extracted archive → Condor | Installer/discovery/mocked tick passed from the extracted package | No running deployment replaced |
| Fresh public ETH/BTC | Two observations per asset, source-linked replay completed, no executed option spreads | Brief public capture, not 48-hour history/private proof |

The Condor checkout base revision was
`07b4601b5a5060e3c7339696b0cd2f8236966fa2`; the verifier also records actual
framework file hashes, so that revision isn't the only provenance evidence.
The archive manifest's Condor result covers packaging only; the separate tick
verifier and this report record runtime fixture evidence, not live certification.
Hummingbot uses the digest in [hummingbot-version.json](../hummingbot-version.json).
The final local validation receipt is
`data/validation/condor-final-20261002/final-checks/validation.json`; all seven
stages passed and its 40 source hashes match the reviewed tree. Raw captures,
traces and logs remain local/ignored; the team can rerun the
[validation workflow](../verification/VALIDATION.md).

The first bundle failed its solver stages because the launch omitted the
existing isolated Z3 dependency path. The corrected final command used
`PYTHONPATH=.local_harness/verification-deps`; both proofs passed. An intermediate
long bundle was interrupted during BTC capture; a separate fresh BTC capture
and replay completed. An initial manual archive import used the wrong class
name; rerunning with `DeriveCesfLongVolConfig` passed. These were verification
command issues, not reasons to alter the accepted controller or erase evidence.

## Economic evaluation

The repeated 20 × 48-hour perp diagnostic produced $37,352.51 summed case
turnover, $12,647.49 below the $50,000 experiment target. Returns ranged from
−1.1741% to 0%; no case reached 150%. BTC minimum orders blocked entries; all
ten SOL baseline/scalp cases lost money. The sum isn't one portfolio's turnover.

The separate 90-case matrix includes nine competition-baseline cases: ETH/BTC
were flat, and SOL train/validation/test returned −1.0196%, −0.3410% and
+0.0247%. That small positive test segment on previously inspected data doesn't
prove an unseen edge. All nine competition-scalp cases were non-positive.
No research policy was promoted. Twenty brief options feasibility cases also
produced no matched spread trades; varying policy on the same short capture
doesn't create twenty independent statistical samples.

## Unchanged launch gates

Samples remain paused. Baseline/5m settings, stable controller IDs, the shared
risk namespace, $800 reference capital and existing sizing caps remain fixed.
At −10% account peak drawdown restricted mode latches; at −15% hard stop latches.
These are action thresholds, not guaranteed maximum realized losses. Live
options, portfolio margin and spot hedging remain disabled.

The real provider/server and team's credentials haven't been exercised. Private
stream recovery, partial/dust closes, fills/fees/funding and restart reconciliation
still need production-infrastructure testing. A passing mocked tick doesn't
prove LLM instruction compliance or a deployed recurrent session.

Upstream Condor's dry-run gate permits stored controller-config upserts, while
tested controller sync requests are refused. The playbook prohibits dry-run
writes, but isn't a complete configuration sandbox. ACP providers don't enforce
the identity tool allowlist as a sandbox either. Don't describe this boundary
as comprehensive isolation. See [live readiness](../COMPETITION_READINESS.md).

## Team handoff

Review the exact submitted GitHub commit and install `condor/flyby` deliberately,
then select the team's accessible API server/model and run the explicit loop in
its shipped one-tick dry-run mode. Select only compatible approved markets and
keep stable IDs/checkpoints. Don't increase caps for ETH/BTC minimums or unpause
to chase volume. The v3 proof/migration remains separate from the legacy-v2
controller; this fix doesn't change endpoints or credentials.
