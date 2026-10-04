"""Network boundaries; pure fixtures and filesystem checks, no venue requests."""
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest
import yaml

from agents.mainnet import (execution_environment, require_mainnet_connector,
                           validate_installed_endpoints)
from scripts.check_mainnet import validate_profiles

ROOT = Path(__file__).resolve().parents[1]


def test_submission_profiles_and_manifest_are_mainnet_only():
    validate_profiles()
    assert execution_environment()["api_generation"] == "legacy_v2"


@pytest.mark.parametrize("domain", ["derive_perpetual_testnet", "derive_perpetual_paper_trade", "derive", None])
def test_wrong_or_unknown_connector_domain_is_rejected(domain):
    with pytest.raises(ValueError, match="mainnet_connector_domain_required"):
        require_mainnet_connector(SimpleNamespace(domain=domain))


def test_mainnet_connector_is_accepted_without_account_access():
    require_mainnet_connector(SimpleNamespace(domain="derive_perpetual"))


@pytest.mark.parametrize("key,value", [
    ("DEFAULT_DOMAIN", "derive_perpetual_testnet"),
    ("BASE_URL", "https://api-demo.lyra.finance"),
    ("WSS_URL", "wss://api-demo.lyra.finance/ws"),
    ("BASE_URL", "https://api.derive.xyz/v3/"),
    ("WSS_URL", None),
])
def test_mismatched_installed_endpoints_fail_closed(key, value):
    constants = SimpleNamespace(DEFAULT_DOMAIN="derive_perpetual",
                                BASE_URL="https://api.lyra.finance",
                                WSS_URL="wss://api.lyra.finance/ws")
    validate_installed_endpoints(constants)
    setattr(constants, key, value)
    with pytest.raises(ValueError, match=f"unsupported_mainnet_connector:{key}"):
        validate_installed_endpoints(constants)


@pytest.mark.parametrize("change,reason", [
    ({"connector_name": "derive_perpetual_testnet"}, "mainnet_profile_required"),
    ({"manual_kill_switch": False}, "paused_install_profile_required"),
    ({"trading_pair": "ETH-PERP"}, "hummingbot_quote_pair_required"),
    ({"options_enabled": True}, "unsupported_live_capability"),
])
def test_preflight_rejects_changed_profiles(tmp_path, change, reason):
    shutil.copytree(ROOT / "conf", tmp_path / "conf")
    shutil.copyfile(ROOT / "hummingbot-version.json", tmp_path / "hummingbot-version.json")
    path = tmp_path / "conf/controllers/conf_flyby_eth.yml"
    config = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump({**config, **change}))
    with pytest.raises(ValueError, match=reason):
        validate_profiles(tmp_path)


def test_manifest_cannot_claim_v3_for_legacy_install(tmp_path):
    shutil.copytree(ROOT / "conf", tmp_path / "conf")
    manifest = json.loads((ROOT / "hummingbot-version.json").read_text())
    manifest["execution_environment"]["api_generation"] = "v3"
    (tmp_path / "hummingbot-version.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="mainnet_manifest_mismatch"):
        validate_profiles(tmp_path)


@pytest.mark.parametrize("selected", [[], ["testnet.yml"], ["conf_flyby_eth.yml"] * 2, [None]])
def test_launcher_cannot_import_unchecked_profiles(tmp_path, selected):
    shutil.copytree(ROOT / "conf", tmp_path / "conf")
    shutil.copyfile(ROOT / "hummingbot-version.json", tmp_path / "hummingbot-version.json")
    (tmp_path / "conf/scripts/conf_v2_flyby.yml").write_text(yaml.safe_dump({"controllers_config": selected}))
    with pytest.raises(ValueError, match="approved_mainnet_launcher_required"):
        validate_profiles(tmp_path)


def test_preflight_handles_empty_profile_without_uncontrolled_error(tmp_path):
    shutil.copytree(ROOT / "conf", tmp_path / "conf")
    (tmp_path / "conf/controllers/conf_flyby_eth.yml").write_text("")
    with pytest.raises(ValueError, match="invalid_profile:eth"):
        validate_profiles(tmp_path)


@pytest.mark.parametrize("change", [{"manual_kill_switch": False}, {"risk_fraction": .02},
    {"options_execution_mode": "v3"}, {"total_amount_quote": 1600}])
def test_optional_rfq_samples_cannot_silently_unpause_or_widen_risk(tmp_path, change):
    shutil.copytree(ROOT / "conf", tmp_path / "conf")
    shutil.copyfile(ROOT / "hummingbot-version.json", tmp_path / "hummingbot-version.json")
    path = tmp_path / "conf/controllers/conf_flyby_options_eth.yml"
    profile = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump({**profile, **change}))
    with pytest.raises(ValueError, match="fixed_paused_rfq_settings_required"):
        validate_profiles(tmp_path)


@pytest.mark.parametrize("change", [{"risk_fraction": .01}, {"max_notional_fraction": .30},
    {"leverage": 3}, {"total_amount_quote": 1600}, {"condor_active": True},
    {"signal_source": "derive_native"}, {"id": "new-history"}, {"interval": "15m"}])
def test_fixed_profile_preflight_refuses_caps_or_signal_drift(tmp_path, change):
    shutil.copytree(ROOT / "conf", tmp_path / "conf")
    path = tmp_path / "conf/controllers/conf_flyby_eth.yml"
    profile = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump({**profile, **change}))
    with pytest.raises(ValueError, match="fixed_submission_settings_required"):
        validate_profiles(tmp_path)


def test_installer_preflight_precedes_all_mutations():
    script = (ROOT / "scripts/install_hummingbot.sh").read_text()
    check = script.index('python "$repo_dir/scripts/check_mainnet.py"')
    assert check < script.index('package_dir="$(mktemp -d)"')
    assert check < script.index("python -m pip install")
    assert check < script.index("install -d")


def test_failed_installer_preflight_does_not_write_target(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "agents").mkdir()
    for name in ("install_hummingbot.sh", "check_mainnet.py"):
        shutil.copyfile(ROOT / "scripts" / name, repo / "scripts" / name)
    shutil.copyfile(ROOT / "agents/mainnet.py", repo / "agents/mainnet.py")
    shutil.copytree(ROOT / "conf", repo / "conf")
    shutil.copyfile(ROOT / "hummingbot-version.json", repo / "hummingbot-version.json")
    path = repo / "conf/controllers/conf_flyby_eth.yml"
    profile = yaml.safe_load(path.read_text())
    profile["connector_name"] = "derive_perpetual_testnet"
    path.write_text(yaml.safe_dump(profile))
    target = tmp_path / "hb"
    (target / "hummingbot/strategy_v2").mkdir(parents=True)
    result = subprocess.run(["bash", str(repo / "scripts/install_hummingbot.sh"), str(target)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert not (target / "conf").exists()
    assert not (target / "controllers").exists()
