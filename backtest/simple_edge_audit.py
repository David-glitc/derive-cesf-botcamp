"""Independent ledger/provenance audit and fee-only counterfactual; no trading."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from src.data.records import digest


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fee_sensitivity(trades, rule):
    maker, taker, base = (float(rule[k]) for k in ("maker_fee_rate", "taker_fee_rate", "base_fee"))
    if any(not math.isfinite(v) or v < 0 for v in (maker, taker, base)):
        raise ValueError("invalid_fee_rule")
    gross = sum(t["net_pnl"] + t["fees"] + t["funding"] for t in trades)
    funding = sum(t["funding"] for t in trades)
    scenarios = {}
    for name, entry_rate, exit_rate, entry_base, exit_base in (
        ("public_taker_both_sides", taker, taker, base, base),
        ("ASSUMED_maker_entry_taker_exit", maker, taker, 0., base),
    ):
        fees = 0.
        for t in trades:
            amount, entry, exit_price = (t[k] for k in ("amount", "entry_price", "exit_price"))
            if any(not math.isfinite(v) or v <= 0 for v in (amount, entry, exit_price)):
                raise ValueError("invalid_fee_trade")
            fees += amount * (entry * entry_rate + exit_price * exit_rate) + entry_base + exit_base
        scenarios[name] = dict(fees=fees, fixed_trade_net_pnl=gross - fees - funding)
    return dict(kind="fee_only_fixed_trade_counterfactual", gross_closed_pnl=gross,
        modeled_funding=funding, scenarios=scenarios, usable_as_strategy_performance=False,
        limitations=["Same fills, quantities, exits and funding; no re-run of sizing, eligibility or drawdown",
                     "Public standard schedule, not verified private-account fees or actual legacy-route charging",
                     "Maker entry is an assumption: immediate proxy fills do not prove resting maker execution",
                     "Entry/exit slippage already remains in gross P&L; not removed or subtracted twice",
                     "No RFQ discount, reward, rebate or zero-cost fill assumed"])


def audit(directory):
    summary = json.loads((directory / "summary.json").read_text())
    for name, expected in summary["source_sha256"].items():
        if sha(Path(name)) != expected:
            raise ValueError("source_hash_changed:" + name)
    for name, expected in summary["artifact_sha256"].items():
        target = directory / name
        if directory.resolve() not in target.resolve().parents or sha(target) != expected:
            raise ValueError("artifact_hash_mismatch:" + name)
    probe = json.loads((directory / "native-probe.json").read_text())
    for record in probe["records"]:
        if digest({k: v for k, v in record.items() if k != "id"}) != record["id"]:
            raise ValueError("native_record_hash_mismatch")
    cases = []
    for case in summary["cases"]:
        target = directory / (case["window"] + "-" + case["id"])
        trades = [json.loads(line) for line in (target / "trades.jsonl").read_text().splitlines()]
        fills = [json.loads(line) for line in (target / "fills.jsonl").read_text().splitlines()]
        if case["residual_perp"] or len(trades) != case["trades"] or len(fills) != 2 * len(trades):
            raise ValueError("audit_requires_closed_trade_ledger")
        for i, trade in enumerate(trades):
            entry, close = fills[2 * i:2 * i + 2]
            if (entry["action"], close["action"]) != ("entry", "exit"):
                raise ValueError("fill_event_order")
            if entry["time"] != trade["opened_at"] or close["time"] != trade["closed_at"]:
                raise ValueError("fill_trade_clock_mismatch")
            if i and trade["opened_at"] < trades[i - 1]["closed_at"]:
                raise ValueError("overlapping_positions")
            if trade["asset"] != "SOL" or entry["notional"] > 160 + 1e-8:
                raise ValueError("scope_or_allocation_cap")
        for actual, expected in (
            (sum(t["net_pnl"] for t in trades), case["net_pnl"]),
            (sum(t["fees"] for t in trades), case["fees"]),
            (sum(t["funding"] for t in trades), case["modeled_funding"]),
            (sum(f["notional"] for f in fills), case["perp_notional_turnover"]),
        ):
            if abs(actual - expected) > 1e-7:
                raise ValueError("ledger_total_mismatch")
        cases.append(dict(window=case["window"], variant=case["variant"], scenario=case["scenario"],
                          ledger_verified=True, fee_sensitivity=fee_sensitivity(trades, probe["rule"])))
    return dict(kind="simple_edge_independent_audit", original_summary_sha256=sha(directory / "summary.json"),
        audit_source_sha256=sha(Path(__file__)), source_hashes_verified=len(summary["source_sha256"]),
        artifacts_verified=len(summary["artifact_sha256"]), native_records_verified=len(probe["records"]),
        unique_ticker_events=len({s["timestamp"] for s in probe["samples"]}),
        cases=cases, production_changes=False, promoted=False, live_ready=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.results)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: result[k] for k in ("source_hashes_verified", "artifacts_verified", "native_records_verified",
                                            "unique_ticker_events", "promoted", "live_ready")}))


if __name__ == "__main__":
    main()
