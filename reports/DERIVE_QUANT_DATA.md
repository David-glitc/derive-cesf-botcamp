# Derive quant-data reference — checked 2026-10-01

We can go beyond candles without buying a premium subscription first. Derive
documents public tickers, option pricing, books and trades. Most requested
metrics must be calculated from those inputs, not fetched as a ready-made
“quant signal.” Historical coverage and executable liquidity remain separate
requirements. Nothing below has been wired into Flyby's trading decisions.

## What was checked directly

Unauthenticated public reads returned:

| Probe | Observed result | What it proves |
|---|---|---|
| `api.derive.xyz/v3/public/get_ticker`, ETH-PERP | HTTP 200; `stats`, mark/index, quotes, hourly funding | v3 public perp ticker schema is reachable |
| `testnet.api.derive.xyz/v3/public/get_ticker`, ETH-PERP | HTTP 200; same short-key schema | Testnet public ticker reachable, not order execution readiness |
| v3 `public/get_instrument`, ETH-PERP | Maker rate 0.0001, taker rate 0.0003, base fee 0.01 | Public instrument fee metadata available; account tier still separate |
| v3 ETH `public/get_all_instruments` | 986 definitions on requested page; 170 with 2–5 DTE | Metadata is not proof of active/executable contracts |
| Active-window filtering in another read | 820 active definitions; 114 at 2–5 DTE | Must check `is_active` and scheduled activation/deactivation |
| Sample option ticker | IV 0.54492, delta −0.36544, gamma 0.00034113, vega/theta; bid=ask=0, OI=0 | Greeks may exist without tradable prices; this sample is **not** a usable option book |
| v3 ETH-PERP `public/get_trade_history` | HTTP 200; paginated trades with price, amount, time, direction and liquidity role | Public historical tape endpoint available; full retention/backfill not measured |
| Unversioned `api.derive.xyz/public/get_ticker` | HTTP 404 | Do not silently use this host/path as v3 |
| Legacy `api.lyra.finance` and `api-demo.lyra.finance` ticker routes | HTTP 200; long-key ticker/metadata/`open_interest` schema | Existing Hummingbot host names still respond; no proof of full private compatibility |

Counts and quoted values are point-in-time observations, not persistent market
properties. The sampled usable model ticker was `ETH-20270924-2700-P`, not a
short-DTE candidate. A metadata-only short-DTE sample (`ETH-20261006-3350-P`)
initially returned “Ticker not found.” The whole short-DTE chain's quote/depth
coverage was **not** validated. No wallet keys, authentication, private APIs,
order submissions or long-running collector were used for these probes.

## Version boundary

