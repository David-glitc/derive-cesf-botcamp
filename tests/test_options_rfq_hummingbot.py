"""Pinned HB RFQ signer/serializer/controller tests; OFFLINE, fixture key only."""
import asyncio
from copy import deepcopy
from decimal import Decimal
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml

pytest.importorskip("hummingbot", reason="Requires the pinned Hummingbot image")
from eth_abi import encode, decode
from web3 import Web3
from hummingbot.connector.derivative.derive_perpetual.derive_perpetual_auth import DerivePerpetualAuth
from hummingbot.connector.other.derive_common_utils import SignedAction
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, RESTRequest
from controllers.directional_trading.flyby import DeriveCesfLongVolConfig, DeriveCesfLongVolController
from src.execution.derive_rfq import DeriveRFQTransport, ExecuteModuleData, RFQ_MODULE
from src.execution.options_rfq import RFQJournal, OptionsRFQ
from src.execution.derive_hb import update_balances
from src.risk.competition import account_binding
from src.risk.exposure import ETH_EXPOSURE_TEST
from tests.test_options_rfq import Transport, NOW, plan, instrument
from tests.test_derive_hb_compat import fake_connector
from tests.test_condor_hummingbot import controller, ROOT


def signer_fixture():
    # Public deterministic test identity; not read from a credential store.
    key = (1).to_bytes(32, "big")
    return DerivePerpetualAuth("0x" + "23" * 20, key, 42, True, "derive_perpetual")


def quote_fixture():
    legs = [dict(instrument_name="ETH-A", direction="buy", amount=".01", price="300"),
            dict(instrument_name="ETH-B", direction="sell", amount=".01", price="100")]
    inst = {"ETH-A": instrument("ETH-A", 3000), "ETH-B": instrument("ETH-B", 4000)}
    module = ExecuteModuleData(legs, inst, Decimal(".05"))
    return dict(quote_id="quote-1", rfq_id="rfq-1", legs=legs, creation_timestamp=NOW * 1000,
                legs_hash="0x" + module.legs_hash().hex().removeprefix("0x")), inst, module


def test_abi_matches_official_maker_opposite_quantity_layout():
    quote, inst, module = quote_fixture()
    expected_hash = Web3.keccak(encode(["(address,uint,uint,int)[]"], [[
        (Web3.to_checksum_address(inst["ETH-A"]["base_asset_address"]), 1, 300 * 10**18, -10**16),
        (Web3.to_checksum_address(inst["ETH-B"]["base_asset_address"]), 2, 100 * 10**18, 10**16)]]))
    assert module.legs_hash() == expected_hash
    assert decode(["bytes32", "uint"], module.to_abi_encoded()) == (expected_hash, 5 * 10**16)


def test_real_hb_signer_and_auth_serializer_preserve_atomic_payload():
    quote, inst, module = quote_fixture()
    connector = SimpleNamespace(domain="derive_perpetual", FLYBY_COMPATIBILITY_VERSION="flyby-derive-2.17.0-r1",
        _subacct_id=42, _auth=signer_fixture(), current_timestamp=NOW, _account_available_balances={})
    calls = []
    async def post(**kwargs):
        calls.append(kwargs)
        if kwargs["path_url"] == "/public/get_instrument":
            return {"result": inst[kwargs["data"]["instrument_name"]]}
        assert kwargs["path_url"] == "/private/execute_quote"
        return {"result": {"tx_status": "requested"}}
    connector._api_post = post
    adapter = DeriveRFQTransport(connector)
    asyncio.run(adapter.execute(quote, ".05", 1800000000000000, "owned-rfq", NOW, plan(), "entry"))
    sent = calls[-1]["data"]
    assert len(sent["legs"]) == 2 and "type" not in sent and sent["direction"] == "buy"
    assert sent["signature_expiry_sec"] == NOW + 600 and calls[-1]["is_auth_required"] is True
    action = SignedAction(subaccount_id=42, owner=connector._auth._wallet_address, signer=sent["signer"],
        signature_expiry_sec=sent["signature_expiry_sec"], nonce=sent["nonce"], module_address=RFQ_MODULE,
        module_data=module, DOMAIN_SEPARATOR=adapter.constants.DOMAIN_SEPARATOR,
        ACTION_TYPEHASH=adapter.constants.ACTION_TYPEHASH, signature=sent["signature"])
    action.validate_signature()
    request = RESTRequest(method=RESTMethod.POST, url="https://api.lyra.finance/private/execute_quote", data=json.dumps(sent))
    encoded = connector._auth.add_auth_to_params_post(deepcopy(sent), request)
    assert json.loads(encoded) == sent


