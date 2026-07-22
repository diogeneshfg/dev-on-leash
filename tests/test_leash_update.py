"""leash_update decision-core tests."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.leash_update import (
    REQUIRED_HOOKS, decide_file, load_manifest, managed_pairs, merge_hooks,
    run_update, sha256_file, write_manifest,
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


def _fake_plugin(tmp_path: Path) -> Path:
    root = tmp_path / "plugin"
    _f(root / "scripts" / "harness" / "session_gate.py", "GATE v2\n")
    _f(root / "scripts" / "harness" / "session_root_guard.py", "GUARD v1\n")
    _f(root / "templates" / "task-schema.md", "SCHEMA v2\n")
    _f(root / "templates" / "plan-template.md", "PLAN v2\n")
    _f(root / "templates" / "hooks" / "pre-commit", "HOOK v2\n")
    _f(root / ".claude-plugin" / "plugin.json", json.dumps({"version": "0.6.0"}))
    return root


def _fake_project(tmp_path: Path) -> Path:
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
    proj = _fake_project(tmp_path)
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
    proj = _fake_project(tmp_path)
    run_update(plugin_root=plugin, target=proj, force=set())
    report = run_update(plugin_root=plugin, target=proj, force=set())
    assert set(report["actions"].values()) <= {"unchanged", "refused"}
    assert report["hooks_added"] == []


def test_run_update_force_overwrites_named_file(tmp_path: Path):
    plugin = _fake_plugin(tmp_path)
    proj = _fake_project(tmp_path)
    report = run_update(plugin_root=plugin, target=proj,
                        force={".harness/hooks/pre-commit"})
    assert report["actions"][".harness/hooks/pre-commit"] == "updated"
    assert (proj / ".harness/hooks/pre-commit").read_text() == "HOOK v2\n"


def test_init_manifest_only_stamps_without_writing(tmp_path: Path):
    plugin = _fake_plugin(tmp_path)
    proj = _fake_project(tmp_path)
    (proj / ".harness" / "leash.json").unlink()
    run_update(plugin_root=plugin, target=proj, force=set(),
               init_manifest_only=True)
    assert (proj / "scripts/harness/session_gate.py").read_text() == "GATE v1\n"
    m = load_manifest(proj)
    assert m["version"] == "0.6.0"
    assert m["files"]["scripts/harness/session_gate.py"] == sha256_file(
        proj / "scripts/harness/session_gate.py")
    assert "scripts/harness/session_root_guard.py" not in m["files"]


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


def test_managed_pairs_covers_harness_and_templates():
    root = Path(".").resolve()
    pairs = dict((rel, src) for src, rel in managed_pairs(root))
    assert "scripts/harness/session_gate.py" in pairs
    assert "scripts/harness/session_root_guard.py" in pairs
    assert pairs["docs/task-schema.md"].name == "task-schema.md"
    assert "docs/plan-template.md" in pairs
    assert ".harness/hooks/pre-commit" in pairs
    assert not any("__pycache__" in str(s) for s in pairs.values())
