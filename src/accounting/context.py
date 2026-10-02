"""Bounded, allowlisted read-only views; never serialize connectors or credentials."""
import json
import tempfile
from pathlib import Path

from src.data.records import digest, number, validate_snapshot
from agents.condor_agent import options_context


def context_path(controller_id):
    # Controller IDs are arbitrary model strings, not trusted filesystem paths.
    return Path("data") / f"flyby-context-{digest(str(controller_id))[:16]}.json"


def scalar(value):
    try:
        return number(value, optional=True)
    except (ValueError, TypeError):
        return None


def fields(raw, keys):
    return {key: scalar(raw.get(key)) for key in keys}


def market_view(snapshot, now, ccy):
    age = validate_snapshot(snapshot, now, ccy)
    perp = snapshot["perp"]
    quoted = [q for q in snapshot["options"] if q["quoted"] and 0 <= now - q["timestamp"] <= 5]
    fresh_index = 0 <= now - perp["timestamp"] <= 5
    analytics = snapshot.get("analytics") or {}
    return {"status": "fresh" if fresh_index else "stale_index", "id": snapshot["id"], "age": age,
            "index": scalar(perp["index"]), "mark": scalar(perp["mark"]),
            "funding_rate": scalar(perp.get("funding_rate")), "quoted_options": len(quoted),
            "model_options": len(snapshot["options"]),
            "native_signal_valid": bool(fresh_index and snapshot["features"].get("valid")),
            "forecast_sigma": scalar(snapshot["features"].get("forecast_sigma")),
            "volume_source": "venue perp trade-chart, not index volume",
            "analytics_status": {k: analytics.get(k, {}).get("status", "not_collected")
                                 if analytics.get(k, {}).get("status") in
                                 ("available", "stale", "unavailable", "no_qualified_spreads") else "not_collected"
                                 for k in ("book", "trades", "surface", "spreads")},
            "spread_candidates": scalar(analytics.get("spreads", {}).get("candidate_count")),
            "mode": "advisory_only", "live_options": False}


def load_market(path, now, ccy):
    with Path(path).open() as stream:
        text = stream.read(512001)
    if len(text) > 512000:
        raise ValueError("market snapshot exceeds bound")
    snapshot = json.loads(text)
    validate_snapshot(snapshot, now, ccy)
    return snapshot


def read_market(path, now, ccy):
    try:
        return market_view(load_market(path, now, ccy), now, ccy)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {"status": "unavailable_or_invalid", "mode": "advisory_only", "live_options": False}


def atomic_owned_json(path, body, kind):
    """Replace only a file of our own declared kind; no broad cleanup."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("refuse symlink context target")
    if path.exists():
        with path.open() as stream:
            previous = json.loads(stream.read(512001))
        if not isinstance(previous, dict) or previous.get("kind") != kind:
            raise ValueError("refuse unrelated context overwrite")
        for owner in ("ccy", "controller_id"):
            if previous.get(owner) != body.get(owner):
                raise ValueError("refuse different context owner overwrite")
    if body.get("kind") != kind:
        raise ValueError("context kind mismatch")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Serialize first; unique exclusive temps allow recovery after a process crash.
    serialized = json.dumps(body, allow_nan=False, sort_keys=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name + ".",
                                     suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(serialized)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def controller_context(controller, now):
    config, data = controller.config, controller.processed_data
    ccy = config.trading_pair.split("-")[0]
    market_path = Path("data") / f"flyby-market-{ccy}.json"
    market = read_market(market_path, now, ccy)
    context = {"schema": 1, "kind": "flyby_controller_context", "controller_id": config.id,
               "time": now, "network": "mainnet", "api_generation": "legacy_v2",
               "paused": bool(config.manual_kill_switch), "pair": config.trading_pair,
               "decision_updated_at": scalar(data.get("updated_at")),
               "decision": {"signal": scalar(data.get("signal")), "halt": bool(data.get("halt", True)),
                            "confidence": scalar(data.get("confidence")), "reason": str(data.get("reason", "not_observed"))[:80],
                            "entry_block": str(data.get("entry_block", ""))[:80]},
               "features": fields(data, ("price", "trend_z", "efficiency", "volume_ratio", "atr_pct",
                                         "forecast_sigma", "realized_sigma", "cesf_score")),
               "risk": {**fields(data, ("equity", "available", "committed", "daily_pnl_pct", "peak_dd",
                                        "stop_loss", "take_profit", "time_limit", "margin_age",
                                        "venue_minimum_notional", "venue_minimum_equity_fraction",
                                        "competition_pnl_pct", "remaining_loss_buffer", "risk_scale",
                                        "risk_trade_budget", "confidence_floor", "cost_multiple")),
                        "mode": str(data.get("risk_mode", "unavailable"))[:32],
                        "policy": str(getattr(config, "risk_policy", "unavailable"))[:64],
                        "strategy_profile": str(getattr(config, "strategy_profile", "baseline"))[:32],
                        "budget": scalar(config.total_amount_quote), "margin_verified": False,
                        "fill_funding_reconciled": False},
               "native_market": market, "native_market_path": str(market_path),
               "active_signal_source": ("opt-in Derive native 5m index + perp volume; Derive execution books"
                                        if getattr(config, "signal_source", "binance_proxy") == "derive_native" else
                                        "baseline Binance closed candles + Derive books; native input is shadow-only"),
               "positions": [], "orders": [], "executors": [], "live_options": False,
               "options_delta": options_context(data, now)}
    try:
        connector = controller._mainnet_connector()
        context["stream"] = {"ready": bool(connector.ready),
                             "private_age": scalar(now - connector._user_stream_tracker.last_recv_time)}
        for p in list(connector.account_positions.values())[:50]:
            context["positions"].append({"pair": str(p.trading_pair)[:32],
                **{key: scalar(getattr(p, key, None)) for key in ("amount", "entry_price", "unrealized_pnl")}})
        for o in list(connector.in_flight_orders.values())[:50]:
            context["orders"].append({"id": str(o.client_order_id)[:128],
                **{key: scalar(getattr(o, key, None)) for key in ("amount", "price")}})
    except (ValueError, KeyError, TypeError, AttributeError):
        context["stream"] = {"ready": False, "private_age": None}
    for e in list(controller.executors_info)[:50]:
        context["executors"].append({"id": str(e.id)[:128], "active": bool(e.is_active),
            **{key: scalar(getattr(e, key, None)) for key in ("net_pnl_quote", "cum_fees_quote", "filled_amount_quote")}})
    return context


def context_summary(context, path):
    decision, market, risk = context["decision"], context["native_market"], context["risk"]
    return {"controller_id": str(context["controller_id"])[:64], "network": "mainnet", "time": context["time"],
            "decision_updated_at": context["decision_updated_at"],
            "paused": context["paused"], "signal": decision["signal"], "reason": decision["reason"],
            "confidence": decision["confidence"], "daily_pnl_pct": risk["daily_pnl_pct"], "peak_dd": risk["peak_dd"],
            "risk_mode": risk.get("mode", "unavailable"),
            "active_executors": sum(e["active"] for e in context["executors"]),
            "native_status": market["status"], "native_id": market.get("id"),
            "quoted_options": market.get("quoted_options"), "live_options": False, "context_path": str(path)[-160:]}
