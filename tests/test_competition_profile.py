from pathlib import Path
import yaml
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_default_launch_does_not_enable_fallback_markets():
    config = yaml.safe_load((ROOT / "conf/scripts/conf_v2_flyby.yml").read_text())
    assert config["controllers_config"] == ["conf_flyby_eth.yml"]


@pytest.mark.parametrize("name", ["eth", "btc", "sol", "hype"])
def test_profiles_require_correct_perp_contract(name):
    config = yaml.safe_load((ROOT / f"conf/controllers/conf_flyby_{name}.yml").read_text())
    assert config["connector_name"] == "derive_perpetual"
    assert config["position_mode"] == "ONEWAY"
    assert config["candles_connector"] == "binance_perpetual"
    assert config["manual_kill_switch"] is True
    assert all(config[key] is False for key in ("options_enabled", "portfolio_margin", "spot_hedge_enabled"))
