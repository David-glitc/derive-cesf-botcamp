"""Offline explicit pinned-source patcher; check-only unless --apply is supplied."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.execution.derive_hb import COMPATIBILITY_VERSION

CONNECTOR = "hummingbot/connector/derivative/derive_perpetual/derive_perpetual_derivative.py"
EXECUTOR = "hummingbot/strategy_v2/executors/position_executor/position_executor.py"
ORIGINAL_HASHES = {
    CONNECTOR: "1cec03be53e233d47fab2130c8bd893486267205ccee3fea3cab1ceaa8bfb80c",
    EXECUTOR: "09aef3092e616822568272e2b75181267913240398779f4cf57791cddae60c09",
}
DELEGATES = {
    "_place_order": '''    async def _place_order(self, order_id, trading_pair, amount, trade_type, order_type, price, position_action=PositionAction.NIL, **kwargs):
        from src.execution.derive_hb import place_order
        return await place_order(self, order_id, trading_pair, amount, trade_type, order_type, price, position_action, **kwargs)
''',
    "_update_balances": '''    async def _update_balances(self):
        from src.execution.derive_hb import update_balances
        return await update_balances(self)
''',
    "_update_positions": '''    async def _update_positions(self):
        from src.execution.derive_hb import update_positions
        return await update_positions(self)
''',
    "_process_update_positions": '''    async def _process_update_positions(self, results):
        from src.execution.derive_hb import process_positions
        return await process_positions(self, results)
''',
    "_process_update_balances": '''    def _process_update_balances(self, balance_msg):
        from src.execution.derive_hb import process_balance
        return process_balance(self, balance_msg)
''',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def transform(path, original):
    text = original.decode()
    if path == CONNECTOR:
        lines = text.splitlines(keepends=True)
        cls = next(n for n in ast.parse(text).body if isinstance(n, ast.ClassDef) and n.name == "DerivePerpetualDerivative")
        selected = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in DELEGATES]
        if len(selected) != len(DELEGATES):
            raise ValueError("missing_pinned_connector_method")
        for node in sorted(selected, key=lambda n: n.lineno, reverse=True):
            lines[node.lineno - 1:node.end_lineno] = [DELEGATES[node.name]]
        text = "".join(lines)
        text = text.replace("class DerivePerpetualDerivative(PerpetualDerivativePyBase):\n",
                            "class DerivePerpetualDerivative(PerpetualDerivativePyBase):\n"
                            f"    FLYBY_COMPATIBILITY_VERSION = {COMPATIBILITY_VERSION!r}\n", 1)
    elif path == EXECUTOR:
        marker = "        if self.is_perpetual:\n            connector = self.connectors[self.config.connector_name]\n            if connector.position_mode == PositionMode.ONEWAY:\n                return PositionAction.OPEN\n"
        replacement = "        if self.is_perpetual:\n            connector = self.connectors[self.config.connector_name]\n            if self.config.connector_name == 'derive_perpetual':\n                return PositionAction.CLOSE\n            if connector.position_mode == PositionMode.ONEWAY:\n                return PositionAction.OPEN\n"
        if text.count(marker) != 1:
            raise ValueError("missing_pinned_executor_close_branch")
        text = text.replace(marker, replacement)
    else:
        raise ValueError("unknown_patch_target")
    ast.parse(text)
    return text.encode()


def inspect_targets(hb_dir):
    """Validate both files before any write; exact originals or exact treatment only."""
    result = []
    for relative, expected in ORIGINAL_HASHES.items():
        target = hb_dir / relative
        if target.is_symlink() or not target.is_file():
            raise ValueError(f"invalid_patch_target:{relative}")
        data = target.read_bytes()
        backup = target.with_suffix(target.suffix + ".flyby-original")
        if digest(data) == expected:
            original = data
            if backup.exists() and (backup.is_symlink() or digest(backup.read_bytes()) != expected):
                raise ValueError(f"invalid_patch_backup:{relative}")
        elif backup.is_file() and not backup.is_symlink() and digest(backup.read_bytes()) == expected:
            original = backup.read_bytes()
            if data != transform(relative, original):
                raise ValueError(f"unsupported_source_hash:{relative}")
        else:
            raise ValueError(f"unsupported_source_hash:{relative}")
        treatment = transform(relative, original)
        result.append((target, backup, original, treatment, data == treatment))
    return result


def apply_compatibility(hb_dir, apply=False, restore=False):
    if apply and restore:
        raise ValueError("choose_apply_or_restore")
    targets = inspect_targets(hb_dir)
    if apply or restore:
        for target, backup, original, treatment, patched in targets:
            if (apply and not patched) or (restore and patched):
                if not backup.exists():
                    with backup.open("xb") as stream:
                        stream.write(original)
                temporary = target.with_suffix(target.suffix + ".flyby-new")
                with temporary.open("xb") as stream:
                    stream.write(original if restore else treatment)
                temporary.replace(target)
    return {"compatibility": COMPATIBILITY_VERSION, "apply_requested": apply,
            "restore_requested": restore,
            "installed": False if restore else apply or all(row[-1] for row in targets),
            "files": {str(row[0].relative_to(hb_dir)): digest(row[3]) for row in targets},
            "orders_submitted": 0, "live_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hb-dir", type=Path, default=Path("/home/hummingbot"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--restore", action="store_true", help="Restore exact verified originals; stop clients first")
    args = parser.parse_args()
    try:
        print(json.dumps(apply_compatibility(args.hb_dir.resolve(), args.apply, args.restore), indent=2))
    except (ValueError, OSError, SyntaxError) as exc:
        print(f"Compatibility preflight failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
