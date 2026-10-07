from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from backtest.replay_derive import paper_row, replay, verify_raw
from src.data.derive_public import DerivePublic
from src.data.records import (digest, native_candles, normalize_option, normalize_perp,
                              public_record, validate_snapshot)
from src.options.pricing import black_price, option_diagnostic
from tests.test_flyby_policy import candles

NOW = 1800000000.0


def definition():
    return {"instrument_name": "ETH-20270118-3000-C", "instrument_type": "option",
            "option_details": {"option_type": "C", "strike": "3000", "expiry": NOW + 3 * 86400},
            "amount_step": ".01", "minimum_amount": ".01", "tick_size": ".1",
            "taker_fee_rate": ".0003", "base_fee": ".5", "mark_price_fee_rate_cap": ".125",
            "is_active": True, "scheduled_activation": NOW - 100, "scheduled_deactivation": NOW + 4 * 86400}


def ticker():
    return {"t": NOW * 1000, "b": 60, "B": 10, "a": 62, "A": 10,
            "stats": {"oi": 20}, "option_pricing": {"d": .5, "g": .001, "v": 100,
            "t": -2, "i": .5, "bi": .49, "ai": .51, "f": 3020, "m": 61, "df": .999}}


def perp():
    return {"instrument_name": "ETH-PERP", "instrument_type": "perp", "t": NOW * 1000,
            "I": 3000, "M": 3001, "b": 2999, "a": 3001, "B": 10, "A": 10, "f": .00001}


def seal(body):
    return {**body, "id": digest({k: v for k, v in body.items() if k != "id"})}


def snapshot():
    source = public_record("public/get_ticker", perp(), NOW - 1, NOW)
    body = {"schema": 1, "kind": "derive_market_context", "network": "mainnet",
            "api_generation": "v3", "ccy": "ETH", "received_at": NOW, "source_ids": [source["id"]],
            "perp": normalize_perp(perp(), "ETH", NOW), "interval": "5m", "candles": [],
            "options": [normalize_option(definition(), ticker(), "ETH", NOW)],
            "features": {"valid": False, "forecast_sigma": .6}, "faults": []}
    return seal(body), source


def test_explicit_legacy_option_pricing_and_book_mapping():
    quote = normalize_option(definition(), ticker(), "ETH", NOW)
    assert quote["quoted"] and quote["fresh"] and quote["active"]
    assert quote["pricing"]["forward"] == 3020 and quote["pricing"]["iv"] == .5
    assert quote["pricing"]["theta"] == -2 and quote["oi"] == 20
    assert quote["bids"] == [[60, 10]] and quote["fees"]["premium_cap"] == .125
    assert quote["multiplier"] == 1


@pytest.mark.parametrize("fault", ["stale", "future", "zero", "crossed", "wide", "inactive", "deactivated"])
def test_unqualified_option_books_not_execution(fault):
    d, t = definition(), ticker()
    if fault == "stale": t["t"] -= 6000
    if fault == "future": t["t"] += 1000
    if fault == "zero": t["a"] = 0
    if fault == "crossed": t["b"] = 70
    if fault == "wide": t["b"] = 1
    if fault == "inactive": d["is_active"] = False
    if fault == "deactivated": d["scheduled_deactivation"] = NOW
    assert not normalize_option(d, t, "ETH", NOW)["quoted"]


@pytest.mark.parametrize("field,value", [("b", -1), ("B", -1), ("a", float("nan")), ("t", float("inf"))])
def test_invalid_option_numeric_data_rejected(field, value):
    t = ticker()
    t[field] = value
    with pytest.raises(ValueError): normalize_option(definition(), t, "ETH", NOW)


def test_missing_iv_oi_are_unknown_not_zero():
    t = ticker()
    t.pop("stats")
    t["option_pricing"].pop("i")
    q = normalize_option(definition(), t, "ETH", NOW)
    assert q["oi"] is None and q["pricing"]["iv"] is None
    assert option_diagnostic(q, NOW)["reason"] == "missing_or_invalid_pricing_inputs"


@pytest.mark.parametrize("field", ["I", "b", "A", "t"])
def test_invalid_perp_numbers(field):
    p = perp()
    p[field] = -1
    with pytest.raises(ValueError): normalize_perp(p, "ETH", NOW)


def test_perp_schema_and_future_freshness():
    p = perp()
    assert normalize_perp(p, "ETH", NOW)["basis"] == pytest.approx(1 / 3000)
    p["t"] += 1000
    assert not normalize_perp(p, "ETH", NOW)["fresh"]
    with pytest.raises(ValueError): normalize_perp(p, "BTC", NOW)


