"""Offline planner-to-RFQ audit. Scripted books are NOT market opportunities.

Uses current captured lot/fee metadata, a real temporary RFQ journal and the
production reducer. No network, credentials, strategy edits or live orders.
"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import random
import tempfile

from backtest.rfq_simulation import Surface, ModelTransport
from src.execution.options_rfq import OptionsRFQ, RFQJournal
from src.options.delta import account_policy
from src.options.paper import Fees
from src.options.ranking import costed_plan
from src.risk.exposure import ETH_EXPOSURE_TEST

NOW = 1800000000


def quotes(kind, rule, *, spot=2900, buy_price=20, sell_price=9, width=100):
    """Deliberately favorable scripted prices/Greeks, not a calibrated chain."""
    result = []
    for name, strike, bid, ask, delta in (
        ("ETH-A", spot, buy_price - .1, buy_price, .5),
        ("ETH-B", spot + width * (1 if kind == "call" else -1), sell_price, sell_price + .1, .25),
    ):
        result.append(dict(instrument=name, underlying="ETH", kind=kind, strike=strike,
            expiry=NOW + 259200, multiplier=1, step=float(rule["amount_step"]),
            min_amount=float(rule["minimum_amount"]), timestamp=NOW,
            bids=((bid, 100),), asks=((ask, 100),), delta=delta * (1 if kind == "call" else -1),
            tick=float(rule["tick_size"]), fees=dict(rate=float(rule["taker_fee_rate"]),
                base=float(rule["base_fee"]), premium_cap=float(rule["mark_price_fee_rate_cap"]))))
    return result


def construct(raw, spot=2900):
    policy = account_policy(spot, 796, underlying="ETH", gross_fraction=.75,
                            exposure_profile=ETH_EXPOSURE_TEST)
    return costed_plan(*raw, NOW, spot, 4, .9, policy)


def construction_sweep(rule, iterations):
    rng = random.Random(20261003)
    counts = dict(accepted=0, rejected=0, invariant_failures=0, invalid_input_acceptances=0)
    trace = []
    for i in range(iterations):
        kind = rng.choice(("call", "put"))
        spot = rng.randrange(2400, 2990, 10)
        raw = quotes(kind, rule, spot=spot, buy_price=rng.randrange(12, 41),
                     sell_price=rng.randrange(5, 11), width=rng.choice((50, 100, 150, 200)))
        fault = i % 8
        if fault == 1: raw[1]["expiry"] += 86400
        if fault == 2: raw[0]["timestamp"] -= 6
        if fault == 3:
            for q in raw: q["fees"]["base"] = 2
        if fault == 4: raw[1]["delta"] *= -1
        if fault == 5: raw[1]["strike"] = spot - (1 if kind == "call" else -1) * 100
        if fault == 6: raw[1]["instrument"] = raw[0]["instrument"]
        if fault == 7: raw[0]["asks"] = ((raw[0]["asks"][0][0], .001),)
        p = construct(raw, spot)
        counts["accepted" if p else "rejected"] += 1
        row = dict(case=i, kind=kind, fault=fault, accepted=p is not None)
        if p:
            fee = Fees(**raw[0]["fees"])
            expected_fees = 2 * (fee.charge(p.amount, p.buy_limit, spot)
                                 + fee.charge(p.amount, p.sell_limit, spot))
            checks = [p.max_loss <= 4 + 1e-9, p.reward_risk >= 1.5 - 1e-9,
                      p.amount >= float(rule["minimum_amount"]),
                      math.isclose(p.amount / float(rule["amount_step"]),
                                   round(p.amount / float(rule["amount_step"])), abs_tol=1e-8),
                      p.gross_reference_quote <= 597 + 1e-8,
                      abs(p.net_delta_quote) <= 159.2 + 1e-8,
                      math.isclose(p.round_trip_fees, expected_fees, abs_tol=1e-8)]
            k1, k2 = raw[0]["strike"], raw[1]["strike"]
            intrinsic = lambda s, k: max(0, (s - k) * (1 if kind == "call" else -1))
            payoffs = [(intrinsic(s, k1) - intrinsic(s, k2)) * p.amount
                       for s in range(0, 6001, 25)]
            checks.extend((min(payoffs) >= -1e-8, max(payoffs) <= p.max_payoff + 1e-8,
                           min(x - p.max_loss for x in payoffs) >= -4 - 1e-8))
            counts["invariant_failures"] += not all(checks)
            counts["invalid_input_acceptances"] += fault != 0
            row.update(amount=p.amount, max_loss=p.max_loss, fees=p.round_trip_fees,
                       reward_risk=p.reward_risk, invariants_passed=all(checks))
        trace.append(row)
    return counts, trace


class ScriptedSurface(Surface):
    def __init__(self, rule, raw):
        super().__init__({"ETH-option": rule}, exposure_profile=ETH_EXPOSURE_TEST)
        self.now, self.spots, self.ivs = NOW, {"ETH": 2900}, {"ETH": .6}
        self.contracts = {q["instrument"]: ("ETH", q["strike"], q["expiry"], q["kind"]) for q in raw}
        self.books = {q["instrument"]: (q["bids"][0][0], q["asks"][0][0], q["delta"]) for q in raw}

    def quote(self, name):
        return self.books[name]


async def lifecycle_case(rule, kind, scenario):
    raw = quotes(kind, rule)
    p = construct(raw)
    if p is None:
        raise ValueError("chosen_execution_fixture_no_longer_qualifies")
    surface = ScriptedSurface(rule, raw)
    account = {"cash": 800.}
    t = ModelTransport(surface, account, faults=scenario == "lost_ack")
    t.now = NOW
    if scenario == "lost_ack": t.execute_count = 10  # deterministic fault trigger only
    with tempfile.TemporaryDirectory(prefix="flyby-options-audit-") as folder:
        c = OptionsRFQ(t, RFQJournal(Path(folder) / "rfq.json", "offline-fixture", "audit"), 42,
                       exposure_profile=ETH_EXPOSURE_TEST, underlying="ETH")
        for _ in range(3):
            await c.tick(t.now, plan=p.to_dict(), budget=4, allow_entry=True,
                         consume_entry=lambda a, now: True)
        if c.journal.state["phase"] != "open" or len(t.positions) != 2:
            raise AssertionError("paired_entry_not_reconciled")
        entry_fee = float(c.journal.state["entry_fee"])
        target_bid = 55 if scenario in ("profit", "lost_ack", "exit_fee_rise") else 14 if scenario == "loss" else 44
        surface.books["ETH-A"] = (target_bid, target_bid + .1, raw[0]["delta"])
        surface.books["ETH-B"] = (9, 9.1, raw[1]["delta"])
        t.now += 21601 if scenario == "time" else 300
        surface.now = t.now
        if scenario == "exit_fee_rise": surface.spots["ETH"] = 3300
        for _ in range(4):
            await c.tick(t.now, budget=4, force_exit=scenario == "hard_stop")
        s = c.journal.state
        attempts = len(t.executed)
        pnl = float(s["realized_pnl"]) if s.get("realized_pnl") is not None else None
        result = dict(kind=kind, scenario=scenario, final_phase=s["phase"],
                      actual_fixture_executions=attempts, intent_attempts=s["executions_submitted"],
                      remaining_legs=len(t.positions), last_error=c.last_error,
                      net_pnl=pnl, starting_equity=800, ending_cash=account["cash"],
                      entry_debit=p.debit, entry_fee=entry_fee, reserved_round_trip_fees=p.round_trip_fees,
                      actual_fixture_fees=t.fees_total, lost_acknowledgements=t.lost_acks,
                      premium_turnover=t.premium_turnover, max_loss_budget=4)
        if scenario == "exit_fee_rise":
            # Report the known unresolved exit, not a fabricated zero-risk close.
            result["exit_fee_required"] = sum(surface.fees("ETH").charge(p.amount, surface.quote(name)[0 if name == "ETH-A" else 1], 3300)
                                              for name in ("ETH-A", "ETH-B"))
            result["exit_fee_cap"] = float(s["max_fee"])
            assert attempts == 1 and len(t.positions) == 2 and s["phase"] == "settling"
            result["economic_or_recovery_gate"] = "FAIL: exit fee exceeds entry-time cap; intent awaits reconciliation"
        else:
            assert s["phase"] == "idle" and not t.positions and attempts == 2
            assert math.isclose(account["cash"], 800 + pnl, abs_tol=1e-7)
            assert math.isclose(float(s["trades"][-1]["fees"]), t.fees_total, abs_tol=1e-7)
            assert pnl >= -4 - 1e-7
            assert (pnl > 0) if scenario != "loss" else (pnl < 0)
            result["economic_or_recovery_gate"] = "PASS: scripted paired close/cash reconciliation"
        return result


def run(rule, iterations=1000):
    if not 1 <= iterations <= 100000:
        raise ValueError("iterations_outside_audit_bound")
    counts, trace = construction_sweep(rule, iterations)
    if counts["invariant_failures"] or counts["invalid_input_acceptances"]:
        raise AssertionError("construction_audit_failed")
    cases = [asyncio.run(lifecycle_case(rule, kind, scenario)) for kind in ("call", "put")
             for scenario in ("profit", "loss", "time", "hard_stop", "lost_ack", "exit_fee_rise")]
    sample = construct(quotes("call", rule))
    charges = [Fees(float(rule["taker_fee_rate"]), float(rule["base_fee"]),
                    float(rule["mark_price_fee_rate_cap"])).charge(sample.amount, price, 2900)
               for price in (sample.buy_limit, sample.sell_limit)]
    return dict(kind="offline_options_construction_and_execution_audit", no_real_orders=True,
        production_profiles_changed=False, starting_equity_per_case=800,
        exposure_profile=ETH_EXPOSURE_TEST, risk_budget=4, construction=counts,
        lifecycle_cases=cases, construction_trace=trace,
        fee_criteria=dict(debit_plus_reserved_fees_at_most=4, min_expiry_reward_risk=1.5,
                          net_take_profit=.30, net_stop_loss=.18,
                          no_fee_discount_assumed_in_production=True,
                          actual_settled_fees_must_not_exceed_signed_cap=True),
        sample_fee_surface=dict(debit=sample.debit, reserved_round_trip_fees=sample.round_trip_fees,
            max_loss=sample.max_loss, fees_as_fraction_of_budget=sample.round_trip_fees / 4,
            expiry_reward_risk=sample.reward_risk, break_even_close_credit=sample.max_loss,
            take_profit_close_credit=(sample.debit + sum(charges)) * 1.3 + sum(charges),
            rfq_discount_sensitivity_round_trip=2 * max(charges),
            rfq_discount_sensitivity_authorized=False),
        limitations=["Scripted favorable prices/Greeks, not coherent historical chains or observed opportunities",
                     "RFQ quote hash/settlement is modeled; native signer is covered by separate HB tests",
                     "Independent $800 cases; do not combine their returns or turnover",
                     "Current published v3 RFQ discounts are sensitivity only; legacy/account fees unverified",
                     "Two exit-fee-rise cases intentionally retain inventory; NO-GO for live activation"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists(): parser.error("choose a new output; prior evidence is immutable")
    rule = json.loads(args.rules.read_text())["instruments"]["ETH-option"]
    result = run(rule, args.iterations)
    sources = [Path(__file__), Path("backtest/rfq_simulation.py"), Path("src/options/ranking.py"),
               Path("src/options/spread_builder.py"), Path("src/options/paper.py"),
               Path("src/options/delta.py"), Path("src/risk/exposure.py"),
               Path("src/execution/options_rfq.py"), Path("src/execution/derive_rfq.py")]
    result["source_sha256"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    result["rule_sha256"] = hashlib.sha256(args.rules.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "construction_trace"}, indent=2))


if __name__ == "__main__":
    main()
