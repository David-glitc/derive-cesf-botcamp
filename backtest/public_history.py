"""Free public history, checked archives, and explicit coverage. No credentials."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import hashlib
import io
import json
from pathlib import Path
import time
import zipfile

import numpy as np
import pandas as pd
import requests

START = int(datetime(2024, 10, 1, tzinfo=timezone.utc).timestamp())
END = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())
ASSETS = ("ETH", "BTC", "SOL")
COLS = ["timestamp", "open", "high", "low", "close", "volume"]


def get(url, *, params=None):
    for attempt in range(4):
        response = requests.get(url, params=params, timeout=45)
        if response.status_code not in (429, 500, 502, 503, 504):
            response.raise_for_status()
            return response
        time.sleep(1 + attempt)
    response.raise_for_status()


def archive(url, cache):
    path = cache / url.rsplit("/", 1)[1]
    checksum = get(url + ".CHECKSUM").text.split()[0]
    content = path.read_bytes() if path.exists() else get(url).content
    actual = hashlib.sha256(content).hexdigest()
    if actual != checksum:
        raise ValueError("public_archive_checksum_mismatch")
    if not path.exists():
        path.write_bytes(content)
    with zipfile.ZipFile(io.BytesIO(content)) as bundle:
        names = bundle.namelist()
        if len(names) != 1 or not names[0].endswith(".csv"):
            raise ValueError("unexpected_public_archive")
        frame = pd.read_csv(bundle.open(names[0]), header=None, dtype=str)
    if frame.shape[1] != 12:
        raise ValueError("unexpected_futures_kline_schema")
    if frame.iloc[0, 0] == "open_time":
        frame = frame.iloc[1:]
    frame = frame.iloc[:, :6].astype(float)
    frame.columns = COLS
    frame.timestamp = (frame.timestamp / 1000).astype("int64")
    return frame, {"url": url, "sha256": actual, "checksum_verified": True, "rows": len(frame)}


def monthly(task):
    asset, month, cache = task
    prefix = "https://data.binance.vision/data/futures/um"
    pair = asset + "USDT"
    url = f"{prefix}/monthly/klines/{pair}/5m/{pair}-5m-{month:%Y-%m}.zip"
    try:
        return asset, [archive(url, cache)]
    except requests.HTTPError as exc:
        if exc.response.status_code not in (403, 404):
            raise
    # The most recent monthly archive may not yet be published. Do not skip it.
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    rows = []
    day = month
    while day < next_month:
        url = f"{prefix}/daily/klines/{pair}/5m/{pair}-5m-{day:%Y-%m-%d}.zip"
        rows.append(archive(url, cache))
        day += timedelta(days=1)
    return asset, rows


def coverage(frame, start, end, step):
    times = frame.timestamp.to_numpy(dtype=np.int64)
    if len(times) != len(set(times)) or (len(times) > 1 and np.any(np.diff(times) <= 0)):
        raise ValueError("duplicate_or_unordered_public_history")
    expected = np.arange(start, end, step, dtype=np.int64)
    missing = np.setdiff1d(expected, times)
    extra = np.setdiff1d(times, expected)
    return {"rows": len(times), "expected_rows": len(expected), "missing_rows": len(missing),
            "extra_rows": len(extra), "missing_first_20": missing[:20].tolist(),
            "first": int(times[0]) if len(times) else None, "last": int(times[-1]) if len(times) else None}


def dvol(asset, output):
    # Modest bounded chunks avoid silently dropping rows at the API page limit.
    frames, sources = [], []
    for begin in range(START - 3600, END, 20 * 86400):
        finish = min(END - 3600, begin + 20 * 86400 - 3600)
        params = dict(currency=asset, start_timestamp=begin * 1000,
                      end_timestamp=finish * 1000, resolution="3600")
        url = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
        path = output / "raw" / f"{asset}-dvol-{begin}.json"
        payload = path.read_bytes() if path.exists() else get(url, params=params).content
        data = json.loads(payload)
        result = data["result"]
        if result.get("continuation") is not None:
            raise ValueError("dvol_truncated_chunk")
        if not path.exists():
            path.write_bytes(payload)
        frame = pd.DataFrame(result["data"], columns=COLS[:5])
        if len(frame):
            frame.timestamp = (frame.timestamp / 1000).astype("int64")
            frames.append(frame)
        sources.append({"url": url, "params": params, "sha256": hashlib.sha256(payload).hexdigest()})
    frame = pd.concat(frames).sort_values("timestamp").reset_index(drop=True)
    frame = frame[(frame.timestamp >= START - 3600) & (frame.timestamp < END)]
    if not np.isfinite(frame[COLS[:5]]).all().all() or (frame.close <= 0).any():
        raise ValueError("invalid_dvol")
    frame.to_csv(output / f"{asset}-dvol-1h.csv", index=False)
    return {"sources": sources, "coverage": coverage(frame, START - 3600, END, 3600),
            "unit": "annualized IV percent; close available only at timestamp + 3600",
            "limitation": "Deribit index, not Derive contract IV, skew or BBO"}


def rules():
    result = {}
    for asset in ASSETS:
        names = [asset + "-PERP"]
        if asset in ("ETH", "BTC"):
            response = requests.post("https://api.lyra.finance/public/get_instruments",
                json=dict(currency=asset, expired=False, instrument_type="option"), timeout=45)
            response.raise_for_status()
            names.append(response.json()["result"][0]["instrument_name"])
        for name in names:
            response = requests.post("https://api.lyra.finance/public/get_instrument",
                                     json={"instrument_name": name}, timeout=45)
            response.raise_for_status()
            row = response.json()["result"]
            result[asset + "-" + row["instrument_type"]] = row
    return {"observed_at": time.time(), "source": "https://api.lyra.finance/public/get_instrument",
            "interpretation": "current rules applied as fixed sensitivity, NOT historical rules", "instruments": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    cache = out / "raw"
    cache.mkdir(exist_ok=True)
    months = pd.date_range("2024-10-01", "2026-09-01", freq="MS", tz="UTC")
    tasks = [(a, m.to_pydatetime(), cache) for a in ASSETS for m in months]
    pieces = {a: [] for a in ASSETS}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for asset, rows in pool.map(monthly, tasks):
            pieces[asset].extend(rows)
            print(f"downloaded {asset}: {len(pieces[asset])} checked archives", flush=True)
    manifest = {"start": START, "end_exclusive": END, "candles": {}, "iv": {},
                "no_historical_option_quotes": True, "fetched_at": time.time()}
    for asset, rows in pieces.items():
        frame = pd.concat([f for f, _ in rows]).sort_values("timestamp").reset_index(drop=True)
        frame = frame[(frame.timestamp >= START) & (frame.timestamp < END)]
        view = coverage(frame, START, END, 300)
        if view["missing_rows"] or view["extra_rows"]:
            raise ValueError(f"incomplete_5m_history:{asset}:{view}")
        if not np.isfinite(frame).all().all() or (frame.volume < 0).any():
            raise ValueError("invalid_public_candles")
        frame.to_csv(out / f"{asset}-5m.csv", index=False)
        manifest["candles"][asset] = {"coverage": view, "sources": [s for _, s in rows]}
    for asset in ("ETH", "BTC"):
        manifest["iv"][asset] = dvol(asset, out)
        print(f"downloaded {asset} IV: {manifest['iv'][asset]['coverage']}", flush=True)
    (out / "venue-rules.json").write_text(json.dumps(rules(), indent=2) + "\n")
    manifest["normalized_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in out.glob("*.csv")}
    manifest["normalized_sha256"]["venue-rules.json"] = hashlib.sha256((out / "venue-rules.json").read_bytes()).hexdigest()
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(out), "coverage": {a: v["coverage"] for a, v in manifest["candles"].items()}}))


if __name__ == "__main__":
    main()