def index_bar(t):
    return {"timestamp_bucket": t, "open_price": 10, "high_price": 12,
            "low_price": 9, "close_price": 11}


def test_native_closed_ohlc_uses_distinct_perp_volume():
    rows = native_candles([index_bar(900), index_bar(300), index_bar(600)],
                         [{"timestamp_bucket": 300, "volume_contracts": 7}], 950)
    assert [r["timestamp"] for r in rows] == [300, 600]
    assert rows[0]["close"] == 11 and rows[0]["volume"] == 7
    assert rows[1]["volume"] is None  # No invented index volume.


@pytest.mark.parametrize("fault", ["duplicate_index", "duplicate_trade", "alignment", "trade_alignment", "negative", "ohlc", "period"])
def test_native_bar_integrity(fault):
    index, trades, period = [index_bar(300)], [{"timestamp_bucket": 300, "volume_contracts": 7}], 300
    if fault == "duplicate_index": index += deepcopy(index)
    if fault == "duplicate_trade": trades += deepcopy(trades)
    if fault == "alignment": index[0]["timestamp_bucket"] += 1
    if fault == "trade_alignment": trades[0]["timestamp_bucket"] += 1
    if fault == "negative": trades[0]["volume_contracts"] = -1
    if fault == "ohlc": index[0]["high_price"] = 8
    if fault == "period": period = "5m"
    with pytest.raises(ValueError): native_candles(index, trades, 1000, period)


def test_black_forward_discount_parity_and_actual_quote_cost():
    years = 3 / 365
    call = black_price(3020, 3000, years, .999, .5, "call")
    put = black_price(3020, 3000, years, .999, .5, "put")
    assert call - put == pytest.approx(.999 * 20)
    q = normalize_option(definition(), ticker(), "ETH", NOW)
    d = option_diagnostic(q, NOW, .6)
    assert d["mark_model"] == pytest.approx(call)
    assert d["model_minus_ask"] == pytest.approx(d["forecast_model"] - 62)
    assert len(d["scenario_prices"]) == 4
    q["quoted"] = False
    assert option_diagnostic(q, NOW, .6)["model_minus_ask"] is None


@pytest.mark.parametrize("args", [(0, 3000, .01, 1, .5, "call"), (3000, 3000, -.01, 1, .5, "call"),
                                  (3000, 3000, .01, 1, float("nan"), "call"), (3000, 3000, .01, 1, .5, "invalid")])
def test_bad_black_inputs(args):
    with pytest.raises(ValueError): black_price(*args)


@pytest.mark.parametrize("fault", ["checksum", "network", "api", "ccy", "stale", "future"])
def test_snapshot_provenance(fault):
    s, _ = snapshot()
    now = NOW
    if fault == "checksum": s["features"]["forecast_sigma"] = .8
    if fault == "network": s = seal({**s, "network": "testnet"})
    if fault == "api": s = seal({**s, "api_generation": "legacy_v2"})
    if fault == "ccy": s = seal({**s, "ccy": "BTC"})
    if fault == "stale": now += 31
    if fault == "future": now -= 1
    with pytest.raises(ValueError): validate_snapshot(s, now, "ETH")


def test_public_client_no_private_methods_credentials_redirects():
    client = DerivePublic()
    assert client.session.auth is None and client.session.trust_env is False
    calls = []
    def post(url, **kw):
        calls.append((url, kw))
        return SimpleNamespace(status_code=200, json=lambda: {"result": {"public": True}})
    client.session.post = post
    with pytest.raises(ValueError): client.call("private/order", {})
    assert not calls
    client.call("public/get_ticker", {"instrument_name": "ETH-PERP"})
    assert calls[0][0] == "https://api.derive.xyz/v3/public/get_ticker"
    assert calls[0][1]["allow_redirects"] is False and calls[0][1]["timeout"] == 8
    assert len(client.records) == 1


@pytest.mark.parametrize("status,body", [(302, {}), (500, {}), (200, {"error": {"code": 1}})])
def test_public_error_response_not_a_snapshot(status, body):
    client = DerivePublic()
    client.session.post = lambda *a, **kw: SimpleNamespace(status_code=status, json=lambda: body)
    with pytest.raises(ValueError): client.call("public/get_ticker", {})
    assert not client.records


