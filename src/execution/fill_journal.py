"""Durable ownership evidence. Reconciliation is not inferred from callbacks.

One journal per executor, bound to account/pair/executor identity. It is NOT a
venue transport adapter. SQLite FULL transactions retain ambiguous intents and
late fills across process restarts; no order or reconciliation state is deleted.
"""
from contextlib import contextmanager
from decimal import Decimal
import json
import math
from pathlib import Path
import sqlite3

ZERO = Decimal(0)
TERMINAL = {"filled", "canceled", "failed"}


def amount(value, *, positive=False):
    result = Decimal(str(value))
    if not result.is_finite() or (result <= 0 if positive else result < 0):
        raise ValueError("invalid_journal_amount")
    return result


class FillJournal:
    def __init__(self, path, binding, pair, executor_id):
        self.path = Path(path)
        if self.path.is_symlink() or not all(isinstance(v, str) and 0 < len(v) <= 256 for v in (binding, pair, executor_id)):
            raise ValueError("invalid_journal_identity")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists()
        self.db = sqlite3.connect(self.path, timeout=5)
        try:
            self.db.execute("PRAGMA synchronous=FULL")
            if existed:
                stored = self.db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
                if stored is None or json.loads(stored[0]) != [binding, pair, executor_id]:
                    raise ValueError("foreign_journal")
            else:
                self.db.executescript("""
                    CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                    CREATE TABLE intents(id TEXT PRIMARY KEY,payload TEXT NOT NULL,order_id TEXT);
                    CREATE TABLE orders(id TEXT PRIMARY KEY,role TEXT NOT NULL,side INTEGER NOT NULL,
                        amount TEXT NOT NULL,status TEXT NOT NULL,time REAL NOT NULL);
                    CREATE TABLE fills(id TEXT PRIMARY KEY,order_id TEXT NOT NULL,payload TEXT NOT NULL);
                """)
                with self.db:
                    self.db.execute("INSERT INTO metadata VALUES('identity',?)", (json.dumps([binding, pair, executor_id]),))
            self.db.execute("PRAGMA journal_mode=WAL")
        except Exception:
            self.db.close()
            raise
        self.pair, self.binding = pair, binding

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    @staticmethod
    def time(value):
        value = float(value)
        if not math.isfinite(value) or value < 0:
            raise ValueError("invalid_journal_time")
        return value

    def intent(self, identity, role, side, quantity, now):
        if role not in ("entry", "close") or side not in (-1, 1) or not identity:
            raise ValueError("invalid_order_intent")
        payload = json.dumps([role, side, str(amount(quantity, positive=True)), self.time(now)])
        with self.transaction():
            self.db.execute("INSERT INTO intents VALUES(?,?,NULL)", (identity, payload))
            self.db.execute("DELETE FROM metadata WHERE key='reconciled'")

    def acknowledge(self, intent_id, order_id):
        if not isinstance(order_id, str) or not order_id:
            raise ValueError("missing_order_acknowledgement")
        with self.transaction():
            row = self.db.execute("SELECT payload,order_id FROM intents WHERE id=?", (intent_id,)).fetchone()
            if row is None or row[1] is not None:
                raise ValueError("unknown_or_acknowledged_intent")
            role, side, quantity, now = json.loads(row[0])
            self.db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?)", (order_id, role, side, quantity, "working", now))
            self.db.execute("UPDATE intents SET order_id=? WHERE id=?", (order_id, intent_id))

    def status(self, order_id, status, now):
        if status not in TERMINAL | {"working", "partial"}:
            raise ValueError("invalid_order_status")
        now = self.time(now)
        with self.transaction():
            row = self.db.execute("SELECT status,time FROM orders WHERE id=?", (order_id,)).fetchone()
            if row is None:
                raise ValueError("unknown_order")
            if now < row[1] or (row[0] in TERMINAL and status not in TERMINAL):
                raise ValueError("backward_order_status")
            self.db.execute("UPDATE orders SET status=?,time=? WHERE id=?", (status, now, order_id))
            self.db.execute("DELETE FROM metadata WHERE key='reconciled'")

    def fill(self, trade_id, order_id, quantity, price, fee_quote, now):
        if not isinstance(trade_id, str) or not trade_id:
            raise ValueError("missing_trade_identity")
        payload = json.dumps([str(amount(quantity, positive=True)), str(amount(price, positive=True)),
                              str(amount(fee_quote)), self.time(now)])
        with self.transaction():
            old = self.db.execute("SELECT order_id,payload FROM fills WHERE id=?", (trade_id,)).fetchone()
            if old:
                if old != (order_id, payload):
                    raise ValueError("conflicting_duplicate_fill")
                return False
            order = self.db.execute("SELECT amount FROM orders WHERE id=?", (order_id,)).fetchone()
            if order is None:
                raise ValueError("unowned_fill")
            filled = sum((Decimal(json.loads(r[0])[0]) for r in self.db.execute(
                "SELECT payload FROM fills WHERE order_id=?", (order_id,))), ZERO)
            if filled + amount(quantity) > Decimal(order[0]):
                raise ValueError("order_overfill")
            # Terminal orders intentionally remain addressable for late fills.
            self.db.execute("INSERT INTO fills VALUES(?,?,?)", (trade_id, order_id, payload))
            self.db.execute("DELETE FROM metadata WHERE key='reconciled'")
        return True

    def totals(self):
        out = {"entry_base": ZERO, "close_base": ZERO, "entry_quote": ZERO, "close_quote": ZERO, "fees_quote": ZERO, "signed_base": ZERO}
        for role, side, payload in self.db.execute("SELECT o.role,o.side,f.payload FROM fills f JOIN orders o ON o.id=f.order_id"):
            q, p, fee, _ = json.loads(payload)
            q, p, fee = Decimal(q), Decimal(p), Decimal(fee)
            out[role + "_base"] += q
            out[role + "_quote"] += q * p
            out["signed_base"] += side * q
            out["fees_quote"] += fee
        return out

    def reconcile(self, snapshot, now, *, minimum_amount, amount_step):
        """Caller must supply a complete authoritative private snapshot.

        No automatic adoption, trading, or intent resolution. A residual below
        the venue minimum is explicitly blocked, not rounded away.
        """
        with self.transaction():
            return self._reconcile(snapshot, now, minimum_amount, amount_step)

    def _reconcile(self, snapshot, now, minimum_amount, amount_step):
        now = self.time(now)
        observed = self.time(snapshot["observed_at"])
        minimum, step = amount(minimum_amount, positive=True), amount(amount_step, positive=True)
        if (snapshot.get("source") != "authenticated_private" or snapshot.get("complete") is not True
                or snapshot.get("pair") != self.pair or snapshot.get("account_binding") != self.binding
                or not 0 <= now - observed <= 60):
            raise ValueError("authoritative_fresh_complete_snapshot_required")
        latest = self.db.execute("SELECT MAX(time) FROM orders").fetchone()[0] or 0
        for row in self.db.execute("SELECT payload FROM fills"):
            latest = max(latest, json.loads(row[0])[-1])
        old = self.db.execute("SELECT value FROM metadata WHERE key='last_snapshot_time'").fetchone()
        if observed < latest or (old and observed < float(old[0])):
            raise ValueError("snapshot_precedes_owned_events")
        venue = Decimal(str(snapshot["position_base"]))
        if not venue.is_finite() or not isinstance(snapshot["open_order_ids"], list):
            raise ValueError("invalid_private_position_or_orders")
        owned = self.totals()["signed_base"]
        pending = self.db.execute("SELECT COUNT(*) FROM intents WHERE order_id IS NULL").fetchone()[0]
        working = [row[0] for row in self.db.execute("SELECT id FROM orders WHERE status NOT IN ('filled','canceled','failed')")]
        owned_ids = {row[0] for row in self.orders()}
        unowned_orders = any(identity not in owned_ids for identity in snapshot["open_order_ids"])
        reason = ("ambiguous_transport_intent" if pending else "position_mismatch" if owned != venue else
                  "unowned_venue_orders" if unowned_orders else
                  "working_or_unresolved_orders" if working or snapshot["open_order_ids"] else
                  "flat" if venue == ZERO else "residual_below_minimum" if abs(venue) < minimum else
                  "residual_not_whole_lot" if abs(venue) % step else "reduce_only_recovery_required")
        close = abs(venue) if reason == "reduce_only_recovery_required" else ZERO
        result = {"entry_allowed": reason == "flat", "reason": reason,
                  "position_base": str(venue), "close_amount": str(close), "close_side": -1 if venue > 0 else 1,
                  "cancel_order_ids": [identity for identity in snapshot["open_order_ids"] if identity in owned_ids], "observed_at": observed}
        self.db.execute("INSERT OR REPLACE INTO metadata VALUES('last_snapshot_time',?)", (str(observed),))
        self.db.execute("INSERT OR REPLACE INTO metadata VALUES('reconciled',?)", (json.dumps(result),))
        return result

    def orders(self):
        return list(self.db.execute("SELECT id,role,side,amount,status FROM orders ORDER BY rowid"))

    def owns(self, order_id):
        return self.db.execute("SELECT 1 FROM orders WHERE id=?", (order_id,)).fetchone() is not None

    def pending_intents(self):
        return self.db.execute("SELECT COUNT(*) FROM intents WHERE order_id IS NULL").fetchone()[0]

    def held_evidence(self):
        rows = []
        for order_id, role, _, _, _ in self.orders():
            fills = [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM fills WHERE order_id=?", (order_id,))]
            quantity = sum((Decimal(r[0]) for r in fills), ZERO)
            if quantity:
                rows.append({"client_order_id": order_id, "role": role, "executed_amount_base": str(quantity),
                             "executed_amount_quote": str(sum((Decimal(r[0]) * Decimal(r[1]) for r in fills), ZERO)),
                             "fee_quote": str(sum((Decimal(r[2]) for r in fills), ZERO)), "journal_evidence_only": True})
        return rows

    def close(self):
        self.db.close()
