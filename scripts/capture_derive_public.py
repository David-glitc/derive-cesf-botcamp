"""Capture bounded public native data; archive immutably and optionally refresh our shadow context."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.accounting.context import atomic_owned_json, market_view
from src.data.derive_public import DerivePublic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--currency", choices=("ETH", "BTC"), required=True)
    parser.add_argument("--samples", type=int, choices=range(1, 7), default=2)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--publish-shadow", action="store_true",
                        help="refresh data/flyby-market-CURRENCY.json; doesn't change trading inputs")
    parser.add_argument("--quant", action="store_true", help="add bounded public L2/tape/surface/spread diagnostics")
    parser.add_argument("--interval-seconds", type=int, default=0, help="delay between bounded samples, 0..60")
    args = parser.parse_args()
    if not 0 <= args.interval_seconds <= 60:
        parser.error("interval-seconds must be 0..60")
    if args.output.exists():
        parser.error("output must be a new immutable capture directory")
    args.output.mkdir(parents=True)
    client = DerivePublic()
    with (args.output / "market.jsonl").open("x") as output, (args.output / "raw.jsonl").open("x") as raw:
        previous = None
        failures = 0
        for i in range(args.samples):
            if i:
                time.sleep(args.interval_seconds)
            first = len(client.records)
            try:
                snapshot = client.snapshot(args.currency, quant=args.quant, previous=previous)
            except Exception as exc:
                failures += 1
                snapshot = None
                print(json.dumps({"status": "failed_sample", "sample": i, "reason": type(exc).__name__}), flush=True)
            for record in client.records[first:]:
                raw.write(json.dumps(record, allow_nan=False) + "\n")
            raw.flush()
            if snapshot is None:
                continue
            output.write(json.dumps(snapshot, allow_nan=False) + "\n")
            output.flush()
            if args.publish_shadow:
                atomic_owned_json(Path("data") / f"flyby-market-{args.currency}.json", snapshot, "derive_market_context")
            print(json.dumps(market_view(snapshot, snapshot["received_at"], args.currency)), flush=True)
            previous = snapshot
        if failures:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
