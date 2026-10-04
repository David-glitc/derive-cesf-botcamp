"""Legacy v2 atomic RFQs over the pinned Hummingbot authenticated transport.

Wire schema: orderbook-stubs@db6b172d5e10553738c74ccab775ef2e7258e955.
Signing layout: v2-action-signing-python@d1914d61985e33559244da242892c7255b6fd0ca.
Deployment: v2-matching@f6c20f46e346151e0969777c5119c92ec21b3be8/957.
No credential discovery, import-time requests, independent legs or v3 fallback.
"""
import asyncio
import time
from dataclasses import dataclass
from decimal import Decimal

from agents.mainnet import require_mainnet_connector, validate_installed_endpoints
from src.accounting.derive_margin import decimal
from src.execution.derive_hb import COMPATIBILITY_VERSION, invalidate_account, update_balances

RFQ_MODULE = "0x9371352CCef6f5b36EfDFE90942fFE622Ab77F1D"


def fixed(value):
    scaled = decimal(value) * 10 ** 18
    if scaled != scaled.to_integral_value():
        raise ValueError("rfq_precision_loss")
    return int(scaled)


def leg_identity(legs):
    if not isinstance(legs, list) or len(legs) != 2:
        raise ValueError("rfq_requires_two_legs")
    result = {}
    for row in legs:
        name, side, amount = row["instrument_name"], row["direction"], decimal(row["amount"])
        if not isinstance(name, str) or not name or name in result or side not in ("buy", "sell") or amount <= 0:
            raise ValueError("rfq_invalid_legs")
        fixed(amount)
        result[name] = (side, amount)
    return result


def quote_cost(legs):
    leg_identity(legs)
    cost = Decimal(0)
    for row in legs:
        price = decimal(row["price"])
        if price <= 0:
            raise ValueError("rfq_invalid_price")
        fixed(price)
        cost += decimal(row["amount"]) * price * (1 if row["direction"] == "buy" else -1)
    return cost


@dataclass
class ExecuteModuleData:
    legs: list
    instruments: dict
    max_fee: Decimal

    def legs_hash(self):
        from eth_abi import encode
        from web3 import Web3
        # Execute signatures commit to the MAKER's quantities, opposite ours.
        rows = [(Web3.to_checksum_address(self.instruments[r["instrument_name"]]["base_asset_address"]),
                 int(self.instruments[r["instrument_name"]]["base_asset_sub_id"]), fixed(r["price"]),
                 fixed(r["amount"]) * (-1 if r["direction"] == "buy" else 1))
                for r in sorted(self.legs, key=lambda r: r["instrument_name"])]
        return Web3.keccak(encode(["(address,uint,uint,int)[]"], [rows]))

    def to_abi_encoded(self):
        from eth_abi import encode
        return encode(["bytes32", "uint"], [self.legs_hash(), fixed(self.max_fee)])

    def to_json(self):
        return {"direction": "buy", "legs": sorted(self.legs, key=lambda r: r["instrument_name"]),
                "max_fee": str(self.max_fee)}


