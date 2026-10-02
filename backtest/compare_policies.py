"""Fixed-parameter costed entry/hold diagnostics. Previously seen proxy data, not new alpha proof."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from agents.condor_agent import decide
from src.risk.position_sizing import cost_allows_entry, dynamic_exits, risk_size
from src.signal.flyby import INTERVAL_SECONDS, feature_frame
from src.risk.venue_sizing import venue_size
from src.risk.competition import POLICY, initial_state, advance, risk_view, scalp_exits, exit_signal_reason

POLICIES = ("baseline", "hold_hysteresis", "competition_baseline", "competition_scalp")
PARAMETERS = {"capital": 800, "fee_per_side": .0006, "slippage_per_side": .0003,
              "funding_drag_8h": .0001, "lookback": 100, "hold_max_seconds": 21600,
              "hold_efficiency_floor": .15, "hold_signed_trend_floor": .2,
              "competition_scalp_trend_horizon_seconds": 1800}
COST_PROFILES = {
    "stressed": {"fee_per_side": .0006, "base_fee_per_order": 0.0, "slippage_per_side": .0003},
    "public_taker": {"fee_per_side": .0003, "base_fee_per_order": .01, "slippage_per_side": .0003},
}


def exit_on_signal(policy, decision, features, side):
    if policy not in POLICIES:
        raise ValueError("unknown experimental policy")
    if decision.halt:
        return "halt"
    if policy.startswith("competition_"):
        return exit_signal_reason("baseline" if policy == "competition_baseline" else policy,
                                  decision, features, side)
    if policy == "baseline":
        return "signal_invalid" if decision.signal != side else None
    if decision.signal == -side:
        return "opposite_confirmation"
    if not features.get("valid") or side * features["trend_z"] <= PARAMETERS["hold_signed_trend_floor"]:
        return "trend_reversal"
    if features["efficiency"] < PARAMETERS["hold_efficiency_floor"]:
        return "trend_decay"
    return None


def split_ranges(n, interval):
    if interval not in INTERVAL_SECONDS or n < 1500:
        raise ValueError("at least 1500 continuous bars required")
    # Disjoint evaluation periods with lookback + maximum outcome embargo.
    embargo = PARAMETERS["lookback"] + int(np.ceil(PARAMETERS["hold_max_seconds"] / INTERVAL_SECONDS[interval]))
    train, validation = int(n * .6), int(n * .8)
    return {"train": (150, train), "validation": (train + embargo, validation),
            "test": (validation + embargo, n)}, embargo


def simulate(frame, features, interval, policy, start, stop, record_trace=False, *, costs=None, venue_rule=None):
    if policy not in POLICIES or (policy.startswith("competition_") and interval != "5m"):
        raise ValueError("competition candidates require 5m")
    seconds = INTERVAL_SECONDS[interval]
    cap = PARAMETERS["capital"]
    costs = COST_PROFILES["stressed"] if costs is None else costs
    fee, slip, base_fee = (costs[key] for key in ("fee_per_side", "slippage_per_side", "base_fee_per_order"))
    if any(not np.isfinite(v) or v < 0 for v in (fee, slip, base_fee)):
        raise ValueError("invalid_replay_costs")
    cash = peak = day_equity = cap
    daily, pos, last_entry = None, None, -float("inf")
    trades, trace, fees, funding, volume, max_dd, loss_blocks = [], [], 0.0, 0.0, 0.0, 0.0, 0
    minimum_blocks = 0
    competition = policy.startswith("competition_")
    risk_state = None
    mode_counts = {"normal": 0, "restricted": 0, "hard_stop": 0}
    for i in range(start, stop):
        row, previous = frame.iloc[i], features.iloc[i - 1].to_dict()
        now, opening = float(row.timestamp), float(row.open)
        mark = cash + (pos["side"] * pos["qty"] * (opening - pos["entry"]) if pos else 0)
        peak = max(peak, mark)
        if daily != int(now // 86400):
            daily, day_equity = int(now // 86400), mark
        previous.update(valid=bool(previous["valid"]), reconciled=True, stale_secs=0,
                        daily_pnl_pct=(mark - day_equity) / cap, peak_dd=(mark - peak) / cap)
        view = None
        if competition:
            if risk_state is None:
                risk_state = initial_state(mark, now, cap, "diagnostic_proxy")
            risk_state = advance(risk_state, mark, now)
            view = risk_view(risk_state, mark)
            previous.update(view)
            mode_counts[view["risk_mode"]] += 1
        decision = decide(previous)
        loss_blocks += decision.reason in ("loss_guard", "competition_hard_stop")
        cooldown = 60 if policy == "competition_scalp" else 300
        if not pos and decision.signal and now - last_entry >= cooldown and i < stop - 1:
            exits = scalp_exits if policy == "competition_scalp" else dynamic_exits
            loss, target, hold = exits(previous["atr_pct"], decision.confidence, seconds)
            extra = ({"drawdown_limit": .15, "size_scale": view["risk_scale"],
                      "trade_risk_budget": view["risk_trade_budget"]} if competition else {})
            notional = risk_size(equity=min(cap, cash), available=max(0, cash), committed=0,
                                 confidence=decision.confidence,
                                 stop_pct=loss + (2 * (fee + slip) + .0001 if competition else 0),
                                 gross_cap=min(cap, cash) * .3, peak_dd=previous["peak_dd"], **extra)
            executable = None
            if venue_rule is not None and notional > 0:
                executable = venue_size(budget=notional, price=opening * (1 + decision.signal * slip),
                    side=decision.signal, min_amount=venue_rule["minimum_amount"],
                    amount_step=venue_rule["amount_step"], price_tick=venue_rule["tick_size"],
                    max_amount=venue_rule["maximum_amount"])
                minimum_blocks += executable.amount == 0
            compatible = executable is None or executable.amount > 0
            round_trip = 2 * (fee + slip) + (2 * base_fee / notional if notional > 0 else 0) + .0001
            multiple = view["cost_multiple"] if competition else 3.0
            risk_ok = not competition or notional * (loss + round_trip) <= view["risk_trade_budget"] * decision.confidence
            if compatible and risk_ok and notional >= 10 and cost_allows_entry(target, round_trip, multiple):
                side = decision.signal
                entry = float(executable.price) if executable is not None else opening * (1 + side * slip)
                qty = float(executable.amount) if executable is not None else notional / entry
                notional = qty * entry
                entry_fee = notional * fee + base_fee
                pos = dict(side=side, qty=qty, entry=entry, time=now, loss=loss, target=target,
                           hold=hold, entry_fee=entry_fee, notional=notional)
                cash -= entry_fee
                fees += entry_fee
                volume += notional
                last_entry = now
        event = None
        if pos:
            side = pos["side"]
            reason = exit_on_signal(policy, decision, previous, side)
            exit_price = opening if reason else None
            stop_price = pos["entry"] * (1 - side * pos["loss"])
            target_price = pos["entry"] * (1 + side * pos["target"])
            if reason is None:
                if now - pos["time"] >= pos["hold"]:
                    reason, exit_price = "time_limit", opening
                elif (row.low <= stop_price if side > 0 else row.high >= stop_price):
                    reason = "stop_loss"
                    exit_price = min(opening, stop_price) if side > 0 else max(opening, stop_price)
                elif (row.high >= target_price if side > 0 else row.low <= target_price):
                    reason, exit_price = "take_profit", target_price
                elif i == stop - 1:
                    reason, exit_price = "split_end", float(row.close)
            if exit_price is not None:
                exit_price *= 1 - side * slip
                gross = side * pos["qty"] * (exit_price - pos["entry"])
                exit_fee = pos["qty"] * exit_price * fee + base_fee
                drag = -pos["notional"] * PARAMETERS["funding_drag_8h"] * (now - pos["time"]) / 28800
                net = gross - exit_fee - pos["entry_fee"] + drag
                cash += gross - exit_fee + drag
                fees += exit_fee
                funding += drag
                volume += pos["qty"] * exit_price
                event = {"entry_time": pos["time"], "exit_time": now, "net": net, "gross": gross,
                         "fee": pos["entry_fee"] + exit_fee, "funding": drag, "reason": reason,
                         "side": side, "notional": pos["notional"]}
                trades.append(event)
                pos = None
        equity = cash + (pos["side"] * pos["qty"] * (float(row.close) - pos["entry"]) if pos else 0)
        peak = max(peak, equity)
        if competition:
            risk_state = advance(risk_state, equity, now)
        max_dd = min(max_dd, (equity - peak) / peak)
        if record_trace:
            trace.append({"i": i, "time": now, "signal": decision.signal, "reason": decision.reason,
                          "risk_mode": view["risk_mode"] if view else "legacy",
                          "equity": equity, "event": event})
    if pos or abs(cash - cap - sum(t["net"] for t in trades)) > 1e-7:
        raise AssertionError("terminal account/fee reconciliation failed")
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    return {"policy": policy, "bars": stop - start, "trades": len(trades),
            "net_return_pct": (cash / cap - 1) * 100, "gross_quote": sum(t["gross"] for t in trades),
            "fees_quote": fees, "funding_quote": funding, "volume_quote": volume,
            "max_drawdown_pct": max_dd * 100, "loss_guard_blocks": loss_blocks,
            "exit_reasons": reasons, "venue_minimum_blocks": int(minimum_blocks),
            "risk_mode_observations": mode_counts,
            "trades_per_day": len(trades) / max(1e-12, (stop - start) * seconds / 86400),
            "mean_hold_seconds": float(np.mean([t["exit_time"] - t["entry_time"] for t in trades])) if trades else 0,
            "net_quote_per_10000_volume": (cash - cap) / volume * 10000 if volume else None,
            "fee_bps_of_volume": fees / volume * 10000 if volume else None}, trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/stress-candles"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cost-profile", choices=COST_PROFILES, default="stressed")
    parser.add_argument("--venue-rules", type=Path, help="Public current-rule snapshot; not contemporaneous history")
    parser.add_argument("--include-sol", action="store_true", help="Include existing SOL proxy history; no HYPE fallback data assumed")
    args = parser.parse_args()
    venue_rules = json.loads(args.venue_rules.read_text()) if args.venue_rules else None
    if venue_rules is not None and (venue_rules.get("kind") != "flyby_public_venue_rules" or venue_rules.get("network") != "mainnet"):
        raise ValueError("public_mainnet_venue_rules_required")
    args.output.mkdir(parents=True, exist_ok=False)
    pairs = ("ETHUSDT", "BTCUSDT", "SOLUSDT") if args.include_sol else ("ETHUSDT", "BTCUSDT")
    sources = [(p, tf, args.data / f"{p}-{tf}.csv") for p in pairs for tf in INTERVAL_SECONDS]
    manifest = {"policies": POLICIES, "parameters": PARAMETERS,
                "cost_profile": args.cost_profile, "costs": COST_PROFILES[args.cost_profile],
                "fee_source": "https://docs.derive.xyz/integrators/trading/trading-fees",
                "account_fee_tier_verified": False,
                "venue_rules_sha256": hashlib.sha256(args.venue_rules.read_bytes()).hexdigest() if args.venue_rules else None,
                "venue_rules_status": "current rules applied to old proxy bars; capacity diagnostic, not venue backtest" if venue_rules else "no venue lots enforced",
                "sources": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for _, _, p in sources},
                "code": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                         (Path(__file__), Path("agents/condor_agent.py"), Path("src/signal/flyby.py"),
                          Path("src/risk/position_sizing.py"), Path("src/risk/venue_sizing.py"),
                          Path("src/accounting/derive_margin.py"), Path("src/risk/competition.py"))},
                "promotion": "none", "data_status": "previously inspected Binance proxy OHLC; not unseen holdout",
                "options_experiment": "blocked: historical contemporaneous Derive chain coverage unavailable",
                "limitations": ["modeled fees/slippage/funding/depth; no exchange matching",
                                "stop first when intrabar order is ambiguous", "4h OHLC cannot resolve six-hour timing exactly"]}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    rows = []
    for pair, interval, path in sources:
        frame = pd.read_csv(path)
        if not frame.timestamp.diff().dropna().eq(INTERVAL_SECONDS[interval]).all():
            raise ValueError("non-continuous experimental history")
        numeric = frame[["open", "high", "low", "close", "volume"]]
        if (not np.isfinite(numeric).all().all() or (numeric.volume < 0).any()
                or (numeric[["open", "high", "low", "close"]] <= 0).any().any()
                or not frame.high.ge(frame[["open", "close", "low"]].max(axis=1)).all()
                or not frame.low.le(frame[["open", "close", "high"]].min(axis=1)).all()):
            raise ValueError("invalid experimental OHLCV")
        features = feature_frame(frame, interval)
        ranges, embargo = split_ranges(len(frame), interval)
        for split, (start, stop) in ranges.items():
            for policy in (POLICIES if interval == "5m" else POLICIES[:2]):
                selected_features = (feature_frame(frame, interval, trend_horizon_seconds=1800)
                                     if policy == "competition_scalp" else features)
                rule = venue_rules["instruments"][pair.replace("USDT", "-PERP")] if venue_rules else None
                result, trace = simulate(frame, selected_features, interval, policy, start, stop, True,
                                         costs=COST_PROFILES[args.cost_profile], venue_rule=rule)
                result.update(pair=pair, interval=interval, split=split, start=start, stop=stop, embargo=embargo)
                target = args.output / f"{pair}-{interval}-{split}-{policy}.jsonl"
                with target.open("x") as stream:
                    for entry in trace: stream.write(json.dumps(entry, allow_nan=False) + "\n")
                result["trace_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
                rows.append(result)
    report = {"mode": "diagnostic_proxy_replay", "results": rows, "live_promoted": False,
              "unseen_edge_proven": False, "options_experiment": manifest["options_experiment"]}
    (args.output / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    pd.DataFrame(rows).to_csv(args.output / "comparisons.csv", index=False)
    print(json.dumps({k:v for k,v in report.items() if k != "results"} | {"comparisons":len(rows)}, indent=2))


if __name__ == "__main__":
    main()
