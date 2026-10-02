"""Bounded public-v3 L1 option snapshots and causal Binance proxy signals.

Local paper harness only. No auth, private methods, orders or network fallback.
This is forward observation, not reconstructed historical option books.
"""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import time

import pandas as pd
import requests

from src.options.spread_builder import OptionQuote
from src.signal.flyby import feature_frame


class PublicV3:
    METHODS = {"public/get_all_instruments", "public/get_tickers", "public/get_ticker"}

    def __init__(self, network="mainnet"):
        if network not in ("mainnet", "testnet"):
            raise ValueError("invalid network")
        self.base = "https://api.derive.xyz/v3/" if network == "mainnet" else "https://testnet.api.derive.xyz/v3/"
        self.session = requests.Session()

    def call(self, method, params):
        if method not in self.METHODS:
            raise ValueError("public method not allowlisted")
        result = self.session.post(self.base + method, json=params, timeout=8)
        result.raise_for_status()
        body = result.json()
        if body.get("error"):
            raise ValueError(f"public RPC error: {body['error'].get('code')}")
        return body["result"]

    def definitions(self, ccy):
        rows = []
        for page in range(1, 6):
            result = self.call("public/get_all_instruments", {"currency": ccy, "instrument_type": "option",
                               "expired": False, "page": page, "page_size": 1000})
            rows.extend(result["instruments"])
            if page >= result["pagination"]["num_pages"]:
                return rows
        raise ValueError("instrument pagination exceeds bounded capture")

    def snapshot(self, ccy, definitions):
        now = time.time()
        eligible = [d for d in definitions if d["is_active"]
                    and d["scheduled_activation"] <= now < d["scheduled_deactivation"]
                    and 2 * 86400 <= d["option_details"]["expiry"] - now <= 5 * 86400]
        by_name = {d["instrument_name"]: d for d in eligible}
        chain, marks, faults = [], [], []
        perp = self.call("public/get_ticker", {"instrument_name": f"{ccy}-PERP"})
        spot = float(perp["I"])
        if not math.isfinite(spot) or spot <= 0:
            raise ValueError("invalid Derive index")
        for expiry in sorted({name.split("-")[1] for name in by_name}):
            tickers = self.call("public/get_tickers", {"instrument_type": "option", "currency": ccy,
                                                       "expiry_date": int(expiry)})["tickers"]
            for name, ticker in tickers.items():
                if name not in by_name:
                    continue
                d = by_name[name]
                p = ticker.get("option_pricing")
                if not p:
                    continue
                try:
                    bid, ask, bq, aq = [float(ticker[key]) for key in ("b", "a", "B", "A")]
                    if not all(math.isfinite(v) and v > 0 for v in (bid, ask, bq, aq)) or bid >= ask:
                        continue
                    quote = OptionQuote(name, ccy, "call" if d["option_details"]["option_type"] == "C" else "put",
                                        float(d["option_details"]["strike"]), d["option_details"]["expiry"],
                                        1, float(d["amount_step"]), float(d["minimum_amount"]), ticker["t"] / 1000,
                                        ((bid, bq),), ((ask, aq),), float(p["d"]), float(d["tick_size"]))
                    cap = d["mark_price_fee_rate_cap"]
                    if cap is None:
                        continue
                    chain.append({**asdict(quote), "fees": {"rate": float(d["taker_fee_rate"]),
                                 "base": float(d["base_fee"]), "premium_cap": float(cap)},
                                 "raw_option_pricing": p, "raw_stats": ticker["stats"]})
                    iv = float(p["i"])
                    if math.isfinite(iv) and iv > 0:
                        marks.append((abs(float(p["d"])) - .5, iv, quote.expiry))
                except (KeyError, ValueError, TypeError):
                    faults.append("invalid_chain_record")
        signal = {"valid": False}
        try:
            response = self.session.get("https://fapi.binance.com/fapi/v1/klines",
                                        params={"symbol": f"{ccy}USDT", "interval": "5m", "limit": 180}, timeout=8)
            response.raise_for_status()
            candles = response.json()
            closed = [r for r in candles if int(r[0]) / 1000 + 300 <= now]
            df = pd.DataFrame([[r[0] / 1000, *map(float, r[1:6])] for r in closed],
                              columns=["timestamp", "open", "high", "low", "close", "volume"])
            if len(df) < 150 or not df.timestamp.diff().dropna().eq(300).all():
                raise ValueError("missing/gapped proxy candles")
            age = now - (df.timestamp.iloc[-1] + 300)
            signal = feature_frame(df, "5m").iloc[-1].to_dict()
            signal.update(valid=bool(signal["valid"]) and 0 <= age <= 360 and abs(signal["price"] / spot - 1) <= .03,
                          stale_secs=max(0, age - 300), ccy=ccy, daily_pnl_pct=0, peak_dd=0, reconciled=True)
            if marks:
                # Diagnostic forecast statistic, not a calibrated option alpha.
                iv = min(marks, key=lambda v: (abs(v[2] - now - 3 * 86400), abs(v[0])))[1]
                signal["option_iv_edge"] = signal["forecast_sigma"] - iv
            signal = {k: (v if not isinstance(v, float) or math.isfinite(v) else None) for k, v in signal.items()}
        except (ValueError, KeyError, TypeError, requests.RequestException):
            faults.append("proxy_signal_unavailable")
            signal = {"valid": False}
        received = time.time()
        if not 0 <= received - perp["t"] / 1000 <= 5:
            faults.append("stale_index")
            signal["valid"] = False
        return {"time": received, "source": "derive_v3_public_l1", "network": self.base,
                "spot": spot, "index_timestamp": perp["t"] / 1000, "ccy": ccy, "chain": chain,
                "signal_snapshot": signal, "eligible_definitions": len(eligible), "faults": faults,
                "signal_source": "closed Binance USD-M 5m proxy", "book_source": "Derive public ticker L1",
                "iv_edge_definition": "annualized HAR-like/EWMA sigma minus near-ATM option mark IV; uncalibrated",
                "amount_unit": "underlying units; multiplier 1; not private margin proof"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--currency", choices=("ETH", "BTC"), default="ETH")
    parser.add_argument("--network", choices=("mainnet", "testnet"), default="mainnet")
    parser.add_argument("--samples", type=int, choices=range(1, 7), default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be a new immutable capture file")
    client = PublicV3(args.network)
    definitions = client.definitions(args.currency)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        for _ in range(args.samples):
            row = client.snapshot(args.currency, definitions)
            stream.write(json.dumps(row, allow_nan=False) + "\n")
            stream.flush()
            print(json.dumps({"time": row["time"], "eligible": row["eligible_definitions"],
                              "quoted": len(row["chain"]), "valid_signal": row["signal_snapshot"].get("valid"),
                              "faults": row["faults"]}), flush=True)


if __name__ == "__main__":
    main()
