"""SMT proof of local algebraic delta/gross bounds, NOT trading safety."""
import argparse
import json
from pathlib import Path

import z3


def check():
    answers = {}
    for sign in (1, -1):
        b, s, q, qb, qs, low, high, used, cap = z3.Reals("b s q qb qs low high used cap")
        solver = z3.Solver()
        solver.set(timeout=10000)
        solver.add(0 <= s, s <= b, b <= 1, q >= 0, 0 <= qb, qb <= q, 0 <= qs, qs <= q,
                   low <= high, -used <= low, high <= used, used >= 0, cap >= used,
                   q * b <= cap - used, q * s <= cap - used)
        # All outstanding-order fill endpoints and both partial option quantities.
        change = sign * (b * qb - s * qs)
        solver.add(z3.Or(low + change < -cap, high + change > cap))
        verdict = solver.check()
        answers["call" if sign == 1 else "put"] = str(verdict)
    q, qb, qs, per_unit, committed, cap = z3.Reals("q qb qs per_unit committed cap")
    solver = z3.Solver()
    solver.set(timeout=10000)
    solver.add(q >= 0, 0 <= qb, qb <= q, 0 <= qs, qs <= q, per_unit > 0,
               committed >= 0, cap >= 0, committed + 2 * q * per_unit <= cap,
               committed + (qb + qs) * per_unit > cap)
    answers["gross"] = str(solver.check())
    return {"kind": "flyby_delta_bound_model", "checks": answers,
            "passed": all(v == "unsat" for v in answers.values()),
            "scope": "real-valued sizing inequalities, same-kind deltas and bounded quantities",
            "limits": ["not implementation equivalence or exchange execution proof",
                       "not jump/gamma/vega, fees, margin, freshness or maximum-loss proof",
                       "unmatched short options remain prohibited despite a finite local delta"],
            "live_ready": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = check()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
