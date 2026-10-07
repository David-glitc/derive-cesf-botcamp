"""Explicit pinned Hummingbot compatibility delegates. Never patched on import.

Only the offline compatibility installer links these functions into Hummingbot.
They use the existing authenticated connector/signing path, not a new client.
No function here runs automatically or accesses a credential store.
"""
import asyncio
import time
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from src.accounting.derive_margin import decimal, margin_snapshot

COMPATIBILITY_VERSION = "flyby-derive-v3-r2"
MAX_MARKET_SLIPPAGE = Decimal("0.0015")


def invalidate_account(connector):
    connector._flyby_account_state = None
    connector._flyby_account_generation = getattr(connector, "_flyby_account_generation", 0) + 1
    connector._account_available_balances["USDC"] = Decimal(0)


async def position_map(connector, rows):
    from hummingbot.connector.derivative.position import Position
    from hummingbot.core.data_type.common import PositionSide
    if not isinstance(rows, list):
        raise ValueError("incomplete_position_snapshot")
    positions = {}
    for row in rows:
        if row.get("instrument_type") == "option":
            # Retain options in the FULL account snapshot. Never map them to
            # perp positions or send them through PositionExecutor.
            continue
        if row.get("instrument_type") != "perp":
            raise ValueError("unsupported_account_position")
        pair = await connector.trading_pair_associated_to_exchange_symbol(row["instrument_name"])
        amount = decimal(row["amount"])
        if pair in positions:
            raise ValueError("duplicate_position")
        if amount == 0:
            continue
        entry = decimal(row["average_price"])
        pnl = decimal(row["unrealized_pnl"])
        # V3 cross-margin positions can omit leverage. This value is display
        # metadata, not sizing permission; never change the configured 2x cap.
        leverage = decimal(row.get("leverage") or 1)
        if entry <= 0 or leverage <= 0:
            raise ValueError("invalid_position_price_or_leverage")
        side = PositionSide.LONG if amount > 0 else PositionSide.SHORT
        positions[pair] = Position(trading_pair=pair, position_side=side,
                                   unrealized_pnl=pnl, entry_price=entry,
                                   amount=amount, leverage=leverage)
    return positions


async def update_balances(connector):
    from hummingbot.connector.derivative.derive_perpetual import derive_perpetual_constants as constants
    if not hasattr(connector, "_flyby_account_lock"):
        connector._flyby_account_lock = asyncio.Lock()
    async with connector._flyby_account_lock:
        invalidate_account(connector)
        generation = connector._flyby_account_generation
        response = await connector._api_post(path_url=constants.ACCOUNTS_PATH_URL,
                    data={"subaccount_id": connector._subacct_id}, is_auth_required=True)
        if not isinstance(response, dict) or response.get("error") or "result" not in response:
            raise ValueError("account_refresh_failed")
        observed = connector.current_timestamp or time.time()
        state = margin_snapshot(response["result"], connector._subacct_id, observed,
                                allow_options=True)
        positions = await position_map(connector, state["positions"])
        if generation != connector._flyby_account_generation:
            raise ValueError("account_changed_during_refresh")
        # Validate every row before replacing any cache. Empty snapshots clear it.
        connector._perpetual_trading.account_positions.clear()
        for key, position in positions.items():
            connector._perpetual_trading.set_position(key, position)
        connector._account_balances.clear()
        connector._account_balances.update(state["balances"])
        connector._account_available_balances.clear()
        connector._account_available_balances["USDC"] = state["available"]
        connector._flyby_account_state = state


async def update_positions(connector):
    # One full authenticated source keeps valuation/margin/positions coherent.
    await update_balances(connector)


async def process_positions(connector, results):
    # Stream payloads may be deltas. Never interpret omitted positions as flat.
    invalidate_account(connector)
    await update_balances(connector)


def process_balance(connector, balance_msg):
    # A collateral delta has no margin proof; next full poll restores capacity.
    invalidate_account(connector)


