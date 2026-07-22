"""Update the copied dev-on-leash layer in a consumer project.

Plugin-side: runs from the plugin cache by path, stdlib-only.
See docs/superpowers/specs/2026-07-22-leash-update-design.md.
"""
from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import shutil
import sys
from pathlib import Path

MANIFEST_REL = Path(".harness") / "leash.json"

REQUIRED_HOOKS: list[tuple[str, str | None, str]] = [
    ("SessionStart", None, "python -m scripts.harness.session_root_guard"),
    ("PreToolUse", "Edit|Write|MultiEdit|NotebookEdit",
     "python -m scripts.harness.session_gate"),
]

TEMPLATE_PAIRS = [
    ("templates/task-schema.md", "docs/task-schema.md"),
    ("templates/plan-template.md", "docs/plan-template.md"),
    ("templates/hooks/pre-commit", ".harness/hooks/pre-commit"),
]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def managed_pairs(plugin_root: Path) -> list[tuple[Path, str]]:
    pairs: list[tuple[Path, str]] = []
    harness = plugin_root / "scripts" / "harness"
    for src in sorted(harness.glob("*.py")):
        pairs.append((src, f"scripts/harness/{src.name}"))
    for plugin_rel, target_rel in TEMPLATE_PAIRS:
        pairs.append((plugin_root / plugin_rel, target_rel))
    return pairs


def decide_file(*, src: Path, dst: Path, manifest_hash: str | None,
                forced: bool) -> tuple[str, str | None]:
    src_hash = sha256_file(src)
    if not dst.exists():
        return "added", None
    dst_hash = sha256_file(dst)
    if dst_hash == src_hash:
        return "unchanged", None
    if forced or (manifest_hash is not None and dst_hash == manifest_hash):
        return "updated", None
    diff = "".join(difflib.unified_diff(
        dst.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True),
        src.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True),
        fromfile=f"local/{dst.name}", tofile=f"plugin/{src.name}"))
    return "refused", diff


def merge_hooks(settings: dict) -> tuple[dict, list[str]]:
    """Additive-only: append REQUIRED_HOOKS entries missing from settings.

    Matched by command string; never removes, reorders, or rewrites user
    entries or permissions."""
    merged = copy.deepcopy(settings)
    hooks = merged.setdefault("hooks", {})
    added: list[str] = []
    for event, matcher, command in REQUIRED_HOOKS:
        entries = hooks.setdefault(event, [])
        present = any(
            h.get("command") == command
            for entry in entries if isinstance(entry, dict)
            for h in entry.get("hooks", []) if isinstance(h, dict))
        if present:
            continue
        entry: dict = {"hooks": [{"type": "command", "command": command}]}
        if matcher is not None:
            entry = {"matcher": matcher, **entry}
        entries.append(entry)
        added.append(command)
    return merged, added


def load_manifest(target: Path) -> dict:
    path = target / MANIFEST_REL
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_manifest(target: Path, *, version: str, files: dict[str, str]) -> None:
    path = target / MANIFEST_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": 1, "version": version, "files": files}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _plugin_version(plugin_root: Path) -> str:
    meta = json.loads((plugin_root / ".claude-plugin" / "plugin.json")
                      .read_text(encoding="utf-8"))
    return str(meta.get("version", "unknown"))


def _merge_settings_file(target: Path) -> list[str]:
    path = target / ".claude" / "settings.json"
    settings: dict = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []  # never rewrite a file we cannot parse
    merged, added = merge_hooks(settings)
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return added


def run_update(*, plugin_root: Path, target: Path, force: set[str],
               init_manifest_only: bool = False) -> dict:
    version = _plugin_version(plugin_root)
    old_files = load_manifest(target).get("files", {})
    actions: dict[str, str] = {}
    diffs: dict[str, str] = {}
    new_files: dict[str, str] = {}
    for src, rel in managed_pairs(plugin_root):
        dst = target / rel
        if init_manifest_only:
            if dst.exists():
                new_files[rel] = sha256_file(dst)
                actions[rel] = "stamped"
            continue
        action, diff = decide_file(
            src=src, dst=dst, manifest_hash=old_files.get(rel),
            forced=rel in force)
        actions[rel] = action
        if action in ("added", "updated"):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        if action == "refused":
            diffs[rel] = diff or ""
            if rel in old_files:
                new_files[rel] = old_files[rel]
        else:
            new_files[rel] = sha256_file(dst)
    hooks_added = [] if init_manifest_only else _merge_settings_file(target)
    write_manifest(target, version=version, files=new_files)
    return {"version": version, "actions": actions,
            "hooks_added": hooks_added, "diffs": diffs}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Update the dev-on-leash layer")
    ap.add_argument("target")
    ap.add_argument("--force", action="append", default=[],
                    metavar="RELPATH", help="overwrite a locally edited file")
    ap.add_argument("--init-manifest", action="store_true",
                    help="only stamp .harness/leash.json; change nothing")
    ns = ap.parse_args(argv)
    plugin_root = Path(__file__).resolve().parent.parent
    target = Path(ns.target).resolve()
    if not target.is_dir():
        print(f"ERROR: target is not a directory: {target}")
        return 1
    report = run_update(plugin_root=plugin_root, target=target,
                        force=set(f.replace("\\", "/") for f in ns.force),
                        init_manifest_only=ns.init_manifest)
    for rel, action in sorted(report["actions"].items()):
        print(f"{action:9}  {rel}")
    for cmd in report["hooks_added"]:
        print(f"hook+     {cmd}")
    for rel, diff in report["diffs"].items():
        print(f"\n--- refused (locally edited): {rel} - "
              f"rerun with --force {rel} to overwrite ---\n{diff}")
    print(f"\nleash.json stamped at version {report['version']}. "
          f"CLAUDE.md/AGENTS.md are never touched - see the plugin "
          f"CHANGELOG for anything worth porting by hand.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
