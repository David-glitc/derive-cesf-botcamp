# Final submission hardening — 2026-10-02

The local review candidate adds pinned, opt-in execution/account compatibility,
correct Hummingbot pair names, venue minimum diagnostics and a reproducible
Condor package. **It remains paused and not cleared for live trading.** No
private account request, signing, order, activation, commit, push or submission
occurred. Read [the installation guide](../MAINNET_SETUP.md) before team testing.

## Runtime changes

| Boundary | Implemented | Remaining limit |
|---|---|---|
| Symbol mapping | BASE-USDC Hummingbot pair -> BASE-PERP venue instrument | Team chooses market/account universe |
| Close action | Derive-only CLOSE; reduce-only market or IOC limit | Real fills, partial close/dust and recovery not verified |
| Signed market price | Finite 15bp bound around mid, rounded inside the bound | Fast moves can leave unfilled residual exposure |
| Price/fee serialization | Exact decimal ticks; post-only maker flag; bounded per-contract fee formula | Tier, signing and charged fees require private validation |
| Account state | Full authenticated legacy SM snapshot; net equity and signed net margin; empty positions clear cache | Unsupported collateral/positions/schema fail closed; no private sample taken |
| Venue sizing | Downward lots, executable ticks, minimum/cap diagnostics | No automatic cap increases or instrument changes |
| Condor package | Identity, canonical wrapper, four identical paused sample configs | Import doesn't install Python dependencies or client patches |

The compatibility installer verifies exact original source hashes for both
Hummingbot 2.17.0 files before any patch write. Check-only is the default.
Explicit apply is idempotent; verified originals remain recoverable via
`--restore`. Other connectors keep their upstream executor behavior. Controller
entry requires the compatibility marker and a fresh full net-margin snapshot.

Legacy fields were checked against the official
[get_subaccount schema](https://github.com/derivexyz/orderbook-stubs/blob/master/typescript/private.get_subaccount.ts).
The current [order guide](https://docs.derive.xyz/trading/order-types) documents
market price bounds and non-resting reduce-only behavior. These sources don't
replace private legacy mainnet execution validation.

## Verification

The final four-stage validation bundle passed: **2,340 host tests** (two
Hummingbot-only skips), **2,410 pinned-image tests** (seven upstream warnings),
the model checker and the 48-case stressed replay. Its source hashes cover
the controller, compatibility delegates, account/venue contracts and replay.
The three cost/capacity scenarios produce 144 comparisons in total.

The model checker again passed 555 states and 8,040 transitions, with six SMT
obligations UNSAT and two deliberately unsafe mutations SAT. Its existing
integer/rational models do not prove the new live connector or floating-point
execution. An initial driver run correctly failed without the optional Z3 path;
the documented solver environment passed the rerun. Both records are retained.

In another fresh disposable pinned image, check/install/check/restore/reapply
passed. All four installed controller profiles imported without the repository
on PYTHONPATH and remained paused. The installed package exposed the bounded
market-price delegate; no persistent container was modified.
All connector requests in contract tests use synthetic responses and mocked
transport. No wallet, signature or private account data is involved.

Condor's official local checkout at
`07b4601b5a5060e3c7339696b0cd2f8236966fa2` parsed the identity and discovered the
directional controller and ETH/BTC/SOL/HYPE samples. This proves filesystem
compatibility with that checkout, not the organizers' unknown deployment version.

The archive tool scans its curated source files for bounded secret patterns,
rejects matches without printing values, includes source hashes, and excludes
runtime state, keys, raw traces, media and the old local harness. This isn't a
comprehensive secret/security audit. A dirty base Git commit doesn't identify
the bundled source; its file hashes do. No upload is performed.

## Cost and capacity diagnostics

The existing 48-policy comparison matrix was rerun with public taker assumptions:
3bp per side plus $0.01 per order, retaining 3bp modeled slippage per side and
the existing funding assumption. The
[official fee schedule](https://docs.derive.xyz/integrators/trading/trading-fees)
supports those public defaults; account tiers aren't verified.

| Partition | Baseline mean net | Hold-hysteresis mean net |
|---|---:|---:|
| Train | −1.3064% | −1.3462% |
| Validation | −0.7593% | −0.6658% |
| Test | −0.3289% | −0.1729% |

Means represent eight separate $800 runs per policy/split, not one portfolio.
The hold policy's test slice produced 202 trades and $21.03 modeled fees.
Lower costs still don't establish profitability, and changing the cost gate
changes which trades enter. Proxy candles were previously inspected, not unseen.

Applying today's venue lots/minimums to old proxy bars produced only three
train trades, zero validation trades and one test trade per policy. Mean train
and test returns were +0.0362% and +0.0678%; this sparse, anachronistic capacity
diagnostic is **not evidence of executable historical Derive alpha**. Both
policies rejected 1,275/362/372 entries by minimum size across the partitions.
No OHLC run claims maker queue fills or contemporaneous options execution.

The current public sizing check found:

| Market | Minimum notional | Fraction of $800 | Fits unchanged $160 notional cap? |
|---|---:|---:|---|
| ETH | $271.68 | 33.96% | No |
| BTC | $855.75 | 106.97% | No |
| SOL | $12.10 | 1.51% | Yes, before other gates |
| HYPE | $88.78 | 11.10% | Yes, before other gates |

Prices/rules can change. These are public capacity observations, not verified
available account margin or a recommendation to activate the fallbacks.
The user requested discussion of any explicit ETH/BTC cap change before launch;
caps and default ETH selection remain unchanged.

Ignored evidence lives under `data/validation/final-submission-20261002/`:
public rule snapshot, `final-release/` validation and `final-{stressed,public-taker,
public-taker-venue}/` matrices and traces. Build the final
review ZIP with `scripts/build_submission.py`; the manifest identifies its source.

## Outstanding launch/submission gates

The team must approve the client patch and validate its own SM account schema,
private stream, signed entry, cancellation, partial/dust close, fees/funding,
reconnect and restart on the final image. No stock atomic options adapter exists;
options remain disabled. Unseen/forward cost-adjusted edge is still unproven.

Commit/push or upload the reviewed source separately by 2026-10-04 00:00 UTC
(02:00 Berlin). The archive is a local review candidate, not a submitted or
live-ready release. See [launch gates](../COMPETITION_READINESS.md).
