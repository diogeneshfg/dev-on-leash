# leash-update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consumer projects detect a stale dev-on-leash harness automatically at SessionStart and update it with one command, refusing to clobber local edits.

**Architecture:** A committed hash manifest (`.harness/leash.json`) makes staleness and local edits detectable. Detection ships as a plugin-level SessionStart hook (`scripts/update_check.py`, runs everywhere the plugin is enabled, silent off leashed repos). Application is one cross-platform Python script (`scripts/leash_update.py`) driven by a thin `leash-update` skill.

**Tech Stack:** Python 3.12 stdlib only (json, hashlib, difflib, pathlib). pytest.

**Spec:** `docs/superpowers/specs/2026-07-22-leash-update-design.md`

## Global Constraints

- Plugin-side scripts live in `scripts/` (NOT `scripts/harness/` — they are not copied into projects) and must be stdlib-only and self-contained (no `from scripts.harness import ...`: they run by path, so `sys.path[0]` is the plugin's `scripts/`).
- `update_check.py` must be fail-silent: any error → exit 0, no output.
- `leash_update.py` never touches `CLAUDE.md`, `AGENTS.md`, `.harness/gates`, `docs/plans/`. Settings merge is additive-only.
- Refused files keep their old manifest hash so the next run still flags them.
- All new behavior is TDD'd; the dogfood script must exercise the real updater end-to-end before merge (feedback-dogfood memory). README must be updated in this plan, not as a follow-up (feedback-plan-includes-readme memory).

---

### Task 1: `leash_update.py` — manifest + per-file decision core

**Files:**
- Create: `scripts/leash_update.py`
- Test: `tests/test_leash_update.py`

**Interfaces (Produces):**
- `sha256_file(p: Path) -> str`
- `managed_pairs(plugin_root: Path) -> list[tuple[Path, str]]` — `(absolute source, target-relative posix path)`; harness pair list is dynamic over `scripts/harness/*.py`, plus `templates/task-schema.md → docs/task-schema.md`, `templates/plan-template.md → docs/plan-template.md`, `templates/hooks/pre-commit → .harness/hooks/pre-commit`.
- `decide_file(*, src: Path, dst: Path, manifest_hash: str | None, forced: bool) -> tuple[str, str | None]` — returns `(action, diff)`, action ∈ `added | updated | unchanged | refused`; diff (unified, dst→src) only for `refused`.
- `load_manifest(target: Path) -> dict` / `write_manifest(target: Path, *, version: str, files: dict[str, str]) -> None` — at `.harness/leash.json`, schema `{"schema": 1, "version": ..., "files": {...}}`.

- [x] **Step 1: Write the failing tests**

```python
"""leash_update decision-core tests."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.leash_update import (
    decide_file, load_manifest, managed_pairs, sha256_file, write_manifest,
)


def _f(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_decide_added_when_target_missing(tmp_path: Path):
    src = _f(tmp_path / "src" / "gate.py", "new\n")
    action, diff = decide_file(
        src=src, dst=tmp_path / "t" / "gate.py", manifest_hash=None, forced=False)
    assert action == "added" and diff is None


def test_decide_unchanged_when_identical(tmp_path: Path):
    src = _f(tmp_path / "src" / "gate.py", "same\n")
    dst = _f(tmp_path / "t" / "gate.py", "same\n")
    action, _ = decide_file(src=src, dst=dst, manifest_hash=sha256_file(dst), forced=False)
    assert action == "unchanged"


def test_decide_updated_when_intact_copy(tmp_path: Path):
    src = _f(tmp_path / "src" / "gate.py", "v2\n")
    dst = _f(tmp_path / "t" / "gate.py", "v1\n")
    action, _ = decide_file(src=src, dst=dst, manifest_hash=sha256_file(dst), forced=False)
    assert action == "updated"


def test_decide_refused_when_locally_edited(tmp_path: Path):
    src = _f(tmp_path / "src" / "gate.py", "v2\n")
    dst = _f(tmp_path / "t" / "gate.py", "v1 hacked\n")
    action, diff = decide_file(
        src=src, dst=dst, manifest_hash="0" * 64, forced=False)
    assert action == "refused"
    assert diff and "hacked" in diff


def test_decide_refused_when_no_manifest_and_different(tmp_path: Path):
    src = _f(tmp_path / "src" / "gate.py", "v2\n")
    dst = _f(tmp_path / "t" / "gate.py", "v1\n")
    action, _ = decide_file(src=src, dst=dst, manifest_hash=None, forced=False)
    assert action == "refused"


def test_decide_forced_overwrites_local_edit(tmp_path: Path):
    src = _f(tmp_path / "src" / "gate.py", "v2\n")
    dst = _f(tmp_path / "t" / "gate.py", "hacked\n")
    action, _ = decide_file(src=src, dst=dst, manifest_hash="0" * 64, forced=True)
    assert action == "updated"


def test_manifest_roundtrip(tmp_path: Path):
    write_manifest(tmp_path, version="0.6.0", files={"a": "h"})
    m = load_manifest(tmp_path)
    assert m["schema"] == 1 and m["version"] == "0.6.0" and m["files"] == {"a": "h"}
    assert (tmp_path / ".harness" / "leash.json").exists()


def test_load_manifest_missing_returns_empty(tmp_path: Path):
    assert load_manifest(tmp_path) == {}


def test_managed_pairs_covers_harness_and_templates():
    root = Path(".").resolve()
    pairs = dict((rel, src) for src, rel in managed_pairs(root))
    assert "scripts/harness/session_gate.py" in pairs
    assert "scripts/harness/session_root_guard.py" in pairs
    assert pairs["docs/task-schema.md"].name == "task-schema.md"
    assert "docs/plan-template.md" in pairs
    assert ".harness/hooks/pre-commit" in pairs
    assert not any("__pycache__" in str(s) for s in pairs.values())
```

- [x] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_leash_update.py -q`
Expected: collection error — `No module named 'scripts.leash_update'`.

- [x] **Step 3: Minimal implementation**

```python
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
```

- [x] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_leash_update.py -q` → all pass.

- [x] **Step 5: Commit**

```bash
git add scripts/leash_update.py tests/test_leash_update.py
git commit -m "feat(update): leash_update decision core - manifest, managed set, per-file actions"
```

---

### Task 2: settings.json additive hook merge

**Files:**
- Modify: `scripts/leash_update.py`
- Test: `tests/test_leash_update.py`

**Interfaces (Produces):**
- `REQUIRED_HOOKS: list[tuple[str, str | None, str]]` — `(event, matcher, command)`; source of truth for hook wiring.
- `merge_hooks(settings: dict) -> tuple[dict, list[str]]` — returns `(new settings, added command strings)`; pure (no I/O).

- [x] **Step 1: Failing tests**

```python
from scripts.leash_update import REQUIRED_HOOKS, merge_hooks


def test_merge_adds_missing_sessionstart_hook():
    settings = {"hooks": {"PreToolUse": [{
        "matcher": "Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [{"type": "command",
                   "command": "python -m scripts.harness.session_gate"}]}]}}
    merged, added = merge_hooks(settings)
    assert added == ["python -m scripts.harness.session_root_guard"]
    ss = merged["hooks"]["SessionStart"]
    assert ss[0]["hooks"][0]["command"] == "python -m scripts.harness.session_root_guard"
    assert "matcher" not in ss[0]


def test_merge_is_idempotent_and_preserves_user_entries():
    user_hook = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}
    settings = {"permissions": {"allow": ["Bash(ls)"]},
                "hooks": {"PreToolUse": [user_hook]}}
    once, _ = merge_hooks(settings)
    twice, added = merge_hooks(once)
    assert added == []
    assert twice == once
    assert user_hook in twice["hooks"]["PreToolUse"]
    assert twice["permissions"] == {"allow": ["Bash(ls)"]}


def test_required_hooks_agree_with_settings_template():
    text = Path("templates/settings.json.tmpl").read_text(encoding="utf-8")
    for _event, _matcher, command in REQUIRED_HOOKS:
        assert command in text, f"template missing required hook: {command}"
```

- [x] **Step 2: Verify RED** — `ImportError: cannot import name 'REQUIRED_HOOKS'`.

- [x] **Step 3: Implementation** (append to `leash_update.py`)

```python
import copy

REQUIRED_HOOKS: list[tuple[str, str | None, str]] = [
    ("SessionStart", None, "python -m scripts.harness.session_root_guard"),
    ("PreToolUse", "Edit|Write|MultiEdit|NotebookEdit",
     "python -m scripts.harness.session_gate"),
]


def merge_hooks(settings: dict) -> tuple[dict, list[str]]:
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
```

- [x] **Step 4: Verify GREEN** — full file: `python -m pytest tests/test_leash_update.py -q`.

- [x] **Step 5: Commit** — `git commit -m "feat(update): additive settings.json hook merge with REQUIRED_HOOKS source of truth"`

---

### Task 3: `run_update` + CLI + `--init-manifest`; init scripts stamp the manifest

**Files:**
- Modify: `scripts/leash_update.py`, `scripts/init.ps1`, `scripts/init.sh`
- Test: `tests/test_leash_update.py`

**Interfaces (Produces):**
- `run_update(*, plugin_root: Path, target: Path, force: set[str], init_manifest_only: bool = False) -> dict` — report `{"version": str, "actions": {relpath: action}, "hooks_added": [...], "diffs": {relpath: diff}}`. Applies copies, merges settings (reading/writing `<target>/.claude/settings.json` if present, creating it with `{"hooks": ...}` if absent), writes manifest. `init_manifest_only` writes only the manifest for files currently identical-or-present, changing nothing else.
- CLI: `python leash_update.py <target> [--force RELPATH]... [--init-manifest]`.

- [x] **Step 1: Failing tests** (fixture builds a fake plugin root + fake project)

```python
from scripts.leash_update import run_update


def _fake_plugin(tmp_path: Path) -> Path:
    root = tmp_path / "plugin"
    _f(root / "scripts" / "harness" / "session_gate.py", "GATE v2\n")
    _f(root / "scripts" / "harness" / "session_root_guard.py", "GUARD v1\n")
    _f(root / "templates" / "task-schema.md", "SCHEMA v2\n")
    _f(root / "templates" / "plan-template.md", "PLAN v2\n")
    _f(root / "templates" / "hooks" / "pre-commit", "HOOK v2\n")
    _f(root / ".claude-plugin" / "plugin.json", json.dumps({"version": "0.6.0"}))
    return root


def _fake_project(tmp_path: Path, plugin: Path) -> Path:
    proj = tmp_path / "proj"
    _f(proj / "scripts" / "harness" / "session_gate.py", "GATE v1\n")
    _f(proj / "docs" / "task-schema.md", "SCHEMA v1\n")
    _f(proj / "docs" / "plan-template.md", "PLAN v2\n")   # already current
    _f(proj / ".harness" / "hooks" / "pre-commit", "HOOK v1 EDITED\n")
    _f(proj / ".claude" / "settings.json", json.dumps({"hooks": {}}))
    write_manifest(proj, version="0.5.0", files={
        "scripts/harness/session_gate.py":
            sha256_file(proj / "scripts/harness/session_gate.py"),
        "docs/task-schema.md": sha256_file(proj / "docs/task-schema.md"),
        "docs/plan-template.md": sha256_file(proj / "docs/plan-template.md"),
        ".harness/hooks/pre-commit": "f" * 64,  # local edit: hash mismatch
    })
    return proj


def test_run_update_full_matrix(tmp_path: Path):
    plugin = _fake_plugin(tmp_path)
    proj = _fake_project(tmp_path, plugin)
    report = run_update(plugin_root=plugin, target=proj, force=set())
    a = report["actions"]
    assert a["scripts/harness/session_gate.py"] == "updated"
    assert a["scripts/harness/session_root_guard.py"] == "added"
    assert a["docs/task-schema.md"] == "updated"
    assert a["docs/plan-template.md"] == "unchanged"
    assert a[".harness/hooks/pre-commit"] == "refused"
    assert ".harness/hooks/pre-commit" in report["diffs"]
    # files actually written
    assert (proj / "scripts/harness/session_gate.py").read_text() == "GATE v2\n"
    assert (proj / "scripts/harness/session_root_guard.py").exists()
    assert (proj / ".harness/hooks/pre-commit").read_text() == "HOOK v1 EDITED\n"
    # settings merged
    st = json.loads((proj / ".claude/settings.json").read_text())
    assert report["hooks_added"] and st["hooks"]["SessionStart"]
    # manifest: refused keeps old hash, updated gets new
    m = load_manifest(proj)
    assert m["version"] == "0.6.0"
    assert m["files"][".harness/hooks/pre-commit"] == "f" * 64
    assert m["files"]["scripts/harness/session_gate.py"] == sha256_file(
        proj / "scripts/harness/session_gate.py")


def test_run_update_second_run_all_unchanged(tmp_path: Path):
    plugin = _fake_plugin(tmp_path)
    proj = _fake_project(tmp_path, plugin)
    run_update(plugin_root=plugin, target=proj, force=set())
    report = run_update(plugin_root=plugin, target=proj, force=set())
    assert set(report["actions"].values()) <= {"unchanged", "refused"}
    assert report["hooks_added"] == []


def test_run_update_force_overwrites_named_file(tmp_path: Path):
    plugin = _fake_plugin(tmp_path)
    proj = _fake_project(tmp_path, plugin)
    report = run_update(plugin_root=plugin, target=proj,
                        force={".harness/hooks/pre-commit"})
    assert report["actions"][".harness/hooks/pre-commit"] == "updated"
    assert (proj / ".harness/hooks/pre-commit").read_text() == "HOOK v2\n"


def test_init_manifest_only_stamps_without_writing(tmp_path: Path):
    plugin = _fake_plugin(tmp_path)
    proj = _fake_project(tmp_path, plugin)
    (proj / ".harness" / "leash.json").unlink()
    report = run_update(plugin_root=plugin, target=proj, force=set(),
                        init_manifest_only=True)
    assert (proj / "scripts/harness/session_gate.py").read_text() == "GATE v1\n"
    m = load_manifest(proj)
    assert m["version"] == "0.6.0"
    assert m["files"]["scripts/harness/session_gate.py"] == sha256_file(
        proj / "scripts/harness/session_gate.py")
    assert "scripts/harness/session_root_guard.py" not in m["files"]
```

- [x] **Step 2: Verify RED** — `ImportError: cannot import name 'run_update'`.

- [x] **Step 3: Implementation** (append to `leash_update.py`)

```python
import argparse
import shutil
import sys


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
            new_files[rel] = sha256_file(dst) if dst.exists() else sha256_file(src)
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
                        force=set(ns.force),
                        init_manifest_only=ns.init_manifest)
    for rel, action in sorted(report["actions"].items()):
        print(f"{action:9}  {rel}")
    for cmd in report["hooks_added"]:
        print(f"hook+     {cmd}")
    for rel, diff in report["diffs"].items():
        print(f"\n--- refused (locally edited): {rel} — "
              f"rerun with --force {rel} to overwrite ---\n{diff}")
    print(f"\nleash.json stamped at version {report['version']}. "
          f"CLAUDE.md/AGENTS.md are never touched - see the plugin "
          f"CHANGELOG for anything worth porting by hand.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [x] **Step 4: Verify GREEN** — `python -m pytest tests/test_leash_update.py -q`.

- [x] **Step 5: init scripts stamp the manifest.** `init.ps1`, before the summary block:

```powershell
# 7. Stamp .harness/leash.json so /leash-update can detect staleness later
$UpdateScript = Join-Path $PluginRoot 'scripts\leash_update.py'
try {
    python $UpdateScript $Target --init-manifest | Out-Null
    Write-Host 'Created: .harness/leash.json'
    $Created.Add('.harness/leash.json')
} catch {
    Write-Warning 'Could not stamp .harness/leash.json (python missing?) - /leash-update will still work.'
}
```

`init.sh`, same position:

```bash
# 7. Stamp .harness/leash.json so /leash-update can detect staleness later
if python "$PLUGIN_ROOT/scripts/leash_update.py" "$TARGET" --init-manifest >/dev/null 2>&1; then
    echo "Created: .harness/leash.json"
else
    echo "WARNING: could not stamp .harness/leash.json (python missing?) - /leash-update will still work." >&2
fi
```

- [x] **Step 6: Commit** — `git commit -m "feat(update): run_update CLI with --force/--init-manifest; init stamps manifest"`

---

### Task 4: `update_check.py` + plugin `hooks/hooks.json`

**Files:**
- Create: `scripts/update_check.py`, `hooks/hooks.json`
- Test: `tests/test_update_check.py`

**Interfaces (Produces):**
- `check(*, cwd: Path, plugin_root: Path) -> str | None` — warning text or None. Self-contained (no imports from `scripts.harness` or `leash_update`).

- [x] **Step 1: Failing tests**

```python
"""update_check tests: silent off leashed repos, warns on stale manifest."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.update_check import check


def _plugin(tmp_path: Path, version: str = "0.6.0") -> Path:
    root = tmp_path / "plugin"
    meta = root / ".claude-plugin" / "plugin.json"
    meta.parent.mkdir(parents=True)
    meta.write_text(json.dumps({"version": version}), encoding="utf-8")
    return root


def _leashed(tmp_path: Path, manifest_version: str | None) -> Path:
    proj = tmp_path / "proj"
    (proj / ".harness").mkdir(parents=True)
    if manifest_version is not None:
        (proj / ".harness" / "leash.json").write_text(
            json.dumps({"schema": 1, "version": manifest_version, "files": {}}),
            encoding="utf-8")
    return proj


def test_silent_on_non_leashed_cwd(tmp_path: Path):
    plugin = _plugin(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    assert check(cwd=plain, plugin_root=plugin) is None


def test_silent_on_plugin_repo_itself(tmp_path: Path):
    plugin = _plugin(tmp_path)
    (plugin / ".harness").mkdir()
    assert check(cwd=plugin, plugin_root=plugin) is None


def test_silent_when_versions_match(tmp_path: Path):
    plugin = _plugin(tmp_path, "0.6.0")
    proj = _leashed(tmp_path, "0.6.0")
    assert check(cwd=proj, plugin_root=plugin) is None


def test_warns_on_version_mismatch(tmp_path: Path):
    plugin = _plugin(tmp_path, "0.6.0")
    proj = _leashed(tmp_path, "0.5.0")
    msg = check(cwd=proj, plugin_root=plugin)
    assert msg and "0.5.0" in msg and "0.6.0" in msg and "/leash-update" in msg


def test_warns_on_missing_manifest(tmp_path: Path):
    plugin = _plugin(tmp_path, "0.6.0")
    proj = _leashed(tmp_path, None)
    msg = check(cwd=proj, plugin_root=plugin)
    assert msg and "/leash-update" in msg


def test_hooks_json_wires_update_check():
    data = json.loads(Path("hooks/hooks.json").read_text(encoding="utf-8"))
    commands = [h["command"]
                for entry in data["hooks"]["SessionStart"]
                for h in entry["hooks"]]
    assert any("update_check.py" in c and "${CLAUDE_PLUGIN_ROOT}" in c
               for c in commands)
```

- [x] **Step 2: Verify RED** — `No module named 'scripts.update_check'`.

- [x] **Step 3: Implementation** — `scripts/update_check.py`:

```python
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
```

`hooks/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"${CLAUDE_PLUGIN_ROOT}/scripts/update_check.py\""
          }
        ]
      }
    ]
  }
}
```

- [x] **Step 4: Verify GREEN** — `python -m pytest tests/test_update_check.py -q`.

- [x] **Step 5: Commit** — `git commit -m "feat(update): plugin-level SessionStart staleness check"`

---

### Task 5: `leash-update` skill + bootstrap note

**Files:**
- Create: `skills/leash-update/SKILL.md`
- Modify: `skills/bootstrap-dev-leash/SKILL.md` (init step: mention the manifest stamp)
- Test: `tests/test_skill_update.py`

- [x] **Step 1: Failing structural test**

```python
"""Structural assertions for the leash-update skill markdown."""
from __future__ import annotations

from pathlib import Path

SKILL_PATH = Path("skills/leash-update/SKILL.md")


def test_skill_exists_with_frontmatter():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\n") and "name: leash-update" in text


def test_skill_invokes_plugin_script_by_path():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "${CLAUDE_PLUGIN_ROOT}/scripts/leash_update.py" in text
    assert "--force" in text and "--init-manifest" not in text.split("## Constraints")[0]


def test_skill_documents_refusal_and_untouched_files():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "CLAUDE.md" in text and "AGENTS.md" in text
    assert "refus" in text.lower()
```

- [x] **Step 2: Verify RED** — file missing.

- [x] **Step 3: Write `skills/leash-update/SKILL.md`**

```markdown
---
name: leash-update
description: Use to update the dev-on-leash layer of an already-bootstrapped project — "update the harness", "leash update", or after the SessionStart warning that the harness is stale. Overwrites intact copies, refuses locally edited files with a diff, and additively merges missing hook wiring into .claude/settings.json.
---

# leash-update

## When to use

A SessionStart warning said this project's harness is older than the
installed plugin, or you know the plugin was updated. Runs inside a
bootstrapped target project (it needs `.harness/`).

## How

1. Run, from the project root:

   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/leash_update.py" .
   ```

2. Read the report to the user: which files were `updated`/`added`,
   which were `refused` (locally edited — show the diff), and which hook
   entries were merged into `.claude/settings.json`.

3. For each refused file, let the user decide: keep the local edit, or
   rerun with `--force <relpath>` to overwrite that one file.

4. Point at the plugin CHANGELOG entries between the old and new version
   for guidance worth porting into `CLAUDE.md`/`AGENTS.md` by hand —
   the updater never touches those two files.

5. Remind the user to review `git diff` and commit the update.

## Constraints

- Additive only on `.claude/settings.json`; never removes or reorders
  user entries. Unparseable settings are left alone.
- Never touches `CLAUDE.md`, `AGENTS.md`, `.harness/gates`, `docs/plans/`.
- Refusal is the default for any divergent file; `--force` is per-file
  and deliberate. (`--init-manifest` exists for the init scripts, not
  for this flow.)
```

- [x] **Step 4: bootstrap-dev-leash SKILL.md** — in the init-script section, after the copy description, add: "The init script finishes by stamping `.harness/leash.json` (a version + hash manifest) so `/leash-update` can later detect staleness and local edits."

- [x] **Step 5: Verify GREEN + commit** — `git commit -m "feat(update): leash-update skill; bootstrap documents the manifest stamp"`

---

### Task 6: dogfood script + smoke_e2e wiring

**Files:**
- Create: `scripts/dogfood_leash_update.py`
- Modify: `scripts/smoke_e2e.py` (add step calling the dogfood script)

- [x] **Step 1: Write `scripts/dogfood_leash_update.py`** — uses this repo as the real plugin root; builds a temp fixture project; asserts the matrix end-to-end via the CLI (subprocess), not by importing internals:

```python
"""Dogfood: run the real leash_update CLI against a fixture project.

Uses this repo as the plugin root. Asserts: stale intact files update,
new files arrive, a planted local edit is refused with a diff, the
missing SessionStart hook is merged, and a second run is all-unchanged.
Exit 0 only if every assertion holds.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def run_cli(target: Path, *extra: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "leash_update.py"),
         str(target), *extra],
        capture_output=True, text=True, cwd=str(REPO))
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / "proj"
        # stale-but-intact copy of one real harness file
        gate_src = REPO / "scripts" / "harness" / "session_gate.py"
        gate_dst = proj / "scripts" / "harness" / "session_gate.py"
        gate_dst.parent.mkdir(parents=True)
        gate_dst.write_text("# old intact copy\n", encoding="utf-8")
        # planted local edit
        hook_dst = proj / ".harness" / "hooks" / "pre-commit"
        hook_dst.parent.mkdir(parents=True)
        hook_dst.write_text("# LOCAL EDIT\n", encoding="utf-8")
        # settings without the SessionStart hook
        st = proj / ".claude" / "settings.json"
        st.parent.mkdir(parents=True)
        st.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        # manifest: gate intact (hash matches), hook edited (hash differs)
        import hashlib
        manifest = {"schema": 1, "version": "0.0.1", "files": {
            "scripts/harness/session_gate.py":
                hashlib.sha256(gate_dst.read_bytes()).hexdigest(),
            ".harness/hooks/pre-commit": "0" * 64}}
        (proj / ".harness" / "leash.json").write_text(
            json.dumps(manifest), encoding="utf-8")

        out1 = run_cli(proj)
        assert "updated" in out1 and "session_gate.py" in out1
        assert gate_dst.read_text(encoding="utf-8") == gate_src.read_text(encoding="utf-8")
        assert "refused" in out1 and "pre-commit" in out1
        assert hook_dst.read_text(encoding="utf-8") == "# LOCAL EDIT\n"
        settings = json.loads(st.read_text(encoding="utf-8"))
        assert settings["hooks"].get("SessionStart"), "SessionStart hook not merged"

        out2 = run_cli(proj)
        assert "updated" not in out2 and "added" not in out2, "second run must be quiet"

        out3 = run_cli(proj, "--force", ".harness/hooks/pre-commit")
        assert hook_dst.read_text(encoding="utf-8") != "# LOCAL EDIT\n"
        assert "refused" not in out3
    print("DOGFOOD leash-update PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 2: Run it** — `python scripts/dogfood_leash_update.py` → `DOGFOOD leash-update PASS`.

- [x] **Step 3: Wire into `scripts/smoke_e2e.py`** — add a step following the existing pattern (find the step list; add `("leash-update: stale->update, edit->refuse", [sys.executable, "scripts/dogfood_leash_update.py"])`-style entry consistent with how `dogfood_worktree_gate.py` is invoked; renumber the `[N/10]` labels if they are literal).

- [x] **Step 4: Run smoke** — `python scripts/smoke_e2e.py` → `SMOKE PASS`.

- [x] **Step 5: Commit** — `git commit -m "test(update): dogfood leash-update end-to-end; wire into smoke_e2e"`

---

### Task 7: README + CHANGELOG

**Files:**
- Modify: `README.md` (new "Updating" section after the bootstrap/init docs), `CHANGELOG.md` (`[Unreleased]`)

- [x] **Step 1: README "Updating" section**

```markdown
## Updating a bootstrapped project

Skills and agents update with the plugin automatically; the *copied*
layer (`scripts/harness/`, `docs/task-schema.md`, `docs/plan-template.md`,
the pre-commit hook) does not. A plugin-level `SessionStart` hook
(`scripts/update_check.py`) compares the project's `.harness/leash.json`
stamp against the installed plugin version and warns when the project is
stale — including projects bootstrapped before the stamp existed.

Run `/leash-update` to apply: intact copies are overwritten, new files
are added, and missing hook entries are merged (additively) into
`.claude/settings.json`. Files you edited locally are **refused** with a
diff — override one at a time with `--force <relpath>`. `CLAUDE.md` and
`AGENTS.md` are never touched; the report points at the CHANGELOG
entries between your version and the plugin's for anything worth porting
by hand. Review `git diff` and commit the result.
```

- [x] **Step 2: CHANGELOG `[Unreleased]` → `### Added`**

```markdown
### Added
- **`/leash-update` + automatic staleness detection.** Consumer projects
  now carry `.harness/leash.json` (version + file-hash manifest, stamped
  by init). A plugin-level SessionStart hook (`scripts/update_check.py`)
  warns when the project's copied layer is older than the installed
  plugin; `/leash-update` (`scripts/leash_update.py`) applies the update:
  intact files overwritten, locally edited files refused with a diff
  (`--force <relpath>` per file), missing hook wiring merged additively
  into `.claude/settings.json`. `CLAUDE.md`/`AGENTS.md` are never touched.
```

- [x] **Step 3: Full suite + smoke** — `python -m pytest -q` all green; `python scripts/smoke_e2e.py` → `SMOKE PASS`.

- [x] **Step 4: Commit** — `git commit -m "docs(update): README Updating section + CHANGELOG"`

---

## Self-review notes

- Spec coverage: Section 1 → Tasks 1/3; Section 2 → Task 4; Section 3 → Tasks 1–3, 5; Section 4 → Tasks 6–7. Non-goals respected (no CLAUDE/AGENTS writes anywhere).
- Type consistency: `run_update` report shape used identically in Task 3 tests, Task 6 dogfood; `REQUIRED_HOOKS` tuples match `merge_hooks` consumption.
- The Task 3 `stamped` action appears only in `--init-manifest` mode and is deliberately absent from the Task 1 decision matrix.
