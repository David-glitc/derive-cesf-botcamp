"""Private bounded snapshot/event feed and idempotent adjustment mailbox.

Trusted operator shared volume, NOT a sandbox against arbitrary filesystem/code
access. No credentials, socket listener or exchange order transport.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import stat
from pathlib import Path
import tempfile

from src.runtime.control import finite, identifier, validate_request

MAX_BYTES = 4 * 1024 * 1024
MAX_EVENTS = 128
MAX_RECEIPTS = 4096


def root_path(controller_id):
    identifier(controller_id)
    return Path("data") / ("flyby-runtime-" + controller_id)


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("runtime_duplicate_json_key")
        result[key] = value
    return result


def seal(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, allow_nan=False).encode()).hexdigest()


class RuntimeBridge:
    def __init__(self, root, controller_id, binding, *, writable=False):
        self.root = Path(root).absolute()
        self.owner = {"controller_id": identifier(controller_id), "account_binding": identifier(binding)}
        if len(binding) != 64 or any(c not in "0123456789abcdef" for c in binding):
            raise ValueError("runtime_invalid_account_binding")
        self.writable = writable

    def _safe_root(self, create=False):
        if self.root.resolve() != self.root:
            raise ValueError("runtime_linked_directory")
        if create:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.root.is_dir():
            raise ValueError("runtime_directory_missing")

    @contextmanager
    def _locked(self, create=False):
        self._safe_root(create)
        fd = os.open(self.root / "bridge.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def _read(self, name, kind):
        fd = os.open(self.root / name, os.O_RDONLY | os.O_NOFOLLOW)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise ValueError("runtime_regular_file_required")
        with os.fdopen(fd) as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("runtime_file_too_large")
        body = json.loads(raw, object_pairs_hook=unique_keys)
        if not isinstance(body, dict) or body.get("kind") != kind or any(
                body.get(k) != v for k, v in self.owner.items()):
            raise ValueError("runtime_file_owner_or_kind_mismatch")
        return body

    def _write(self, name, kind, body):
        target = self.root / name
        if target.exists() or target.is_symlink():
            self._read(name, kind)
        payload = json.dumps({**body, "kind": kind, **self.owner}, sort_keys=True, allow_nan=False)
        if len(payload.encode()) > MAX_BYTES:
            raise ValueError("runtime_file_too_large")
        with tempfile.NamedTemporaryFile(mode="w", dir=self.root, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            temporary.replace(target)
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)

    def _journal(self):
        self._read("initialized.json", "flyby_runtime_initialized")
        return self._read("requests.json", "flyby_runtime_requests")

    def publish(self, context, session, mode, now):
        identifier(session)
        finite(now)
        if mode not in ("observe", "bounded") or context.get("controller_id") != self.owner["controller_id"]:
            raise ValueError("runtime_invalid_publication")
        with self._locked(create=True):
            marker = self.root / "initialized.json"
            fresh = not marker.exists() and not marker.is_symlink()
            if fresh:
                # Never bootstrap around orphaned or foreign runtime files.
                if any(p.name != "bridge.lock" for p in self.root.iterdir()):
                    raise ValueError("runtime_orphaned_files_require_review")
                self._write("initialized.json", "flyby_runtime_initialized", {})
                self._write("requests.json", "flyby_runtime_requests", {"receipts": {}, "active": None})
                self._write("events.json", "flyby_runtime_events", {"events": []})
            journal = self._journal()  # missing/corrupt receipts never reset
            old = None if fresh else self._read("snapshot.json", "flyby_runtime_snapshot")
            if old and now < old["time"]:
                raise ValueError("runtime_clock_regressed")
            events = self._read("events.json", "flyby_runtime_events")["events"]
            sequence = max(old["sequence"] if old else 0, events[-1]["sequence"] if events else 0) + 1
            event = {"sequence": sequence, "time": now, "session": session,
                     "signal": context["decision"]["signal"], "risk_mode": context["risk"]["mode"],
                     "position_count": len(context["positions"]), "order_count": len(context["orders"]),
                     "context_digest": seal(context)}
            self._write("events.json", "flyby_runtime_events", {"events": (events + [event])[-MAX_EVENTS:]})
            state = {**self.owner, "kind": "flyby_runtime_snapshot", "schema": 1, "session": session,
                     "sequence": sequence, "time": now, "mode": mode, "context": context,
                     "latest_receipts": dict(sorted(journal["receipts"].items(), key=lambda row: row[1]["time"])[-8:])}
            self._write("snapshot.json", "flyby_runtime_snapshot", state)
            return state

    def read_state(self, now):
        self._safe_root()
        self._journal()
        state = self._read("snapshot.json", "flyby_runtime_snapshot")
        state["age"] = finite(now) - state["time"]
        state["fresh"] = 0 <= state["age"] <= 5
        return state

    def events(self, after_sequence=0, limit=64):
        if type(after_sequence) is not int or after_sequence < 0 or type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("runtime_invalid_event_cursor")
        self._safe_root()
        self._journal()
        rows = self._read("events.json", "flyby_runtime_events")["events"]
        return {"gap": bool(rows and after_sequence < rows[0]["sequence"] - 1),
                "events": [r for r in rows if r["sequence"] > after_sequence][:limit],
                "earliest_sequence": rows[0]["sequence"] if rows else None}

    def submit(self, request, now):
        if not self.writable:
            raise ValueError("runtime_dry_run_write_denied")
        with self._locked():
            journal = self._journal()
            state = self.read_state(now)
            patch = validate_request(request, state, now)
            digest = seal(request)
            previous = journal["receipts"].get(request["id"])
            if previous:
                if previous["digest"] != digest:
                    raise ValueError("runtime_conflicting_request_id")
                return previous
            if len(journal["receipts"]) >= MAX_RECEIPTS:
                raise ValueError("runtime_receipt_history_full")
            if journal["active"]:
                prior_id = journal["active"]["id"]
                journal["receipts"][prior_id]["status"] = "superseded"
            receipt = {"digest": digest, "status": "queued", "sequence": state["sequence"],
                       "time": now, "effect": "no_exchange_order"}
            journal["receipts"][request["id"]] = receipt
            journal["active"] = {**request, "patch": patch}
            self._write("requests.json", "flyby_runtime_requests", journal)
            return receipt

    def consume(self, state, now):
        with self._locked():
            journal = self._journal()
            request = journal["active"]
            if request is None:
                raise ValueError("runtime_lease_required")
            # Basis age/sequence checked at submission; consumption rechecks session,
            # time, bounds and ownership against the current actual controller state.
            patch = validate_request(request, state, now, consuming=True)
            receipt = journal["receipts"].get(request["id"])
            if receipt is None or receipt["digest"] != seal(request):
                raise ValueError("runtime_receipt_mismatch")
            if receipt["status"] != "validated":
                receipt.update(status="validated", effect="controller_gates_still_required")
                self._write("requests.json", "flyby_runtime_requests", journal)
            return patch

    def status(self, request_id, now=None):
        identifier(request_id)
        self._safe_root()
        journal = self._journal()
        result = dict(journal["receipts"].get(request_id, {"status": "unknown", "effect": "no_verified_fill"}))
        if now is not None:
            result["lease_active"] = False
            active = journal["active"]
            if active and active["id"] == request_id:
                try:
                    validate_request(active, self.read_state(now), now, consuming=True)
                    result["lease_active"] = True
                except (OSError, ValueError, KeyError, TypeError):
                    pass
        return result
