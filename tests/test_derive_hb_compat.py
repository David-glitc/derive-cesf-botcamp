"""Real pinned Hummingbot classes, mocked transport and synthetic account state."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("hummingbot")
from hummingbot.connector.derivative.derive_perpetual.derive_perpetual_derivative import DerivePerpetualDerivative as Connector
from hummingbot.connector.perpetual_trading import PerpetualTrading
from hummingbot.core.data_type.common import PositionAction, PositionMode, TradeType, OrderType
from hummingbot.strategy_v2.executors.position_executor.position_executor import PositionExecutor
from tests.test_submission_hardening import account_result
from src.execution.derive_hb import COMPATIBILITY_VERSION, process_balance


def instrument():
    return {"instrument_type": "perp", "instrument_name": "ETH-PERP", "is_active": True,
            "base_asset_address": "0x" + "1" * 40, "base_asset_sub_id": "0", "minimum_amount": ".1",
            "amount_step": ".001", "tick_size": ".01", "maker_fee_rate": ".0001",
            "taker_fee_rate": ".0003", "base_fee": ".01"}


def fake_connector(result=None):
    c = SimpleNamespace(domain="derive_perpetual", _subacct_id=7, current_timestamp=100,
        _account_balances={}, _account_available_balances={}, _instrument_ticker=[instrument()],
        _perpetual_trading=PerpetualTrading(["ETH-USDC"]), get_mid_price=lambda _: Decimal("2717.93"),
        exchange_symbol_associated_to_pair=AsyncMock(return_value="ETH-PERP"),
        trading_pair_associated_to_exchange_symbol=AsyncMock(return_value="ETH-USDC"),
        _api_post=AsyncMock(return_value={"result": result or account_result()}))
    return c


def test_source_guard_marks_actual_installed_connector():
    assert Connector.FLYBY_COMPATIBILITY_VERSION == COMPATIBILITY_VERSION


def test_actual_symbol_mapping_is_quote_currency_not_venue_instrument():
    c = Connector.__new__(Connector)
    c._initialize_trading_pair_symbols_from_exchange_info([instrument()])
    assert asyncio.run(c.exchange_symbol_associated_to_pair("ETH-USDC")) == "ETH-PERP"
    assert asyncio.run(c.trading_pair_associated_to_exchange_symbol("ETH-PERP")) == "ETH-USDC"


@pytest.mark.parametrize("side", [TradeType.BUY, TradeType.SELL])
@pytest.mark.parametrize("action", [PositionAction.OPEN, PositionAction.CLOSE])
@pytest.mark.parametrize("kind", [OrderType.LIMIT, OrderType.LIMIT_MAKER, OrderType.MARKET])
def test_actual_payload_preserves_ticks_reduce_only_and_post_only(side, action, kind):
    c = fake_connector()
    c._api_post.return_value = {"result": {"order": {"order_id": "synthetic-order", "creation_timestamp": 100000}}}
    if kind == OrderType.LIMIT_MAKER and action == PositionAction.CLOSE:
        with pytest.raises(ValueError, match="reduce_only_cannot_rest"):
            asyncio.run(Connector._place_order(c, "owned", "ETH-USDC", Decimal(".1"), side,
                                              kind, Decimal("2718.09"), action))
        c._api_post.assert_not_called()
        return
    outcome = asyncio.run(Connector._place_order(c, "owned", "ETH-USDC", Decimal(".1"), side,
                                                kind, Decimal("2718.09"), action))
    payload = c._api_post.call_args.kwargs["data"]
    assert payload["amount"] == "0.1"
    if kind != OrderType.MARKET:
        assert payload["limit_price"] == "2718.09"
    else:
        limit = Decimal(payload["limit_price"])
        assert limit % Decimal(".01") == 0
        if side == TradeType.BUY:
            assert Decimal("2717.93") < limit <= Decimal("2717.93") * Decimal("1.0015")
        else:
            assert Decimal("2717.93") > limit >= Decimal("2717.93") * Decimal(".9985")
    assert payload["reduce_only"] == (action == PositionAction.CLOSE)
    assert payload["time_in_force"] == ("post_only" if kind == OrderType.LIMIT_MAKER else
                                       "ioc" if kind == OrderType.MARKET or action == PositionAction.CLOSE else "gtc")
    assert Decimal(payload["max_fee"]) < 1000
    assert outcome == ("synthetic-order", 100)
    assert c._flyby_account_state is None


def test_self_cross_error_never_returns_false_success():
    c = fake_connector(); c._api_post.return_value = {"error": {"message": "Self-crossing disallowed"}}
    with pytest.raises(IOError, match="derive_order_rejected"):
        asyncio.run(Connector._place_order(c, "owned", "ETH-USDC", Decimal(".1"), TradeType.BUY,
                                          OrderType.LIMIT, Decimal("2718.09"), PositionAction.OPEN))


@pytest.mark.parametrize("amount,price", [(".01", "2718.09"), (".1005", "2718.09"), (".1", "2718.091"), ("NaN", "2718.09")])
def test_invalid_order_never_reaches_mock_transport(amount, price):
    c = fake_connector()
    with pytest.raises(ValueError):
        asyncio.run(Connector._place_order(c, "owned", "ETH-USDC", Decimal(amount), TradeType.BUY,
                                          OrderType.LIMIT, Decimal(price), PositionAction.OPEN))
    c._api_post.assert_not_called()


def test_full_snapshot_replaces_closed_positions_and_has_real_net_margin():
    r = account_result()
    r["positions"] = [{"instrument_type": "perp", "instrument_name": "ETH-PERP", "amount": ".1",
                        "average_price": "2700", "index_price": "2717.93", "unrealized_pnl": "1.793", "leverage": "1"}]
    c = fake_connector(r)
    asyncio.run(Connector._update_balances(c))
    assert c._flyby_account_state["available"] == 600
    p = c._perpetual_trading.account_positions["ETH-USDC"]
    assert p.entry_price == 2700 and p.amount == Decimal(".1")
    c._api_post.return_value = {"result": account_result()}
    asyncio.run(Connector._update_positions(c))
    assert c._perpetual_trading.account_positions == {}
    assert c._flyby_account_state["equity"] == 800


def test_bad_refresh_invalidates_old_margin_without_inventing_flat_account():
    c = fake_connector(); asyncio.run(Connector._update_balances(c))
    c._perpetual_trading.account_positions["known"] = object()
    c._api_post.return_value = {"error": {"message": "synthetic outage"}}
    with pytest.raises(ValueError): asyncio.run(Connector._update_balances(c))
    assert c._flyby_account_state is None and c._account_available_balances["USDC"] == 0
    assert "known" in c._perpetual_trading.account_positions


def test_stream_delta_cannot_authorize_entry_as_full_margin():
    c = fake_connector(); asyncio.run(Connector._update_balances(c))
    process_balance(c, {"asset_name": "USDC", "amount": "999999"})
    assert c._flyby_account_state is None and c._account_available_balances["USDC"] == 0


@pytest.mark.parametrize("connector,mode,expected", [
    ("derive_perpetual", PositionMode.ONEWAY, PositionAction.CLOSE),
    ("binance_perpetual", PositionMode.ONEWAY, PositionAction.OPEN),
    ("binance_perpetual", PositionMode.HEDGE, PositionAction.CLOSE)])
def test_actual_executor_close_branch_changes_only_derive(connector, mode, expected):
    e = SimpleNamespace(is_perpetual=True, config=SimpleNamespace(connector_name=connector),
                        connectors={connector: SimpleNamespace(position_mode=mode)})
    assert PositionExecutor.close_position_action.fget(e) == expected


def test_auth_existing_serializer_retains_post_only_and_reduce_only():
    from hummingbot.connector.derivative.derive_perpetual.derive_perpetual_web_utils import order_to_call
    payload = dict(instrument_name="ETH-PERP", direction="sell", order_type="limit",
                   reduce_only=True, referral_code="", mmp=False, time_in_force="post_only", label="owned")
    serialized = order_to_call(payload)
    assert serialized["reduce_only"] is True and serialized["time_in_force"] == "post_only"
