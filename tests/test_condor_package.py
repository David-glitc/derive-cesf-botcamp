"""Condor packaging boundaries; no live runtime, credentials or API calls."""
from pathlib import Path
import shutil

import pytest
import yaml

from scripts.check_condor_package import FIXED_SETTINGS, LOOP_ID, PROFILE_ID, validate_package
from scripts.install_condor import install

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def candidate(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "condor", root / "condor")
    shutil.copytree(ROOT / "conf", root / "conf")
    return root


def replace_frontmatter(path, change):
    _, meta, body = path.read_text().split("---\n", 2)
    values = yaml.safe_load(meta)
    change(values)
    path.write_text("---\n" + yaml.safe_dump(values, sort_keys=False) + "---\n" + body)


def test_package_has_a_continuous_live_operator_loop():
    verdict = validate_package()
    assert verdict["loop_id"] == LOOP_ID and verdict["profile_id"] == PROFILE_ID
    assert verdict["tick_verified"] is False and verdict["orders_submitted"] == 0


def test_missing_loop_is_a_build_blocker(candidate):
    (candidate / "condor/flyby/loops/flyby_operator/loop.md").unlink()
    with pytest.raises(FileNotFoundError): validate_package(candidate)


@pytest.mark.parametrize("key,value", [("execution_mode", "dry_run"), ("execution_mode", "run_once"),
    ("restart_on_boot", True), ("restart_on_boot", 0), ("bot_mode", "executors"),
    ("bot_name", "unrelated-bot"), ("total_amount_quote", 1600), ("max_ticks", 1),
    ("frequency_sec", 1), ("tick_timeout_sec", 60),
    ("server_name", "old-testnet"), ("agent_key", "hardcoded-model")])
def test_changed_loop_defaults_are_rejected(candidate, key, value):
    replace_frontmatter(candidate / "condor/flyby/loops/flyby_operator/loop.md",
                        lambda m: m["default_config"].update({key: value}))
    with pytest.raises(ValueError, match="invalid_condor_loop_contract"): validate_package(candidate)


@pytest.mark.parametrize("tools", [[], ["manage_bots"], ["run_code"], ["delegate"]])
def test_unrestricted_or_wrong_tools_are_rejected(candidate, tools):
    replace_frontmatter(candidate / "condor/flyby/AGENT.md", lambda m: m.update(tools=tools))
    with pytest.raises(ValueError, match="invalid_condor_tools_or_binding"): validate_package(candidate)


@pytest.mark.parametrize("key,value", [("strategy_profile", "competition_scalp"),
    ("risk_fraction", .01), ("max_notional_fraction", .30), ("leverage", 3),
    ("total_amount_quote", 1600), ("risk_state_id", "new-risk"), ("condor_active", True),
    ("interval", "15m"), ("options_signal_enabled", False), ("option_buy_delta_target", .9)])
def test_identical_but_unreviewed_samples_still_fail(candidate, key, value):
    for path in (candidate / "conf/controllers/conf_flyby_eth.yml",
                 candidate / "condor/flyby/controllers/derive_cesf_long_vol/sample_configs/eth.yml"):
        config = yaml.safe_load(path.read_text())
        config[key] = value
        path.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError, match="fixed_controller_profile_mismatch"): validate_package(candidate)


def test_unknown_signal_override_is_not_part_of_fixed_profile(candidate):
    for path in (candidate / "conf/controllers/conf_flyby_sol.yml",
                 candidate / "condor/flyby/controllers/derive_cesf_long_vol/sample_configs/sol.yml"):
        config = yaml.safe_load(path.read_text())
        config["signal_source"] = "derive_native"
        path.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError, match="fixed_controller_profile_mismatch"): validate_package(candidate)


def test_identity_cannot_relax_the_fixed_contract(candidate):
    path = candidate / "condor/flyby/PROFILE.yml"
    profile = yaml.safe_load(path.read_text())
    profile["controller_settings"]["risk_fraction"] = .02
    path.write_text(yaml.safe_dump(profile))
    with pytest.raises(ValueError, match="fixed_submission_profile_mismatch"): validate_package(candidate)


