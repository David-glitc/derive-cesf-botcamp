"""Read-only replay of checksummed legacy native captures; fills remain simulated."""
import argparse
import hashlib
import json
from pathlib import Path

from backtest.options_paper import write_results
from src.data.derive_public import DerivePublic
from src.data.records import digest, number, validate_snapshot
from src.options.paper import PaperOptions


def verify_raw(rows):
    records = {}
    for row in rows:
        if (row.get("network") != "mainnet" or row.get("api_generation") != "legacy_v2"
                or row.get("schema") != 1 or row.get("method") not in DerivePublic.SOURCES
                or digest({k: v for k, v in row.items() if k != "id"}) != row.get("id")
                or not 0 <= number(row["sent_at"]) <= number(row["received_at"])):
            raise ValueError("invalid raw public provenance")
        if row["id"] in records:
            raise ValueError("duplicate raw observation")
        records[row["id"]] = row
    return records


def paper_row(snapshot):
    now, ccy = number(snapshot["received_at"]), snapshot["ccy"]
    validate_snapshot(snapshot, now, ccy)
    if ccy not in ("ETH", "BTC") or snapshot["interval"] != "5m":
        raise ValueError("unsupported replay universe/interval")
    times = [number(c["timestamp"]) for c in snapshot["candles"]]
    if any(t + 300 > now for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("future/duplicate/out-of-order native candle")
    chain = [q for q in snapshot["options"] if q["quoted"] and q["delta"] is not None
             and 0 <= now - number(q["timestamp"]) <= 5 and q["expiry"] > now
             and all(v is not None for v in q["fees"].values())]
    # Nearest-strike call/put IVs, not tail averages or model-mark fill proxies.
    ivs = []
    spot = number(snapshot["perp"]["index"])
    for kind in ("call", "put"):
        candidates = [q for q in chain if q["kind"] == kind and q["pricing"].get("iv") is not None
                      and q["pricing"]["iv"] > 0]
        if candidates:
            ivs.append(min(candidates, key=lambda q: (abs(q["strike"] / spot - 1), q["expiry"]))["pricing"]["iv"])
    features = dict(snapshot["features"])
    features.update(ccy=ccy, price=spot, reconciled=True, daily_pnl_pct=0, peak_dd=0,
                    valid=bool(features.get("valid") and snapshot["perp"]["fresh"]
                               and 0 <= now - snapshot["perp"]["timestamp"] <= 5))
    if ivs and features.get("forecast_sigma") is not None:
        features["option_iv_edge"] = number(features["forecast_sigma"]) - sum(ivs) / len(ivs)
    else:
        features.pop("option_iv_edge", None)
    return {"time": now, "source": "derive_legacy_public_l1", "ccy": ccy,
            "spot": spot, "chain": chain, "signal_snapshot": features,
            "market_id": snapshot["id"], "source_ids": snapshot["source_ids"],
            "account_assumption": "paper account only; not exchange reconciliation",
            "iv_edge_status": "uncalibrated native forecast minus nearest-strike observed IV"}


def replay(snapshots, raw):
    records = verify_raw(raw)
    if not snapshots or len({s["ccy"] for s in snapshots}) != 1:
        raise ValueError("nonempty single-underlying replay required")
    engine = PaperOptions()
    used, last = set(), None
    for snapshot in snapshots:
        now = number(snapshot["received_at"])
        if last is not None and now <= last:
            raise ValueError("strictly increasing capture times required")
        ids = snapshot["source_ids"]
        if not ids or len(ids) != len(set(ids)) or used.intersection(ids):
            raise ValueError("missing/duplicate/reused source observations")
        for source in ids:
            if source not in records or records[source]["received_at"] > now:
                raise ValueError("missing/future source observation")
        engine.step(paper_row(snapshot))
        engine.events.append({"time": now, "type": "native_context", "market_id": snapshot["id"],
                              "source_ids": ids, "valid": snapshot["features"].get("valid", False)})
        used.update(ids)
        last = now
    return engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    content, raw_content = args.input.read_bytes(), args.raw.read_bytes()
    engine = replay([json.loads(s) for s in content.decode().splitlines() if s.strip()],
                    [json.loads(s) for s in raw_content.decode().splitlines() if s.strip()])
    summary = write_results(engine, args.output, hashlib.sha256(content).hexdigest())
    summary.update(raw_sha256=hashlib.sha256(raw_content).hexdigest(),
                   strategy_status="shadow native input only; baseline live entry policy unchanged")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