def test_native_replay_determinism_and_no_manufactured_entries():
    s, raw = snapshot()
    engine = replay([s], [raw])
    again = replay([s], [raw])
    assert engine.curve == again.curve and engine.events == again.events
    assert engine.cash == 800 and engine.position is None
    assert engine.summary()["data_sources"] == ["derive_legacy_public_l1"]
    assert engine.events[-1]["market_id"] == s["id"]
    assert engine.summary()["live"]["orders_submitted"] == 0
    assert paper_row(s)["signal_snapshot"]["option_iv_edge"] == pytest.approx(.1)


@pytest.mark.parametrize("fault", ["raw_hash", "private", "missing", "future_raw", "duplicate", "future_bar", "future_quote", "mixed"])
def test_replay_integrity_faults(fault):
    s, raw = snapshot()
    snapshots, raws = [s], [raw]
    if fault == "raw_hash": raw["data"]["index_price"] = 1
    if fault == "private": raws = [seal({**raw, "method": "private/order"})]
    if fault == "missing": raws = []
    if fault == "future_raw":
        raw = public_record("public/get_ticker", perp(), NOW, NOW + 1)
        raws, snapshots = [raw], [seal({**s, "source_ids": [raw["id"]]})]
    if fault == "duplicate": snapshots += deepcopy(snapshots)
    if fault == "future_bar": snapshots = [seal({**s, "candles": [{"timestamp": NOW}]})]
    if fault == "future_quote":
        s["options"][0]["timestamp"] = NOW + 1
        snapshots = [seal(s)]
        assert paper_row(snapshots[0])["chain"] == []
        return
    if fault == "mixed": snapshots.append(seal({**s, "ccy": "BTC"}))
    with pytest.raises(ValueError): replay(snapshots, raws)


def test_duplicate_instrument_definitions_rejected():
    client = DerivePublic()
    client.call = lambda *a: {"instruments": [definition(), definition()], "pagination": {"num_pages": 1}}
    with pytest.raises(ValueError, match="duplicate"): client.definitions("ETH")


@pytest.mark.parametrize("fault", ["none", "missing_volume", "gap", "warmup", "stale_perp", "future_perp", "basis", "bad_option", "no_l1"])
def test_full_public_capture_with_bounded_fake_responses(monkeypatch, fault):
    monkeypatch.setattr("src.data.derive_public.time.time", lambda: NOW)
    frame = candles(180)
    index, trades = [], []
    for i, row in frame.iterrows():
        t = NOW - (180 - i) * 300
        index.append({"timestamp_bucket": t, **{f"{k}_price": float(row[k]) for k in ("open", "high", "low", "close")}})
        trades.append({"timestamp_bucket": t, "volume_contracts": float(row.volume)})
    p, d, t = perp(), definition(), ticker()
    p["I"] = float(frame.close.iloc[-1])
    p["M"] = p["I"]
    if fault == "missing_volume": trades.pop()
    if fault == "gap": index.pop(20)
    if fault == "warmup": index = index[-10:]
    if fault == "stale_perp": p["t"] -= 6000
    if fault == "future_perp": p["t"] += 1000
    if fault == "basis": p["I"] *= 1.1
    if fault == "bad_option": t["a"] = "invalid"
    if fault == "no_l1": t["a"] = t["b"] = 0
    responses = {"public/get_all_instruments": {"instruments": [d], "pagination": {"num_pages": 1}},
                 "public/get_index_chart_data": index, "public/get_tradingview_chart_data": trades,
                 "public/get_tickers": {"tickers": {d["instrument_name"]: t}}, "public/get_ticker": p}
    client = DerivePublic()
    requests_seen = []
    def call(method, params):
        requests_seen.append((method, params))
        data = responses[method]
        client.records.append(public_record(method, data, NOW, NOW))
        return data
    client.call = call
    s = client.snapshot("ETH")
    validate_snapshot(s, NOW, "ETH")
    assert len(requests_seen) == 5
    chart_params = requests_seen[1][1]
    assert chart_params["period"] == 300 and chart_params["end_timestamp"] == NOW
    assert chart_params["start_timestamp"] == NOW - 180 * 300
    if fault in ("none", "no_l1", "bad_option"):
        assert s["features"]["valid"]
    else:
        assert not s["features"]["valid"] and s["faults"]
    if fault == "no_l1":
        assert not s["options"][0]["quoted"] and s["option_diagnostics"][0]["mark_model"] is not None
    if fault == "bad_option": assert s["options"] == []
