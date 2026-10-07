"""Deterministic Flyby decision policy used by Condor, V2 and replay."""
from __future__ import annotations
import math
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import time


@dataclass(frozen=True)
class AgentDecision:
    regime: str
    thresh: float = 2.5
    cesf_min: float = 0.35
    reason: str = "no_clean_signal"
    halt: bool = False
    execution_venue: str = "none"
    derive_instrument: str | None = None
    collateral_hint: str = "adapter-reported USDC"
    margin_model: str = "adapter-reported margin"
    signal: int = 0
    confidence: float = 0.0
    option_direction: str | None = None


def number(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def decide(snapshot: dict, active: bool = False) -> AgentDecision:
    fields = ("price", "trend_z", "efficiency", "volume_ratio", "atr_pct", "stale_secs", "daily_pnl_pct", "peak_dd",
              "previous_trend_z", "previous_volume_ratio", "previous_efficiency")
    values = {name: number(snapshot.get(name)) for name in fields}
    if any(value is None for value in values.values()) or snapshot.get("valid") is not True:
        return AgentDecision("HALT", reason="invalid_snapshot", halt=True)
    if values["stale_secs"] < 0 or values["stale_secs"] > 60:
        return AgentDecision("HALT", reason="stale_data", halt=True)
    if not 0 <= values["efficiency"] <= 1 or values["volume_ratio"] < 0:
        return AgentDecision("HALT", reason="invalid_snapshot", halt=True)
    from src.risk.competition import POLICY, HARD_STOP_DRAWDOWN, RESTRICTED_DRAWDOWN
    competition = snapshot.get("risk_policy") == POLICY
    restricted = competition and snapshot.get("risk_mode") == "restricted"
    if competition:
        mode = snapshot.get("risk_mode")
        if mode not in ("normal", "restricted", "hard_stop"):
            return AgentDecision("HALT", reason="invalid_risk_mode", halt=True)
        if mode == "hard_stop" or values["peak_dd"] <= -float(HARD_STOP_DRAWDOWN):
            return AgentDecision("HALT", reason="competition_hard_stop", halt=True)
        if mode == "normal" and values["peak_dd"] <= -float(RESTRICTED_DRAWDOWN):
            return AgentDecision("HALT", reason="risk_mode_mismatch", halt=True)
    elif values["daily_pnl_pct"] <= -0.02 or values["peak_dd"] <= -0.04:
        return AgentDecision("HALT", reason="loss_guard", halt=True)
    if snapshot.get("reconciled") is not True:
        return AgentDecision("HALT", reason="account_unreconciled", halt=True)
    if values["price"] <= 0 or not 0.0003 <= values["atr_pct"] <= 0.03:
        return AgentDecision("flat", reason="volatility_gate")
    volume_floor = 1.50 if restricted else 1.10 if active else 1.20
    trend_floor = 1.50 if restricted else .70 if active else .90
    efficiency_floor = .45 if restricted else .30
    if values["volume_ratio"] < volume_floor:
        return AgentDecision("flat", reason="volume_gate")
    if values["efficiency"] < efficiency_floor or abs(values["trend_z"]) < trend_floor:
        return AgentDecision("flat", reason="trend_gate")
    if (values["previous_trend_z"] * values["trend_z"] <= 0
            or abs(values["previous_trend_z"]) < trend_floor
            or values["previous_volume_ratio"] < volume_floor
            or not efficiency_floor <= values["previous_efficiency"] <= 1):
        return AgentDecision("flat", reason="confirmation_gate")
    confidence = min(1.0, 0.35 * min(abs(values["trend_z"]) / 2, 1)
                     + 0.35 * values["efficiency"] + 0.30 * min(values["volume_ratio"] / 2, 1))
    if confidence < (.85 if restricted else .70):
        return AgentDecision("flat", reason="confidence_gate")
    direction = 1 if values["trend_z"] > 0 else -1
    ccy = snapshot.get("ccy", "ETH")
    option_candidate = ccy in ("ETH", "BTC") and confidence >= 0.75 and number(snapshot.get("option_iv_edge"), 0) >= 0.02
    return AgentDecision(
        "call-debit-spread" if option_candidate and direction > 0 else
        "put-debit-spread" if option_candidate else
        "perp-scalp-long" if direction > 0 else "perp-scalp-short",
        reason="confirmed_price_volume", signal=direction, confidence=confidence,
        execution_venue="spread-plan" if option_candidate else "derive-perp",
        derive_instrument=f"{ccy}-PERP" if not option_candidate else None,
        option_direction=("call" if direction > 0 else "put") if option_candidate else None,
    )


def decide_active(snapshot: dict) -> AgentDecision:
    return decide(snapshot, active=True)


def options_context(snapshot: dict, now: float) -> dict:
    """Allowlisted advisory context; cannot alter policy or authorize option orders."""
    from src.options.delta import delta_context
    context = delta_context(snapshot.get("spread_plan"), now)
    context["execution_mode"] = "shadow_only"
    execution = snapshot.get("options_execution")
    if isinstance(execution, dict) and execution.get("adapter") in ("derive_v3_atomic_rfq", "derive_v3_atomic_rfq_book"):
        context["execution_mode"] = "atomic_rfq_v3"
        context["execution_phase"] = str(execution.get("phase", "unavailable"))[:32]
        context["live_execution_verified"] = False
    context["intent"] = "bounded_directional_spread_not_delta_neutral"
    context["risk_mode"] = snapshot.get("risk_mode") if snapshot.get("risk_mode") in ("normal", "restricted", "hard_stop") else "unavailable"
    context["remaining_loss_buffer"] = number(snapshot.get("remaining_loss_buffer"))
    return context


def log_decision(path: Path, snapshot: dict, decision: AgentDecision):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps({"ts": time.time(), "snapshot": snapshot, "decision": asdict(decision)}, allow_nan=False) + "\n")


def condor_options_demo(spot=3000, ccy="ETH"):
    """Legacy research helper, outside the competition decision path."""
    from src.pricing.black76 import black76_price
    return {"ok": True, "venue": "research-only", "ccy": ccy,
            "call_model": black76_price(spot, spot, 3 / 365, 0, 0.6, "call")}
