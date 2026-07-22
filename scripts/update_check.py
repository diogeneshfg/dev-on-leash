"""Plugin-level SessionStart hook: warn when a leashed project is stale.

Runs in every project where the dev-on-leash plugin is enabled, so it
must cost nothing off leashed repos and never break a session: any
uncertainty -> silent exit 0. Self-contained stdlib (runs by path from
the plugin cache; nothing else is importable).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _json_or_none(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def check(*, cwd: Path, plugin_root: Path) -> str | None:
    if not (cwd / ".harness").is_dir():
        return None  # not a leashed project
    if (cwd / ".claude-plugin" / "plugin.json").exists():
        return None  # the plugin repo itself
    meta = _json_or_none(plugin_root / ".claude-plugin" / "plugin.json")
    if not meta or "version" not in meta:
        return None
    plugin_version = str(meta["version"])
    manifest = _json_or_none(cwd / ".harness" / "leash.json")
    local = str(manifest.get("version")) if manifest else None
    if local == plugin_version:
        return None
    have = local or "unstamped (pre-0.6.0 bootstrap)"
    return (
        f"DEV-ON-LEASH UPDATE: this project's harness layer is {have}; the "
        f"installed plugin is {plugin_version}. Run /leash-update to bring "
        f"scripts/harness/ and the hook wiring up to date (local edits are "
        f"detected and never clobbered)."
    )


def main() -> int:
    try:
        try:
            payload = json.loads(sys.stdin.read().lstrip("﻿") or "{}")
        except json.JSONDecodeError:
            payload = {}
        raw = payload.get("cwd") if isinstance(payload, dict) else None
        cwd = Path(raw) if isinstance(raw, str) and raw else Path(os.getcwd())
        plugin_root = Path(__file__).resolve().parent.parent
        msg = check(cwd=cwd.resolve(), plugin_root=plugin_root)
        if msg:
            sys.stdout.write(msg)
    except Exception:  # noqa: BLE001 - fail-silent by contract
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