def test_loop_must_pin_the_operator_selected_controller_ids(candidate):
    path = candidate / "condor/flyby/loops/flyby_operator/loop.md"
    replace_frontmatter(path, lambda m: m.update(default_trading_context="Only ETH"))
    with pytest.raises(ValueError, match="invalid_condor_loop_contract"): validate_package(candidate)


def test_active_profiles_are_included_and_match_operator_configs(candidate):
    verdict = validate_package(candidate)
    assert set(verdict["active_samples"]) == {"eth", "sol"}
    path = candidate / "condor/flyby/controllers/derive_cesf_long_vol/sample_configs/eth_active.yml"
    profile = yaml.safe_load(path.read_text())
    profile["id"] = "unreviewed-id"
    path.write_text(yaml.safe_dump(profile))
    with pytest.raises(ValueError, match="condor_active_sample_drift:eth"): validate_package(candidate)


def test_matching_active_configs_cannot_silently_raise_risk(candidate):
    for path in (candidate / "conf/controllers/conf_flyby_eth_active.yml",
                 candidate / "condor/flyby/controllers/derive_cesf_long_vol/sample_configs/eth_active.yml"):
        profile = yaml.safe_load(path.read_text())
        profile["risk_fraction"] = .01
        path.write_text(yaml.safe_dump(profile))
    with pytest.raises(ValueError, match="invalid_condor_active_sample:eth"): validate_package(candidate)


@pytest.mark.parametrize("value", [True, {}, {"activation_price": .01}])
def test_explicit_null_trailing_stop_cannot_enable_an_unreviewed_barrier(candidate, value):
    for path in (candidate / "conf/controllers/conf_flyby_eth_active.yml",
                 candidate / "condor/flyby/controllers/derive_cesf_long_vol/sample_configs/eth_active.yml"):
        profile = yaml.safe_load(path.read_text())
        profile["trailing_stop"] = value
        path.write_text(yaml.safe_dump(profile))
    with pytest.raises(ValueError, match="invalid_condor_active_sample:eth"):
        validate_package(candidate)


@pytest.mark.parametrize("name", ["loops/flyby_operator/config.yml", "loops/flyby_operator/state.json",
                                  "credentials.yml", "routines/custom.py"])
def test_runtime_or_unknown_files_cannot_ship(candidate, name):
    path = candidate / "condor/flyby" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture")
    with pytest.raises(ValueError, match="unexpected_or_linked"): validate_package(candidate)


def test_authored_symlink_is_rejected(candidate):
    (candidate / "condor/flyby/link.yml").symlink_to(candidate / "conf/controllers/conf_flyby_eth.yml")
    with pytest.raises(ValueError, match="unexpected_or_linked"): validate_package(candidate)


def test_install_is_explicit_live_loop_complete_and_never_starts_or_overwrites(tmp_path):
    agents = tmp_path / "agents"
    verdict = install(agents)
    assert verdict["started"] is False and verdict["execution_mode"] == "loop"
    source = ROOT / "condor/flyby"
    for path in source.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            assert (agents / "flyby" / path.relative_to(source)).read_bytes() == path.read_bytes()
    sentinel = agents / "flyby/loops/flyby_operator/state.json"
    sentinel.write_text("preserve runtime")
    with pytest.raises(FileExistsError): install(agents)
    assert sentinel.read_text() == "preserve runtime"


def test_failed_validation_writes_no_install_target(candidate, tmp_path):
    (candidate / "condor/flyby/loops/flyby_operator/loop.md").unlink()
    target = tmp_path / "untouched"
    with pytest.raises(FileNotFoundError): install(target, candidate)
    assert not target.exists()


def test_installer_rejects_linked_root(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="linked_condor_agents_root_refused"): install(link)
    assert not (real / "flyby").exists()
