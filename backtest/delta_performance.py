"""Twenty predeclared independent-account public option replays. No optimization.

Reusing brief captures under different policies does not add market evidence.
The sum of case turnover is NOT the turnover/return of a shared portfolio.
"""
import argparse
import hashlib
import json
from pathlib import Path

from src.options.paper import PaperOptions

SELECTIONS = {"any": {}, "ATM": {"buy_moneyness": "ATM"},
              "OTM": {"buy_moneyness": "OTM"}, "ITM": {"buy_moneyness": "ITM", "buy_target": .65},
              "OTM_35d": {"buy_moneyness": "OTM", "buy_target": .35}}


def target_assessment(results):
    # Targets never feed back into sizing, policy, forecasts or trading decisions.
    volume = sum(r["premium_volume_quote"] for r in results)
    return {"return_target_pct": 150, "return_horizon_hours": 48,
            "sum_case_volume_target_quote": 50000, "sum_case_volume_quote": volume,
            "volume_gap_quote": max(0, 50000 - volume), "volume_target_met": volume >= 50000,
            "qualified_48h_return_cases": sum(r["observed_hours"] >= 48 and r["closed_matched_spreads"] > 0 for r in results),
            "return_target_supported": False,
            "competitor_return_forecast": None, "competitor_relative_markup": 1.50,
            "competitor_status": "not_estimated: no audited competitor strategies or comparable data",
            "aggregation": "sum of twenty experiment volumes; no combined account return",
            "optimisation_floor_enforced": False}


