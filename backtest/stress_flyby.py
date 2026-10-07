"""Fixed-seed OHLCV replay and fault injection, not a Derive execution backtest.

Every run evaluates the shared policy on 5,000 CLOSED candles. Marketable
orders fill at the NEXT open. Depth, funding and option books are explicit
scenario models, not reconstructed historical Derive order books.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import asdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import time
import platform

import numpy as np
import pandas as pd
import requests

from agents.condor_agent import decide
from src.signal.flyby import feature_frame, INTERVAL_SECONDS
from src.risk.position_sizing import risk_size, dynamic_exits, depth_quote, cost_allows_entry
from src.options.spread_builder import OptionQuote, build_spread, spread_exit
from src.accounting.ledger import AccountingLedger

ROOT = Path(__file__).resolve().parents[1]
PAIRS = ("ETHUSDT", "BTCUSDT", "SOLUSDT")
SCENARIOS = ("base", "fees_x3", "slippage_x5", "thin_book", "rejected_orders",
             "partial_fills", "stale_feed", "bad_data", "gap_crash", "restart")
END = 1790812800  # 2026-10-01 00:00 UTC, no currently forming candles.


def fetch(item):
    pair, interval, directory = item
    path = directory / f"{pair}-{interval}.csv"
    if not path.exists():
        seconds = INTERVAL_SECONDS[interval]
        start, rows = END - 5400 * seconds, []
        with requests.Session() as session:
            while start < END:
                response = session.get("https://fapi.binance.com/fapi/v1/klines", params={
                    "symbol": pair, "interval": interval, "startTime": start * 1000,
                    "endTime": END * 1000 - 1, "limit": 1000}, timeout=30)
                response.raise_for_status()
                batch = response.json()
                if not isinstance(batch, list) or not batch:
                    raise RuntimeError(f"incomplete dataset: {pair} {interval}")
                rows.extend(batch)
                start = batch[-1][0] // 1000 + seconds
        frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume",
                                           "end", "quote", "trades", "taker_base", "taker_quote", "ignore"])
        frame = frame[["timestamp", "open", "high", "low", "close", "volume"]].astype(float)
        frame.timestamp /= 1000
        frame = frame.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
        if len(frame) < 5200 or not np.all(np.diff(frame.timestamp) == seconds):
            raise RuntimeError(f"bad history: {pair} {interval}")
        frame.to_csv(path, index=False)  # Generated cache, not source editing.
    frame = pd.read_csv(path)
    if len(frame) < 5200 or not np.all(np.diff(frame.timestamp) == INTERVAL_SECONDS[interval]):
        raise RuntimeError(f"invalid cache: {path}")
    return {"pair": pair, "interval": interval, "bars": len(frame),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "first": float(frame.timestamp.iloc[0]), "last": float(frame.timestamp.iloc[-1]),
            "url": "https://fapi.binance.com/fapi/v1/klines"}


def option_probe(run, now):
    """Synthetic two-leg planner/lifecycle test, never an options P&L estimate."""
    kind = "call" if run % 2 == 0 else "put"
    strikes = (3000, 3100) if kind == "call" else (3000, 2900)
    chain = [OptionQuote(f"ETH-{k}-{kind}", "ETH", kind, k, now + 3 * 86400,
                         1, .01, .01, now, ((bid, 10),), ((ask, 10),), delta)
             for k, bid, ask, delta in zip(strikes, (29, 9), (30, 10),
                                           (.4, .2) if kind == "call" else (-.4, -.2))]
    plan = build_spread(chain, kind=kind, underlying="ETH", now=now, debit_budget=8, confidence=.9)
    if plan is None or plan.max_loss > 8 or not plan.signal_only:
        raise AssertionError("spread invariant")
    cases = {"take_profit": plan.debit * 1.40, "stop_loss": plan.debit * .70,
             "time_limit": plan.debit, "signal_invalid": plan.debit}
    exits = {name: spread_exit(plan, credit, plan.max_hold_seconds if name == "time_limit" else 60,
                              now + 60, name != "signal_invalid") for name, credit in cases.items()}
    if any(name != value for name, value in exits.items()):
        raise AssertionError("spread exit invariant")
    return {"plan": plan.to_dict(), "exits": exits, "orders_submitted": 0,
            "paired_execution_tested": False, "pricing": "synthetic"}


_CACHE = {}


def run_one(task):
    run, directory, output, bars, seed = task
    rng = np.random.default_rng(seed + run)
    interval = tuple(INTERVAL_SECONDS)[run % 4]
    pair = PAIRS[(run // 4) % len(PAIRS)]
    # Cycle scenario independently of timeframe and pair.
    scenario = SCENARIOS[(run // 12) % len(SCENARIOS)]
    seconds = INTERVAL_SECONDS[interval]
    key = (pair, interval)
    if key not in _CACHE:
        candles = pd.read_csv(directory / f"{pair}-{interval}.csv")
        features = feature_frame(candles, interval)
        _CACHE[key] = candles, features
    candles, features = _CACHE[key]
    start = 150 + int(rng.integers(0, len(candles) - bars - 151))
    stop = start + bars
    values = candles.iloc[start:stop + 1].to_numpy()
    features = features.iloc[start:stop].to_dict("records")
    fee = .0006 * (3 if scenario == "fees_x3" else 1)
    slippage = .0003 * (5 if scenario == "slippage_x5" else 1)
    cash = peak = day_equity = 800.0
    daily, position = None, None
    max_dd, volume, trades, wins, costs, funding = 0.0, 0.0, 0, 0, 0.0, 0.0
    guard_blocks = fault_blocks = 0
    loss_streak = max_loss_streak = 0
    last_entry = -1e20
    ledger = AccountingLedger()
    trace_path = output / "traces" / f"run-{run:04d}.jsonl.gz"
    first48h_equity = None
    curve = []
    decisions = {"-1": 0, "0": 0, "1": 0}
    matrix = np.zeros((3, 3), dtype=int)
    with gzip.open(trace_path, "wt", compresslevel=3) as trace:
        trace.write(json.dumps({"type": "metadata", "run": run, "seed": seed + run,
                                "pair": pair, "interval": interval, "scenario": scenario,
                                "fee_per_side": fee, "slippage_per_side": slippage,
                                "trace_fields": ["i", "time", "signal", "reason", "equity", "drawdown", "event"]}) + "\n")
        for i, raw in enumerate(features):
            timestamp, opening, high, low, close, candle_volume = values[i + 1]
            # Fault transforms are applied to execution prices, not secretly to
            # precomputed signals. The gap also invalidates the proxy basis.
            crash = scenario == "gap_crash" and i == bars // 2
            if crash:
                opening *= .8
                high, low, close = max(opening, high), min(opening, low), opening
            mark = cash + (position["side"] * position["qty"] * (opening - position["entry"]) if position else 0)
            day = int(timestamp // 86400)
            if daily != day:
                daily, day_equity = day, mark
            peak = max(peak, mark)
            snapshot = {**raw, "valid": bool(raw["valid"]), "stale_secs": 0,
                        "daily_pnl_pct": (mark - day_equity) / 800,
                        "peak_dd": (mark - peak) / 800, "reconciled": True,
                        "ccy": pair.replace("USDT", "")}
            if scenario == "stale_feed" and i % 101 < 3:
                snapshot["stale_secs"] = 120
            if scenario == "bad_data" and i % 503 < 101:
                snapshot["valid"] = False  # Missing/corrupt OHLCV poisons a full warmup window.
            if crash:
                snapshot["valid"] = False
            decision = decide(snapshot)
            decisions[str(decision.signal)] += 1
            guard_blocks += decision.reason == "loss_guard"
            fault_blocks += decision.halt and decision.reason != "loss_guard"
            event = ""
            if not position and decision.signal and timestamp - last_entry >= 300 and i < bars - 1:
                stop_pct, profit, hold = dynamic_exits(raw["atr_pct"], decision.confidence, seconds)
                notional = risk_size(equity=min(cash, 800), available=max(0, cash), committed=0,
                                     confidence=decision.confidence, stop_pct=stop_pct, gross_cap=min(cash, 800) * .3,
                                     peak_dd=snapshot["peak_dd"])
                side = decision.signal
                entry = opening * (1 + side * slippage)
                # Proxy book capacity: random scenario quantity, not venue depth.
                capacity = notional / entry * float(rng.uniform(.01, .15) if scenario == "thin_book" else rng.uniform(1, 5))
                quote = depth_quote(((entry, capacity),), notional / entry)
                rejected = scenario == "rejected_orders" and rng.random() < .3
                if not cost_allows_entry(profit, 2 * (fee + slippage) + .0001):
                    event = "reject:cost_gate"
                elif quote is None or rejected or notional < 10:
                    event = "reject:depth" if quote is None else "reject:order" if rejected else "reject:min_notional"
                else:
                    qty = notional / entry
                    if scenario == "partial_fills":
                        qty *= float(rng.uniform(.1, .8))
                    entry_fee = qty * entry * fee
                    cash -= entry_fee
                    volume += qty * entry
                    position = {"side": side, "qty": qty, "entry": entry, "stop": stop_pct,
                                "profit": profit, "hold": hold, "time": timestamp,
                                "notional": qty * entry, "fee": entry_fee}
                    last_entry, event = timestamp, "entry"
                    if qty * entry > min(cash + entry_fee, 800) * .2 + 1e-8:
                        raise AssertionError("notional cap")
                    ledger.apply_fill({"trade_id": f"{run}-{trades + 1}-open", "instrument": pair,
                                       "side": "buy" if side > 0 else "sell", "amount": qty,
                                       "price": entry, "fee": entry_fee})
                    trace.write(json.dumps({"type": "entry_fill", "i": i, **position,
                                            "equity_before_fee": cash + entry_fee,
                                            "confidence": decision.confidence}) + "\n")
            if position:
                pos = position
                stop_price = pos["entry"] * (1 - pos["side"] * pos["stop"])
                target = pos["entry"] * (1 + pos["side"] * pos["profit"])
                stop_hit = low <= stop_price if pos["side"] > 0 else high >= stop_price
                target_hit = high >= target if pos["side"] > 0 else low <= target
                exit_price, reason = None, ""
                # An exit based on already closed bar precedes this bar's OHLC.
                if decision.halt or decision.signal != pos["side"]:
                    exit_price, reason = opening, "halt" if decision.halt else "signal_invalid"
                elif timestamp - pos["time"] >= pos["hold"]:
                    exit_price, reason = opening, "time_limit"
                elif stop_hit:
                    exit_price = min(opening, stop_price) if pos["side"] > 0 else max(opening, stop_price)
                    reason = "stop_loss"  # Stop first when OHLC cannot resolve order.
                elif target_hit:
                    exit_price, reason = target, "take_profit"
                if exit_price is not None or i == bars - 1:
                    exit_price = (close if exit_price is None else exit_price) * (1 - pos["side"] * slippage)
                    gross = pos["side"] * pos["qty"] * (exit_price - pos["entry"])
                    exit_fee = pos["qty"] * exit_price * fee
                    fund = -pos["notional"] * .0001 * ((timestamp - pos["time"]) / (8 * 3600))
                    cash += gross - exit_fee + fund
                    pnl = gross - exit_fee - pos["fee"] + fund
                    costs += exit_fee + pos["fee"]
                    funding += fund
                    volume += pos["qty"] * exit_price
                    trades += 1
                    wins += pnl > 0
                    loss_streak = loss_streak + 1 if pnl < 0 else 0
                    max_loss_streak = max(max_loss_streak, loss_streak)
                    ledger.apply_fill({"trade_id": f"{run}-{trades}-close", "instrument": pair,
                                       "side": "sell" if pos["side"] > 0 else "buy", "amount": pos["qty"],
                                       "price": exit_price, "fee": exit_fee, "realized_pnl_ex_fees": gross})
                    ledger.apply_funding({"event_id": f"{run}-{trades}-fund", "instrument": pair, "amount": fund})
                    trace.write(json.dumps({"type": "fill", "i": i, "entry": pos["entry"], "exit": exit_price,
                                            "qty": pos["qty"], "net": pnl, "gross": gross,
                                            "entry_fee": pos["fee"], "exit_fee": exit_fee, "funding": fund,
                                            "side": pos["side"], "reason": reason or "end_of_run"}) + "\n")
                    position, event = None, "close:" + (reason or "end_of_run")
            if scenario == "restart" and i % 997 == 0:
                exported = ledger.export_state()
                restored = AccountingLedger()
                restored.replay(exported["fills"], exported["funding_events"])
                restored.replay(exported["fills"], exported["funding_events"])
                if restored.snapshot() != ledger.snapshot():
                    raise AssertionError("ledger restart replay")
                ledger = restored
            equity = cash + (position["side"] * position["qty"] * (close - position["entry"]) if position else 0)
            peak = max(peak, equity)
            dd = (equity - peak) / peak
            max_dd = min(max_dd, dd)
            curve.append(equity)
            if first48h_equity is None and timestamp + seconds - values[1][0] >= 48 * 3600:
                first48h_equity = equity
            horizon = max(1, int(6 * 3600 / seconds))
            if i + horizon < bars:
                forward = values[i + horizon][4] / values[i][4] - 1
                actual = -1 if forward < -.005 else 1 if forward > .005 else 0
                matrix[actual + 1, decision.signal + 1] += 1
            trace.write(json.dumps([i, int(timestamp), decision.signal, decision.reason,
                                    round(equity, 6), round(dd, 6), event], separators=(",", ":")) + "\n")
        trace.write(json.dumps({"type": "options_probe", **option_probe(run, values[-1][0])}) + "\n")
    if position:
        raise AssertionError("unclosed terminal position")
    if not math.isclose(float(ledger.net_cash_pnl), cash - 800, abs_tol=1e-7):
        raise AssertionError("cash/ledger drift")
    window = max(1, int(48 * 3600 / seconds))
    curve = np.asarray(curve)
    two_day = curve[window:] / curve[:-window] - 1
    return {"run": run, "seed": seed + run, "pair": pair, "interval": interval,
            "scenario": scenario, "bars": bars, "trades": trades, "win_rate": wins / max(1, trades),
            "ending_equity": cash, "return_pct": (cash / 800 - 1) * 100,
            "max_drawdown_pct": max_dd * 100, "volume_quote": volume, "fees_quote": costs,
            "funding_quote": funding, "guard_blocks": guard_blocks, "fault_blocks": fault_blocks,
            "max_losing_streak": max_loss_streak, "first48h_return_pct": ((first48h_equity or cash) / 800 - 1) * 100,
            "worst48h_return_pct": float(two_day.min() * 100) if two_day.size else None, "decisions": decisions,
            "confusion_6h": matrix.tolist(), "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=1000)
    parser.add_argument("--bars", type=int, default=5000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261001)
    parser.add_argument("--output", type=Path, default=ROOT / "stress_artifacts" / "campaign-20261001")
    args = parser.parse_args()
    if not 100 <= args.bars <= 5000 or args.runs < 1 or not 1 <= args.workers <= 6:
        parser.error("bars 100..5000, runs >=1, workers 1..6")
    if (args.output / "manifest.json").exists():
        parser.error("Choose a new output directory; existing campaign evidence is immutable")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "traces").mkdir(exist_ok=True)
    directory = ROOT / "data" / "stress-candles"
    directory.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with ThreadPoolExecutor(max_workers=3) as pool:
        sources = list(pool.map(fetch, [(p, tf, directory) for p in PAIRS for tf in INTERVAL_SECONDS]))
    print(f"Downloaded/validated {len(sources)} datasets; {sum(s['bars'] for s in sources)} unique candles", flush=True)
    code = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [ROOT / "agents/condor_agent.py", ROOT / "src/signal/flyby.py",
                         ROOT / "src/risk/position_sizing.py", ROOT / "src/options/spread_builder.py",
                         ROOT / "src/accounting/ledger.py", ROOT / "condor/flyby/controllers/derive_cesf_long_vol/derive_cesf_long_vol.py",
                         ROOT / "conf/controllers/conf_flyby_eth.yml", Path(__file__)]}
    (args.output / "source").mkdir(exist_ok=True)
    for name in code:
        destination = args.output / "source" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    manifest = {"seed": args.seed, "runs": args.runs, "bars_per_run": args.bars,
                "environment": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
                "sources": sources, "code_sha256": code, "scenarios": SCENARIOS,
                "limitations": ["Repeated overlapping proxy periods, not 1,000 independent historical samples",
                                "OHLC replay, not Hummingbot exchange/order lifecycle E2E",
                                "Depth/funding/partial fills/options books are scenario models",
                                "Live candle source is cross-venue; no historical Derive basis",
                                "4h bars cannot resolve a 6h timer or intrabar ordering precisely",
                                "Fee/slippage assumptions are stress parameters, not verified venue fees"]}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        tasks = [(i, directory, args.output, args.bars, args.seed) for i in range(args.runs)]
        for result in pool.map(run_one, tasks, chunksize=4):
            results.append(result)
            if len(results) % 50 == 0:
                print(f"Completed {len(results)}/{args.runs}; {sum(r['bars'] for r in results):,} bar evaluations", flush=True)
    frame = pd.DataFrame([{k: v for k, v in r.items() if k not in ("decisions", "confusion_6h")} for r in results])
    frame.to_csv(args.output / "runs.csv", index=False)
    total = {"runs": len(results), "bar_evaluations": int(frame.bars.sum()),
             "unique_candles": sum(s["bars"] for s in sources), "elapsed_seconds": time.time() - started,
             "profitable_runs": int((frame.return_pct > 0).sum()), "mean_return_pct": float(frame.return_pct.mean()),
             "median_return_pct": float(frame.return_pct.median()), "worst_return_pct": float(frame.return_pct.min()),
             "worst_drawdown_pct": float(frame.max_drawdown_pct.min()), "trades": int(frame.trades.sum()),
             "by_timeframe": frame.groupby("interval").agg(runs=("run", "count"),
                 mean_return_pct=("return_pct", "mean"), worst_drawdown_pct=("max_drawdown_pct", "min"),
                 trades=("trades", "sum")).to_dict("index"),
             "by_scenario": frame.groupby("scenario").agg(runs=("run", "count"),
                 mean_return_pct=("return_pct", "mean"), worst_drawdown_pct=("max_drawdown_pct", "min")).to_dict("index"),
             "confusion_6h": np.sum([r["confusion_6h"] for r in results], axis=0).tolist(),
             "trace_files": len(list((args.output / "traces").glob("*.gz"))), "live_ready": False,
             "limitations": manifest["limitations"]}
    (args.output / "summary.json").write_text(json.dumps(total, indent=2))
    print(json.dumps(total, indent=2), flush=True)


if __name__ == "__main__":
    main()
