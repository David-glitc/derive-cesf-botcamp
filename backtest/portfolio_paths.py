"""Fast, offline portfolio risk paths, not a full controller/market backtest.

Block-resample recorded conditional trade outcomes with pessimistic OHLC mark
envelopes. Unexpected gaps/costs and optional scripted spreads are sensitivity
assumptions. Never change production settings, send orders or guarantee safety.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import pandas as pd
from numba import njit

from src.risk.competition import RESTRICTED_DRAWDOWN, HARD_STOP_DRAWDOWN, advance, initial_state, risk_view
from src.risk.exposure import ETH_EXPOSURE_TEST
from src.risk.position_sizing import cost_allows_entry, risk_size

METRICS = ("ending_equity", "minimum_equity", "max_drawdown_dollars", "max_drawdown_fraction",
           "trades", "perp_turnover", "option_premium_turnover", "fees", "restricted",
           "hard_stop", "insolvent", "gap_events", "blocked_option_exit", "terminal_option_legs")
CASES = (("baseline_empirical", False, False, False),
         ("eth_caps_empirical", True, False, False),
         ("baseline_gap_fee_stress", False, True, False),
         ("eth_caps_gap_fee_stress", True, True, False),
         ("combined_hypothetical_option_fault_stress", True, True, True))
RESTRICTED_EQUITY_FRACTION = float(1 - RESTRICTED_DRAWDOWN)
HALT_EQUITY_FRACTION = float(1 - HARD_STOP_DRAWDOWN)
RESTRICTED_BAND_FRACTION = float(HARD_STOP_DRAWDOWN - RESTRICTED_DRAWDOWN)


@njit
def random_step(state):
    # Per-path deterministic xorshift; independent of batch size/work scheduling.
    state ^= state << np.uint64(13)
    state ^= state >> np.uint64(7)
    state ^= state << np.uint64(17)
    return state, float(state >> np.uint64(11)) / 9007199254740992.0


@njit
def policy_numbers(equity, peak, restricted, hard):
    peak = max(peak, equity)
    restricted = restricted or equity <= peak * RESTRICTED_EQUITY_FRACTION
    hard = hard or equity <= peak * HALT_EQUITY_FRACTION
    if hard:
        return peak, True, True, 0., 0.
    if restricted:
        remaining = max(0., equity - peak * HALT_EQUITY_FRACTION)
        scale = min(.25, .25 * remaining / (peak * RESTRICTED_BAND_FRACTION))
        budget = min(equity * .005 * scale, remaining * .10)
    else:
        scale, budget = 1., equity * .005
    return peak, restricted, hard, scale, budget


@njit
def perp_size(equity, peak, restricted, hard, eth, wider):
    peak, restricted, hard, scale, trade_budget = policy_numbers(equity, peak, restricted, hard)
    capped = min(800., equity)
    if hard or capped <= 0 or (.01365 < (4. if restricted else 3.) * .0043):
        return 0.
    cap = .40 if wider and eth else .20
    gross_cap = .40 if wider and eth else .30
    budget = min(capped * .005 * scale, trade_budget)
    # Explicit risk-only surrogate: 0.7% stop, 6bps/side estimate, 15bps/side
    # allowed slippage, 1bp funding allowance; confidence is NOT probability.
    return max(0., min(budget * .9 / .0113, capped * cap * scale,
                       capped * gross_cap, capped))


@njit
def mark_risk(value, peak, minimum, maxdd, maxfrac, restricted, hard):
    peak, restricted, hard, _, _ = policy_numbers(value, peak, restricted, hard)
    minimum = min(minimum, value)
    maxdd = max(maxdd, peak - value)
    maxfrac = max(maxfrac, (peak - value) / peak)
    return peak, minimum, maxdd, maxfrac, restricted, hard


@njit
def path(pool, wider, stress, options, slots, seed, path_id, trace):
    state = np.uint64(seed) ^ (np.uint64(path_id + 1) * np.uint64(0x9E3779B97F4A7C15))
    if state == 0: state = np.uint64(1)
    equity = peak = minimum = 800.
    maxdd = maxfrac = turnover = premium = fees_total = 0.
    restricted = hard = blocked = False
    trades = gaps = ready = block_left = cursor = 0
    # An unclosed option remains marked; it is never a fabricated terminal fill.
    option_cash = option_mark = 0.
    for slot in range(slots):
        if blocked:
            state, draw = random_step(state)
            # Bounded vertical mark under declared adversarial price swings.
            option_mark = 10. * draw
            equity = option_cash + option_mark
            peak, minimum, maxdd, maxfrac, restricted, hard = mark_risk(
                equity, peak, minimum, maxdd, maxfrac, restricted, hard)
        elif not hard and slot >= ready:
            state, draw = random_step(state)
            _, _, _, scale, budget = policy_numbers(equity, peak, restricted, hard)
            use_option = options and draw < .10 and not restricted and budget >= 3.448 and slot + 24 <= slots
            if use_option:
                # Exactly the audit's hypothetical 0.1 ETH vertical at $2,900:
                # debit1.10, entry fee1.174, stored total reserve2.348, payoff10.
                use_option = 580. <= (min(800., equity) - 4.) * .75
            if use_option:
                cash = equity - 2.274
                peak, minimum, maxdd, maxfrac, restricted, hard = mark_risk(
                    cash + 1.09, peak, minimum, maxdd, maxfrac, restricted, hard)
                fees_total += 1.174
                premium += 2.9
                trades += 1
                state, fault = random_step(state)
                if fault < .10:
                    blocked, option_cash, option_mark = True, cash, 1.09
                    equity = option_cash + option_mark
                    # Do not continue trading around owned unresolved inventory.
                else:
                    state, draw = random_step(state)
                    credit = .49 if draw < 1 / 3 else 3.49 if draw < 2 / 3 else 4.59
                    equity = cash + credit - 1.174
                    fees_total += 1.174
                    premium += 2.31 if credit == .49 else 5.31 if credit == 3.49 else 6.41
                    ready = slot + 24  # declared 6h hold at 15m opportunities
                    peak, minimum, maxdd, maxfrac, restricted, hard = mark_risk(
                        equity, peak, minimum, maxdd, maxfrac, restricted, hard)
            else:
                if block_left == 0:
                    state, draw = random_step(state)
                    cursor = min(len(pool) - 1, int(draw * len(pool)))
                    block_left = 8
                row = pool[cursor]
                cursor = (cursor + 1) % len(pool)
                block_left -= 1
                n = perp_size(equity, peak, restricted, hard, row[4] > .5, wider)
                n = math.floor(n / row[6] + 1e-10) * row[6]
                if slot + int(row[9]) > slots:
                    n = 0.  # Do not fabricate a close beyond the 48h horizon.
                if n >= row[5] and n > 0:
                    gross, adverse, favorable, ratio = row[0], row[1], row[2], row[3]
                    state, draw = random_step(state)
                    if stress and draw < .0002:
                        # Not a calibrated occurrence rate. Adversarial tail test.
                        state, draw = random_step(state)
                        move = 4.0 if draw < .5 else -.80
                        gross, ratio = row[7] * move, 1. + move
                        adverse, favorable = gross, max(0., gross)
                        gaps += 1
                    cost_multiplier = 3. if stress else 1.
                    entry_fee = cost_multiplier * (.0006 * n + .01)
                    # Favorable-before-adverse ordering is a pessimistic envelope,
                    # not a claim about unknown intrabar price chronology.
                    peak, minimum, maxdd, maxfrac, restricted, hard = mark_risk(
                        equity - entry_fee + n * favorable, peak, minimum, maxdd, maxfrac, restricted, hard)
                    peak, minimum, maxdd, maxfrac, restricted, hard = mark_risk(
                        equity - entry_fee + n * adverse, peak, minimum, maxdd, maxfrac, restricted, hard)
                    if hard:
                        gross = adverse
                        ratio = max(.001, 1. + row[7] * gross)
                    exit_fee = cost_multiplier * (.0006 * n * ratio + .01)
                    extra_slip = .0008 * n * (1. + ratio) if stress else 0.
                    equity += n * (gross - row[8]) - entry_fee - exit_fee - extra_slip
                    fees_total += entry_fee + exit_fee
                    turnover += n * (1. + ratio)
                    trades += 1
                    ready = slot + int(row[9])
                    peak, minimum, maxdd, maxfrac, restricted, hard = mark_risk(
                        equity, peak, minimum, maxdd, maxfrac, restricted, hard)
        if len(trace):
            trace[slot] = np.array((float(slot), equity, peak, minimum, maxdd, maxfrac, float(trades), turnover,
                                    premium, fees_total, 1. if restricted else 0., 1. if hard else 0.,
                                    float(gaps), 1. if blocked else 0.))
    return np.array((equity, minimum, maxdd, maxfrac, float(trades), turnover, premium, fees_total,
                     1. if restricted else 0., 1. if hard else 0., 1. if minimum <= 0 else 0.,
                     float(gaps), 1. if blocked else 0.,
                     2. if blocked else 0.), dtype=np.float64)


@njit
def batch(pool, wider, stress, options, slots, seed, start, count):
    out = np.empty((count, len(METRICS)), dtype=np.float64)
    dummy = np.empty((0, len(METRICS)), dtype=np.float64)
    for i in range(count):
        out[i] = path(pool, wider, stress, options, slots, seed, start + i, dummy)
    return out


def load_pool(summary_path, history):
    summary = json.loads(summary_path.read_text())
    for name, digest in summary["source_sha256"].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
            raise ValueError("replay_source_changed:" + name)
    case = next(c for c in summary["cases"] if c["id"].startswith("perps-base-current-rules"))
    trade_path = summary_path.parent / case["id"] / "trades.jsonl"
    trades = [json.loads(line) for line in trade_path.read_text().splitlines()]
    if not trades: raise ValueError("empty_conditional_trade_pool")
    rules_path = history / "venue-rules.json"
    rules = json.loads(rules_path.read_text())["instruments"]
    candles = {asset: pd.read_csv(history / f"{asset}-5m.csv") for asset in {r["asset"] for r in trades}}
    rows = []
    for t in trades:
        c, r = candles[t["asset"]], rules[t["asset"] + "-perp"]
        lo = int(np.searchsorted(c.timestamp.values, t["opened_at"]))
        hi = int(np.searchsorted(c.timestamp.values, t["closed_at"], side="right"))
        if not 0 <= lo < hi <= len(c): raise ValueError("missing_trade_ohlc_envelope")
        n = t["amount"] * t["entry_price"]
        high, low = float(c.high.iloc[lo:hi].max()), float(c.low.iloc[lo:hi].min())
        gross = (t["net_pnl"] + t["fees"] + t["funding"]) / n
        adverse = min(0., t["side"] * ((low if t["side"] > 0 else high) / t["entry_price"] - 1))
        favorable = max(0., t["side"] * ((high if t["side"] > 0 else low) / t["entry_price"] - 1))
        rows.append((gross, adverse, favorable, t["exit_price"] / t["entry_price"], t["asset"] == "ETH",
                     float(r["minimum_amount"]) * t["entry_price"], float(r["amount_step"]) * t["entry_price"],
                     t["side"], t["funding"] / n,
                     max(1, math.ceil((t["closed_at"] - t["opened_at"]) / 900))))
    pool = np.asarray(rows, dtype=np.float64)
    if not np.isfinite(pool).all(): raise ValueError("nonfinite_pool")
    sources = [summary_path, trade_path, rules_path] + [history / f"{a}-5m.csv" for a in candles]
    return pool, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}


def validate_surrogate():
    checked = 0
    for peak in (800., 850., 1200.):
        for fraction in (1., .90, .85, .80, .75, .70):
            equity = peak * fraction
            for latched in (False, True):
                state = initial_state(peak, 0, 800, "surrogate")
                if latched: state = advance(state, peak * RESTRICTED_EQUITY_FRACTION, 1)
                state = advance(state, equity, 2)
                view = risk_view(state, equity)
                p, restricted, hard, scale, budget = policy_numbers(equity, peak, latched, False)
                assert restricted == state["restricted"] and hard == state["hard_stop"]
                assert math.isclose(scale, view["risk_scale"], abs_tol=1e-12)
                assert math.isclose(budget, view["risk_trade_budget"], abs_tol=1e-10)
                for wider in (False, True):
                    for eth in (False, True):
                        cap = .4 if wider and eth else .2
                        actual = risk_size(equity=min(800., equity), available=min(800., equity), committed=0,
                            confidence=.9, stop_pct=.0113, gross_cap=min(800., equity) * (.4 if wider and eth else .3),
                            notional_fraction=cap, peak_dd=view["peak_dd"], drawdown_limit=float(HARD_STOP_DRAWDOWN),
                            size_scale=scale, trade_risk_budget=budget,
                            exposure_profile=ETH_EXPOSURE_TEST if wider and eth else "baseline",
                            underlying="ETH" if eth else "SOL")
                        if not cost_allows_entry(.01365, .0043, view["cost_multiple"]): actual = 0.
                        assert math.isclose(perp_size(equity, peak, latched, False, eth, wider), actual, abs_tol=1e-10)
                        checked += 1
    return checked


def summarize(metrics, threshold):
    loss = np.maximum(0., 800. - metrics[:, 1])
    dd = metrics[:, 2]
    failures = (loss > threshold) | (dd > threshold)
    pnl = metrics[:, 0] - 800.
    q = np.quantile(pnl, (.001, .01, .05, .5, .95, .99, .999))
    return dict(paths=len(metrics), mean_pnl=float(pnl.mean()), pnl_quantiles=dict(zip(
        ("p0_1", "p1", "p5", "median", "p95", "p99", "p99_9"), map(float, q))),
        worst_initial_capital_loss=float(loss.max()), worst_peak_to_trough_loss=float(dd.max()),
        loss_over_threshold_paths=int(failures.sum()), loss_over_threshold_fraction=float(failures.mean()),
        risk_verdict="DISCARDED_DANGEROUS" if failures.any() else "NO_500_BREACH_IN_MODELED_PATHS",
        terminal_loss_over_threshold_paths=int(np.count_nonzero(pnl < -threshold)),
        expected_shortfall_1pct=float(pnl[pnl <= q[1]].mean()),
        worst_drawdown_fraction=float(metrics[:, 3].max()),
        restricted_paths=int(metrics[:, 8].sum()), hard_stop_paths=int(metrics[:, 9].sum()),
        insolvency_paths=int(metrics[:, 10].sum()), gap_event_count=int(metrics[:, 11].sum()),
        blocked_option_exit_paths=int(metrics[:, 12].sum()), terminal_option_legs=int(metrics[:, 13].sum()),
        mean_trades=float(metrics[:, 4].mean()), mean_perp_turnover=float(metrics[:, 5].mean()),
        mean_option_premium_turnover=float(metrics[:, 6].mean()), mean_fees=float(metrics[:, 7].mean()),
        live_ready=False, zero_breach_is_not_proof_of_safety=True)


def run(output, total_paths, batch_size=50000, slots=192, seed=20261003):
    if total_paths < 5 or total_paths % 5 or not 1 <= batch_size <= 1000000 or slots != 192:
        raise ValueError("use_equal_five_case_path_counts_and_48h_192_slot_horizon")
    if output.exists(): raise ValueError("choose_new_output_directory")
    checked = validate_surrogate()
    root = Path("data/validation/two-year-20261003")
    baseline, sources1 = load_pool(root / "cap-change-baseline-regression/summary.json", root / "history")
    wider, sources2 = load_pool(root / "options-audit-replay/summary.json", root / "history")
    output.mkdir(parents=True)
    started = time.monotonic()
    n = total_paths // 5
    results, artifacts = [], {}
    for name, wide, stress, options in CASES:
        pool = wider if wide else baseline
        metrics = np.empty((n, len(METRICS)), dtype=np.float64)
        for start in range(0, n, batch_size):
            count = min(batch_size, n - start)
            metrics[start:start + count] = batch(pool, wide, stress, options, slots, seed, start, count)
            print(json.dumps(dict(case=name, completed_paths=start + count, case_paths=n,
                                  elapsed_seconds=round(time.monotonic() - started, 1))), flush=True)
        if not np.isfinite(metrics).all(): raise ValueError("nonfinite_path_metrics")
        result = {"case": name, "profile_group": "combined_hypothetical" if options else "eth_caps" if wide else "baseline",
                  **summarize(metrics, 500.)}
        result["execution_verdict"] = "QUARANTINED_KNOWN_OPTION_EXIT_BLOCKER" if options else "PRIVATE_EXECUTION_UNVERIFIED"
        file = output / (name + ".npz")
        with file.open("xb") as stream: np.savez_compressed(stream, metrics=metrics, columns=np.array(METRICS))
        artifacts[file.name] = hashlib.sha256(file.read_bytes()).hexdigest()
        worst_id = int(np.argmax(np.maximum(800. - metrics[:, 1], metrics[:, 2])))
        trace = np.zeros((slots, len(METRICS)), dtype=np.float64)
        repeated = path(pool, wide, stress, options, slots, seed, worst_id, trace)
        assert np.array_equal(repeated, metrics[worst_id])
        trace_path = output / (name + "-worst-path.csv")
        with trace_path.open("x") as stream:
            writer = csv.writer(stream)
            writer.writerow(("slot", "equity", "peak", "minimum", "max_dd_dollars", "max_dd_fraction", "trades",
                             "perp_turnover", "option_premium_turnover", "fees", "restricted", "hard_stop", "gaps", "blocked_option"))
            writer.writerows(trace)
        artifacts[trace_path.name] = hashlib.sha256(trace_path.read_bytes()).hexdigest()
        result["worst_path_id"] = worst_id
        results.append(result)
    groups = {g: ("DISCARDED_DANGEROUS" if any(c["loss_over_threshold_paths"] for c in results if c["profile_group"] == g)
                  else "NOT_LIVE_READY") for g in {c["profile_group"] for c in results}}
    sources = [Path(__file__), Path("src/risk/competition.py"), Path("src/risk/position_sizing.py"),
               Path("src/risk/exposure.py"), Path("src/execution/options_rfq.py")]
    summary = dict(kind="conditional_portfolio_risk_monte_carlo", total_paths=total_paths,
        completed_paths=sum(c["paths"] for c in results), starting_equity=800, horizon_hours=48,
        loss_discard_threshold=500, discard_rule="any modeled intra-path capital loss OR peak-to-trough dollar loss strictly >500",
        opportunity_slots=slots, slot_seconds=900, historical_signal_frequency_used=False,
        minimums_enforced=True, surrogate_contract_checks=checked,
        risk_surrogate=dict(risk_fraction=.005, initial_risk_budget=4, allocation_ceiling=800,
                            confidence=.9, stop_fraction=.007, target_fraction=.01365,
                            estimated_round_trip_cost=.0043, normal_cost_multiple=3,
                            restricted_cost_multiple=4, baseline_notional_fraction=.20,
                            eth_test_notional_fraction=.40, eth_test_gross_fraction=.40,
                            option_delta_fraction=.20, option_gross_fraction=.75,
                            leverage_does_not_multiply_notional_or_pnl=True),
        block_length_trades=8, empirical_pool_trades=dict(baseline=len(baseline), eth_caps=len(wider)),
        stress=dict(unexpected_cost_multiplier=3, extra_slippage_per_side=.0008,
                    gap_probability_per_filled_perp=.0002, gap_price_changes=[4., -.8],
                    probabilities_calibrated=False, option_opportunity_fraction=.10,
                    option_blocked_exit_fraction=.10, option_close_credits=[.49, 3.49, 4.59]),
        limitations=["Risk-only surrogate, NOT 5 million full controller/Condor/RFQ/market replays",
                     "Episode cash/mark extrema are applied at an opportunity slot; holding time blocks subsequent entries; no episode extends beyond48h",
                     "Signal, data freshness, native books and venue margin are not re-executed; entries are conditional stress opportunities",
                     "192 conditional opportunity slots in48h, not observed signal frequency or turnover forecast",
                     "Conditional trade pools are small/selected by prior drawdown latches; bootstrap cannot create missing regimes",
                     "Pessimistic favorable-before-adverse OHLC envelope includes the closing bar; intrabar chronology unknown",
                     "Gap probabilities, cost shocks and hypothetical option outcomes are assumptions, not measured probabilities",
                     "Blocked paired option marks stay bounded0..10; no liquidation/margin, settlement or true executable-book proof",
                     "Negative modeled equity is retained, not clipped to hide tail losses",
                     "Passed500 screen does not clear the current drawdown, economic or private execution gates"],
        source_sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        input_sha256={**sources1, **sources2}, artifact_sha256=artifacts,
        seed=seed, profile_verdicts=groups, cases=results, elapsed_seconds=time.monotonic() - started,
        no_real_orders=True, production_changes=False, live_ready=False)
    with (output / "summary.json").open("x") as stream:
        json.dump(summary, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", type=int, default=5000000)
    parser.add_argument("--batch-size", type=int, default=50000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output, args.paths, args.batch_size)


if __name__ == "__main__":
    main()
