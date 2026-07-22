"""leash_update decision-core tests."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.leash_update import (
    REQUIRED_HOOKS, decide_file, load_manifest, managed_pairs, merge_hooks,
    sha256_file, write_manifest,
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
