import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.accounting.context import (atomic_owned_json, context_summary, controller_context,
                                    market_view, read_market, context_path)
from tests.test_native_data import NOW, seal, snapshot


def fake_controller():
    connector = SimpleNamespace(ready=True, _user_stream_tracker=SimpleNamespace(last_recv_time=NOW),
        account_positions={"ETH": SimpleNamespace(trading_pair="ETH-PERP", amount=1, entry_price=3000,
                                                 unrealized_pnl=10, private_key="SECRET_POSITION")},
        in_flight_orders={"x": SimpleNamespace(client_order_id="owned", amount=.1, price=3000, token="SECRET_ORDER")},
        private_key="SECRET_CONNECTOR")
    return SimpleNamespace(config=SimpleNamespace(id="unit", trading_pair="ETH-PERP", manual_kill_switch=True,
                                                 total_amount_quote=800, api_secret="SECRET_CONFIG"),
                           processed_data={"signal": 0, "halt": True, "confidence": .5, "updated_at": NOW,
                                           "api_secret": "SECRET_DATA", "reason": "paused"},
                           executors_info=[], _mainnet_connector=lambda: connector)


def test_context_allowlist_budget_and_staleness(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    context = controller_context(fake_controller(), NOW)
    encoded = json.dumps(context, allow_nan=False)
    assert "SECRET" not in encoded
    assert context["paused"] and context["risk"]["margin_verified"] is False
    assert context["native_market"]["status"] == "unavailable_or_invalid"
    assert len(context["positions"]) == len(context["orders"]) == 1
    assert context["decision_updated_at"] == NOW
    assert len(json.dumps({"flyby": context_summary(context, "data/flyby-context-unit.json")})) < 1024


def test_summary_bounds_worst_identifiers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctl = fake_controller()
    ctl.config.id = "x" * 10000
    ctl.processed_data["reason"] = "x" * 10000
    context = controller_context(ctl, NOW)
    summary = context_summary(context, "x" * 10000)
    assert len(json.dumps({"flyby": summary})) < 1024


def test_native_market_age_masks_signal_and_books():
    s, _ = snapshot()
    s = seal({**s, "features": {"valid": True}})
    assert market_view(s, NOW, "ETH")["quoted_options"] == 1
    view = market_view(s, NOW + 6, "ETH")
    assert view["status"] == "stale_index" and view["quoted_options"] == 0
    assert view["native_signal_valid"] is False


@pytest.mark.parametrize("fault", ["malformed", "oversized", "stale", "wrong_ccy", "wrong_hash"])
def test_context_read_failures_are_advisory(tmp_path, fault):
    s, _ = snapshot()
    if fault == "wrong_ccy": s = seal({**s, "ccy": "BTC"})
    if fault == "wrong_hash": s["network"] = "testnet"
    content = "{" if fault == "malformed" else "x" * 512001 if fault == "oversized" else json.dumps(s)
    target = tmp_path / "market.json"
    target.write_text(content)
    view = read_market(target, NOW + (31 if fault == "stale" else 0), "ETH")
    assert view["status"] == "unavailable_or_invalid" and not view["live_options"]


def test_atomic_context_owned_only_and_recovery(tmp_path):
    target = tmp_path / "context.json"
    body = {"kind": "flyby_controller_context", "controller_id": "unit", "value": 1}
    atomic_owned_json(target, body, body["kind"])
    target.with_suffix(".json.tmp").write_text("old interrupted temp")
    atomic_owned_json(target, {**body, "value": 2}, body["kind"])
    assert json.loads(target.read_text())["value"] == 2
    assert target.with_suffix(".json.tmp").read_text() == "old interrupted temp"
    with pytest.raises(ValueError): atomic_owned_json(target, {**body, "controller_id": "other"}, body["kind"])
    with pytest.raises(ValueError): atomic_owned_json(target, {**body, "kind": "other"}, "other")
    with pytest.raises(ValueError): atomic_owned_json(target, {**body, "value": float("nan")}, body["kind"])
    assert json.loads(target.read_text())["value"] == 2
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ValueError): atomic_owned_json(link, body, body["kind"])


def test_public_shadow_context_does_not_copy_arbitrary_fields(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s, _ = snapshot()
    s = seal({**s, "credentials": "SECRET_SNAPSHOT"})
    atomic_owned_json(Path("data/flyby-market-ETH.json"), s, s["kind"])
    context = controller_context(fake_controller(), NOW)
    assert context["native_market"]["quoted_options"] == 1
    assert "SECRET" not in json.dumps(context)
    assert "shadow-only" in context["active_signal_source"]


def test_context_path_cannot_escape_data_directory():
    assert context_path("../../outside").parent == Path("data")
    assert context_path("stable-id") == context_path("stable-id")
    assert context_path("first") != context_path("second")


@pytest.mark.parametrize("body", [[], None, 42, "text", {"kind": "bad"}])
def test_nonobject_context_unavailable(tmp_path, body):
    path = tmp_path / "context.json"
    path.write_text(json.dumps(body))
    assert read_market(path, NOW, "ETH")["status"] == "unavailable_or_invalid"
