from copy import deepcopy
import asyncio
import json

import pytest

from backtest.options_paper import smoke_rows
from src.options.ranking import rank_spreads
from src.signal.microstructure import book_metrics, trade_metrics
from src.signal.options_surface import surface
from tests.test_native_data import NOW, definition, normalize_option, ticker
from src.data.derive_public import DerivePublic


def book():
    return {"instrument_name": "ETH-PERP", "timestamp": NOW * 1000, "publish_id": 1,
            "bids": [[2999, 1], [2998, 2]], "asks": [[3001, 1], [3002, 1]]}


def trade(identity="one", price=3000, amount=1, **changes):
    return {"trade_id": identity, "instrument_name": "ETH-PERP", "timestamp": NOW * 1000,
            "trade_price": price, "trade_amount": amount, **changes}


def chain(kind="call"):
    rows = smoke_rows()[0 if kind == "call" else 3]["chain"]
    for i, q in enumerate(rows):
        q.update(timestamp=NOW, expiry=NOW + 3 * 86400, quoted=True, active=True,
                 pricing={"iv": .5, "forward": 3000, "discount": 1, "gamma": .01 - i * .005}, oi=10)
    return rows


def test_book_depth_imbalance_and_probe_capacity():
    result = book_metrics(book(), "ETH-PERP", NOW, 1.5)
    assert result["imbalance"] == pytest.approx(.2)
    assert result["buy_vwap"] == pytest.approx((3001 + .5 * 3002) / 1.5)
    assert book_metrics(book(), "ETH-PERP", NOW, 4)["buy_vwap"] is None
    assert book_metrics(book(), "ETH-PERP", NOW + 6)["status"] == "stale"


@pytest.mark.parametrize("fault", ["crossed", "unsorted", "duplicate", "negative", "nan", "wrong_pair"])
def test_invalid_l2(fault):
    b = book()
    if fault == "crossed": b["asks"][0][0] = 1
    if fault == "unsorted": b["bids"].reverse()
    if fault == "duplicate": b["asks"][1][0] = b["asks"][0][0]
    if fault == "negative": b["bids"][0][1] = -1
    if fault == "nan": b["bids"][0][0] = float("nan")
    if fault == "wrong_pair": b["instrument_name"] = "BTC-PERP"
    with pytest.raises(ValueError): book_metrics(b, "ETH-PERP", NOW)


def test_counterparty_trade_deduplication_and_poc():
    rows = [trade(direction="buy", liquidity_role="taker"), trade(direction="sell", liquidity_role="maker"),
            trade("two", 3010, 2), trade("future", timestamp=(NOW + 1) * 1000)]
    result = trade_metrics(rows, "ETH-PERP", NOW, 5)
    assert result["sample_volume"] == 3 and result["prints"] == 2
    assert result["counterparty_duplicates"] == 1 and result["future_excluded"] == 1
    assert result["vwap"] == pytest.approx((3000 + 6020) / 3)
    assert result["poc"] == 3012.5 and result["cvd"] is None
    with pytest.raises(ValueError): trade_metrics([trade(), trade(price=1)], "ETH-PERP", NOW, 5)
    with pytest.raises(ValueError): trade_metrics(rows, "ETH-PERP", NOW, 0)


def test_trade_metrics_ignore_old_prints_and_counterparty_fields():
    result = trade_metrics([trade(timestamp=(NOW - 1000) * 1000, wallet="SECRET")], "ETH-PERP", NOW, 5)
    assert result["status"] == "unavailable" and result["vwap"] is None
    assert "SECRET" not in str(result)


def test_expiry_specific_surface_unknown_gex_and_causal_oi_changes():
    options = []
    for kind, delta, iv in (("call", .5, .5), ("put", -.5, .6), ("call", .25, .45), ("put", -.25, .65)):
        d, t = definition(), ticker()
        d["instrument_name"] += f"-{kind}-{delta}"
        d["option_details"]["option_type"] = "C" if kind == "call" else "P"
        t["option_pricing"].update(d=delta, i=iv)
        options.append(normalize_option(d, t, "ETH", NOW))
    old = deepcopy(options)
    for q in old: q["oi"] -= 1
    result = surface(options, NOW, 3000, {"received_at": NOW - 1, "options": old})
    tenor = result["tenors"][0]
    assert tenor["atm_iv"] == pytest.approx(.55)
    assert tenor["put_minus_call_25d_iv"] == pytest.approx(.2)
    assert result["common_oi_delta"] == 4 and result["signed_gex"] is None
    assert "unverified" in tenor["gamma_oi_units"]
    assert surface(options, NOW + 6, 3000)["status"] == "unavailable"
    with pytest.raises(ValueError): surface(options, NOW, 3000, {"received_at": NOW, "options": old})


def test_zero_books_do_not_generate_atm_skew_or_ranked_trades():
    options = chain()
    for q in options: q["quoted"] = False
    result = surface(options, NOW, 3000)
    assert result["tenors"][0]["atm_iv"] is None
    assert rank_spreads(options, NOW, 3000)["candidate_count"] == 0


@pytest.mark.parametrize("kind", ["call", "put"])
def test_costed_short_horizon_ranking(kind):
    result = rank_spreads(chain(kind), NOW, 3000)
    assert result["candidate_count"] == 1 and not result["live_options"]
    p = result["candidates"][0]
    assert 0 < p["max_loss"] <= 8 and p["round_trip_fees"] > 0
    assert len(p["scenario_net_quote"]) == 10 and p["signal_only"]
    assert p["max_loss"] == pytest.approx(p["debit"] + p["round_trip_fees"])
    assert p["worst_scenario_net"] == min(p["scenario_net_quote"].values())
    assert rank_spreads(chain(kind), NOW + 6, 3000)["candidate_count"] == 0


@pytest.mark.parametrize("fault", ["missing_iv", "huge_fees", "tiny_budget", "thin_book"])
def test_ranking_fails_closed(fault):
    qs, budget = chain(), 8
    if fault == "missing_iv": qs[0]["pricing"]["iv"] = None
    if fault == "huge_fees": qs[0]["fees"]["base"] = 10
    if fault == "tiny_budget": budget = .1
    if fault == "thin_book": qs[0]["asks"] = [[30, .001]]
    assert rank_spreads(qs, NOW, 3000, budget)["candidate_count"] == 0


def test_bounded_public_ws_snapshot_records_channel_and_rejects_wrong_frames(monkeypatch):
    sent, kwargs = [], {}
    messages = [{"params": {"channel": "wrong", "data": book()}},
                {"params": {"channel": "orderbook.ETH-PERP.1.100", "data": book()}}]
    class Socket:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def send(self, data): sent.append(json.loads(data))
        async def recv(self): return json.dumps(messages.pop(0))
    def connect(url, **kw):
        assert url == "wss://api.derive.xyz/v3/ws"
        kwargs.update(kw)
        return Socket()
    monkeypatch.setattr("websockets.connect", connect)
    client = DerivePublic()
    raw = asyncio.run(client._book("ETH"))
    assert raw == book() and len(sent) == 1 and sent[0]["method"] == "subscribe"
    assert kwargs["open_timeout"] == 8 and kwargs["max_size"] == 300000
    assert client.records[0]["params"] == {"channel": "orderbook.ETH-PERP.1.100"}
    assert client.records[0]["method"] == "ws/orderbook"