@pytest.mark.parametrize("mutation", ["hash", "clock", "expiry", "type", "strike", "lot", "kind"])
def test_pre_sign_validation_never_submits_an_invalid_spread(mutation):
    quote, inst, _ = quote_fixture()
    connector = SimpleNamespace(domain="derive_perpetual", FLYBY_COMPATIBILITY_VERSION="flyby-derive-2.17.0-r1",
        _subacct_id=42, _auth=signer_fixture(), current_timestamp=NOW, _account_available_balances={})
    if mutation == "hash": quote["legs_hash"] = "0x" + "00" * 32
    if mutation == "clock": connector.current_timestamp += 6
    if mutation == "expiry": inst["ETH-A"]["option_details"]["expiry"] += 1
    if mutation == "type": inst["ETH-A"]["instrument_type"] = "perp"
    if mutation == "strike": inst["ETH-A"]["option_details"]["strike"] = "5000"
    if mutation == "lot": inst["ETH-A"]["amount_step"] = ".03"
    if mutation == "kind": inst["ETH-A"]["option_details"]["option_type"] = "P"
    calls = []
    async def post(**kwargs):
        calls.append(kwargs["path_url"])
        return {"result": inst[kwargs["data"]["instrument_name"]]}
    connector._api_post = post
    with pytest.raises(ValueError):
        asyncio.run(DeriveRFQTransport(connector).execute(quote, ".05", 1, "owned", NOW, plan(), "entry"))
    assert "/private/execute_quote" not in calls


def test_compatibility_retains_options_in_full_snapshot_not_perp_map():
    c = fake_connector()
    c._flyby_rfq_enabled = True
    raw = c._api_post.return_value["result"]
    raw["positions"] = [dict(instrument_type="option", instrument_name="ETH-A", amount=".01")]
    asyncio.run(update_balances(c))
    assert c._flyby_account_state["positions"] == raw["positions"]
    assert c._perpetual_trading.account_positions == {}


def test_rfq_profiles_load_paused_with_unchanged_risk_caps():
    for market in ("eth", "btc"):
        raw = yaml.safe_load((ROOT / f"conf/controllers/conf_flyby_options_{market}.yml").read_text())
        config = DeriveCesfLongVolConfig(**raw)
        assert config.options_enabled and config.options_execution_mode == "rfq_v2" and config.manual_kill_switch
        assert config.total_amount_quote == 800 and config.risk_fraction == .005
        assert config.max_notional_fraction == .20
    with pytest.raises(ValueError):
        DeriveCesfLongVolConfig(id="bad", trading_pair="ETH-USDC", options_enabled=True)


def test_approved_eth_exposure_sample_is_separate_paused_and_propagates_to_rfq(tmp_path):
    raw = yaml.safe_load((ROOT / "conf/controllers/conf_flyby_eth_exposure_test.yml").read_text())
    config = DeriveCesfLongVolConfig(**raw)
    assert config.manual_kill_switch and config.exposure_profile == ETH_EXPOSURE_TEST
    assert config.max_notional_fraction == .40 and config.max_gross_exposure_fraction == .40
    assert config.option_gross_fraction == .75 and config.total_amount_quote == 800 and config.risk_fraction == .005
    ctl, provider = controller(tmp_path)
    ctl.config = config
    ctl._ensure_options(provider.connector)
    assert ctl._options.exposure_profile == ETH_EXPOSURE_TEST and ctl._options.underlying == "ETH"
    from src.accounting.context import controller_context
    risk = controller_context(ctl, NOW)["risk"]
    assert risk["exposure_profile"] == ETH_EXPOSURE_TEST
    assert risk["option_gross_fraction"] == .75 and risk["option_delta_fraction"] == .20


@pytest.mark.parametrize("change", [{"trading_pair": "BTC-USDC", "candles_trading_pair": "BTC-USDT"},
    {"risk_fraction": .01}, {"total_amount_quote": 1600}, {"option_gross_fraction": .80},
    {"max_notional_fraction": .41}, {"max_gross_exposure_fraction": .30}])
def test_eth_exposure_profile_cannot_widen_other_limits(change):
    raw = yaml.safe_load((ROOT / "conf/controllers/conf_flyby_eth_exposure_test.yml").read_text())
    with pytest.raises(ValueError):
        DeriveCesfLongVolConfig(**{**raw, **change})


@pytest.mark.parametrize("change", [{"max_notional_fraction": .40}, {"option_gross_fraction": .75},
                                     {"max_gross_exposure_fraction": .40}])
def test_baseline_config_cannot_inherit_wider_caps_without_identity(change):
    with pytest.raises(ValueError):
        DeriveCesfLongVolConfig(id="reject-caps", trading_pair="ETH-USDC", **change)


