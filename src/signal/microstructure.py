"""Observed book/tape diagnostics. No inferred complete tape or aggressor flow."""
import math

from src.data.records import number
from src.risk.position_sizing import depth_quote


def book_metrics(raw, instrument, now, amount=.01):
    if raw["instrument_name"] != instrument:
        raise ValueError("book instrument mismatch")
    timestamp = number(raw["timestamp"]) / 1000
    publish_id = number(raw["publish_id"])
    if publish_id < 0 or publish_id != int(publish_id):
        raise ValueError("invalid book publish id")
    sides = {}
    for key in ("bids", "asks"):
        levels = [[number(p), number(q)] for p, q in raw[key]]
        if not levels or len(levels) > 100 or any(min(x) <= 0 for x in levels):
            raise ValueError("invalid book levels")
        prices = [x[0] for x in levels]
        if len(set(prices)) != len(prices) or prices != sorted(prices, reverse=key == "bids"):
            raise ValueError("unsorted/duplicate book levels")
        sides[key] = levels
    bid, ask = sides["bids"][0][0], sides["asks"][0][0]
    if bid >= ask:
        raise ValueError("crossed book")
    fresh = 0 <= now - timestamp <= 5
    mid = (bid + ask) / 2
    bq, aq = (sum(x[1] for x in sides[k]) for k in ("bids", "asks"))
    buy, sell = depth_quote(sides["asks"], amount), depth_quote(sides["bids"], amount)
    return {"status": "available" if fresh else "stale", "timestamp": timestamp,
            "publish_id": int(publish_id), "spread_bps": (ask - bid) / mid * 10000,
            "bid_depth": bq, "ask_depth": aq, "imbalance": (bq - aq) / (bq + aq),
            "probe_amount": amount, "buy_vwap": buy.vwap if buy and fresh else None,
            "sell_vwap": sell.vwap if sell and fresh else None,
            "bids": sides["bids"], "asks": sides["asks"],
            "coverage": "bounded public L2 snapshot; not matching/queue proof"}


def trade_metrics(raw, instrument, now, bin_width, window=900):
    bin_width, window = number(bin_width), number(window)
    if min(bin_width, window) <= 0:
        raise ValueError("invalid trade window/bin")
    seen, duplicates, future = {}, 0, 0
    for trade in raw:
        if trade["instrument_name"] != instrument:
            raise ValueError("trade instrument mismatch")
        event = (number(trade["timestamp"]) / 1000, number(trade["trade_price"]), number(trade["trade_amount"]))
        if min(event) <= 0 or not trade["trade_id"]:
            raise ValueError("invalid trade")
        identity = str(trade["trade_id"])
        if identity in seen:
            if seen[identity] != event:
                raise ValueError("conflicting duplicate trade")
            duplicates += 1
            continue
        seen[identity] = event
    prints, bins = [], {}
    for t, price, amount in seen.values():
        if t > now:
            future += 1
            continue
        if now - t > window:
            continue
        prints.append((t, price, amount))
        bucket = math.floor(price / bin_width)
        bins[bucket] = bins.get(bucket, 0) + amount
    volume = sum(p[2] for p in prints)
    return {"status": "available" if prints else "unavailable", "prints": len(prints),
            "counterparty_duplicates": duplicates, "future_excluded": future,
            "sample_volume": volume, "vwap": sum(p * q for _, p, q in prints) / volume if volume else None,
            "poc": (max(bins, key=lambda b: (bins[b], -b)) + .5) * bin_width if bins else None,
            "bin_width": bin_width, "window_seconds": window, "cvd": None,
            "coverage": "deduplicated bounded recent page; not complete rolling tape",
            "cvd_reason": "aggressor convention and complete tape not verified"}
