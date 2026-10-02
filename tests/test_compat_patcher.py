"""Pin, idempotency and no-write-on-drift behavior; synthetic offline source files."""
import hashlib

import pytest

from scripts import hummingbot_compat as compat


@pytest.fixture
def targets(tmp_path, monkeypatch):
    original = "class DerivePerpetualDerivative(PerpetualDerivativePyBase):\n"
    for name in compat.DELEGATES:
        original += f"    async def {name}(self):\n        pass\n"
    executor = "class PositionExecutor:\n    def close_position_action(self):\n" + (
        "        if self.is_perpetual:\n            connector = self.connectors[self.config.connector_name]\n"
        "            if connector.position_mode == PositionMode.ONEWAY:\n                return PositionAction.OPEN\n"
        "        return PositionAction.CLOSE\n")
    files = {compat.CONNECTOR: original.encode(), compat.EXECUTOR: executor.encode()}
    hashes = {}
    for name, data in files.items():
        path = tmp_path / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(compat, "ORIGINAL_HASHES", hashes)
    return tmp_path, files


def test_patch_is_explicit_idempotent_and_backed_up(targets):
    root, files = targets
    assert compat.apply_compatibility(root)["installed"] is False
    for name, data in files.items(): assert (root / name).read_bytes() == data
    first = compat.apply_compatibility(root, True)
    assert first["installed"] and compat.apply_compatibility(root)["installed"]
    assert compat.apply_compatibility(root, True) == first
    for name, data in files.items():
        path = root / name
        assert path.with_suffix(".py.flyby-original").read_bytes() == data


def test_second_target_drift_prevents_first_write(targets):
    root, files = targets
    (root / compat.EXECUTOR).write_text("changed upstream")
    with pytest.raises(ValueError, match="unsupported_source_hash"):
        compat.apply_compatibility(root, True)
    assert (root / compat.CONNECTOR).read_bytes() == files[compat.CONNECTOR]
    assert not (root / compat.CONNECTOR).with_suffix(".py.flyby-original").exists()


def test_post_patch_edits_and_bad_backup_are_rejected(targets):
    root, _ = targets
    compat.apply_compatibility(root, True)
    target = root / compat.CONNECTOR
    target.write_text(target.read_text() + "# unexpected edit\n")
    with pytest.raises(ValueError, match="unsupported_source_hash"):
        compat.apply_compatibility(root, True)


def test_restore_exact_originals_keeps_recovery_backup(targets):
    root, files = targets
    compat.apply_compatibility(root, True)
    assert not compat.apply_compatibility(root, restore=True)["installed"]
    for name, data in files.items(): assert (root / name).read_bytes() == data
    assert compat.apply_compatibility(root, True)["installed"]