def test_canonical_controller_uses_approved_caps_in_both_entry_sizers(tmp_path, monkeypatch):
    import controllers.directional_trading.flyby as module
    from tests.test_flyby_policy import chain
    ctl, provider = controller(tmp_path)
    raw = yaml.safe_load((ROOT / "conf/controllers/conf_flyby_eth_exposure_test.yml").read_text())
    # Offline action fixture only. The shipped file above remains paused.
    ctl.config = DeriveCesfLongVolConfig(**{**raw, "manual_kill_switch": False})
    ctl.processed_data.update(signal=1, halt=False, confidence=.8, atr_pct=.004)
    sizing, policies = [], []
    original_size, original_policy = module.risk_size, module.account_policy
    def size(**kwargs):
        sizing.append(kwargs)
        return original_size(**kwargs)
    def policy(*args, **kwargs):
        result = original_policy(*args, **kwargs)
        policies.append((kwargs, result))
        return result
    monkeypatch.setattr(module, "risk_size", size)
    monkeypatch.setattr(module, "account_policy", policy)
    ctl.create_actions_proposal()
    assert sizing and sizing[-1]["notional_fraction"] == .40 and sizing[-1]["gross_cap"] == 320
    assert sizing[-1]["exposure_profile"] == ETH_EXPOSURE_TEST
    assert sizing[-1]["trade_risk_budget"] == 4 and sizing[-1]["risk_fraction"] == .005
    ctl.plan_options(chain(), NOW, .04)
    assert policies and policies[-1][0]["gross_fraction"] == .75
    assert policies[-1][0]["net_fraction"] == .20
    assert policies[-1][1].gross_cap_quote == 597
    assert policies[-1][1].net_cap_quote == pytest.approx(159.2)


def wired_controller(tmp_path):
    ctl, provider = controller(tmp_path)
    ctl.config = DeriveCesfLongVolConfig(**{**ctl.config.model_dump(), "options_enabled": True,
        "options_execution_mode": "rfq_v2", "manual_kill_switch": False})
    t = Transport()
    j = RFQJournal(ctl._options_path(), account_binding(provider.connector), ctl.config.id)
    ctl._options = OptionsRFQ(t, j, 42)
    ctl.processed_data.update(spread_plan=plan(), valid=True, signal=1, halt=False, updated_at=NOW,
                              trend_z=2., previous_trend_z=2., volume_ratio=2., previous_volume_ratio=2.,
                              efficiency=.9, previous_efficiency=.9, reconciled=True, entry_allowed=True)
    return ctl, provider, t


def test_canonical_controller_routes_atomic_options_and_blocks_perp_actions(tmp_path):
    ctl, provider, t = wired_controller(tmp_path)
    asyncio.run(ctl._service_options())
    assert ctl._options.journal.state["phase"] == "quoting_entry"
    assert ctl.create_actions_proposal() == []
    t.offer(ctl._options)
    asyncio.run(ctl._service_options())  # own reservation must NOT cancel own RFQ
    assert ctl._options.journal.state["phase"] == "settling" and t.writes == ["send", "execute"]
    t.settle(ctl._options)
    asyncio.run(ctl._service_options())
    assert ctl._options.journal.state["phase"] == "open"


def test_stale_entry_data_still_services_owned_paired_exit(tmp_path):
    ctl, provider, t = wired_controller(tmp_path)
    asyncio.run(ctl._service_options())
    t.offer(ctl._options)
    asyncio.run(ctl._service_options())
    t.settle(ctl._options)
    asyncio.run(ctl._service_options())
    ctl._halt("stale_order_book")
    asyncio.run(ctl._service_options())
    assert ctl._options.journal.state["intent"] == "exit"
    t.offer(ctl._options, "310", "100")
    asyncio.run(ctl._service_options())
    assert ctl._options.journal.state["phase"] == "settling"
    assert t.writes.count("execute") == 2


def test_drawdown_latches_against_fresh_account_before_entry_execute(tmp_path):
    ctl, provider, t = wired_controller(tmp_path)
    asyncio.run(ctl._service_options())
    t.offer(ctl._options)
    original = t.account
    async def account():
        result = await original()
        result["equity"] = Decimal(600)  # exactly -25% from $800 peak
        return result
    t.account = account
    asyncio.run(ctl._service_options())
    assert "execute" not in t.writes and ctl._options.journal.state["phase"] == "cancelling"
    _, risk = ctl._risk_store.observe(Decimal(800), NOW)
    assert risk["risk_mode"] == "hard_stop"  # recovery doesn't clear latch


def test_owned_options_exposure_and_greeks_are_visible_to_condor(tmp_path, monkeypatch):
    from src.accounting.context import controller_context
    monkeypatch.chdir(tmp_path)
    ctl, provider, t = wired_controller(tmp_path)
    asyncio.run(ctl._service_options())
    t.offer(ctl._options)
    asyncio.run(ctl._service_options())
    t.settle(ctl._options)
    asyncio.run(ctl._service_options())
    state = provider.connector._flyby_account_state
    state["positions"] = asyncio.run(t.account())["positions"]
    state["observed_at"] = NOW
    account = ctl._account(provider.connector, NOW)
    assert account["committed"] == 60 and not account["entry_allowed"] and account["reconciled"]
    context = controller_context(ctl, NOW)
    assert len(context["positions"]) == 2 and context["positions"][0]["delta"] is not None
    assert context["options_execution"]["phase"] == "open"
    assert context["options_delta"]["execution_mode"] == "atomic_rfq_v2"
