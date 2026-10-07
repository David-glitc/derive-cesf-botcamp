"""V3 integration/upgrade contracts with offline fixtures, no exchange writes."""
import asyncio
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest

from scripts.upgrade_condor import upgrade, rollback
from src.data.options_feed import OptionsFeed
from src.execution.options_book import OptionsBook
from src.execution.options_rfq import OptionsRFQ, RFQJournal, expected_positions
from tests.test_options_rfq import Transport, NOW, plan, open_spread
from tests.test_native_data import definition, ticker, perp

ROOT = Path(__file__).resolve().parents[1]


def test_vendor_pin_and_no_network_installer():
    directory = ROOT / "vendor/derive_v3"
    manifest = json.loads((directory / "manifest.json").read_text())
    for path, expected in manifest["files"].items():
        assert hashlib.sha256((directory / path).read_bytes()).hexdigest() == expected
    assert manifest["framework"] == "Hummingbot V2"
    assert "requests" not in (ROOT / "scripts/install_derive_v3.py").read_text()


def test_existing_agent_upgrade_preserves_routines_runtime_and_can_rollback(tmp_path):
    root = tmp_path / "agents"
    home = root / "flyby"
    (home / "routines").mkdir(parents=True)
    (home / "routines/_flyby_derive.py").write_text("team-owned signer\n")
    (home / "config.yml").write_text("execution_mode: dry_run\n")
    (home / "AGENT.md").write_text("old observer\n")
    backup = tmp_path / "backup"
    preview = upgrade(root)
    assert preview["authored_files_changed"] and not backup.exists()
    assert (home / "AGENT.md").read_text() == "old observer\n"
    result = upgrade(root, backup, True)
    assert not result["started"] and result["orders_submitted"] == 0
    assert (home / "routines/_flyby_derive.py").read_text() == "team-owned signer\n"
    assert (home / "config.yml").read_text() == "execution_mode: dry_run\n"
    assert upgrade(root)["authored_files_changed"] == 0
    rollback(backup, True)
    assert (home / "AGENT.md").read_text() == "old observer\n"
    assert not (home / "PROFILE.yml").exists()
    assert (home / "routines/_flyby_derive.py").exists()


def test_rollback_refuses_later_operator_edits(tmp_path):
    home = tmp_path / "agents/flyby"
    home.mkdir(parents=True)
    backup = tmp_path / "backup"
    upgrade(home.parent, backup, True)
    (home / "AGENT.md").write_text("operator changed it\n")
    with pytest.raises(ValueError, match="drift"):
        rollback(backup, True)
    assert (home / "PROFILE.yml").exists()


class PublicTransport:
    def __init__(self):
        self.now, self.calls = NOW, []
    def clock(self):
        return self.now
    async def call(self, method, params, private=True):
        assert private is False and method.startswith("public/")
        self.calls.append(method)
        if method.endswith("get_all_instruments"):
            return {"instruments": [definition()], "pagination": {"num_pages": 1}}
        if method.endswith("get_tickers"):
            assert params["expiry_date"] == int(definition()["instrument_name"].split("-")[1])
            return {"tickers": {definition()["instrument_name"]: ticker()}}
        return perp()


def test_autonomous_native_feed_no_sidecar_or_private_calls():
    t = PublicTransport()
    feed = OptionsFeed(t, "ETH")
    data = asyncio.run(feed.refresh())
    assert data["api_generation"] == "v3" and data["perp"]["index"] == 3000
    assert len(data["options"]) == 1 and data["options"][0]["quoted"]
    asyncio.run(feed.refresh())
    assert len(t.calls) == 3
    t.now += 3
    asyncio.run(feed.refresh())
    assert t.calls.count("public/get_all_instruments") == 1


def test_slow_public_feed_is_background_only_and_cancellable():
    async def check():
        t = PublicTransport()
        event = asyncio.Event()
        original = t.call
        async def slow(*args, **kwargs):
            await event.wait()
            return await original(*args, **kwargs)
        t.call = slow
        feed = OptionsFeed(t, "ETH")
        feed.poll()
        task = feed._task
        feed.poll()
        assert feed._task is task  # only one capture task, no request stampede
        await asyncio.sleep(0)
        assert not task.done() and feed.market is None
        feed.close()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(check())


def test_two_durable_spread_slots_and_disjoint_inventory(tmp_path):
    t = Transport()
    book = OptionsBook(t, tmp_path / "rfq.json", "account", "owner", 42, underlying="ETH")
    first, second = book.slots
    open_spread(t, first)
    assert book.owns(expected_positions(plan())) and not book.blocked
    p2 = {**plan(), "buy": "ETH-C", "sell": "ETH-D"}
    asyncio.run(book.tick(NOW, plan=p2, budget=4, allow_entry=True, consume_entry=lambda a, n: True))
    assert second.journal.state["phase"] == "quoting_entry"
    t.offer(second)
    asyncio.run(book.tick(NOW, plan=p2, budget=4, allow_entry=True, consume_entry=lambda a, n: True))
    assert second.journal.state["phase"] == "settling"
    t.positions.update(expected_positions(p2))
    t.quote_rows[-1].update(tx_status="settled", last_update_timestamp=NOW * 1000)
    next(row for row in t.rfq_rows if row["rfq_id"] == second.journal.state["rfq_id"])["status"] = "filled"
    asyncio.run(book.tick(NOW, budget=4))
    assert book.open_count == 2 and second.journal.state["phase"] == "open"
    assert book.owns({**expected_positions(plan()), **expected_positions(p2)})
    restored = OptionsBook(t, tmp_path / "rfq.json", "account", "owner", 42, underlying="ETH")
    assert restored.open_count == 2
    t.positions["ETH-FOREIGN"] = Decimal(".01")
    with pytest.raises(ValueError, match="unowned"):
        asyncio.run(second.transport.account())


def test_v3_filled_inventory_does_not_wait_for_l1_or_replay(tmp_path):
    t = Transport()
    t.api_generation = "v3"
    async def executions(rfq_id, quote_id):
        return [row for row in t.quote_rows if row["rfq_id"] == rfq_id]
    t.executions = executions
    c = OptionsRFQ(t, RFQJournal(tmp_path / "rfq.json", "a", "owner"), 42)
    def tick():
        asyncio.run(c.tick(NOW, plan=plan(), budget=4, allow_entry=True, consume_entry=lambda a, n: True))
    tick(); t.offer(c); tick()
    t.positions = expected_positions(plan())
    t.quote_rows[-1].pop("tx_status")
    t.quote_rows[-1].update(batch_status="Proving", tx_hash=None,
                          nonce=str(c.journal.state["nonce"]), quote_id="taker-owned-quote")
    tick()
    assert c.journal.state["phase"] == "open"
    assert c.journal.state["settlement_confirmation"] == "matched_inventory"
    assert t.writes.count("execute") == 1


def test_active_legacy_intent_is_preserved_not_resigned(tmp_path):
    t = Transport()
    c = OptionsRFQ(t, RFQJournal(tmp_path / "rfq.json", "a", "owner"), 42)
    open_spread(t, c)
    original = deepcopy(c.journal.state)
    t.api_generation = "v3"
    asyncio.run(c.tick(NOW, force_exit=True))
    assert c.journal.state == original and "legacy_rfq" in c.last_error
