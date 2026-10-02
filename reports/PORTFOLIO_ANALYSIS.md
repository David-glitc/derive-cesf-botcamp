# Flyby performance and sizing — 2026-10-01

The completed replay still does not establish a profitable trading edge. Mean
account return improved from −4.22% to −1.88%, but gross P&L before fees and
funding remained negative. Trading rules and paused configurations were not
changed for this analysis.

## Open the charts

- [Performance, first 48h, modeled volume and fees](flyby_performance_overview.png)
- [Equity and drawdown paths](flyby_equity_drawdown.png)
- [Filled position sizing and marked exposure](flyby_sizing_exposure.png)
- [Exit reasons, P&L decomposition and trade win rates](flyby_trade_diagnostics.png)
- [Machine-readable statistics](flyby_portfolio_summary.json)
- [Timeframe CSV](flyby_portfolio_by_timeframe.csv)

![Performance overview](flyby_performance_overview.png)

## What “15M” means

Three campaigns each evaluated 5M bars, in 1,000 runs of 5,000 bars. Runs reuse
64,800 closed Binance USD-M candles across ETH, BTC and SOL. This is a paired
stress comparison, not 15M independent observations. The final campaign
reproduced the mitigated campaign's P&L with additional entry records.

Sizing and path charts use those final 5M bars: 1,000 independent simulated
accounts starting at $800, with one instrument per account. The *accounts* are
separate; their overlapping market samples are not statistically independent.
They cannot be added into a synchronized multi-asset portfolio. There is no
options P&L or historical HYPE cohort here. “15m” below denotes the timeframe,
not the 15-million-evaluation total.

## Performance and allocation

All rows include cost/fault scenarios and no-trade runs. The full-run durations
differ; compare first-48h results for the competition horizon, not annualized
returns or a ranking based solely on unequal-duration terminal returns.

| Timeframe | Run span | Mean net return | Mean first 48h | Median filled allocation | Net trade win rate |
|---|---:|---:|---:|---:|---:|
| 5m | 17.4 days | −0.52% | −0.058% | 17.71% | 19.10% |
| 15m | 52.1 days | −1.37% | −0.059% | 15.30% | 24.73% |
| 1h | 208.3 days | −3.22% | −0.045% | 6.14% | 27.78% |
| 4h | 833.3 days | −2.42% | −0.014% | 6.51% | 34.70% |

Filled allocation is entry notional divided by pre-entry equity, not deposited
margin or leverage. The observed entry cap was 20%; median across all trades
was 7.82%. Planned stop risk peaked at 0.30% of pre-entry equity, excluding
fees, gap risk and liquidation. A stop distance is not a guaranteed loss bound.

The risk rule shrinks allocation toward a 25%-of-normal floor as peak losses
approach the 4% halt. Together with the 20% notional cap, this explains the
cluster near 5% allocation. Partial-fill scenarios create smaller positions.
The scatter uses pre-entry account return, not peak drawdown; it illustrates
the pattern but is not an exact plot of the risk scaler's input.

Bar-close occupancy was 0.45% / 2.35% / 4.52% / 2.83% for 5m / 15m / 1h / 4h.
These observations undercount intrabar exposure: 19,810 of 92,598 trades opened
and closed within the same simulated bar. Their fills and fees are included,
but their positions are absent from the bar-close exposure snapshot. Do not
interpret low close exposure as low intrabar risk or infer exact holding times
from coarse candle indices.

## Where the losses came from

Of 92,598 closed trades, 56,717 (61.25%) closed on signal invalidation,
19,475 on stops, 10,363 at targets, 5,742 at time limits, 283 on halts and 18
at the run boundary. Signal-invalid closes contributed −$13.62 to mean account
P&L; stops contributed −$19.36, targets +$15.60 and timers +$2.37.

Mean gross P&L was −$5.36, modeled fees −$9.52, funding approximately −$0.17,
and net P&L −$15.05 per account. Gross already includes modeled slippage.
This supports investigating both entry selection and exit churn. It does not
prove that holding invalid signals longer would improve results.

## Reproduce and verify

From the repository root, with the ignored campaign traces present:

```bash
python3 -m backtest.plot_portfolio
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests/test_portfolio_analysis.py
```

The plotter rechecks all 1,000 final gzip SHA-256 hashes, 5M sequential bar
records, timestamps, entry/close matching, cash, fees and terminal equity.
It reconstructs marked notional from the trace's rounded equity and cash;
this avoids mixing the gap-shock scenario with unmodified candle marks.
Six-decimal equity rounding introduces negligible reconstruction precision loss.
Bands are scenario percentiles, not confidence intervals; median paths do not
represent any one tradable account. Source hashes are in the JSON summary.

The final campaign snapshot is not byte-identical to today's entire worktree:
subsequent controller hardening added ID/proxy/checkpoint validation and
executable-limit sizing, and the harness's 48h sampling expression was corrected.
The shared decision, feature, sizing, options and ledger source hashes still
match the snapshot. These plots reconstruct the completed immutable traces,
not a fresh backtest of every later controller change. The 48h chart uses the
correct close-time boundary, not the older CSV's one-bar-late value.

Plots use NumPy, pandas and Matplotlib locally. The competition runtime does
not import Matplotlib. See the [stress report](STRESS_REPORT.md) for source
snapshots, execution assumptions and remaining live blockers, and the
[code review](FLYBY_CODE_REVIEW.md) for the current strategy's decision path.
