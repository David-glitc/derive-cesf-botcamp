import unittest
from decimal import Decimal

from src.accounting.ledger import AccountingLedger
from src.accounting.reconciliation import reconcile


class AccountingTests(unittest.TestCase):
    def test_fill_and_funding_are_idempotent(self):
        ledger = AccountingLedger()
        fill = {
            "trade_id": "trade-1",
            "order_id": "order-1",
            "instrument": "ETH-PERP",
            "side": "buy",
            "amount": "0.1",
            "price": "2500",
            "fee": "0.75",
            "rebate": "0.10",
            "realized_pnl": "4.25",
            "realized_pnl_ex_fees": "4.90",
        }
        funding = {"event_id": "fund-1", "instrument": "ETH-PERP", "amount": "-0.20"}

        self.assertTrue(ledger.apply_fill(fill))
        self.assertFalse(ledger.apply_fill(fill))
        self.assertTrue(ledger.apply_funding(funding))
        self.assertFalse(ledger.apply_funding(funding))

        snapshot = ledger.snapshot()
        self.assertEqual(snapshot["fill_count"], 1)
        self.assertEqual(snapshot["volume_quote"], "250.0")
        self.assertEqual(snapshot["fees_paid"], "0.75")
        self.assertEqual(snapshot["funding"], "-0.20")
        self.assertEqual(ledger.net_cash_pnl, Decimal("4.05"))

    def test_reconciliation_accepts_matching_state(self):
        result = reconcile(
            {"equity": "800", "realized_pnl": "4", "open_order_ids": ["o1"], "positions": {"ETH-PERP": "0.1"}},
            {"equity": "800.004", "realized_pnl": "4.004", "open_order_ids": ["o1"], "positions": {"ETH-PERP": "0.1"}},
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.reasons, ())

    def test_reconciliation_blocks_unknown_order_and_position_drift(self):
        result = reconcile(
            {"equity": "800", "realized_pnl": "4", "open_order_ids": ["unknown"], "positions": {"ETH-PERP": "0.3"}},
            {"equity": "800", "realized_pnl": "4", "open_order_ids": [], "positions": {"ETH-PERP": "0.1"}},
        )
        self.assertFalse(result.ok)
        self.assertIn("unknown_local_orders", result.reasons)
        self.assertIn("position_drift", result.reasons)


if __name__ == "__main__":
    unittest.main()