class DeriveRFQTransport:
    """Only explicitly constructed by an RFQ-enabled controller; reuses its auth."""
    def __init__(self, connector):
        from hummingbot.connector.derivative.derive_perpetual import derive_perpetual_constants as constants
        require_mainnet_connector(connector)
        validate_installed_endpoints(constants)
        if getattr(connector, "FLYBY_COMPATIBILITY_VERSION", None) != COMPATIBILITY_VERSION:
            raise ValueError("reviewed_connector_compatibility_required")
        self.connector, self.constants = connector, constants

    def clock(self):
        return self.connector.current_timestamp or time.time()

    async def call(self, method, params, private=True):
        # Explicit aggregate limit: these RFQ paths are absent from stock HB's
        # endpoint table. Still consume its reviewed authenticated rate budget.
        response = await asyncio.wait_for(self.connector._api_post(
            path_url="/" + method, data=params, is_auth_required=private,
            limit_id=self.constants.ORDERS_IP), timeout=10)
        if not isinstance(response, dict) or response.get("error") or "result" not in response:
            raise ValueError("rfq_venue_response_rejected")
        return response["result"]

    async def account(self):
        await asyncio.wait_for(update_balances(self.connector), timeout=10)
        return self.connector._flyby_account_state

    async def send(self, legs, label, max_cost):
        leg_identity(legs)
        return await self.call("private/send_rfq", {"subaccount_id": self.connector._subacct_id,
            "legs": legs, "label": label, "max_total_cost": str(max_cost)})

    async def cancel(self, rfq_id):
        return await self.call("private/cancel_rfq", {"subaccount_id": self.connector._subacct_id, "rfq_id": rfq_id})

    async def rows(self, method, key, **filters):
        rows = []
        for page in range(1, 11):
            result = await self.call("private/" + method, {"subaccount_id": self.connector._subacct_id,
                "page": page, "page_size": 100, **filters})
            batch = result[key]
            if not isinstance(batch, list):
                raise ValueError("rfq_invalid_page")
            rows.extend(batch)
            pages = result["pagination"]["num_pages"]
            if not isinstance(pages, int) or isinstance(pages, bool) or pages < 0:
                raise ValueError("rfq_invalid_pagination")
            if page >= pages:
                return rows
        raise ValueError("rfq_reconciliation_page_limit")

    async def rfqs(self, **filters):
        return await self.rows("get_rfqs", "rfqs", **filters)

    async def offers(self, rfq_id):
        return await self.rows("poll_quotes", "quotes", rfq_id=rfq_id, status="open")

    async def executions(self, rfq_id, quote_id):
        return await self.rows("get_quotes", "quotes", rfq_id=rfq_id, quote_id=quote_id)

    async def instruments(self, legs):
        result = {}
        for name in leg_identity(legs):
            result[name] = await self.call("public/get_instrument", {"instrument_name": name}, private=False)
        return result

    async def prepare(self, quote, max_fee, nonce, label, now, plan, intent):
        """Read public metadata and sign in memory; never submit an order."""
        from hummingbot.connector.other.derive_common_utils import SignedAction
        instruments = await self.instruments(quote["legs"])
        clock = self.clock()
        if not 0 <= clock - quote["creation_timestamp"] / 1000 <= 5:
            raise ValueError("rfq_quote_expired_before_signing")
        validate_instruments(instruments, quote["legs"], clock)
        bought, sold = instruments[plan["buy"]], instruments[plan["sell"]]
        b, s = bought["option_details"], sold["option_details"]
        width = (decimal(s["strike"]) - decimal(b["strike"])) * (1 if plan["kind"] == "call" else -1)
        expected = {plan["buy"]: ("buy" if intent == "entry" else "sell", decimal(plan["amount"])),
                    plan["sell"]: ("sell" if intent == "entry" else "buy", decimal(plan["amount"]))}
        if (intent not in ("entry", "exit") or leg_identity(quote["legs"]) != expected or width <= 0
                or b["expiry"] != plan["expiry"] or bought["base_currency"] != plan["underlying"]
                or b["option_type"] != ("C" if plan["kind"] == "call" else "P")
                or abs(width * decimal(plan["amount"]) - decimal(plan["max_payoff"])) > Decimal(".000001")):
            raise ValueError("rfq_native_contract_disagrees_with_plan")
        module = ExecuteModuleData(quote["legs"], instruments, decimal(max_fee))
        if ("0x" + module.legs_hash().hex().removeprefix("0x")).lower() != quote["legs_hash"].lower():
            raise ValueError("rfq_legs_hash_mismatch")
        auth = self.connector._auth
        if auth._domain != "derive_perpetual" or int(auth._subacct_id) != self.connector._subacct_id:
            raise ValueError("rfq_auth_identity_mismatch")
        action = SignedAction(subaccount_id=self.connector._subacct_id, owner=auth._wallet_address,
            signer=auth.session_key_wallet.address, signature_expiry_sec=int(clock) + 600, nonce=nonce,
            module_address=RFQ_MODULE, module_data=module, DOMAIN_SEPARATOR=self.constants.DOMAIN_SEPARATOR,
            ACTION_TYPEHASH=self.constants.ACTION_TYPEHASH)
        action.sign(auth._session_private_key)
        action.validate_signature()  # pinned HB returns None on success, raises on failure
        # No "type": stock HB auth attaches headers without replacing the RFQ signature.
        payload = {**action.to_json(), "quote_id": quote["quote_id"], "rfq_id": quote["rfq_id"], "label": label}
        return payload

    async def submit(self, payload):
        """Called only after the coordinator durably records the execution intent."""
        invalidate_account(self.connector)
        return await self.call("private/execute_quote", payload)

    async def execute(self, quote, max_fee, nonce, label, now, plan, intent):
        """Convenience for offline adapter tests; production uses prepare/submit."""
        return await self.submit(await self.prepare(quote, max_fee, nonce, label, now, plan, intent))


def validate_instruments(instruments, legs, now):
    """Reject wrong tenors, lot sizes and naked/credit structures before signing."""
    identity = leg_identity(legs)
    details = []
    currencies = set()
    for row in legs:
        name = row["instrument_name"]
        inst = instruments[name]
        if (inst["instrument_name"] != name or inst["instrument_type"] != "option"
                or inst["is_active"] is not True or inst["quote_currency"] != "USDC"
                or inst["base_currency"] not in ("ETH", "BTC")):
            raise ValueError("rfq_unapproved_instrument")
        currencies.add(inst["base_currency"])
        amount, price = decimal(row["amount"]), decimal(row["price"])
        step, tick = decimal(inst["amount_step"]), decimal(inst["tick_size"])
        if (min(step, tick, amount, price) <= 0 or amount % step or price % tick
                or not decimal(inst["minimum_amount"]) <= amount <= decimal(inst["maximum_amount"])):
            raise ValueError("rfq_invalid_instrument_increment")
        detail = inst["option_details"]
        # Legacy instrument expiry is Unix seconds (not milliseconds).
        if detail["option_type"] not in ("C", "P") or decimal(detail["expiry"]) <= decimal(now):
            raise ValueError("rfq_expired_or_invalid_option")
        details.append(detail)
    if (len(currencies) != 1 or details[0]["expiry"] != details[1]["expiry"]
            or details[0]["option_type"] != details[1]["option_type"]
            or len({side for side, amount in identity.values()}) != 2
            or len({amount for side, amount in identity.values()}) != 1
            or decimal(details[0]["strike"]) == decimal(details[1]["strike"])):
        raise ValueError("rfq_not_matched_vertical")
