# Backtest evidence

Use `stress_flyby.py` for the current shared policy. It replays closed Binance
USD-M perpetual candles and emits local ignored traces and source hashes.
It doesn't reconstruct Derive liquidity, execute Hummingbot orders, or prove
options profitability. See [the current report](../reports/STRESS_REPORT.md).

To plot completed final-campaign equity, sizing, exposure and exits without
rerunning the strategy, use `python3 -m backtest.plot_portfolio` from the repo
root. It needs the local ignored campaign traces and local Matplotlib. See
[portfolio analysis](../reports/PORTFOLIO_ANALYSIS.md), the
[execution-path review](../reports/FLYBY_CODE_REVIEW.md) and
[richer-data reference](../reports/DERIVE_QUANT_DATA.md).

Options now have a separate paper replay, not a retroactive addition to the
15M perp campaign. See [the runbook](OPTIONS_PAPER.md) and
[observed results and live blocker](../reports/OPTIONS_PAPER_REPORT.md).

Other scripts and pre-existing plots in this directory test older strategies.
They are historical research, not results for the current controller. The
fixed pre-cleanup controller diagnostic is `current_flyby_confusion.json`;
its original script is archived locally because it imports a controller
that has since changed. It isn't a reproduction of the new implementation.
