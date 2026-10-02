from copy import deepcopy

import pytest

from src.execution.contracts import AccountMirror, close_intent


def account(**changes):
    return {"network": "mainnet", "api_generation": "legacy_v2", "received_at": 100,
            "equity": 800, "available_margin": 600, "margin_source": "verified_free_margin",
            "realized_pnl": 0, "positions": {"ETH-PERP": ".01"}, "open_order_ids": [], **changes}


def test_authoritative_empty_snapshot_clears_positions_not_cached_exposure():
    mirror = AccountMirror()
    mirror.replace(account(), 100)
    assert mirror.snapshot["positions"]
    mirror.replace(account(received_at=101, positions={}), 101)
    assert mirror.snapshot["positions"] == {}
    assert mirror.matches({"equity": 800, "realized_pnl": 0, "positions": {}, "open_order_ids": []})


@pytest.mark.parametrize("changes", [{"network": "testnet"}, {"margin_source": "collateral_balance"},
                                    {"available_margin": -1}, {"equity": float("nan")}, {"received_at": 106},
                                    {"open_order_ids": ["dup", "dup"]}])
def test_account_contract_requires_actual_free_margin_and_freshness(changes):
    mirror = AccountMirror()
    with pytest.raises(ValueError): mirror.replace(account(**changes), 100)
    assert mirror.snapshot is None


@pytest.mark.parametrize("position", [-10, -1, 0, 1, 10])
@pytest.mark.parametrize("requested", [0, 1, 10, 20])
@pytest.mark.parametrize("pending", [0, 1, 20])
def test_reduce_only_intent_never_overallocates_close(position, requested, pending):
    intent = close_intent(position, requested, pending)
    if intent is not None:
        assert intent["reduce_only"] and intent["lots"] + min(pending, abs(position)) <= abs(position)
        assert abs(intent["remaining_after_this_close"]) <= abs(position)
        assert intent["remaining_after_this_close"] * position >= 0
