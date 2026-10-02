"""Competition risk reducer and owned local checkpoint. No exchange transport."""
from contextlib import contextmanager
from decimal import Decimal
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

POLICY = "flyby-dd10-dd15-v1"
PAIRS = {"ETH-USDC", "BTC-USDC", "SOL-USDC", "HYPE-USDC"}


def money(value):
    if isinstance(value, bool):
        raise ValueError("invalid_risk_number")
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError("invalid_risk_number") from exc
    if not result.is_finite():
        raise ValueError("invalid_risk_number")
    return result


def timestamp(value):
    result = float(money(value))
    if not math.isfinite(result) or result < 0:
        raise ValueError("invalid_risk_time")
    return result


def account_binding(connector):
    identity = getattr(connector, "_subacct_id", None)
    if isinstance(identity, bool) or not isinstance(identity, (int, str)) or not str(identity).isdigit():
        raise ValueError("risk_account_identity_required")
    return hashlib.sha256(f"derive_perpetual:{int(identity)}".encode()).hexdigest()


def initial_state(equity, now, budget, binding):
    equity, budget = money(equity), money(budget)
    if equity < 0 or budget <= 0:
        raise ValueError("invalid_risk_equity")
    now = timestamp(now)
    state = {"kind": "flyby_competition_risk", "schema": 2, "policy": POLICY,
             "account_binding": binding, "budget": str(budget), "peak": str(max(budget, equity)),
             "day": int(now // 86400), "day_equity": str(max(equity, Decimal("0.01"))),
             "last_observed": now, "restricted": False, "hard_stop": False, "entries": {}}
    return advance(state, equity, now)


def validate_state(state, budget, binding):
    if (not isinstance(state, dict) or state.get("kind") != "flyby_competition_risk"
            or state.get("schema") != 2 or state.get("policy") != POLICY
            or state.get("account_binding") != binding or money(state.get("budget")) != money(budget)):
        raise ValueError("risk_checkpoint_contract_mismatch")
    if money(state["peak"]) < money(budget) or money(state["day_equity"]) <= 0:
        raise ValueError("invalid_risk_checkpoint")
    if (type(state.get("day")) is not int or state["day"] != int(timestamp(state["last_observed"]) // 86400)
            or type(state.get("restricted")) is not bool or type(state.get("hard_stop")) is not bool
            or (state["hard_stop"] and not state["restricted"])):
        raise ValueError("invalid_risk_checkpoint")
    entries = state.get("entries")
    if not isinstance(entries, dict) or not set(entries).issubset(PAIRS):
        raise ValueError("invalid_risk_entries")
    for entry in entries.values():
        if (not isinstance(entry, dict) or timestamp(entry["time"]) > state["last_observed"]
                or timestamp(entry["signal_time"]) > entry["time"]):
            raise ValueError("invalid_risk_entries")
    return state


def advance(state, equity, now):
    """Both latches survive recovery and day rollover. Boundaries use Decimal."""
    validate_state(state, state["budget"], state["account_binding"])
    equity, now = money(equity), timestamp(now)
    if equity < 0 or now < state["last_observed"]:
        raise ValueError("risk_clock_or_equity_invalid")
    result = {**state, "entries": dict(state["entries"])}
    if int(now // 86400) != state["day"]:
        result.update(day=int(now // 86400), day_equity=str(max(equity, Decimal("0.01"))))
    peak = max(money(state["peak"]), equity)
    result.update(peak=str(peak), last_observed=now)
    result["restricted"] |= equity <= peak * Decimal("0.90")
    result["hard_stop"] |= equity <= peak * Decimal("0.85")
    return result


def risk_view(state, equity):
    validate_state(state, state["budget"], state["account_binding"])
    equity, peak, budget = money(equity), money(state["peak"]), money(state["budget"])
    dd = (equity - peak) / peak
    remaining = max(Decimal(0), equity - peak * Decimal("0.85"))
    mode = "hard_stop" if state["hard_stop"] else "restricted" if state["restricted"] else "normal"
    if mode == "hard_stop":
        scale, trade_budget = 0.0, Decimal(0)
    elif mode == "restricted":
        scale = float(min(Decimal("0.25"), Decimal("0.25") * remaining / (peak * Decimal("0.05"))))
        trade_budget = min(equity * Decimal("0.005") * money(scale), remaining * Decimal("0.10"))
    else:
        scale, trade_budget = 1.0, equity * Decimal("0.005")
    return {"risk_policy": POLICY, "risk_mode": mode, "peak_dd": float(dd),
            "daily_pnl_pct": float((equity - money(state["day_equity"])) / budget),
            "competition_pnl_pct": float((equity - budget) / budget),
            "risk_scale": scale, "remaining_loss_buffer": float(remaining),
            "risk_trade_budget": float(trade_budget),
            "confidence_floor": .85 if mode == "restricted" else .70,
            "cost_multiple": 4.0 if mode == "restricted" else 3.0}


def scalp_exits(atr_pct, confidence, interval_seconds):
    from src.risk.position_sizing import dynamic_exits
    stop, target, _ = dynamic_exits(atr_pct, confidence, interval_seconds)
    # At coarse resolutions we cannot promise a sub-bar exit measurement.
    hold = max(2 * interval_seconds, int(600 + 1200 * confidence))
    return stop, target, hold


def exit_signal_reason(profile, decision, features, side):
    if decision.halt:
        return "halt"
    if profile == "baseline":
        return "signal_invalid" if decision.signal != side else None
    if profile != "competition_scalp":
        raise ValueError("unknown strategy profile")
    if decision.signal == -side:
        return "opposite_confirmation"
    if (not features.get("valid") or side * features.get("trend_z", 0) <= .2):
        return "trend_reversal"
    if features.get("efficiency", 0) < .15:
        return "trend_decay"
    return None


def _unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate_risk_checkpoint_key")
        result[key] = value
    return result


class RiskCheckpoint:
    """One owned persistent account file, shared across profiles in one client."""
    def __init__(self, path, binding, budget):
        self.path, self.binding, self.budget = Path(path), binding, money(budget)
        if (self.budget <= 0 or not isinstance(binding, str) or len(binding) != 64
                or any(c not in "0123456789abcdef" for c in binding)):
            raise ValueError("invalid_risk_store_identity_or_budget")

    def _read(self, path):
        if path.is_symlink():
            raise ValueError("risk_checkpoint_symlink")
        with path.open() as stream:
            raw = stream.read(32769)
        if len(raw) > 32768:
            raise ValueError("risk_checkpoint_too_large")
        return json.loads(raw, object_pairs_hook=_unique_object)

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_suffix(".lock")
        if lock.is_symlink() or self.path.is_symlink():
            raise ValueError("risk_checkpoint_symlink")
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def _write(self, state):
        serialized = json.dumps(state, allow_nan=False, sort_keys=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, prefix=self.path.name + ".",
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            temporary.replace(self.path)
            fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)

    def _load(self, equity, now, allow_bootstrap):
        marker = self.path.with_suffix(".initialized")
        expected = {"kind": "flyby_risk_initialized", "account_binding": self.binding,
                    "budget": str(self.budget), "policy": POLICY}
        if marker.exists() or marker.is_symlink():
            if self._read(marker) != expected:
                raise ValueError("risk_checkpoint_contract_mismatch")
            if not self.path.exists():
                raise ValueError("risk_checkpoint_lost")
        elif self.path.exists():
            raise ValueError("risk_initialization_marker_missing")
        else:
            if not allow_bootstrap:
                raise ValueError("risk_bootstrap_requires_flat_account")
            with marker.open("x") as stream:
                json.dump(expected, stream)
                stream.flush()
                os.fsync(stream.fileno())
            return initial_state(equity, now, self.budget, self.binding)
        return validate_state(self._read(self.path), self.budget, self.binding)

    def observe(self, equity, now, *, allow_bootstrap=False):
        with self._locked():
            state = advance(self._load(equity, now, allow_bootstrap), equity, now)
            self._write(state)
            return state, risk_view(state, equity)

    def consume_entry(self, equity, now, pair, signal_time, cooldown):
        now, signal_time, cooldown = timestamp(now), timestamp(signal_time), float(money(cooldown))
        if pair not in PAIRS or signal_time > now or not math.isfinite(cooldown) or cooldown <= 0:
            raise ValueError("invalid_risk_entry")
        with self._locked():
            state = advance(self._load(equity, now, False), equity, now)
            previous = state["entries"].get(pair)
            allowed = not state["hard_stop"] and (previous is None or (
                signal_time > previous["signal_time"] and now - previous["time"] >= cooldown))
            if allowed:
                state["entries"][pair] = {"time": timestamp(now), "signal_time": timestamp(signal_time)}
            self._write(state)
            return allowed
