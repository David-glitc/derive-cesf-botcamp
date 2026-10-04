"""Approved ETH exposure identity; no larger loss budget or automatic activation."""
from decimal import Decimal
from pathlib import Path
import shutil

import pytest
import yaml

from scripts.check_mainnet import validate_profiles
from src.options.delta import account_policy
from src.execution.options_rfq import exposure_requires_exit, OptionsRFQ, RFQJournal
from src.risk.competition import initial_state, risk_view
from src.risk.exposure import ETH_EXPOSURE_TEST
from src.risk.position_sizing import risk_size
from tests.test_options_rfq import Transport, NOW, plan

ROOT = Path(__file__).resolve().parents[1]


def test_exact_approved_option_caps_and_restricted_scale():
    policy = account_policy(3000, 800, underlying="ETH", exposure_profile=ETH_EXPOSURE_TEST, gross_fraction=.75)
    assert policy.net_cap_quote == 160 and policy.gross_cap_quote == 600
    restricted = account_policy(3000, 720, underlying="ETH", exposure_profile=ETH_EXPOSURE_TEST,
                                gross_fraction=.75, scale=.25)
    assert restricted.net_cap_quote == 36 and restricted.gross_cap_quote == 135
    with pytest.raises(ValueError):
        account_policy(3000, 800, gross_fraction=.75)
    with pytest.raises(ValueError):
        account_policy(90000, 800, underlying="BTC", exposure_profile=ETH_EXPOSURE_TEST, gross_fraction=.75)
    with pytest.raises(ValueError):
        account_policy(3000, 800, underlying="ETH", exposure_profile=ETH_EXPOSURE_TEST, net_fraction=.21)


def test_perp_cap_increases_only_with_identity_and_preserves_loss_budget():
    kwargs = dict(equity=800, available=800, committed=0, confidence=1, stop_pct=.005,
                  gross_cap=320, notional_fraction=.40, size_scale=1, trade_risk_budget=4)
    assert risk_size(**kwargs) == 0
    assert risk_size(**kwargs, exposure_profile=ETH_EXPOSURE_TEST, underlying="ETH") == 320
    assert risk_size(**kwargs, exposure_profile=ETH_EXPOSURE_TEST, underlying="BTC") == 0
    kwargs["stop_pct"] = .02
    assert risk_size(**kwargs, exposure_profile=ETH_EXPOSURE_TEST, underlying="ETH") == 200
    assert risk_view(initial_state(800, NOW, 800, "test"), 800)["risk_trade_budget"] == 4


def account(amount=".1", spot="2680"):
    return dict(equity="800", available="800", positions=[
        dict(instrument_name="ETH-A", amount=amount, delta=".5", index_price=spot),
        dict(instrument_name="ETH-B", amount="-" + amount, delta=".25", index_price=spot)])


def test_paired_exit_respects_approved_gross_and_unchanged_delta():
    p = {**plan(), "gross_cap_quote": 600, "net_cap_quote": 160}
    assert exposure_requires_exit(account(), p)  # baseline 30% still rejects
    assert not exposure_requires_exit(account(), p, exposure_profile=ETH_EXPOSURE_TEST)
    assert exposure_requires_exit(account(spot="3100"), p, exposure_profile=ETH_EXPOSURE_TEST)
    a = account()
    a["positions"][1]["delta"] = "-.25"  # directional exposure > unchanged $160
    assert exposure_requires_exit(a, p, exposure_profile=ETH_EXPOSURE_TEST)
    p["gross_cap_quote"] = 240  # old owned plan never gains a wider stored cap
    assert exposure_requires_exit(account(), p, exposure_profile=ETH_EXPOSURE_TEST)


def test_live_entry_cap_recheck_does_not_trust_plan_declared_caps(tmp_path):
    t = Transport()
    c = OptionsRFQ(t, RFQJournal(tmp_path / "rfq.json", "test", "owner"), 42,
                   exposure_profile=ETH_EXPOSURE_TEST, underlying="ETH")
    p = {**plan(), "gross_cap_quote": 9999, "gross_reference_quote": 610}
    with pytest.raises(ValueError, match="configured_exposure"):
        c._validate_plan(p, NOW, Decimal(4), dict(equity="800", available="800"))
    p["gross_reference_quote"] = 550
    c._validate_plan(p, NOW, Decimal(4), dict(equity="800", available="800"))
    with pytest.raises(ValueError, match="configured_exposure"):
        c._validate_plan(p, NOW, Decimal(4), dict(equity="720", available="720"))
    p["underlying"] = "BTC"
    with pytest.raises(ValueError):
        c._validate_plan(p, NOW, Decimal(4), dict(equity="800", available="800"))


@pytest.mark.parametrize("change", [{"manual_kill_switch": False}, {"risk_fraction": .01},
    {"option_gross_fraction": .80}, {"max_notional_fraction": .50}, {"total_amount_quote": 1600},
    {"risk_state_id": "reset-checkpoint"}, {"trading_pair": "BTC-USDC"}])
def test_install_preflight_rejects_exposure_test_drift(tmp_path, change):
    shutil.copytree(ROOT / "conf", tmp_path / "conf")
    shutil.copyfile(ROOT / "hummingbot-version.json", tmp_path / "hummingbot-version.json")
    path = tmp_path / "conf/controllers/conf_flyby_eth_exposure_test.yml"
    raw = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump({**raw, **change}))
    with pytest.raises(ValueError, match="fixed_paused_eth_exposure_test"):
        validate_profiles(tmp_path)