def run_cases(inputs, output):
    if len(inputs) != 2 or {ccy for ccy, _ in inputs} != {"ETH", "BTC"}:
        raise ValueError("two_public_underlyings_required")
    results, hashes = [], {}
    prepared = []
    for ccy, path in inputs:
        content = Path(path).read_bytes()
        rows = [json.loads(line) for line in content.decode().splitlines() if line.strip()]
        if not rows or any(r["ccy"] != ccy or r["source"] not in ("derive_v3_public_l1", "derive_legacy_public_l1") for r in rows):
            raise ValueError("observed_public_options_required_not_synthetic")
        prepared.append((ccy, rows))
        hashes[str(path)] = hashlib.sha256(content).hexdigest()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for ccy, rows in prepared:
        for label, settings in SELECTIONS.items():
            for fraction in (.10, .20):
                engine = PaperOptions(delta_settings=settings, delta_net_fraction=fraction)
                for row in rows:
                    engine.step(row)
                name = f"{ccy}-{label}-{int(fraction * 100)}"
                trace = output / f"{name}.jsonl"
                with trace.open("x") as stream:
                    for event in engine.events:
                        stream.write(json.dumps(event, allow_nan=False) + "\n")
                results.append({"case": name, **engine.summary(), "observed_hours": (rows[-1]["time"] - rows[0]["time"]) / 3600,
                                "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
                                "rejections": [e["reason"] for e in engine.events if e["type"] in ("reject", "no_entry")]})
    root = Path(__file__).resolve().parents[1]
    sources = ["src/options/delta.py", "src/options/spread_builder.py", "src/options/paper.py",
               "agents/condor_agent.py", "src/risk/competition.py", "backtest/delta_performance.py"]
    report = {"kind": "flyby_delta_public_replay", "cases": results, "case_count": len(results),
              "targets": target_assessment(results), "input_sha256": hashes,
              "source_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sources},
              "profitability_proven": False, "live_promoted": False,
              "limitations": ["brief previously observed captures, not 48h option history",
                              "case configurations share observations; not independent statistical samples",
                              "simulated paired fills, no exchange execution verification",
                              "option premium turnover, not verified competition volume metric"]}
    (output / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def run_perp_cases(data, rules_path, output):
    """Twenty 48h proxy runs: two markets, two fixed policies, five windows.

    Options are not retroactively synthesized from candles. Different policies
    share periods; BTC minimums may block every entry under existing caps.
    """
    import numpy as np
    import pandas as pd
    from backtest.compare_policies import simulate, COST_PROFILES
    from src.signal.flyby import feature_frame
    rules_content = Path(rules_path).read_bytes()
    rules = json.loads(rules_content)
    if rules.get("kind") != "flyby_public_venue_rules" or rules.get("network") != "mainnet":
        raise ValueError("current_public_rules_required")
    prepared, hashes = [], {}
    for pair in ("BTCUSDT", "SOLUSDT"):
        path = Path(data) / f"{pair}-5m.csv"
        frame = pd.read_csv(path)
        prices = frame[["open", "high", "low", "close"]]
        if (len(frame) < 3718 or not frame.timestamp.diff().dropna().eq(300).all()
                or not np.isfinite(frame[["timestamp", "open", "high", "low", "close", "volume"]]).all().all()
                or (prices <= 0).any().any() or (frame.volume < 0).any()
                or not frame.high.ge(frame[["open", "close", "low"]].max(axis=1)).all()
                or not frame.low.le(frame[["open", "close", "high"]].min(axis=1)).all()):
            raise ValueError("continuous_positive_proxy_history_required")
        prepared.append((pair, frame))
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for pair, frame in prepared:
        for policy, horizon in (("competition_baseline", 14400), ("competition_scalp", 1800)):
            features = feature_frame(frame, "5m", trend_horizon_seconds=horizon)
            for n in range(5):
                start = 150 + n * (576 + 172)
                stop = start + 576
                result, trace = simulate(frame, features, "5m", policy, start, stop, True,
                    costs=COST_PROFILES["public_taker"], venue_rule=rules["instruments"][pair.replace("USDT", "-PERP")])
                name = f"{pair}-{policy}-48h-{n + 1}"
                path = output / f"{name}.jsonl"
                with path.open("x") as stream:
                    for event in trace:
                        stream.write(json.dumps(event, allow_nan=False) + "\n")
                results.append({"case": name, "pair": pair, "start": start, "stop": stop, **result,
                                "observed_hours": 48, "trace_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    volume = sum(r["volume_quote"] for r in results)
    report = {"kind": "twenty_48h_perp_proxy_cases", "case_count": len(results), "results": results,
              "volume_quote_sum": volume, "volume_target_quote": 50000, "volume_target_met": volume >= 50000,
              "volume_gap_quote": max(0, 50000 - volume), "return_target_pct": 150,
              "cases_meeting_return_target": sum(r["net_return_pct"] >= 150 for r in results),
              "return_range_pct": [min(r["net_return_pct"] for r in results), max(r["net_return_pct"] for r in results)],
              "input_sha256": hashes, "rules_sha256": hashlib.sha256(rules_content).hexdigest(),
              "capital_per_case": 800, "combined_portfolio_return": None, "profitability_proven": False,
              "live_promoted": False, "limitations": ["previously inspected proxy bars; not new holdout",
                  "current rules applied to old prices, modeled fees/slippage/funding, no queue model",
                  "no simultaneous options/perp account simulation; no historical option chain synthesized",
                  "five disjoint 48h windows; two policies share each market window",
                  "sum of experiment volume, not one-account competition volume"]}
    (output / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eth", type=Path, default=Path("data/options-paper/eth-20261001-public.jsonl"))
    parser.add_argument("--btc", type=Path, default=Path("data/options-paper/btc-20261001-public.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--perps-data", type=Path)
    parser.add_argument("--venue-rules", type=Path)
    args = parser.parse_args()
    if bool(args.perps_data) != bool(args.venue_rules):
        parser.error("--perps-data and --venue-rules must be supplied together")
    report = run_cases([("ETH", args.eth), ("BTC", args.btc)], args.output)
    print(json.dumps({"case_count": report["case_count"], "targets": report["targets"]}, indent=2))
    if args.perps_data:
        perps = run_perp_cases(args.perps_data, args.venue_rules, args.output / "perps-48h")
        print(json.dumps({k: v for k, v in perps.items() if k not in ("results", "input_sha256")}, indent=2))


if __name__ == "__main__":
    main()
