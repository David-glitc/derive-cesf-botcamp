"""Bounded public mainnet REST capture. No credentials, redirects or private calls."""
import time
import math
import asyncio
import inspect
import json

import pandas as pd
import requests

from agents.mainnet import MAINNET_HTTP_URL, MAINNET_WS_URL
from src.data.records import (digest, native_candles, normalize_option, normalize_perp,
                              number, public_record)
from src.options.pricing import option_diagnostic
from src.signal.flyby import feature_frame
from src.signal.microstructure import book_metrics, trade_metrics
from src.signal.options_surface import surface
from src.options.ranking import rank_spreads


class DerivePublic:
    METHODS = {"public/get_all_instruments", "public/get_tickers", "public/get_ticker",
               "public/get_index_chart_data", "public/get_tradingview_chart_data", "public/get_trade_history"}
    SOURCES = METHODS | {"ws/orderbook"}

    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False  # Never inherit .netrc or authenticated proxy settings.
        self.records = []

    def call(self, method, params):
        if method not in self.METHODS:
            raise ValueError("public method not allowlisted")
        sent = time.time()
        r = self.session.post(MAINNET_HTTP_URL + "/" + method, json=params, timeout=8, allow_redirects=False)
        if r.status_code != 200:
            raise ValueError(f"public HTTP status:{r.status_code}")
        body = r.json()
        if body.get("error"):
            raise ValueError(f"public RPC error:{body['error'].get('code')}")
        data = body["result"]
        self.records.append(public_record(method, data, sent, time.time(), params))
        return data

    async def _book(self, ccy):
        import websockets
        channel = f"orderbook.{ccy}-PERP.10.10"
        sent = time.time()
        kwargs = {"open_timeout": 8, "close_timeout": 2, "max_size": 300000}
        if "proxy" in inspect.signature(websockets.connect).parameters:
            kwargs["proxy"] = None
        async with asyncio.timeout(12):
            async with websockets.connect(MAINNET_WS_URL, **kwargs) as ws:
                await ws.send(json.dumps({"id": 1, "method": "subscribe", "params": {"channels": [channel]}}))
                for _ in range(12):
                    msg = json.loads(await ws.recv())
                    params = msg.get("params") or {}
                    data = params.get("data")
                    if data and params.get("channel") == channel and data.get("instrument_name") == f"{ccy}-PERP":
                        self.records.append(public_record("ws/orderbook", data, sent, time.time(), {"channel": channel}))
                        return data
        raise ValueError("public book snapshot unavailable")

    def definitions(self, ccy):
        rows = []
        for page in range(1, 6):
            result = self.call("public/get_all_instruments", {"currency": ccy, "instrument_type": "option",
                               "expired": False, "page": page, "page_size": 1000})
            rows.extend(result["instruments"])
            if page >= result["pagination"]["num_pages"]:
                names = [row["instrument_name"] for row in rows]
                if len(names) != len(set(names)):
                    raise ValueError("duplicate instrument definition")
                return rows
        raise ValueError("instrument pagination exceeds capture bound")

    def snapshot(self, ccy, quant=False, previous=None):
        if ccy not in ("ETH", "BTC"):
            raise ValueError("first milestone uses ETH/BTC mainnet only")
        first = len(self.records)
        start = time.time()
        definitions = self.definitions(ccy)
        end = int(start // 300) * 300
        params = {"start_timestamp": end - 180 * 300, "end_timestamp": end, "period": 300}
        index = self.call("public/get_index_chart_data", {**params, "currency": ccy})
        trades = self.call("public/get_tradingview_chart_data", {**params, "instrument_name": f"{ccy}-PERP"})
        selected = [d for d in definitions if d["is_active"]
                    and number(d["scheduled_activation"]) <= start < number(d["scheduled_deactivation"])
                    and 2 * 86400 <= number(d["option_details"]["expiry"]) - start <= 5 * 86400]
        tickers = {}
        expiries = sorted({int(d["instrument_name"].split("-")[1]) for d in selected})
        if len(expiries) > 4:
            raise ValueError("expiry capture exceeds bound")
        extras = {}
        if quant:
            for name, request in (("trades", lambda: self.call("public/get_trade_history", {"instrument_name": f"{ccy}-PERP", "count": 100})),
                                  ("book", lambda: asyncio.run(self._book(ccy)))):
                try:
                    extras[name] = request()
                except Exception as exc:
                    extras[name] = {"unavailable": type(exc).__name__}
        for expiry in expiries:
            result = self.call("public/get_tickers", {"currency": ccy, "instrument_type": "option", "expiry_date": expiry})
            if tickers.keys() & result["tickers"].keys():
                raise ValueError("duplicate option ticker")
            tickers.update(result["tickers"])
        perp = self.call("public/get_ticker", {"instrument_name": f"{ccy}-PERP"})
        received = time.time()
        candles = native_candles(index, trades, start)
        features = {"valid": False}
        faults = []
        if len(candles) >= 150:
            frame = pd.DataFrame(candles)
            if not frame.timestamp.diff().dropna().eq(300).all():
                faults.append("native_candle_gap")
            else:
                row = feature_frame(frame, "5m").iloc[-1].to_dict()
                features = {key: (bool(v) if key == "valid" else number(v, optional=True))
                            for key, v in row.items() if key == "valid" or (pd.notna(v) and math.isfinite(float(v)))}
                age = received - (candles[-1]["timestamp"] + 300)
                features["valid"] = bool(features["valid"]) and 0 <= age <= 360
                features["stale_secs"] = max(0, age - 300)
        else:
            faults.append("native_candle_warmup")
        if any(c["volume"] is None for c in candles):
            faults.append("native_trade_volume_missing")
            features["valid"] = False
        native = normalize_perp(perp, ccy, received)
        if not native["fresh"]:
            faults.append("stale_native_index")
            features["valid"] = False
        if candles and abs(candles[-1]["close"] / native["index"] - 1) > .03:
            faults.append("native_index_basis")
            features["valid"] = False
        options = []
        for d in selected:
            name = d["instrument_name"]
            if name not in tickers:
                continue
            try:
                options.append(normalize_option(d, tickers[name], ccy, received))
            except (KeyError, ValueError, TypeError):
                faults.append("invalid_option_record")
        diagnostics = [option_diagnostic(q, received, features.get("forecast_sigma")) for q in options]
        record = {"schema": 1, "kind": "derive_market_context", "network": "mainnet",
                  "api_generation": "legacy_v2", "ccy": ccy, "received_at": received,
                  "source_ids": [r["id"] for r in self.records[first:]], "interval": "5m",
                  "perp": native, "candles": candles, "features": features,
                  "options": options, "option_diagnostics": diagnostics,
                  "eligible_definitions": len(selected), "faults": faults,
                  "volume_source": "Derive perpetual trade-chart volume_contracts; not index volume",
                  "limitations": ["HTTP L1 samples, not L2/queue or matching proof",
                                  "volatility forecasts and Black-76 diagnostics are uncalibrated",
                                  "no private margin/fill verification; no orders"]}
        if quant:
            analytics = {}
            for name, calculation in (("book", lambda: book_metrics(extras["book"], f"{ccy}-PERP", received)),
                 ("trades", lambda: trade_metrics(extras["trades"]["trades"], f"{ccy}-PERP", received, 5 if ccy == "ETH" else 100)),
                 ("surface", lambda: surface(options, received, native["index"], previous)),
                 ("spreads", lambda: rank_spreads(options, received, native["index"]))):
                try:
                    analytics[name] = calculation()
                except (ValueError, TypeError, KeyError, IndexError):
                    analytics[name] = {"status": "unavailable", "reason": "invalid_or_missing_public_inputs"}
            record["analytics"] = analytics
        return {**record, "id": digest(record)}
