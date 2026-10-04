"""Read-only native-loop contract and monotonic observation window."""
import time

from src.runtime.control import finite

OBSERVATION_SETTINGS = {"execution_mode": "loop", "frequency_sec": 60, "tick_timeout_sec": 30,
                        "max_ticks": 0, "restart_on_boot": False, "bot_mode": "bot",
                        "bot_name": "flyby-flyby_operator", "total_amount_quote": 800,
                        "canvas_enabled": False}
OBSERVATION_LIMITS = {"max_position_size_quote": 160, "max_open_executors": 1, "max_leverage": 2,
                      "max_drawdown_pct": -1, "shutdown_drawdown_pct": -1}


def validate_observation_config(config, *, require_setup=True):
    for key, expected in OBSERVATION_SETTINGS.items():
        actual = config.get(key)
        if actual != expected or isinstance(actual, bool) != isinstance(expected, bool):
            raise ValueError("observation_profile_mismatch:" + key)
    limits = config.get("risk_limits", {})
    if not isinstance(limits, dict) or any(limits.get(k) != v or isinstance(limits.get(k), bool)
                                          for k, v in OBSERVATION_LIMITS.items()):
        raise ValueError("observation_risk_limits_mismatch")
    for field in ("server_name", "agent_key"):
        value = config.get(field, "")
        if not isinstance(value, str) or len(value) > 160 or require_setup and not value.strip():
            raise ValueError("observation_model_and_server_required")
    return config


class ObservationWindow:
    def __init__(self, seconds=48 * 3600, *, clock=time.monotonic):
        self.seconds = finite(seconds)
        if not 0 < self.seconds <= 50 * 3600:
            raise ValueError("observation_invalid_duration")
        self.clock = clock
        self.started_at = None
        self.last_time = None

    def remaining(self):
        now = finite(self.clock())
        if self.last_time is not None and now < self.last_time:
            raise ValueError("observation_clock_regressed")
        if self.started_at is None:
            self.started_at = now
        self.last_time = now
        return max(0., self.seconds - (now - self.started_at))
