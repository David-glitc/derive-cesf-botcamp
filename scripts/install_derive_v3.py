"""Explicit, offline, hash-verified Derive connector overlay. Starts nothing.

Run against a STOPPED Hummingbot V2 client. Accepts only exact stock 2.17
sources, this pinned V3 overlay, or a verified Flyby-delegated variant.
Original files/backups are preserved; unexpected edits abort before writes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.hummingbot_compat import CONNECTOR, EXECUTOR, ORIGINAL_HASHES, transform

VENDOR = ROOT / "vendor/derive_v3"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def old_connector(data):
    # Exact old delegated form only, reconstructed from its verified original.
    text = transform(CONNECTOR, data).decode()
    return text.replace("flyby-derive-v3-r2", "flyby-derive-2.17.0-r1").encode()


def install(hb_dir, apply=False):
    manifest = json.loads((VENDOR / "manifest.json").read_text())
    executor = hb_dir / EXECUTOR
    if executor.is_symlink() or not executor.is_file():
        raise ValueError("v3_invalid_executor_target")
    current_executor = executor.read_bytes()
    expected_executor = ORIGINAL_HASHES[EXECUTOR]
    executor_backup = executor.with_suffix(executor.suffix + ".flyby-original")
    if digest(current_executor) != expected_executor:
        if (not executor_backup.is_file() or executor_backup.is_symlink() or
                digest(executor_backup.read_bytes()) != expected_executor or
                current_executor != transform(EXECUTOR, executor_backup.read_bytes())):
            raise ValueError("v3_unreviewed_executor_source")
    targets = []
    for relative, expected in manifest["files"].items():
        source, target = VENDOR / relative, hb_dir / relative
        if source.is_symlink() or not source.is_file() or digest(source.read_bytes()) != expected:
            raise ValueError("v3_vendor_hash_mismatch:" + relative)
        if target.is_symlink() or not target.is_file():
            raise ValueError("v3_invalid_target:" + relative)
        new, current = source.read_bytes(), target.read_bytes()
        legacy = manifest["legacy_files"][relative]
        allowed = digest(current) in (expected, legacy)
        compatibility_backup = target.with_suffix(target.suffix + ".flyby-original")
        if relative == CONNECTOR:
            if current == transform(relative, new):
                allowed = True
            elif compatibility_backup.is_file() and not compatibility_backup.is_symlink():
                previous = compatibility_backup.read_bytes()
                allowed = allowed or (digest(previous) == legacy and current == old_connector(previous))
        if not allowed:
            raise ValueError("v3_unreviewed_installed_source:" + relative)
        # Native V3 compatibility uses a separate backup; retain any V2 backup.
        backup = target.with_suffix(target.suffix + ".flyby-v2-original")
        if backup.exists() and (backup.is_symlink() or digest(backup.read_bytes()) != legacy):
            raise ValueError("v3_invalid_legacy_backup:" + relative)
        if compatibility_backup.exists() and relative == CONNECTOR:
            data = compatibility_backup.read_bytes()
            if compatibility_backup.is_symlink() or digest(data) not in (legacy, expected):
                raise ValueError("v3_invalid_compatibility_backup")
            moved = target.with_suffix(target.suffix + ".flyby-v2-compat-backup")
            if moved.exists() and (moved.is_symlink() or digest(moved.read_bytes()) != legacy):
                raise ValueError("v3_invalid_preserved_compatibility_backup")
        targets.append((target, new, current, legacy, backup, compatibility_backup))
    if apply:
        for target, new, current, legacy, backup, compatibility_backup in targets:
            if str(target).endswith(CONNECTOR) and compatibility_backup.exists():
                if digest(compatibility_backup.read_bytes()) == legacy:
                    moved = target.with_suffix(target.suffix + ".flyby-v2-compat-backup")
                    if not moved.exists():
                        compatibility_backup.rename(moved)
                    else:
                        # Leave an existing identical V2 copy intact; patcher
                        # accepts the native V3 original recorded below.
                        compatibility_backup.write_bytes(new)
            if current == new or (str(target).endswith(CONNECTOR) and current == transform(CONNECTOR, new)):
                continue
            original = current
            if digest(original) != legacy:
                original = target.with_suffix(target.suffix + ".flyby-v2-compat-backup").read_bytes()
            if digest(original) == legacy and not backup.exists():
                with backup.open("xb") as stream:
                    stream.write(original)
            temporary = target.with_suffix(target.suffix + ".flyby-v3-new")
            with temporary.open("xb") as stream:
                stream.write(new)
            temporary.replace(target)
    return {"api_generation": "v3", "framework": "Hummingbot V2", "apply_requested": apply,
            "upstream_commit": manifest["upstream_commit"], "files_verified": len(targets),
            "orders_submitted": 0, "services_started": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hb-dir", type=Path, default=Path("/home/hummingbot"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.hb_dir.resolve(), args.apply), indent=2))
    except (ValueError, OSError, SyntaxError) as exc:
        print("V3 overlay preflight failed: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
