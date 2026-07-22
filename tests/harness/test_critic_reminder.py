"""critic_reminder: PostToolUse advisory hook for spec/plan writes."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.harness.critic_reminder import (
    build_context,
    find_config,
    is_spec_or_plan,
    load_models,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


# --- is_spec_or_plan: component-aware matching -------------------------------

@pytest.mark.parametrize("p", [
    "docs/plans/foo.md",
    ".worktrees/feat-x/docs/plans/foo.md",
    "docs/superpowers/specs/2026-07-22-x-design.md",
    "/proj/docs/plans/foo.md",
    # Backslash splitting is platform-independent (_parts), so this case
    # must run — and pass — on POSIX CI too, not only on Windows.
    r"C:\proj\docs\plans\foo.md",
])
def test_matches_spec_and_plan_paths(p):
    assert is_spec_or_plan(Path(p))


@pytest.mark.parametrize("p", [
    "docs/plans/foo.txt",                      # not .md
    "src/plans/foo.md",                        # plans not under docs/
    "docs/notes/foo.md",                       # neither plans nor specs
    "node_modules/pkg/specs/foo.md",           # excluded component
    "tests/fixtures/docs/plans/foo.md",        # excluded component
    ".venv/lib/site-packages/x/specs/a.md",    # excluded component
])
def test_rejects_non_spec_plan_paths(p):
    assert not is_spec_or_plan(Path(p))


# --- load_models -------------------------------------------------------------

def test_load_models_absent_is_off(tmp_path):
    models, warning = load_models(tmp_path / "critics.json")
    assert models is None and warning is None


def test_load_models_valid(tmp_path):
    cfg = tmp_path / "critics.json"
    cfg.write_text('{"models": ["opus", "fable"]}', encoding="utf-8")
    models, warning = load_models(cfg)
    assert models == ["opus", "fable"] and warning is None


@pytest.mark.parametrize("body", ["not json {", '{"models": []}', '{"models": "opus"}', "[]"])
def test_load_models_malformed_warns(tmp_path, body):
    cfg = tmp_path / "critics.json"
    cfg.write_text(body, encoding="utf-8")
    models, warning = load_models(cfg)
    assert models is None
    assert warning and "critics.json" in warning


# --- find_config: ancestor walk from the written file ------------------------

def test_find_config_walks_ancestors(tmp_path):
    (tmp_path / ".harness").mkdir()
    cfg = tmp_path / ".harness" / "critics.json"
    cfg.write_text('{"models": ["opus"]}', encoding="utf-8")
    target = tmp_path / "docs" / "plans" / "p.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    assert find_config(target) == cfg


def test_find_config_none_when_absent(tmp_path):
    target = tmp_path / "docs" / "plans" / "p.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    assert find_config(target) is None


def test_find_config_stops_at_repo_boundary(tmp_path):
    # A config ABOVE an intervening .git (e.g. a stray ~/.harness) must
    # never leak into the repo below it.
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "critics.json").write_text(
        '{"models": ["opus"]}', encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    target = repo / "docs" / "plans" / "p.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    assert find_config(target) is None


# --- build_context -----------------------------------------------------------

def test_build_context_names_models_and_protocol():
    ctx = build_context(Path("docs/plans/p.md"), ["opus", "fable"])
    assert "opus" in ctx and "fable" in ctx
    assert "antagonist" in ctx.lower()
    assert "one round" in ctx.lower()


# --- end-to-end via subprocess: exit 0 always, correct JSON ------------------

def _run_hook(stdin: str) -> subprocess.CompletedProcess:
    # cwd is the plugin repo so `-m scripts.harness...` resolves; the hook
    # itself only looks at the target file's ancestors, never at cwd.
    return subprocess.run(
        [sys.executable, "-m", "scripts.harness.critic_reminder"],
        input=stdin, capture_output=True, text=True,
        cwd=str(ROOT),
    )


def _payload(file_path: str, tool: str = "Write") -> str:
    return json.dumps({"tool_name": tool, "tool_input": {"file_path": file_path}})


def test_hook_emits_context_for_plan_write(tmp_path):
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "critics.json").write_text(
        '{"models": ["opus", "fable"]}', encoding="utf-8")
    target = tmp_path / "docs" / "plans" / "p.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    r = _run_hook(_payload(str(target)))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PostToolUse"
    assert "opus" in hso["additionalContext"]


def test_hook_silent_without_config(tmp_path):
    target = tmp_path / "docs" / "plans" / "p.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    r = _run_hook(_payload(str(target)))
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_hook_silent_for_unwatched_tool():
    r = _run_hook(_payload("docs/plans/p.md", tool="Bash"))
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_hook_exit_zero_on_garbage_stdin():
    r = _run_hook("not json at all {{{")
    assert r.returncode == 0


def test_hook_warns_on_malformed_config(tmp_path):
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "critics.json").write_text("{broken", encoding="utf-8")
    target = tmp_path / "docs" / "plans" / "p.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    r = _run_hook(_payload(str(target)))
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert "critics.json" in out["hookSpecificOutput"]["additionalContext"]
