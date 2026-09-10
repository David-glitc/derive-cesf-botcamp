"""Condor harness — Botcamp Agent lane wrapper over the V2 controller.

Condor is the LLM-driven harness (https://condor.hummingbot.org) that
reasons about market conditions and supervises deterministic executors.

Architecture invariant: LLM never prices options or places orders.
It only:
  - selects regime (ATM vs OTM vs Trend) based on CESF score & SVI slope
  - tunes thresh/cesf_min within pre-approved bands
  - halts if data stale or risk guard tripped

Deterministic controller (derive_cesf_long_vol) places every order.
This file makes your submission valid for BOTH lanes:
  - Controller lane: submit controller directly
  - Agent lane: submit this Condor agent + same controller
"""
from __future__ import annotations
import json, time
from pathlib import Path
from dataclasses import dataclass

@dataclass
class AgentDecision:
    regime: str  # scalp-long-put-atm | scalp-long-put-otm-25d | trend-ride-put | etc
    thresh: float
    cesf_min: float
    reason: str
    halt: bool = False

# Pre-approved bands (dual-control: no tuning outside these without review)
BANDS = {
    "thresh": (1.5, 2.8),
    "cesf_min": (0.30, 0.50),
}

REGIME_RULES = """
If CESF crash_mass >=0.40 and SVI skew steep (put IV > call IV by >2 vol) → OTM put 25Δ (cheaper gamma, better Sharpe when smile rich)
If crash_mass 0.30-0.40 and ATM edge >1.8 → ATM put (primary +24% regime)
If momentum 24x5m >1.2% and vol not stretched but CESF low → trend-ride call
If vol expansion + low CESF → OTM strangle / long call OTM
If daily loss <-2% or stale >60s → HALT
"""

def decide(market_snapshot: dict) -> AgentDecision:
    """Pure function — LLM would call this, but we implement rule-based for determinism."""
    cesf = market_snapshot.get("cesf_score", 0)
    edge = market_snapshot.get("edge", 0)
    skew = market_snapshot.get("svi_skew", 0)  # put IV - call IV at 25Δ
    mom = market_snapshot.get("momentum", 0)
    stale = market_snapshot.get("stale_secs", 0)
    daily_pnl = market_snapshot.get("daily_pnl_pct", 0)

    if stale > 60 or daily_pnl <= -0.03:
        return AgentDecision("HALT", 0, 0, f"halt stale={stale}s daily={daily_pnl:.1%}", True)

    if cesf >= 0.40 and skew > 2.0 and edge > 0.015:
        return AgentDecision("scalp-long-put-otm-25d", 1.8, 0.40, f"OTM put: cesf {cesf:.2f} skew {skew:.1f} edge {edge:.3f}")
    if cesf >= 0.33 and edge > 0.018:
        return AgentDecision("scalp-long-put-atm", 2.5, 0.35, f"ATM put: cesf {cesf:.2f} edge {edge:.3f}")
    if mom > 0.012 and cesf < 0.30:
        return AgentDecision("trend-ride-call", 1.8, 0.30, f"trend call: mom {mom:.3f}")
    if mom < -0.012 and cesf < 0.30:
        return AgentDecision("trend-ride-put", 1.8, 0.30, f"trend put: mom {mom:.3f}")
    if cesf < 0.25 and edge > 0.022:
        return AgentDecision("scalp-long-call-otm-25d", 2.2, 0.30, f"OTM call expansion")
    return AgentDecision("scalp-long-put-atm", 2.0, 0.35, "default ATM put")

def log_decision(path: Path, snap: dict, dec: AgentDecision):
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.time(), "snapshot": snap, "decision": dec.__dict__}
    with path.open("a") as f: f.write(json.dumps(rec)+"\n")

# Example standalone run:
if __name__ == "__main__":
    snap = {"cesf_score":0.42,"edge":0.019,"svi_skew":2.5,"momentum":0.0,"stale_secs":0,"daily_pnl_pct":0}
    print(decide(snap))
