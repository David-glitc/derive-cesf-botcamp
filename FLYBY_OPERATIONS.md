# How Flyby operates

Flyby is a deterministic Hummingbot V2 controller with Condor oversight—not an
LLM improvising orders. This numbered cycle explains what the code checks,
which decisions you can inspect and where it can reject a trade. Samples remain
paused; describing the cycle doesn't establish that it is running live.

## The operating cycle

1. **Load the fixed profile.** The operator selects the market, stable controller
   ID and shared risk checkpoint. Baseline allocates $800, uses five-minute
   candles, 2× leverage and a five-minute entry cooldown. A kill switch blocks
   entries. The bot doesn't automatically switch profiles to chase volume.
   See [sample configuration](conf/controllers/conf_flyby_sol.yml).

2. **Check connection and data health.** The controller requires a ready mainnet
   connector, a recent private stream, updating order book, uncrossed quotes and
   fresh completed candles. Proxy/reference basis must stay within its limit.
   Failure blocks new entries; owned protective exits still need servicing.
   See [controller update](condor/flyby/controllers/derive_cesf_long_vol/derive_cesf_long_vol.py).

3. **Read and reconcile the account.** Read authenticated equity, available funds,
   positions and orders. Unknown exposure isn't treated as zero. Peer controllers
   using the same connector must share the account-risk contract. Working
   orders, positions or an unresolved option journal block another entry.
   This is intended gating, not a proved live cross-process concurrency lock.

4. **Update persistent drawdown risk.** Track the account's high-water mark.
   At −15%, latch restricted mode: stricter signals and smaller risk allocation.
   At −25%, latch hard stop and propose owned-position protection/closure.
   Recovery or restarting doesn't silently clear those latches. A stop trigger
   isn't a guaranteed fill price through a gap. See [risk governor](src/risk/competition.py).

5. **Build causal market features.** Use completed candles only. Compute price
   momentum, a four-hour baseline trend z-score, directional efficiency, ATR,
   volume ratio, volatility estimates and CESF diagnostics. These describe market
   conditions; they aren't automatically a forecast of net trade profit.
   See [shared feature computation](src/signal/flyby.py).

6. **Decide whether the direction qualifies.** The original policy checks valid
   data and risk state, then volume, trend, efficiency and same-direction
   confirmation on the current and previous completed bars. Normal baseline
   entry score must reach 0.70; restricted mode requires 0.85. The score combines
   trend/efficiency/volume and is **not a win probability**. The policy produces
   a long, short, flat or halt decision. See [shared decision policy](agents/condor_agent.py).

7. **Consider the optional options lane.** Only an explicitly selected RFQ profile
   can execute options. Fresh native pricing/IV, books, expiry, fees and signed
   delta must support a same-expiry call or put debit spread. Long and short legs
   have matched size; naked legging isn't authorized. Missing, oversized or
   uneconomic spreads are rejected, not forced into minimum size. Delta affects
   construction; extra gamma/vega/theta checks remain separate research diagnostics,
   not full live Greek risk control. See [options execution](OPTIONS_EXECUTION.md).

8. **Size a candidate within the account budget.** Perp size is the smallest
   allowed by loss budget, stop-plus-cost risk, available balance and notional/gross
   caps. Baseline perp notional is at most $160 at $800 equity. Initial trade
   risk is at most $4 and uses the quality score as a sizing weight, not a
   probability. Leverage doesn't double the $160 cap. Option sizing includes
   debit and conservative paired entry/exit fees, gross exposure and delta caps.

9. **Check the executable order, not just the chart.** Round quantity down to
   venue lot steps, reject incompatible minimums, and check current depth and
   worst fill price. Include entry fees/slippage, an exit reserve, fixed fees and
   funding allowance. The configured target must cover at least 3× estimated
   costs normally or 4× in restricted mode. No qualified order means no trade.
   See [risk/cost sizing](src/risk/position_sizing.py).

10. **Consume the signal and submit through the owner.** The checkpoint prevents
    reuse of a consumed signal and enforces cooldown. The perp lane proposes a
    limit-entry position executor with protective barriers. The options lane
    requests an atomic two-leg RFQ, checks the quote/account again and journals
    intent before submission. An acknowledgement alone doesn't prove settlement.
    The intended setup is one perp or one owned paired spread, not a basket of
    simultaneous leveraged positions.

11. **Manage the position and reconcile exits.** Perps have ATR/score-based TP/SL
    and time limits; baseline also exits when the original direction vanishes or
    reverses. Configured TP/SL/time-limit closes are market orders. Options use
    costed paired exit quotes, profit/loss/time/delta checks and RFQ reconciliation.
    No partial/unconfirmed close is declared flat. The known option exit-fee-cap
    blocker remains unresolved. See [fee/recovery audit](reports/OPTIONS_EXECUTION_FEE_AUDIT.md).

12. **Publish status and let Condor observe.** Report signal and entry-block reason,
    equity/risk mode, positions/orders, fees, funding, net P&L and distinct turnover
    measures. Condor's configured 60-second dry-run loop checks the owned bot and
    journals an observation verdict. It doesn't independently submit trades,
    change the profile or reset risk. See [operator loop](condor/flyby/loops/flyby_operator/loop.md).

## What changes in the enhanced research run

The [48-hour experiment](reports/ENHANCED_48H_REPORT.md) adds **entry-only** quality
thresholds: score ≥0.85, signed trend ≥1.50, efficiency ≥0.45 and volume ≥1.50,
with current/previous confirmation. The third variant also adds the frozen
model's cost/error veto and research lean-option checks. Those candidates aren't
registered as production Condor profiles. “High quality” labels the heuristics;
it doesn't promise a solid winning trade.

In the replay, ETH/BTC/SOL perp priority is fixed and there is one shared $800
ledger per independent case. Live operation uses the operator-selected controller
configuration, not an assumed three-market portfolio. Historical execution uses
modeled fills and an in-memory RFQ journal; it doesn't verify the live cycle above.

## How you can help diagnose the edge

For each potential trade, ask: did the original signal qualify, which additional
gate rejected it, could venue size fit the budget, and would the forecast clear
all-in costs? For an entered trade, inspect gross versus net P&L, hold time and
exit reason. Avoid treating confidence as probability or equity recovery as
proof of a clean close. The operation traces and trade ledgers make those
questions inspectable without changing live settings.
