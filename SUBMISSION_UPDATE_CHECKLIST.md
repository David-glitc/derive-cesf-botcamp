# Submission update checklist

- [x] One canonical controller; historical name is an import alias.
- [x] Correct perp connector, one-way mode and actual triple-barrier fields.
- [x] Mainnet-only config/runtime domain gates, installer endpoint preflight,
  and consistent portable Condor/team setup instructions.
- [x] Shared policy, closed-bar features, depth/account/cost gates.
- [x] ETH/BTC primary candidates; SOL/HYPE opt-in fallback profiles.
- [x] Matched call/put plans and opt-in atomic v2 RFQ execution, paired exits,
  durable restart reconciliation and separate paused ETH/BTC profiles.
- [ ] Verify accepted mainnet RFQ/fill/close with an operator-approved account;
  offline signer/lifecycle tests are not private venue proof.
- [x] Preserve old testnet runner/traces locally, outside public navigation.
- [x] Test pinned Hummingbot v2.17.0 and run traced stress campaigns.
- [x] Run source-bound two-year underlying/IV proxy simulations with one shared
  $800 combined ledger; report zero eligible option executions and negative
  cost-adjusted perp results without changing caps or promoting candidates.
- [x] Replace stale profit/options/portfolio-margin claims with measured evidence.
- [x] Correct BASE-USDC mapping, report minimum-cap incompatibility, and ship
  explicit pinned close/account compatibility with recoverable originals.
- [x] Include identical paused Condor samples and curated archive/hash tooling.
- [x] Include explicit `AGENT.md` / `loops/flyby_operator/loop.md`, fixed profile,
  no-overwrite installer and real registry/mocked-tick verification.
- [ ] Pass [live readiness gates](COMPETITION_READINESS.md).
- [ ] Operator chooses account universe and deliberately enables the sample.
- [x] Review curated source and run bounded secret/hash checks plus local validation.
- [ ] Record organizer confirmation of the exact submitted GitHub commit.
- [x] Prepare a [source-aligned Botcamp description](BOTCAMP_STRATEGY_DESCRIPTION.md).
- [ ] Publish the reviewed description from the author's Botcamp account and
  verify that the public page matches the accepted code version.

Do not submit runtime state, `stress_artifacts/`, `data/` or `.local_harness/`.
