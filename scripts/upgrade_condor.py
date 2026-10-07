"""Backed-up authored-file upgrade for an existing Flyby. Starts nothing.

Check-only unless --apply. Preserve extra routines and all runtime files.
Rollback refuses post-upgrade drift rather than overwriting operator changes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_condor_package import validate_package


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_root(path):
    path = Path(path).absolute()
    if path != path.resolve():
        raise ValueError("linked_upgrade_path_refused")
    return path


def upgrade(agents_root, backup_dir=None, apply=False, root=ROOT):
    validate_package(root)
    agents_root = safe_root(agents_root)
    target = agents_root / "flyby"
    if not target.is_dir() or target.is_symlink():
        raise ValueError("existing_flyby_required")
    source = root / "condor/flyby"
    rows = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(source)
        destination = target / relative
        if destination.resolve() != destination or (destination.exists() and not destination.is_file()):
            raise ValueError("invalid_authored_upgrade_target:" + str(relative))
        before = destination.read_bytes() if destination.exists() else None
        after = path.read_bytes()
        if before != after:
            rows.append((str(relative), destination, before, after))
    if apply:
        if backup_dir is None:
            raise ValueError("explicit_new_backup_directory_required")
        backup = safe_root(backup_dir)
        if backup.exists() or target == backup or target in backup.parents:
            raise ValueError("new_backup_outside_agent_required")
        backup.mkdir(parents=True, exist_ok=False, mode=0o700)
        manifest = {"kind": "flyby_authored_upgrade", "schema": 1, "target": str(target), "files": []}
        for relative, destination, before, after in rows:
            if before is not None:
                saved = backup / "files" / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                saved.write_bytes(before)
                saved.chmod(0o600)
            manifest["files"].append({"path": relative, "before": digest(before) if before is not None else None,
                                      "after": digest(after)})
        (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (backup / "manifest.json").chmod(0o600)
        for relative, destination, before, after in rows:
            # Recheck after backup, before replacement; don't clobber a race.
            current = destination.read_bytes() if destination.exists() else None
            if current != before:
                raise ValueError("upgrade_target_changed_after_backup:" + relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".flyby-upgrade-new")
            with temporary.open("xb") as stream:
                stream.write(after)
            temporary.replace(destination)
    return {"agent": "flyby", "target": str(target), "authored_files_changed": len(rows),
            "apply_requested": apply, "runtime_files_preserved": True, "extra_routines_preserved": True,
            "started": False, "orders_submitted": 0}


def rollback(backup_dir, apply=False):
    backup = safe_root(backup_dir)
    manifest = json.loads((backup / "manifest.json").read_text())
    if manifest.get("kind") != "flyby_authored_upgrade" or manifest.get("schema") != 1:
        raise ValueError("invalid_upgrade_backup")
    target = safe_root(manifest["target"])
    if target.name != "flyby" or not target.is_dir():
        raise ValueError("invalid_rollback_agent")
    rows = []
    for entry in manifest["files"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("invalid_rollback_relative_path")
        destination, saved = target / relative, backup / "files" / relative
        if destination.resolve() != destination or digest(destination.read_bytes()) != entry["after"]:
            raise ValueError("rollback_refused_authored_file_drift:" + str(relative))
        before = None
        if entry["before"] is not None:
            if saved.is_symlink():
                raise ValueError("invalid_rollback_backup_link")
            before = saved.read_bytes()
            if digest(before) != entry["before"]:
                raise ValueError("rollback_backup_hash_mismatch")
        rows.append((destination, before))
    if apply:
        for destination, before in rows:
            if before is None:
                destination.unlink()  # only a hash-verified file introduced by this upgrade
            else:
                temporary = destination.with_name(destination.name + ".flyby-rollback-new")
                with temporary.open("xb") as stream:
                    stream.write(before)
                temporary.replace(destination)
    return {"rollback_requested": apply, "authored_files": len(rows), "started": False, "orders_submitted": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents-root", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--rollback", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.rollback:
        result = rollback(args.rollback, args.apply)
    elif args.agents_root:
        result = upgrade(args.agents_root, args.backup_dir, args.apply)
    else:
        parser.error("--agents-root or --rollback required")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
