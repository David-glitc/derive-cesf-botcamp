"""Read-only public mainnet sizing diagnostics. Never loads credentials or trades."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.data.derive_public import DerivePublic
from src.accounting.context import atomic_owned_json
from src.risk.venue_sizing import venue_size


def inspect(capital=800, fraction=.20):
    if not 0 < fraction <= .30 or capital <= 0:
        raise ValueError("use_existing_approved_sizing_limits")
    client = DerivePublic()
    instruments, diagnostics = {}, []
    for ccy in ("ETH", "BTC", "SOL", "HYPE"):
        result = client.call("public/get_all_instruments", {"currency": ccy, "instrument_type": "perp",
                            "expired": False, "page": 1, "page_size": 1000})
        if result["pagination"]["num_pages"] > 1:
            raise ValueError("unexpected_perpetual_pagination")
        raw = next((r for r in result["instruments"] if r["instrument_name"] == ccy + "-PERP" and r["is_active"]), None)
        if raw is None:
            diagnostics.append({"pair": ccy + "-USDC", "status": "not_listed"}); continue
        rule = {k: raw[k] for k in ("minimum_amount", "amount_step", "tick_size", "maximum_amount",
                                   "maker_fee_rate", "taker_fee_rate", "base_fee")}
        tick = client.call("public/get_ticker", {"instrument_name": ccy + "-PERP"})
        price = tick["best_ask_price"]
        size = venue_size(budget=capital * fraction, price=price, side=1,
                          min_amount=rule["minimum_amount"], amount_step=rule["amount_step"],
                          price_tick=rule["tick_size"], max_amount=rule["maximum_amount"])
        instruments[ccy + "-PERP"] = rule
        diagnostics.append({"pair": ccy + "-USDC", "instrument": ccy + "-PERP", "price": price,
            "status": size.reason, "minimum_notional": str(size.minimum_notional),
            "minimum_equity_fraction": float(size.minimum_notional) / capital,
            "approved_notional_fraction": fraction, "amount": str(size.amount)})
    return {"kind": "flyby_public_venue_rules", "network": "mainnet", "observed_at": time.time(),
            "capital": capital, "instruments": instruments, "diagnostics": diagnostics,
            "source_ids": [r["id"] for r in client.records], "account_verified": False, "orders_submitted": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inspect()
    if args.output:
        if args.output.exists(): raise ValueError("refuse_snapshot_overwrite")
        atomic_owned_json(args.output, result, "flyby_public_venue_rules")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
