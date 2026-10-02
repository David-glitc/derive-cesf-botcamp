from pathlib import Path

import pytest
import yaml

from scripts.prepare_competition_profile import prepare
from src.risk.competition import POLICY

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("market", ["ETH", "BTC", "SOL", "HYPE"])
@pytest.mark.parametrize("profile", ["baseline", "competition_scalp"])
def test_preparation_preserves_caps_account_identity_and_pause(tmp_path, market, profile):
    output = tmp_path / "new.yml"
    result = prepare(market, profile, output)
    config = yaml.safe_load(output.read_text())
    canonical = yaml.safe_load((ROOT / f"conf/controllers/conf_flyby_{market.lower()}.yml").read_text())
    assert result["orders_submitted"] == 0 and not result["installed"] and not result["live_ready"]
    assert config["manual_kill_switch"] and not config["options_enabled"]
    assert config["risk_policy"] == POLICY and config["strategy_profile"] == profile
    assert config["cooldown_time"] == (60 if profile == "competition_scalp" else 300)
    for key in ("risk_fraction", "max_notional_fraction", "total_amount_quote", "leverage", "id", "risk_state_id"):
        assert config[key] == canonical[key]
    before = output.read_bytes()
    with pytest.raises(FileExistsError): prepare(market, profile, output)
    assert output.read_bytes() == before


@pytest.mark.parametrize("market,profile", [("BASE", "baseline"), ("SOL", "guaranteed_win"), ("../bad", "baseline")])
def test_preparation_rejects_unknown_choices(tmp_path, market, profile):
    with pytest.raises(ValueError): prepare(market, profile, tmp_path / "unsafe.yml")
