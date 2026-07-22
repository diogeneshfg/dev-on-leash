"""Update the copied dev-on-leash layer in a consumer project.

Plugin-side: runs from the plugin cache by path, stdlib-only.
See docs/superpowers/specs/2026-07-22-leash-update-design.md.
"""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path

MANIFEST_REL = Path(".harness") / "leash.json"

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
