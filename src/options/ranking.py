"""Costed, short-horizon spread diagnostics. Never send orders or promise edge."""
from dataclasses import replace
import math

from src.options.paper import normalize_quote
from src.options.pricing import black_price
from src.options.spread_builder import build_spread
from src.data.records import number
from src.options.delta import account_policy, exposure


def costed_plan(buy_raw, sell_raw, now, spot, budget, confidence, delta_policy=None):
    buy, fb = normalize_quote(buy_raw)
    sell, fs = normalize_quote(sell_raw)
    plan = build_spread([buy, sell], kind=buy.kind, underlying=buy.underlying,
                        now=now, debit_budget=budget, confidence=confidence, fee_fraction=0,
                        delta_policy=delta_policy)
    if plan is None or plan.buy != buy.instrument:
        return None
    fixed = 2 * (fb.base + fs.base)
    fees_unit = 2 * (min(spot * fb.rate, plan.buy_limit * fb.premium_cap)
                     + min(spot * fs.rate, plan.sell_limit * fs.premium_cap))
    unit_debit = plan.debit / plan.amount
    amount = min(plan.amount, math.floor(max(0, budget - fixed) / (unit_debit + fees_unit) / buy.step + 1e-10) * buy.step)
    if amount < max(buy.min_amount, sell.min_amount):
        return None
    ratio = amount / plan.amount
    debit, payoff = plan.debit * ratio, plan.max_payoff * ratio
    reserve = 2 * (fb.charge(amount, plan.buy_limit, spot) + fs.charge(amount, plan.sell_limit, spot))
    loss = debit + reserve
    if loss > budget or (payoff - loss) / loss < 1.5:
        return None
    delta_fields = {}
    if delta_policy:
        view = exposure(delta_policy, buy.delta, sell.delta, amount, amount)
        if not view["within_caps"]:
            return None
        delta_fields = {k: view[k] for k in ("net_delta_quote", "worst_delta_quote", "gross_reference_quote")}
        delta_fields["delta_target"] = view["net_delta"]
    return replace(plan, amount=amount, debit=debit, max_payoff=payoff, max_loss=loss,
                   max_profit=payoff - loss, reward_risk=(payoff - loss) / loss,
                   round_trip_fees=reserve, net_delta=plan.net_delta * ratio,
                   break_even=buy.strike + loss / amount * (1 if buy.kind == "call" else -1),
                   fees_verified=True, **delta_fields)


def rank_spreads(options, now, spot, budget=8, confidence=.85, max_candidates=20, *,
                 equity=800, delta_policy=None):
    now, spot, budget, confidence = (number(v) for v in (now, spot, budget, confidence))
    if min(spot, budget) <= 0 or not .75 <= confidence <= 1 or not 1 <= max_candidates <= 50:
        raise ValueError("invalid ranking parameters")
    delta_policy = delta_policy or account_policy(spot, max(.01, equity - budget))
    if delta_policy.spot != spot:
        raise ValueError("delta_reference_mismatch")
    eligible = [q for q in options if q.get("quoted") and q.get("delta") is not None
                and 0 <= now - q["timestamp"] <= 5 and all(v is not None for v in q["fees"].values())]
    candidates, rejected = [], 0
    if len(eligible) > 500:
        raise ValueError("option ranking bound exceeded")
    for buy in eligible:
        if not delta_policy.buy_min <= abs(buy["delta"]) <= delta_policy.buy_max:
            continue
        for sell in eligible:
            if sell["kind"] != buy["kind"] or sell["expiry"] != buy["expiry"] or sell["instrument"] == buy["instrument"]:
                continue
            if (sell["strike"] - buy["strike"]) * (1 if buy["kind"] == "call" else -1) <= 0:
                continue
            try:
                plan = costed_plan(buy, sell, now, spot, budget, confidence, delta_policy)
                if plan is None:
                    rejected += 1
                    continue
                scenarios = {}
                # Keep observed mark-to-book wedges; model prices aren't future fills.
                for horizon in (3600, 21600):
                    for label, move, iv_shift in (("flat", 0, 0), ("up", .01, 0), ("down", -.01, 0),
                                                  ("iv_down", 0, -.05), ("iv_up", 0, .05)):
                        prices = []
                        for q in (buy, sell):
                            p = q["pricing"]
                            model = black_price(p["forward"] * (1 + move), q["strike"],
                                max(0, (q["expiry"] - now - horizon) / (365 * 86400)),
                                p["discount"], max(.001, p["iv"] + iv_shift), q["kind"])
                            base = black_price(p["forward"], q["strike"], (q["expiry"] - now) / (365 * 86400),
                                               p["discount"], p["iv"], q["kind"])
                            prices.append(max(0, model + (q["bids"][0][0] if q is buy else q["asks"][0][0]) - base))
                        scenarios[f"{horizon // 3600}h_{label}"] = (prices[0] - prices[1]) * plan.amount - plan.max_loss
                row = {**plan.to_dict(), "scenario_net_quote": scenarios,
                       "worst_scenario_net": min(scenarios.values()),
                       "directional_1h_net": scenarios["1h_up" if plan.kind == "call" else "1h_down"],
                       "stress_exceeds_budget": min(scenarios.values()) < -budget,
                       "entry_authorized": False,
                       "net_gamma_proxy": (buy["pricing"]["gamma"] - sell["pricing"]["gamma"]) * plan.amount
                                          if all(q["pricing"].get("gamma") is not None for q in (buy, sell)) else None,
                       "interpretation": "fixed-wedge model stress; four-side fee reserve; not expected return or fills"}
                candidates.append(row)
            except (ValueError, TypeError, KeyError):
                rejected += 1
    candidates.sort(key=lambda p: (-p["directional_1h_net"] / p["max_loss"], -p["worst_scenario_net"], p["buy"], p["sell"]))
    return {"status": "available" if candidates else "no_qualified_spreads", "budget": budget,
            "candidate_count": len(candidates), "rejected_pairs": rejected,
            "candidates": candidates[:max_candidates], "live_options": False,
            "ranking_rule": "directional 1h scenario / debit-plus-fees, then worst stress; uncalibrated"}
