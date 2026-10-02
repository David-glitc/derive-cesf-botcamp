"""Explicit legacy schemas: slim bulk tickers, long single tickers, native bars."""
import hashlib
import json
import math


def number(value, *, optional=False):
    if value is None and optional:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite market value")
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def public_record(method, data, sent, received, params=None):
    if not 0 <= sent <= received:
        raise ValueError("invalid observation times")
    record = {"schema": 1, "network": "mainnet", "api_generation": "legacy_v2",
              "method": method, "sent_at": sent, "received_at": received, "data": data}
    if params is not None:
        record["params"] = params
    return {**record, "id": digest(record)}


def normalize_perp(raw, ccy, now):
    if raw.get("instrument_name") != f"{ccy}-PERP" or raw.get("instrument_type") != "perp":
        raise ValueError("unexpected perp instrument")
    result = {"instrument": raw["instrument_name"],
              "timestamp": number(raw["timestamp"]) / 1000,
              "index": number(raw["index_price"]), "mark": number(raw["mark_price"]),
              "bid": number(raw["best_bid_price"]), "ask": number(raw["best_ask_price"]),
              "bid_size": number(raw["best_bid_amount"]), "ask_size": number(raw["best_ask_amount"]),
              "funding_rate": number((raw.get("perp_details") or {}).get("funding_rate"), optional=True)}
    if result["index"] <= 0 or result["mark"] <= 0:
        raise ValueError("invalid native price")
    if min(result[k] for k in ("bid", "ask", "bid_size", "ask_size", "timestamp")) < 0:
        raise ValueError("negative perp quote")
    result["fresh"] = 0 <= now - result["timestamp"] <= 5
    result["quoted"] = (result["fresh"] and 0 < result["bid"] < result["ask"]
                        and min(result["bid_size"], result["ask_size"]) > 0)
    result["basis"] = result["mark"] / result["index"] - 1
    result["funding_units"] = "venue hourly rate; not settled account funding"
    return result


def normalize_option(definition, ticker, ccy, now):
    d, p = definition, ticker.get("option_pricing") or {}
    details = d["option_details"]
    name = d["instrument_name"]
    if d.get("instrument_type") != "option" or not name.startswith(ccy + "-"):
        raise ValueError("unexpected option instrument")
    if details["option_type"] not in ("C", "P"):
        raise ValueError("unknown option kind")
    quote = {"instrument": name, "underlying": ccy,
             "kind": "call" if details["option_type"] == "C" else "put",
             "strike": number(details["strike"]), "expiry": number(details["expiry"]),
             "multiplier": 1, "step": number(d["amount_step"]),
             "min_amount": number(d["minimum_amount"]), "tick": number(d["tick_size"]),
             "timestamp": number(ticker["t"]) / 1000,
             "bids": [[number(ticker["b"]), number(ticker["B"])]],
             "asks": [[number(ticker["a"]), number(ticker["A"])]],
             "delta": number(p.get("d"), optional=True),
             "pricing": {key: number(p.get(short), optional=True) for key, short in
                         (("iv", "i"), ("bid_iv", "bi"), ("ask_iv", "ai"), ("delta", "d"),
                          ("gamma", "g"), ("theta", "t"), ("vega", "v"),
                          ("forward", "f"), ("discount", "df"), ("mark", "m"))},
             "oi": number((ticker.get("stats") or {}).get("oi"), optional=True),
             "fees": {"rate": number(d["taker_fee_rate"]), "base": number(d["base_fee"]),
                      "premium_cap": number(d.get("mark_price_fee_rate_cap"), optional=True)}}
    if min(quote[k] for k in ("strike", "expiry", "step", "min_amount", "tick")) <= 0:
        raise ValueError("invalid option metadata")
    if any(v < 0 for side in (quote["bids"], quote["asks"]) for level in side for v in level):
        raise ValueError("negative option quote")
    if quote["oi"] is not None and quote["oi"] < 0:
        raise ValueError("negative OI")
    if any(v is not None and v < 0 for v in quote["fees"].values()):
        raise ValueError("negative fee")
    quote["fresh"] = 0 <= now - quote["timestamp"] <= 5
    quote["active"] = bool(d["is_active"] and number(d["scheduled_activation"]) <= now
                           < number(d["scheduled_deactivation"]) and quote["expiry"] > now)
    bid, ask = quote["bids"][0], quote["asks"][0]
    quote["quoted"] = bool(quote["active"] and quote["fresh"] and 0 < bid[0] < ask[0]
                           and min(bid[1], ask[1]) > 0 and (ask[0] - bid[0]) / ask[0] <= .15)
    quote["amount_units"] = "underlying-unit normalization; multiplier 1; not private margin proof"
    return quote


def native_candles(index_rows, trade_rows, now, period=300):
    """Index OHLC + separate venue perp traded volume; never invent index volume."""
    if period != 300:
        raise ValueError("first capture milestone supports native 5m only")
    volume = {}
    for row in trade_rows:
        timestamp = number(row["timestamp_bucket"])
        if timestamp < 0 or timestamp % period:
            raise ValueError("unaligned trade candle")
        if timestamp in volume:
            raise ValueError("duplicate trade candle")
        amount = number(row["volume_contracts"])
        if amount < 0:
            raise ValueError("negative volume")
        volume[timestamp] = amount
    result, seen = [], set()
    for raw in index_rows:
        t = number(raw["timestamp_bucket"])
        if t in seen:
            raise ValueError("duplicate index candle")
        seen.add(t)
        if t < 0 or t % period:
            raise ValueError("unaligned index candle")
        if t + period > now:
            continue
        row = {"timestamp": t, **{key: number(raw[f"{key}_price"]) for key in ("open", "high", "low", "close")},
               "volume": volume.get(t)}
        if min(row[k] for k in ("open", "high", "low", "close")) <= 0:
            raise ValueError("invalid index OHLC")
        if not row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]:
            raise ValueError("inconsistent index OHLC")
        result.append(row)
    result.sort(key=lambda r: r["timestamp"])
    return result


def validate_snapshot(snapshot, now, ccy):
    if not isinstance(snapshot, dict):
        raise ValueError("market context must be an object")
    if (snapshot.get("schema") != 1 or snapshot.get("kind") != "derive_market_context"
            or snapshot.get("network") != "mainnet" or snapshot.get("api_generation") != "legacy_v2"
            or snapshot.get("ccy") != ccy):
        raise ValueError("market context provenance mismatch")
    if digest({k: v for k, v in snapshot.items() if k != "id"}) != snapshot.get("id"):
        raise ValueError("market context checksum mismatch")
    age = number(now) - number(snapshot["received_at"])
    if not 0 <= age <= 30:
        raise ValueError("stale/future market context")
    return age
