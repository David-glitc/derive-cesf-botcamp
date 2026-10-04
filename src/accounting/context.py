"""Bounded, allowlisted read-only views; never serialize connectors or credentials."""
import json
import tempfile
from pathlib import Path

from src.data.records import digest, number, validate_snapshot
from agents.condor_agent import options_context
from src.accounting.derive_margin import require_margin_state


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
               "features": fields(data, ("price", "entry_mid", "trend_z", "efficiency", "volume_ratio", "atr_pct",
                                         "forecast_sigma", "realized_sigma", "cesf_score")),
               "risk": {**fields(data, ("equity", "venue_equity", "available", "committed", "daily_pnl_pct", "peak_dd",
                                        "stop_loss", "take_profit", "time_limit", "margin_age",
                                        "venue_minimum_notional", "venue_minimum_equity_fraction",
                                        "competition_pnl_pct", "remaining_loss_buffer", "risk_scale",
                                        "risk_trade_budget", "confidence_floor", "cost_multiple")),
                        "mode": str(data.get("risk_mode", "unavailable"))[:32],
                        "policy": str(getattr(config, "risk_policy", "unavailable"))[:64],
                        "strategy_profile": str(getattr(config, "strategy_profile", "baseline"))[:32],
                        "exposure_profile": str(getattr(config, "exposure_profile", "baseline"))[:64],
                        "perp_notional_fraction": scalar(getattr(config, "max_notional_fraction", .20)),
                        "perp_gross_fraction": scalar(getattr(config, "max_gross_exposure_fraction", .30)),
                        "option_gross_fraction": scalar(getattr(config, "option_gross_fraction", .30)),
                        "option_delta_fraction": .20,
                        "budget": scalar(config.total_amount_quote), "margin_verified": False,
                        "fill_funding_reconciled": False},
               "native_market": market, "native_market_path": str(market_path),
               "active_signal_source": ("opt-in Derive native 5m index + perp volume; Derive execution books"
                                        if getattr(config, "signal_source", "binance_proxy") == "derive_native" else
                                        "baseline Binance closed candles + Derive books; native input is shadow-only"),
               "positions": [], "orders": [], "executors": [], "live_options": False,
               "options_delta": options_context(data, now)}
    # Only isolated candidates expose this bounded diagnostic. Never include a
    # model path, coefficients, arbitrary model payload or credential-bearing data.
    if isinstance(data.get("candidate_alpha"), dict):
        alpha = data["candidate_alpha"]
        context["candidate_alpha"] = {**fields(alpha, ("expected_gross_return", "noise_margin", "horizon_seconds")),
                                      "in_distribution": alpha.get("in_distribution") is True,
                                      "confidence_is_probability": False, "live_authorized": False}
    execution = data.get("options_execution")
    if isinstance(execution, dict) and execution.get("adapter") == "derive_v2_atomic_rfq":
        context["options_execution"] = {"adapter": "derive_v2_atomic_rfq",
            "enabled": getattr(config, "options_enabled", False) is True,
            "phase": str(execution.get("phase", "unavailable"))[:32],
            "reason": str(execution.get("reason", ""))[:80], "live_execution_verified": False,
            "submission_count_incomplete": execution.get("submission_count_incomplete") is True,
            **fields(execution, ("orders_submitted", "execution_attempts", "closed_spreads", "entry_debit", "entry_fee", "realized_pnl"))}
    connector = None
    try:
        connector = controller._mainnet_connector()
        context["stream"] = {"ready": bool(connector.ready),
                             "private_age": scalar(now - connector._user_stream_tracker.last_recv_time)}
        for p in list(connector.account_positions.values())[:50]:
            context["positions"].append({"pair": str(p.trading_pair)[:32],
                **{key: scalar(getattr(p, key, None)) for key in ("amount", "entry_price", "unrealized_pnl")}})
        state = getattr(connector, "_flyby_account_state", None)
        if isinstance(state, dict):
            for row in state.get("positions", [])[:50]:
                if row.get("instrument_type") == "option":
                    context["positions"].append({"instrument": str(row.get("instrument_name", ""))[:80],
                        "type": "option", **fields(row, ("amount", "average_price", "unrealized_pnl", "delta", "index_price"))})
        for o in list(connector.in_flight_orders.values())[:50]:
            context["orders"].append({"id": str(o.client_order_id)[:128],
                **{key: scalar(getattr(o, key, None)) for key in ("amount", "price")}})
    except (ValueError, KeyError, TypeError, AttributeError):
        context["stream"] = {"ready": False, "private_age": None}
    context["runtime_health"] = {"account_verified": False, "reconciled": data.get("reconciled") is True,
                                 "decision_age": scalar(now - data.get("updated_at", now + 1)),
                                 "book_age": scalar(now - getattr(controller, "_last_book_time", 0)),
                                 "inventory_complete": False, "fill_ledger_verified": False}
    try:
        account = require_margin_state(connector, now)
        if not isinstance(account.get("positions"), list) or not isinstance(account.get("open_orders"), list):
            raise ValueError("incomplete_runtime_account_inventory")
        context["risk"].update(venue_equity=scalar(account["equity"]),
                               available=scalar(account["available"]), margin_age=scalar(now - account["observed_at"]),
                               margin_source="authenticated_legacy_get_subaccount", margin_verified=True)
        context["portfolio"] = {**fields(account, ("equity", "available", "initial_margin", "maintenance_margin")),
                                "observed_at": scalar(account["observed_at"]), "source": account["source"],
                                "position_count": len(account["positions"]), "open_order_count": len(account["open_orders"])}
        # Keep venue-wide inventory separate from connector-local tracking. Never
        # call a capped or malformed array a complete picture of the account.
        for name, rows in (("venue_positions", account["positions"]), ("venue_orders", account["open_orders"])):
            if not all(isinstance(row, dict) for row in rows):
                raise ValueError("invalid_runtime_inventory_row")
            context[name] = [{"instrument": str(row.get("instrument_name", ""))[:80],
                "type": str(row.get("instrument_type", "unknown"))[:16],
                **fields(row, ("amount", "filled_amount", "price", "average_price", "unrealized_pnl", "delta", "index_price"))}
                for row in rows[:50]]
        complete = (len(account["positions"]) <= 50 and len(account["open_orders"]) <= 50
                    and len(connector.account_positions) <= 50 and len(connector.in_flight_orders) <= 50
                    and len(controller.executors_info) <= 50)
        context["runtime_health"].update(account_verified=True, inventory_complete=complete,
                                         inventory_truncated=not complete)
    except (ValueError, KeyError, TypeError, AttributeError):
        context["portfolio"] = {"source": "unverified", "equity": None, "available": None}
    for e in list(controller.executors_info)[:50]:
        context["executors"].append({"id": str(e.id)[:128], "active": bool(e.is_active),
            **{key: scalar(getattr(e, key, None)) for key in ("net_pnl_quote", "cum_fees_quote", "filled_amount_quote")}})
    context["execution_book"] = {"status": "unavailable", "bids": [], "asks": []}
    try:
        bids, asks = data["bids"], data["asks"]
        bid_levels = [{"price": scalar(row.price), "amount": scalar(row.amount)}
                      for row in bids.head(5).itertuples()]
        ask_levels = [{"price": scalar(row.price), "amount": scalar(row.amount)}
                      for row in asks.head(5).itertuples()]
        book_age = context["runtime_health"]["book_age"]
        if not bid_levels or not ask_levels or any(level[k] is None or level[k] <= 0
                for level in bid_levels + ask_levels for k in ("price", "amount")):
            raise ValueError("invalid_runtime_book")
        context["execution_book"] = {"status": "fresh" if book_age is not None and
            0 <= book_age <= getattr(config, "max_book_age", 30) else "stale",
            "age": book_age, "bids": bid_levels, "asks": ask_levels, "source": "Derive execution book"}
    except (ValueError, KeyError, AttributeError, TypeError):
        pass
    return context


def context_summary(context, path):
    decision, market, risk = context["decision"], context["native_market"], context["risk"]
    return {"controller_id": str(context["controller_id"])[:64], "network": "mainnet", "time": context["time"],
            "decision_updated_at": context["decision_updated_at"],
            "paused": context["paused"], "signal": decision["signal"], "reason": decision["reason"],
            "confidence": decision["confidence"], "daily_pnl_pct": risk["daily_pnl_pct"], "peak_dd": risk["peak_dd"],
            "risk_mode": risk.get("mode", "unavailable"),
            "exposure_profile": risk.get("exposure_profile", "baseline"),
            "active_executors": sum(e["active"] for e in context["executors"]),
            "native_status": market["status"], "native_id": market.get("id"),
            "quoted_options": market.get("quoted_options"), "live_options": False, "context_path": str(path)[-160:]}
