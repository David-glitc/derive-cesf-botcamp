from copy import deepcopy
import json
import os
import pytest

from src.runtime.bridge import RuntimeBridge, MAX_EVENTS

BINDING = "a" * 64
NOW = 1800000000.


def context():
    return {"controller_id": "unit", "time": NOW, "decision": {"signal": 1},
            "risk": {"mode": "normal"}, "positions": [], "orders": [],
            "executors": [{"id": "owned", "active": True}],
            "runtime_health": {"account_verified": True, "inventory_complete": True},
            "options_execution": {"enabled": True}}


def request(state, patch=None, now=NOW, request_id="request-one"):
    return {"id": request_id, "controller_id": state["controller_id"], "account_binding": state["account_binding"],
            "session": state["session"], "basis_sequence": state["sequence"], "issued_at": now,
            "expires_at": now + 60, "patch": patch or {"size_multiplier": .5}}


def setup(tmp_path):
    bridge = RuntimeBridge(tmp_path / "owned", "unit", BINDING, writable=True)
    state = bridge.publish(context(), "session1", "bounded", NOW)
    return bridge, state


def test_private_state_read_and_idempotent_receipt(tmp_path):
    bridge, state = setup(tmp_path)
    r = request(state)
    assert bridge.submit(r, NOW)["status"] == "queued"
    assert bridge.submit(r, NOW)["status"] == "queued"
    assert bridge.consume(state, NOW) == {"size_multiplier": .5}
    assert bridge.status(r["id"])["status"] == "validated"
    assert bridge.status(r["id"])["effect"] == "controller_gates_still_required"
    assert bridge.status(r["id"], NOW)["lease_active"]
    assert not bridge.status(r["id"], NOW + 60)["lease_active"]
    assert RuntimeBridge(bridge.root, "unit", BINDING).read_state(NOW)["fresh"]
    for name in ("requests.json", "snapshot.json", "initialized.json", "events.json"):
        assert os.stat(bridge.root / name).st_mode & 0o777 == 0o600


@pytest.mark.parametrize("fault", ["foreign", "session", "future_sequence", "old_sequence", "future_time",
    "expired", "duration", "extra_field", "foreign_executor", "increase_size", "nonfinite"])
def test_rejected_request_never_overwrites_a_valid_lease(tmp_path, fault):
    bridge, state = setup(tmp_path)
    r = request(state)
    bridge.submit(r, NOW)
    bad = request(state, request_id="bad")
    if fault == "foreign": bad["account_binding"] = "b" * 64
    if fault == "session": bad["session"] = "other"
    if fault == "future_sequence": bad["basis_sequence"] += 1
    if fault == "old_sequence": bad["basis_sequence"] = 0
    if fault == "future_time": bad["issued_at"] += 1
    if fault == "expired": bad.update(issued_at=NOW - 5, expires_at=NOW)
    if fault == "duration": bad["expires_at"] += 1
    if fault == "extra_field": bad["budget"] = 1600
    if fault == "foreign_executor": bad["patch"] = {"close_executor_id": "foreign"}
    if fault == "increase_size": bad["patch"] = {"size_multiplier": 2}
    if fault == "nonfinite": bad["patch"] = {"hold_multiplier": float("nan")}
    before = (bridge.root / "requests.json").read_bytes()
    with pytest.raises(ValueError): bridge.submit(bad, NOW)
    assert (bridge.root / "requests.json").read_bytes() == before


def test_conflicting_duplicate_denied_and_restart_invalidates_only_lease(tmp_path):
    bridge, state = setup(tmp_path)
    r = request(state)
    bridge.submit(r, NOW)
    with pytest.raises(ValueError, match="conflicting"):
        bridge.submit({**r, "patch": {"size_multiplier": 1}}, NOW)
    new = bridge.publish(context(), "session2", "bounded", NOW + 1)
    with pytest.raises(ValueError, match="session"):
        bridge.consume(new, NOW + 1)
    assert bridge.status(r["id"])["status"] == "queued"


def test_expiry_during_fresh_publications_and_gap_reporting(tmp_path):
    bridge, state = setup(tmp_path)
    bridge.submit(request(state), NOW)
    for i in range(1, 150):
        state = bridge.publish(context(), "session1", "bounded", NOW + i)
    assert bridge.read_state(NOW + 149)["fresh"]
    assert len(bridge.events(limit=128)["events"]) == MAX_EVENTS
    assert bridge.events()["gap"]
    with pytest.raises(ValueError): bridge.consume(state, NOW + 149)


@pytest.mark.parametrize("component", ["requests.json", "snapshot.json", "events.json", "initialized.json"])
def test_lost_owned_component_never_reinitializes(tmp_path, component):
    bridge, state = setup(tmp_path)
    (bridge.root / component).unlink()  # deliberate fault in test-owned temp state
    with pytest.raises((OSError, ValueError)):
        bridge.publish(context(), "session1", "bounded", NOW + 1)
    assert not (bridge.root / component).exists()


def test_observation_and_dry_run_deny_writes(tmp_path):
    bridge, state = setup(tmp_path)
    read_only = RuntimeBridge(bridge.root, "unit", BINDING)
    with pytest.raises(ValueError, match="dry_run"):
        read_only.submit(request(state), NOW)
    state = bridge.publish(context(), "session1", "observe", NOW)
    with pytest.raises(ValueError, match="observe"):
        bridge.submit(request(state), NOW)


def test_unverified_inventory_never_means_flat(tmp_path):
    bridge, state = setup(tmp_path)
    body = context()
    body["runtime_health"]["account_verified"] = False
    state = bridge.publish(body, "session1", "bounded", NOW)
    with pytest.raises(ValueError, match="unverified"):
        bridge.submit(request(state), NOW)


def test_inventory_loss_after_submission_invalidates_lease(tmp_path):
    bridge, state = setup(tmp_path)
    bridge.submit(request(state), NOW)
    body = context()
    body["runtime_health"]["inventory_complete"] = False
    state = bridge.publish(body, "session1", "bounded", NOW + 1)
    with pytest.raises(ValueError, match="unverified"):
        bridge.consume(state, NOW + 1)
    with pytest.raises(ValueError, match="unverified"):
        bridge.submit(request(state, now=NOW + 1, request_id="incomplete"), NOW + 1)


def test_symlink_and_foreign_file_are_not_overwritten(tmp_path):
    bridge, state = setup(tmp_path)
    target = bridge.root / "requests.json"
    saved = bridge.root / "saved.json"
    target.rename(saved)
    target.symlink_to(saved)
    before = saved.read_bytes()
    with pytest.raises(OSError): bridge.submit(request(state), NOW)
    assert saved.read_bytes() == before


def test_fifty_hour_virtual_ingestion_with_restarts(tmp_path, monkeypatch):
    # Virtual clock/state sequence, not a disk durability or real-time uptime soak.
    # Atomic replacement and permissions are exercised separately above.
    monkeypatch.setattr(os, "fsync", lambda fd: None)
    bridge, state = setup(tmp_path)
    for minute in range(3000):
        now = NOW + minute * 60
        session = "session" + str(minute // 300)
        state = bridge.publish(context(), session, "bounded", now)
        bridge.submit(request(state, now=now, request_id="r" + str(minute)), now)
        assert bridge.consume(state, now)["size_multiplier"] == .5
    assert len(bridge._journal()["receipts"]) == 3000
    assert len(bridge.events(limit=128)["events"]) == 128
    assert not bridge.read_state(NOW + 3000 * 60)["fresh"]