async def place_order(connector, order_id, trading_pair, amount, trade_type,
                      order_type, price, position_action, **kwargs):
    from hummingbot.core.data_type.common import PositionAction, OrderType, TradeType
    from hummingbot.connector.derivative.derive_perpetual import derive_perpetual_constants as constants
    if connector.domain != "derive_perpetual":
        raise ValueError("mainnet_connector_domain_required")
    if position_action not in (PositionAction.OPEN, PositionAction.CLOSE):
        raise ValueError("explicit_position_action_required")
    if trade_type not in (TradeType.BUY, TradeType.SELL):
        raise ValueError("unsupported_order_side")
    if order_type not in (OrderType.LIMIT, OrderType.LIMIT_MAKER, OrderType.MARKET):
        raise ValueError("unsupported_order_type")
    amount, price = decimal(amount), decimal(price)
    if min(amount, price) <= 0:
        raise ValueError("invalid_order_size_or_price")
    symbol = await connector.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
    if not connector._instrument_ticker:
        await connector._make_trading_pairs_request()
    instrument = next((r for r in connector._instrument_ticker if r["instrument_name"] == symbol), None)
    if not instrument or instrument["instrument_type"] != "perp":
        raise ValueError("perpetual_instrument_required")
    tick, step = decimal(instrument["tick_size"]), decimal(instrument["amount_step"])
    minimum = decimal(instrument["minimum_amount"])
    if min(tick, step, minimum) <= 0 or amount % step != 0:
        raise ValueError("invalid_order_increment")
    if amount < minimum:
        raise ValueError("below_venue_minimum")
    # Preserve exact caller tick price; never round to four significant figures.
    if price % tick != 0:
        raise ValueError("invalid_order_price_tick")
    if order_type == OrderType.LIMIT_MAKER and position_action == PositionAction.CLOSE:
        raise ValueError("reduce_only_cannot_rest")
    tif = ("post_only" if order_type == OrderType.LIMIT_MAKER else
           "ioc" if order_type == OrderType.MARKET or position_action == PositionAction.CLOSE else "gtc")
    reference = decimal(connector.get_mid_price(trading_pair))
    if reference <= 0:
        raise ValueError("invalid_fee_reference")
    if order_type == OrderType.MARKET:
        # A market order's signed limit is a real price bound. Mid cannot cross
        # a positive spread. Bound by 15bps and round INSIDE that limit.
        is_buy = trade_type == TradeType.BUY
        bound = reference * (1 + MAX_MARKET_SLIPPAGE if is_buy else 1 - MAX_MARKET_SLIPPAGE)
        price = (bound / tick).to_integral_value(rounding=ROUND_FLOOR if is_buy else ROUND_CEILING) * tick
        if price <= 0:
            raise ValueError("invalid_market_price_bound")
    rate = max(decimal(instrument["maker_fee_rate"]), decimal(instrument["taker_fee_rate"]))
    base = decimal(instrument["base_fee"])
    if min(rate, base) < 0:
        raise ValueError("invalid_instrument_fees")
    # max_fee is PER CONTRACT, with a strict > buffer. Cover one step partial fill.
    fee = 6 * rate * max(reference, price) + (base / step if tif != "post_only" else Decimal(0))
    fee = fee.quantize(Decimal("0.000001"), rounding=ROUND_CEILING) + Decimal("0.000001")
    payload = {"asset_address": instrument["base_asset_address"], "sub_id": instrument["base_asset_sub_id"],
               "limit_price": str(price), "type": "order", "max_fee": str(fee),
               "amount": str(amount), "instrument_name": symbol, "label": order_id,
               "is_bid": trade_type == TradeType.BUY,
               "direction": "buy" if trade_type == TradeType.BUY else "sell",
               "order_type": "market" if order_type == OrderType.MARKET else "limit",
               "reduce_only": position_action == PositionAction.CLOSE,
               "referral_code": constants.REFERRAL_CODE, "mmp": False,
               "time_in_force": tif, "recipient_id": connector._subacct_id}
    invalidate_account(connector)
    response = await connector._api_post(path_url=constants.CREATE_ORDER_URL,
                                         data=payload, is_auth_required=True)
    if not isinstance(response, dict) or response.get("error"):
        # Self-cross errors must be failures too, not a None/false success.
        raise IOError("derive_order_rejected")
    row = response["result"]["order"]
    return str(row["order_id"]), float(row["creation_timestamp"]) / 1000
