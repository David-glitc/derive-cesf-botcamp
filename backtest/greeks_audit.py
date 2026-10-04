"""Bounded public-only Greek capture and diagnostics; never send orders."""
import argparse
import json
from pathlib import Path
import time

from src.data.derive_public import DerivePublic
from src.options.greeks_research import quote_diagnostic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cases, raw = [], []
    for asset in ("ETH", "BTC"):
        client = DerivePublic()
        try:
            snapshot = client.snapshot(asset)
            quotes = snapshot["options"]
            rows = [quote_diagnostic(q, snapshot["received_at"]) for q in quotes]
            (args.output / f"{asset}-snapshot.json").write_text(json.dumps(snapshot, indent=2, allow_nan=False))
            cases.append(dict(asset=asset, status="public_snapshot", observed_at=snapshot["received_at"],
                snapshot_id=snapshot["id"], quotes=len(quotes), quoted=sum(q["quoted"] for q in quotes),
                greek_complete=sum(all(v is not None for v in r["api_greeks"].values()) for r in rows),
                diagnostics=rows, faults=snapshot["faults"]))
        except Exception as exc:
            cases.append(dict(asset=asset, status="public_capture_failed", error_type=type(exc).__name__))
        raw.extend(client.records)
        print(json.dumps({k: v for k, v in cases[-1].items() if k != "diagnostics"}), flush=True)
    (args.output / "raw.jsonl").write_text("".join(json.dumps(r, allow_nan=False) + "\n" for r in raw))
    (args.output / "summary.json").write_text(json.dumps(dict(kind="read_only_legacy_v2_greeks_audit",
        captured_at=time.time(), cases=cases, no_real_orders=True, live_ready=False,
        api_vega_theta_units_verified=False,
        limitations=["Current snapshot, not historical Greek coverage",
                     "Model theta holds discount/forward/IV fixed; reported per calendar day",
                     "Model vega reports per absolute IV unit and per one vol point separately",
                     "Current v3 docs expose Greek names but do not establish legacy vega/theta units",
                     "No private margin/order/fill or v3 migration verification"]), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
