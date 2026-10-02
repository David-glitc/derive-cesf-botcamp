"""Executable model proofs, not verification of all Python/Hummingbot/exchange code."""
import argparse
from collections import deque
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.execution.paired import (State, entry_guard, invariant, matched_report_guard,
                                 reserve_guard, remaining_position, transition)


def exhaustive(max_lots=3):
    start = State()
    seen, queue, edges = {start}, deque([start]), 0
    guards = {"paused": False, "fresh": True, "reconciled": True, "daily_pnl": 0, "peak_dd": 0}
    while queue:
        state = queue.popleft()
        events = [{"type": "request_close"}, {"type": "timeout"}]
        events += [{"type": "prepare", "target": target, "reserve": 8, "budget": budget, "guards": guards}
                   for target in range(1, max_lots + 1) for budget in (0, 8)]
        if state.phase != "halted":
            events += [{"type": kind, "buy": b, "sell": s, "terminal": terminal}
                       for kind in ("open_report", "close_report") for b in range(max_lots + 2)
                       for s in range(max_lots + 2) for terminal in (False, True)]
        for event in events:
            nxt = transition(state, event)
            edges += 1
            if not invariant(nxt):
                raise AssertionError({"state": asdict(state), "event": event, "next": asdict(nxt)})
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return {"max_integer_lots": max_lots, "reachable_states": len(seen), "transitions": edges,
            "invariant_failures": 0, "scope": "actual reducer; bounded quantities, canonical safe entry flags"}


def smt():
    import z3
    obligations = []
    def check(name, assumptions, violation, expected="unsat"):
        solver = z3.Solver()
        solver.set(timeout=10000)
        solver.add(*assumptions, violation)
        result = str(solver.check())
        row = {"name": name, "result": result, "expected": expected,
               "formula_sha256": hashlib.sha256(solver.sexpr().encode()).hexdigest()}
        if result == "sat":
            row["counterexample"] = str(solver.model())
        if result != expected:
            raise AssertionError(row)
        obligations.append(row)

    pb, ps, b, s, limit = z3.Ints("previous_buy previous_sell buy sell limit")
    base = [limit > 0, pb == ps, pb >= 0, pb <= limit]
    guard = matched_report_guard(pb, ps, b, s, limit, z3.And)
    nb, ns = z3.If(guard, b, pb), z3.If(guard, s, ps)
    check("matched_fill_inductive_bound", base,
          z3.Or(nb != ns, nb < pb, nb > limit, ns < 0))
    check("matched_close_cannot_reverse", base,
          z3.And(guard, z3.Or(limit - b < 0, limit - b != limit - s)))
    check("mutation_remove_matching_guard", base,
          z3.And(b >= pb, s >= ps, b <= limit, s <= limit, b != s), "sat")
    budget, committed, request = z3.Ints("budget committed request")
    reserve = z3.If(reserve_guard(committed, request, budget, z3.And), request, 0)
    check("shared_reservation_bound", [budget >= 0, committed >= 0, committed <= budget],
          z3.Or(reserve < 0, committed + reserve > budget))
    check("mutation_ignore_committed", [budget > 0, committed > 0, committed <= budget,
                                        request > 0, request <= budget], committed + request > budget, "sat")
    q, close = z3.Ints("position close_quantity")
    remaining = remaining_position(q, close, z3.If)
    check("reduce_only_intent_no_flip", [close >= 0, close <= z3.Abs(q)],
          z3.Or(z3.Abs(remaining) > z3.Abs(q), q * remaining < 0))
    paused, fresh, reconciled, flat, pending = z3.Bools("paused fresh reconciled flat pending")
    daily, dd = z3.Reals("daily_pnl peak_dd")
    allowed = entry_guard(paused, fresh, reconciled, flat, pending, daily, dd, z3.And)
    check("entry_respects_loss_pause_data_account", [], z3.And(allowed,
          z3.Or(paused, z3.Not(fresh), z3.Not(reconciled), z3.Not(flat), pending,
                daily <= z3.RealVal("-0.02"), dd <= z3.RealVal("-0.04"))))
    risk_cap, notional_cap, available, gross_free = z3.Reals("risk_cap notional_cap available gross_free")
    bounds = (risk_cap, notional_cap, available, gross_free)
    sized = bounds[0]
    for bound in bounds[1:]:
        sized = z3.If(sized <= bound, sized, bound)
    sized = z3.If(sized > 0, sized, 0)
    check("idealized_notional_caps", [b >= 0 for b in bounds],
          z3.Or(sized < 0, *[sized > b for b in bounds]))
    return {"solver": z3.get_version_string(), "obligations": obligations,
            "scope": "exact integer/rational model; not floating-point, network or exchange correctness"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"mode": "local_model_verification", "exhaustive": exhaustive(), "smt": smt(),
              "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (ROOT / "src/execution/paired.py", ROOT / "src/risk/position_sizing.py", Path(__file__))},
              "live_execution_verified": False, "profitability_proven": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
