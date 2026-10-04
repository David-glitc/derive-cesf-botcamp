from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from scripts.prepare_observation_profile import prepare
from src.runtime.observation import ObservationWindow, validate_observation_config

ROOT = Path(__file__).resolve().parents[1]


def profile():
    config = yaml.safe_load((ROOT / "condor/profiles/flyby_observe_48h.yml").read_text())
    config.update(server_name="fixture-server", agent_key="openai:fixture")
    return config


def test_native_loop_contract_and_deadline():
    validate_observation_config(profile())
    now = [100.]
    window = ObservationWindow(clock=lambda: now[0])
    assert window.remaining() == 48 * 3600
    now[0] += 48 * 3600 - 1
    assert window.remaining() == 1
    now[0] += 1
    assert window.remaining() == 0
    now[0] -= 1
    with pytest.raises(ValueError, match="regressed"):
        window.remaining()


@pytest.mark.parametrize("seconds", [0, -1, True, None, "48", float("nan"), float("inf"), 50 * 3600 + 1])
def test_invalid_duration(seconds):
    with pytest.raises(ValueError):
        ObservationWindow(seconds)


@pytest.mark.parametrize("field,bad", [("execution_mode", "dry_run"), ("max_ticks", 2880),
    ("restart_on_boot", True), ("frequency_sec", 20), ("tick_timeout_sec", 120),
    ("total_amount_quote", 1600), ("bot_name", "other"), ("canvas_enabled", True),
    ("server_name", ""), ("agent_key", "")])
def test_invalid_profile(field, bad):
    config = profile()
    config[field] = bad
    with pytest.raises(ValueError):
        validate_observation_config(config)


@pytest.mark.parametrize("field", ["max_position_size_quote", "max_open_executors", "max_leverage",
                                    "max_drawdown_pct", "shutdown_drawdown_pct"])
def test_no_caps_or_guard_changes(field):
    config = profile()
    config["risk_limits"][field] += 1
    with pytest.raises(ValueError, match="risk_limits"):
        validate_observation_config(config)


def test_preparation_is_paused_and_no_overwrite(tmp_path):
    output = tmp_path / "review"
    result = prepare(output, "sol")
    assert not result["started"] and not result["setup_complete"]
    config = yaml.safe_load((output / "controller.yml").read_text())
    original = yaml.safe_load((ROOT / "conf/controllers/conf_flyby_sol.yml").read_text())
    assert config == {**original, "runtime_oversight_mode": "observe"}
    assert config["manual_kill_switch"] and config["risk_state_id"] == "flyby-competition"
    loop = yaml.safe_load((output / "condor.yml").read_text())
    validate_observation_config(loop, require_setup=False)
    with pytest.raises(FileExistsError):
        prepare(output, "sol")
    assert yaml.safe_load((output / "controller.yml").read_text()) == config


def test_preparation_rejects_links_and_invalid_setup_before_writing(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="linked"):
        prepare(link / "review", "sol")
    with pytest.raises(ValueError):
        prepare(tmp_path / "invalid", "sol", agent_key=None)
    assert not (tmp_path / "invalid").exists()

