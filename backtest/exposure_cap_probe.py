"""Offline cap sensitivity: no production edits, live orders or cap promotion.

Reuses fixed historical signals and the existing fee-adjusted spread planner.
Only reference-exposure bounds vary, not risk budgets, fees, or venue minimums.
This is entry eligibility, NOT filled-trade performance or portfolio P&L.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from backtest.rfq_simulation import Surface
from backtest.two_year_flyby import load_history
from src.options.delta import DeltaPolicy

CAPS = ((.20, .30), (.20, .75), (.20, 1.25), (.40, 2.25), (.60, 3.25))


def probe(history, rules):
    rows = []
    for asset in ("ETH", "BTC"):
        signals = history[asset]["decisions"]["normal"]
        for net_fraction, gross_fraction in CAPS:
            counts, amounts = Counter(), []
            surface = Surface(rules)

            def policy(spot, equity, *, scale=1, **kwargs):
                # DeltaPolicy permits explicit numeric bounds. This replacement
                # exists only inside the modeled Surface planner's test scope;
                # production account_policy still rejects these larger fractions.
                kwargs.pop("exposure_profile", None)
                kwargs.pop("gross_fraction", None)
                return DeltaPolicy(spot=spot, net_cap_quote=equity * net_fraction * scale,
                                   gross_cap_quote=equity * gross_fraction * scale, **kwargs)

            with patch("backtest.rfq_simulation.account_policy", policy):
                for i in range(101, len(signals)):
                    decision = signals[i - 1]
                    if decision.option_direction is None:
                        continue
                    candle = history[asset]["candles"][i]
                    surface.now = int(candle["timestamp"])
                    surface.spots = {asset: float(candle["open"])}
                    surface.ivs = {asset: float(history[asset]["iv"][i])}
                    plan, reason = surface.plan(asset, decision.option_direction, surface.now, 800,
                                                dict(risk_trade_budget=4., risk_scale=1.), decision.confidence)
                    counts[reason] += 1
                    if plan:
                        amounts.append(plan["amount"])
            rows.append(dict(asset=asset, option_delta_fraction=net_fraction,
                option_gross_fraction=gross_fraction, delta_cap_before_debit=800 * net_fraction,
                gross_cap_before_debit=800 * gross_fraction, signal_observations=sum(counts.values()),
                qualified_plans=len(amounts), reasons=dict(counts),
                min_qualified_amount=min(amounts) if amounts else None,
                max_qualified_amount=max(amounts) if amounts else None))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output file; previous evidence is immutable")
    history, rules, _ = load_history(args.history)
    result = dict(kind="offline_option_cap_entry_eligibility", starting_equity=800,
        risk_trade_budget=4, venue_minimums_unchanged=True, fees_unchanged=True,
        production_profiles_changed=False, simulated_or_actual_orders=0,
        limitations=["Eligibility counts, not fills, trades, P&L or deployable cap approvals",
                     "Fixed $800 normal-risk account; no sequential cash/DD simulation",
                     "Modeled proxy chains, not historical Derive executable quotes",
                     "Gross reference exposure is not maximum defined-spread loss"],
        history_manifest_sha256=hashlib.sha256((args.history / "manifest.json").read_bytes()).hexdigest(),
        cases=probe(history, rules))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
