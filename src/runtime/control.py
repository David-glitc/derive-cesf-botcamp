"""Reviewed adjustment bounds, shared by agent bridge and authoritative controller."""
import math
import re

TOOLS = {"flyby_get_runtime_state", "flyby_read_events", "flyby_submit_adjustment",
         "flyby_get_adjustment_status"}
BOUNDS = {"size_multiplier": (0., 1.), "confidence_floor": (.70, .95),
          "cost_multiple": (3., 6.), "stop_multiplier": (.5, 1.),
          "take_profit_multiplier": (1., 2.), "hold_multiplier": (.5, 1.5)}
MAX_LEASE = 60
MAX_STATE_AGE = 5


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("runtime_invalid_number")
    return float(value)


def identifier(value, limit=64):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1," + str(limit) + "}", value):
        raise ValueError("runtime_invalid_identifier")
    return value


def patch_view(patch):
    if not isinstance(patch, dict) or not patch or set(patch) - set(BOUNDS) - {
            "veto_entry", "close_executor_id", "close_options"}:
        raise ValueError("runtime_unknown_adjustment")
    result = {}
    for field, value in patch.items():
        if field in BOUNDS:
            low, high = BOUNDS[field]
            if not low <= finite(value) <= high:
                raise ValueError("runtime_adjustment_out_of_bounds")
        elif field in ("veto_entry", "close_options"):
            if type(value) is not bool:
                raise ValueError("runtime_invalid_boolean")
        else:
            identifier(value, 128)
        result[field] = value
    return result


def validate_request(request, state, now, *, consuming=False):
    keys = {"id", "controller_id", "account_binding", "session", "basis_sequence",
            "issued_at", "expires_at", "patch"}
    if not isinstance(request, dict) or set(request) != keys:
        raise ValueError("runtime_invalid_request")
    identifier(request["id"])
    for name in ("controller_id", "account_binding", "session"):
        if request[name] != state[name]:
            raise ValueError("runtime_request_owner_or_session_mismatch")
    issued, expires = finite(request["issued_at"]), finite(request["expires_at"])
    finite(now)
    if not 0 <= now - state["time"] <= MAX_STATE_AGE:
        raise ValueError("runtime_stale_state")
    seq = request["basis_sequence"]
    oldest = 1 if consuming else max(1, state["sequence"] - 5)
    if type(seq) is not int or not oldest <= seq <= state["sequence"]:
        raise ValueError("runtime_invalid_basis_sequence")
    if (issued > now or not issued < expires <= issued + MAX_LEASE
            or not consuming and issued < state["time"] - MAX_STATE_AGE):
        raise ValueError("runtime_invalid_lease")
    if now >= expires:
        raise ValueError("runtime_expired_lease")
    if state["mode"] != "bounded":
        raise ValueError("runtime_observe_only")
    health = state["context"].get("runtime_health", {})
    if health.get("account_verified") is not True or health.get("inventory_complete") is not True:
        raise ValueError("runtime_unverified_account_inventory")
    patch = patch_view(request["patch"])
    owned = {e["id"] for e in state["context"].get("executors", []) if e.get("active") is True}
    if "close_executor_id" in patch and patch["close_executor_id"] not in owned:
        raise ValueError("runtime_foreign_executor")
    if patch.get("close_options") and not state["context"].get("options_execution", {}).get("enabled"):
        raise ValueError("runtime_options_not_enabled")
    return patch


def entry_allowed(patch, confidence, floor):
    return (not patch.get("veto_entry", False) and patch.get("size_multiplier", 1) > 0
            and confidence >= max(floor, patch.get("confidence_floor", floor)))


def tune_exits(patch, stop, target, hold):
    # Only for NEW executors; risk sizing uses the original stop, not this tighter one.
    return (stop * patch.get("stop_multiplier", 1), target * patch.get("take_profit_multiplier", 1),
            min(21600, max(1, int(hold * patch.get("hold_multiplier", 1)))))