The official developer hub and machine-readable schema currently describe v3.
Keep the data adapter versioned: v3 uses `I/M`, `a/b`, `A/B`, `t`,
`option_pricing`, and `stats`; metadata comes from `get_instrument`. Legacy
payloads use long keys and different OI structure. Never take a ticker object
from one version and feed it directly to the other adapter.
[Migration reference](https://docs.derive.xyz/migrating/breaking-changes.md),
[OpenAPI](https://docs.derive.xyz/openapi.json).

The inspected Hummingbot connector uses the legacy Lyra hosts. Keep its
private execution path untouched during data exploration. A sidecar should
only read public data and emit normalized snapshots. v3 legacy-statistics
methods are listed as forthcoming; do not base the collector on assumed
availability of `public/statistics`.
[Availability notes](https://docs.derive.xyz/migrating/coming-soon.md).

## Data and metric inventory

The following rows distinguish venue inputs from proposed calculations. No
historical Derive books, IV, Greeks or OI exist in the completed OHLC replay.

| Requested metric | Raw source | Calculation / role | Historical limitation |
|---|---|---|---|
| Underlying/index, mark and basis | Ticker `I`, `M`; synchronized external price if retained | Mark–index basis, cross-venue basis and venue quality | Old Binance candles are not synchronized Derive quotes |
| Depth/order book | `orderbook.{instrument_name}.{group}.{depth}` | Spread, impact curve, top-N imbalance, capacity, approximate microprice | Record snapshots forward; archived L2 not established |
| Volume and flow | `trades.{instrument_name}` and public trade history | Rolling base/notional volume, VWAP, trade intensity; CVD after side verification | Verify pagination, timestamp units, deduplication and maker/taker representation |
| POC / value area / HVN / LVN | Individual executed trades with price and quantity | Fixed-window volume-at-price bins; POC is largest-volume bin | Cannot recover exact price-level volume from OHLCV |
| OI and OI change | Ticker `stats.oi`; legacy ticker OI has different structure | Per-contract levels, ΔOI, expiry/strike concentration | Current OI is not a historical time series; store timestamped observations |
| IV surface | Option `option_pricing.i`, `bi`, `ai`; strike/expiry metadata | ATM term structure and robust bid/ask-aware surface | Mark IV can exist with no executable quote; no historic surface established |
| Skew / risk reversal | Matched-tenor chain IV and delta | `IV(25Δ call) − IV(25Δ put)`; butterfly against ATM | Declare convention, interpolation and strike coverage; no stale/missing extrapolation |
| Realized / implied volatility edge | Venue trade/index returns and matched-tenor IV | Causal RV estimate versus option implied variance | Existing HAR-like diagnostic is not a calibrated future-RV model |
| Gamma exposure proxy / strike concentrations | Per-option OI, gamma, underlying units and spot | Unsigned OI-weighted gamma profile and scenarios | Dealer inventory sign is not supplied by OI; historic OI/Greeks cannot be fabricated |
| Portfolio delta/gamma/vega/theta | Signed actual positions and per-option Greeks | Net sensitivities, spot/IV/time stress, risk budget | A public chain is not your portfolio; need verified position units and Greek conventions |
| Funding and carry | Ticker hourly `f`; funding-rate history | Signed carry forecast integrated over actual hold | Do not copy the replay's fixed 8h expense model into live decisions |
| Liquidity-adjusted spread return | Both-leg books or paired RFQ quote; instrument/account fees | Executable entry debit and closing credit after fees/impact | A model mark or payoff RR is not expected return or guaranteed fill |

Public ticker details, IV/Greek fields and 24h statistics are specified in
[Ticker slim](https://docs.derive.xyz/api-reference/channels/tickerslim.md).
The aggregated book channel supports group 1/10/100 and depth 1/10/20/100;
its records include instrument, publish ID, timestamp and `[price, amount]`
levels. It is not a full order-by-order queue feed.
[Orderbook specification](https://docs.derive.xyz/api-reference/channels/orderbook.md).

Historical trade queries provide paginated, filtered records, but some broad
queries are constrained to a 30-day window. This is not a blanket assertion
that all instrument-filtered history has 30-day retention. Test requested
ranges and completeness. Trade-price OHLCV is also available, with seconds
for chart request bounds; funding-history request bounds use milliseconds.
[Trade history](https://docs.derive.xyz/api-reference/market-data/publicget_trade_history.md),
[Trading chart](https://docs.derive.xyz/api-reference/market-data/publicget_tradingview_chart_data.md),
[Funding history](https://docs.derive.xyz/api-reference/market-data/publicget_funding_rate_history.md).

Oracle feeds offer forward, rate and SVI volatility parameters. They can help
interpret the mark surface, but do not replace quoted executable prices or
prove a predictive edge. [Signed feeds](https://docs.derive.xyz/api-reference/market-data/publicget_latest_signed_feeds.md).

## Definitions that prevent misleading charts

**Unsigned GEX proxy.** If gamma is per underlying unit and OI is in contracts,
one possible dollar-delta-change-per-1%-spot-move convention is:

```text
unsigned GEX = Σ OI_contracts × underlying_units_per_contract × gamma × spot² × 0.01
```

First verify the venue's OI and gamma amount units. If OI already represents
underlying units, do not multiply by the contract multiplier again. This is
a proposed analytical convention, not a field returned by Derive. Ordinary
long call and long put gamma are both positive: automatically assigning
negative signs to puts does not reveal actual dealer inventory. “Dealer GEX”
and “gamma flip” need explicit ownership/sign assumptions and a repriced
surface. Show scenarios as estimates, never as observed positions.

**Skew.** Use common expiry, verified absolute delta and consistent quote
quality. Interpolate only within adequate strike coverage. A 25-delta call
minus put convention is the opposite sign of put-minus-call; label it. Keep
mark-IV skew separate from executable bid/ask-IV skew. Zero bid/ask IV is
missing information, not an arbitrage opportunity.

**POC.** Pick instrument, UTC window, volume units and price bin width before
aggregation. Sum executed volume into bins, then choose the maximum. Declare
value-area selection/tie rules. A rolling POC may be used only after the
window's trades arrive; a session-end POC cannot leak into earlier decisions.
Neither interpolating candle volume across high/low nor a 24h volume total
reconstructs the actual profile.

**Order flow.** Verify whether a public trade row represents the aggressor
or a participant, using liquidity role and unique identifiers. If matching
produces both participant rows, avoid double-counting volume or canceling
out the signed flow. Aggregated snapshots allow book imbalance and depth
change estimates, not exact cancel attribution, spoof detection or queue rank.

**Net options efficiency.** Compare paired debit/credit after both-leg fees
and realistic exit impact, plus net Greeks and spot/IV/time stress. Rank by
estimated net opportunity and liquidity—not max expiration payoff alone.
Published option fees include a fixed taker component and a notional/premium
cap; RFQ structures have different discounts. Verify network/version/account
fees before modeling them. [Derive fees](https://docs.derive.xyz/integrators/trading/trading-fees.md).

## Proposed analytical chart pack

Once genuine timestamped data exists, plot underlying price with VWAP/POC;
volume and validated CVD; bid/ask spread, depth and impact; OI/ΔOI; ATM-IV/RV
and term structure; 25Δ skew; unsigned strike gamma concentrations; and each
candidate spread's debit/credit, net Greeks and stress P&L. Every panel should
show venue, window, units, age, missing-data mask and observed/model status.
Keep actual portfolio positions distinct from option candidates.

This is a chart specification, not completed charts of historical GEX/skew/OI.
The 15M campaign cannot retrospectively supply inputs it never recorded.

## Recommended acquisition order

1. Capture free public ETH/BTC trades, books, tickers and instrument definitions,
   with version/network and exchange/receive times. Keep orders disabled.
2. Prove coverage, side semantics, units, reconnects and quote quality before
   computing flow, POC, skew and unsigned GEX. Record raw inputs immutably.
3. Collect at least a 48h shadow dataset as a plumbing/liquidity check, then
   a longer chronological research set spanning regimes. Two days do not prove
   profitability. Audit historical backfills independently.
4. Replay venue-priced, net-cost decisions and evaluate isolated feature
   additions on a locked chronological holdout. Include paired options
   lifecycle tests before considering any option execution.
5. Research paid archives only if a specified Derive historical gap remains.
   Other exchanges' options data is contextual, not Derive liquidity or OI.
   No paid provider has been selected, bought or connected in this pass.

The implementation proposal is in
[/home/david/.claude/plans/flyby-derive-quant-data.md](/home/david/.claude/plans/flyby-derive-quant-data.md).
It is a plan, not authorization to enable trading or remove safety gates.
