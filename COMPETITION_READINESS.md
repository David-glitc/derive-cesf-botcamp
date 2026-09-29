# Competition readiness checklist

This is the public, sanitized checklist for the Agent Builders Cup profile. It is intentionally operational at the level needed to reproduce the safety gates without publishing account details, credentials, raw fills, or private execution methodology.

## Runtime boundary

The intended path is:

`Condor decision policy → Hummingbot V2 controller/executor → Derive Hummingbot adapter → account and fill events → local ledger/reconciliation`

The adapter owns venue primitives: instruments, trading rules, order books, candles, balances, positions, fees, funding, order submission, cancellation, and fill events. Condor does not place direct Derive orders or maintain a parallel private account poller.

## Approved market profile

- Live perpetual candidates: `ETH-PERP`, `BTC-PERP`, `SOL-PERP`, and `HYPE-PERP`, subject to connector discovery and trading-rule validation.
- Options: ETH and BTC only, and only after the installed adapter proves first-class option discovery, quoting, order lifecycle, fills, fees, and reconciliation. Otherwise options remain disabled.
- ARB, AVAX, and OP: research/backtest only.
- Default collateral and margin assumptions: adapter-reported USDC account state. Do not claim portfolio margin or multi-collateral until live fields and tests prove them.

## Two-phase campaign

1. **Pre-launch soak: 24–36 hours.** Run through the actual Hummingbot/Derive adapter path. Prove startup, reconnect, stale-data halt, post-only entry, cancellation, partial-fill handling, reduce-only close, fee capture, restart replay, and account reconciliation. This is the competition launch gate.
2. **Shadow/testnet campaign: 120 hours.** Run the same profile without risking competition capital. Record hourly health summaries and aggregate net-of-fees performance. If it overlaps the competition, label it as an ongoing validation campaign; it is not pre-competition evidence.

The requested 60–125% return range is an aspirational scenario for research reporting. It is not guaranteed, is not used to loosen risk controls, and is not a go/no-go criterion.

## Go/no-go gates

- [ ] The installed Hummingbot and Derive connector versions are recorded outside this public document.
- [ ] Adapter discovery returns only approved symbols and valid tick/step/minimum-order rules.
- [ ] Condor receives a normalized snapshot with timestamp, equity, margin, positions, open orders, and fees.
- [ ] Every submitted order has a client/order ID and every fill is idempotently recorded by trade ID.
- [ ] Quote, fee, spread, slippage, funding, and minimum-size costs are included before sizing.
- [ ] Reconnect and restart replay produce no duplicate fills, unknown orders, or position drift.
- [ ] A protective exit is reduce-only and is observed in the adapter fill stream.
- [ ] Ledger equity, realized P&L, fees, funding, open orders, and positions reconcile within configured tolerances.
- [ ] Any stale stream, unknown order, unsupported symbol, margin breach, or reconciliation mismatch halts new entries.
- [ ] Public-release audit passes; private artifacts remain outside GitHub.

## Evidence to retain privately

Keep the signed preflight output, connector capability report, account snapshots, raw fill history, incident timeline, and operator sign-off in the deployment workspace or secret-managed artifact store. Publish only aggregate, redacted results after the competition if appropriate.
