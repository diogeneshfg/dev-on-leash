# Worktree-Mandatory Leash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the session-leash (PID-election + lockfiles, fragile on Windows) with a stateless git-based gate: the main worktree is read-only to write tools, all work happens in a linked worktree, and a one-shot audited escape allows the occasional direct main-tree write.

**Architecture:** A `PreToolUse` hook (`session_gate.py`, rewritten) resolves the write target, runs `git worktree list --porcelain`, and denies the write iff the target's longest-prefix-matching worktree is the *main* worktree — unless a one-shot marker (`.harness/allow-main-write`) is present, which it consumes and logs. No PIDs, no `primary_cwd`, no election. Concurrency becomes impossible by construction (no session may edit the main tree; each works on its own branch+worktree). The session-detection machinery is deleted; the two worktree skills collapse to `leash-start-work` (create) + `leash-finish-work` (cleanup).

**Tech Stack:** Python 3.12 stdlib only (no third-party deps), `git` CLI, pytest, Claude Code hooks (`SessionStart` removed, `PreToolUse` kept).

## Global Constraints

- **Stdlib only.** No new third-party dependencies in `scripts/harness/`.
- **Cross-platform, Windows-first.** The whole motivation is a Windows bug. Use `pathlib` and `Path.is_relative_to` for path-component-aware containment (never `str.startswith`). Resolve all paths with `.resolve()`.
- **Hook protocol.** `PreToolUse` hook reads JSON `{tool_name, tool_input, ...}` from stdin, writes JSON `{"decision": "allow"|"deny", "reason": str}` to stdout, exits 0 always.
- **Gated tools:** `Edit`, `Write`, `MultiEdit`, `NotebookEdit`. `Bash`, `Read`, `Grep`, `Glob` are NOT gated (leash-start-work needs `git worktree add` via Bash).
- **Fail-open on uncertainty.** If `git worktree list` fails or the dir is not a repo, allow the write and append a warning to `.harness/exceptions.log`.
- **Audit pattern.** The one-shot escape logs to `.harness/exceptions.log`, same convention as `cycle_done --force`.
- **No WIP copying.** Worktree creation never copies uncommitted changes (unchanged stance).
- **Commit cadence:** one commit per task, conventional-commit messages, end every commit message body with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Spec:** `docs/superpowers/specs/2026-06-19-worktree-mandatory-leash-design.md`.

---

## File Structure

**New:**
- `scripts/harness/allow_main_write.py` — writes the one-shot marker.
- `scripts/harness/finish_work.py` — backend for `/leash-finish-work` (stateless cleanup).
- `skills/leash-finish-work/SKILL.md` — renamed/rewritten from `leash-session-end`.
- `tests/harness/test_allow_main_write.py` — marker writer unit tests.
- `tests/harness/test_finish_work.py` — cleanup backend unit tests.
- `scripts/dogfood_worktree_gate.py` — rewritten dogfood (replaces `dogfood_session.py`).

**Rewritten:**
- `scripts/harness/session_gate.py` — stateless git-based gate.
- `tests/harness/test_session_gate.py` — new decision matrix.
- `scripts/smoke_e2e.py` — replace the session-leash e2e steps.

**Deleted:**
- `scripts/harness/session_lockfile.py`, `scripts/harness/session_start.py`, `scripts/harness/session_new.py`, `scripts/harness/session_end.py`, `scripts/harness/list_sessions.py`, `scripts/dogfood_session.py`
- `skills/leash-session-new/`, `skills/leash-session-end/`
- `tests/harness/test_session_lockfile.py`, `tests/harness/test_session_start.py`, `tests/harness/test_session_new.py`, `tests/harness/test_session_end.py`, `tests/harness/test_list_sessions.py`, `tests/harness/test_cycle_done_session_sweep.py`, `tests/test_session_new.py`

**Modified:**
- `scripts/harness/cycle_done.py` — remove `sweep_session_worktrees` + its lockfile import; keep `advise_merged_worktrees`.
- `templates/settings.json.tmpl` — drop `SessionStart`; keep gate.
- `templates/CLAUDE.md.tmpl`, `templates/AGENTS.md.tmpl` — replace "Concurrent sessions".
- `README.md` — "Session leash" → "Worktree leash"; trust-model update.
- `tests/test_docs.py` — assertions for the new README section.
- `CHANGELOG.md` — breaking-change entry.
- `skills/leash-start-work/SKILL.md` — reframe as the single mandatory path.
- `skills/bootstrap-dev-leash/SKILL.md` — migration note (remove `SessionStart` on re-bootstrap).

---

## Task 1: Rewrite the gate (`session_gate.py`) — stateless, git-based

**Files:**
- Modify (full rewrite): `scripts/harness/session_gate.py`
- Test: `tests/harness/test_session_gate.py` (rewritten in Task 2)

**Interfaces:**
- Produces:
  - `Decision(allow: bool, reason: str)` with `.to_json()`.
  - `list_worktrees(cwd: Path) -> list[Path] | None` — absolute worktree paths, main worktree first; `None` on git failure / non-repo.
  - `decide(*, tool_name: str, tool_input: dict, worktrees: list[Path] | None, marker_path: Path, log_path: Path, gate_pid: int = 0) -> Decision` — consumes `marker_path` + appends to `log_path` on a sanctioned main-tree write.
  - `GATED_TOOLS = frozenset({"Edit","Write","MultiEdit","NotebookEdit"})`
  - `MARKER_NAME = "allow-main-write"`, `EXCEPTIONS_LOG = "exceptions.log"`

- [ ] **Step 1: Write the failing tests** — see Task 2 (write Task 2's test file first; it imports the new symbols and will fail to import).

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/harness/test_session_gate.py -q`
Expected: FAIL — `ImportError`/`AttributeError` (no `list_worktrees`, `decide` signature changed).

- [ ] **Step 3: Replace the file contents**

```python
"""PreToolUse hook: the main worktree is read-only to write tools.

Stateless and git-based. A write whose target resolves into the *main*
worktree is denied; the developer works in a linked worktree (created by
/leash-start-work). A one-shot marker (.harness/allow-main-write)
authorizes exactly one main-tree write and is consumed + logged.

No lockfiles, no PIDs, no session election — that machinery mis-elected
two primaries on Windows (non-monotonic PIDs). Concurrency is now
prevented by construction: no session may write the main tree.

Hook protocol: read JSON from stdin {tool_name, tool_input, ...}, print
JSON {"decision": "allow"|"deny", "reason": str} on stdout. Exit 0.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

GATED_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

MARKER_NAME = "allow-main-write"
EXCEPTIONS_LOG = "exceptions.log"

DENY_MESSAGE = (
    "SESSION LEASH: the main worktree is read-only. Start your change in a "
    "worktree with /leash-start-work, then write there. To make a one-off "
    "write to the main tree, run:\n"
    '  python -m scripts.harness.allow_main_write "<reason>"\n'
    "and retry — it authorizes exactly one main-tree write and is logged."
)


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str

    def to_json(self) -> str:
        return json.dumps(
            {"decision": "allow" if self.allow else "deny", "reason": self.reason}
        )


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_worktrees(cwd: Path) -> list[Path] | None:
    """Absolute worktree paths, main worktree first. None on git failure.

    `git worktree list` is repo-global: it returns every worktree
    (main + linked) regardless of which one `cwd` sits in, so probing
    from the project dir is sufficient. The first `worktree` line is the
    main worktree.
    """
    try:
        proc = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(cwd), capture_output=True, text=True,
        )
    except (OSError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    out: list[Path] = []
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            raw = line[len("worktree "):].strip()
            try:
                out.append(Path(raw).resolve())
            except (OSError, ValueError):
                pass
    return out or None


def _resolve_target(tool_input: dict) -> Path | None:
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(target, str) or not target:
        return None
    try:
        return Path(target).resolve()
    except (OSError, ValueError):
        return None


def _containing_worktree(target: Path, worktrees: list[Path]) -> Path | None:
    """Longest path-component-aware prefix match, or None if outside all.

    Uses Path.is_relative_to (component-aware) so a sibling whose name
    merely starts with a worktree name is NOT treated as inside it.
    """
    best: Path | None = None
    best_len = -1
    for wt in worktrees:
        if target == wt or target.is_relative_to(wt):
            n = len(wt.parts)
            if n > best_len:
                best = wt
                best_len = n
    return best


def _append_log(log_path: Path, *, kind: str, gate_pid: int, target: Path | None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{_now_iso()}  {kind}  pid={gate_pid}  target={target}\n"
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def decide(
    *,
    tool_name: str,
    tool_input: dict,
    worktrees: list[Path] | None,
    marker_path: Path,
    log_path: Path,
    gate_pid: int = 0,
) -> Decision:
    """Decide allow/deny. Consumes the marker + logs on a sanctioned main write."""
    if tool_name not in GATED_TOOLS:
        return Decision(allow=True, reason="")
    target = _resolve_target(tool_input)
    if target is None:
        return Decision(allow=True, reason="")
    if not worktrees:
        return Decision(allow=True, reason="")  # fail-open (main() logs the warning)
    main_wt = worktrees[0]
    containing = _containing_worktree(target, worktrees)
    if containing is None:
        return Decision(allow=True, reason="")  # outside the repo entirely
    if containing != main_wt:
        return Decision(allow=True, reason="")  # a linked worktree — allowed
    # target is in the main worktree
    if marker_path.exists():
        try:
            marker_path.unlink()
        except FileNotFoundError:
            pass
        _append_log(log_path, kind="main-write", gate_pid=gate_pid, target=target)
        return Decision(allow=True, reason="one-shot main-tree write authorized")
    return Decision(allow=False, reason=DENY_MESSAGE)


def main(argv: list[str]) -> int:
    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    harness = cwd / ".harness"
    marker_path = harness / MARKER_NAME
    log_path = harness / EXCEPTIONS_LOG
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    worktrees: list[Path] | None = None
    if tool_name in GATED_TOOLS and _resolve_target(tool_input) is not None:
        worktrees = list_worktrees(cwd)
        if worktrees is None:
            try:
                _append_log(log_path, kind="gate-failopen",
                            gate_pid=os.getppid(),
                            target=_resolve_target(tool_input))
            except OSError:
                pass

    d = decide(
        tool_name=tool_name, tool_input=tool_input, worktrees=worktrees,
        marker_path=marker_path, log_path=log_path, gate_pid=os.getppid(),
    )
    sys.stdout.write(d.to_json())
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/harness/test_session_gate.py -q`
Expected: PASS (all of Task 2's tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/harness/session_gate.py tests/harness/test_session_gate.py
git commit -m "feat(gate): stateless git-based worktree gate, drop PID election"
```

---

## Task 2: Gate decision-matrix tests

**Files:**
- Test (full rewrite): `tests/harness/test_session_gate.py`

**Interfaces:**
- Consumes: `decide`, `Decision`, `list_worktrees`, `GATED_TOOLS` from `scripts.harness.session_gate` (Task 1).

> Write this file as part of Task 1, Step 1 (it is the failing test). Shown
> here as its own task for the reviewer gate.

- [ ] **Step 1: Replace the file contents**

```python
"""Stateless worktree-gate tests."""
from __future__ import annotations

from pathlib import Path

from scripts.harness.session_gate import (
    Decision, decide, list_worktrees, GATED_TOOLS,
)


def _mk(tmp_path: Path) -> tuple[Path, Path]:
    """Return (marker_path, log_path) under a fresh .harness."""
    harness = tmp_path / ".harness"
    harness.mkdir(parents=True, exist_ok=True)
    return harness / "allow-main-write", harness / "exceptions.log"


def test_non_gated_tool_allows(tmp_path: Path):
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    main_wt.mkdir()
    d = decide(
        tool_name="Bash", tool_input={"command": "ls"},
        worktrees=[main_wt], marker_path=marker, log_path=log,
    )
    assert d.allow is True


def test_main_tree_write_denied(tmp_path: Path):
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    main_wt.mkdir()
    d = decide(
        tool_name="Edit",
        tool_input={"file_path": str(main_wt / "README.md")},
        worktrees=[main_wt], marker_path=marker, log_path=log,
    )
    assert d.allow is False
    assert "/leash-start-work" in d.reason


def test_linked_worktree_write_allowed(tmp_path: Path):
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    linked = tmp_path / "repo--wt"
    main_wt.mkdir()
    linked.mkdir()
    d = decide(
        tool_name="Write",
        tool_input={"file_path": str(linked / "x.py")},
        worktrees=[main_wt, linked], marker_path=marker, log_path=log,
    )
    assert d.allow is True


def test_nested_worktree_beats_main_prefix(tmp_path: Path):
    """`.worktrees/<slug>` lives inside the repo; longest-prefix match
    must classify a target there as the *linked* worktree, not main."""
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    nested = main_wt / ".worktrees" / "feat-x"
    nested.mkdir(parents=True)
    d = decide(
        tool_name="Edit",
        tool_input={"file_path": str(nested / "x.py")},
        worktrees=[main_wt, nested], marker_path=marker, log_path=log,
    )
    assert d.allow is True


def test_outside_repo_allows(tmp_path: Path):
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    main_wt.mkdir()
    d = decide(
        tool_name="Edit",
        tool_input={"file_path": str(tmp_path / "elsewhere" / "x.py")},
        worktrees=[main_wt], marker_path=marker, log_path=log,
    )
    assert d.allow is True


def test_sibling_prefix_attack_denied(tmp_path: Path):
    """A sibling whose name starts with the main name is still outside
    every linked worktree, so it falls back to... outside the repo →
    allow. The real regression we guard: a target literally inside main
    must not be mis-allowed by a startswith bug. Use a nested case."""
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    linked = main_wt / ".worktrees" / "abc"
    evil = main_wt / ".worktrees" / "abcEVIL"
    linked.mkdir(parents=True)
    evil.mkdir(parents=True)
    d = decide(
        tool_name="Edit",
        tool_input={"file_path": str(evil / "bad.py")},
        worktrees=[main_wt, linked], marker_path=marker, log_path=log,
    )
    # abcEVIL is not inside `abc`; longest match is main → deny.
    assert d.allow is False
    assert "/leash-start-work" in d.reason


def test_one_shot_marker_allows_consumes_and_logs(tmp_path: Path):
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    main_wt.mkdir()
    marker.write_text('{"schema":1,"reason":"typo"}', encoding="utf-8")
    d = decide(
        tool_name="Edit",
        tool_input={"file_path": str(main_wt / "README.md")},
        worktrees=[main_wt], marker_path=marker, log_path=log, gate_pid=42,
    )
    assert d.allow is True
    assert not marker.exists(), "marker must be consumed"
    assert log.exists() and "main-write" in log.read_text(encoding="utf-8")


def test_second_main_write_after_consume_denied(tmp_path: Path):
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    main_wt.mkdir()
    marker.write_text("{}", encoding="utf-8")
    first = decide(
        tool_name="Edit", tool_input={"file_path": str(main_wt / "a.md")},
        worktrees=[main_wt], marker_path=marker, log_path=log,
    )
    second = decide(
        tool_name="Edit", tool_input={"file_path": str(main_wt / "b.md")},
        worktrees=[main_wt], marker_path=marker, log_path=log,
    )
    assert first.allow is True
    assert second.allow is False


def test_fail_open_when_no_worktrees(tmp_path: Path):
    marker, log = _mk(tmp_path)
    d = decide(
        tool_name="Edit", tool_input={"file_path": str(tmp_path / "x.py")},
        worktrees=None, marker_path=marker, log_path=log,
    )
    assert d.allow is True


def test_notebook_edit_is_gated(tmp_path: Path):
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    main_wt.mkdir()
    d = decide(
        tool_name="NotebookEdit",
        tool_input={"notebook_path": str(main_wt / "n.ipynb")},
        worktrees=[main_wt], marker_path=marker, log_path=log,
    )
    assert d.allow is False


def test_no_target_allows(tmp_path: Path):
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    main_wt.mkdir()
    d = decide(
        tool_name="Edit", tool_input={},
        worktrees=[main_wt], marker_path=marker, log_path=log,
    )
    assert d.allow is True


def test_list_worktrees_on_real_repo(tmp_path: Path):
    import subprocess
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=repo)
    subprocess.check_call(["git", "config", "user.email", "d@d"], cwd=repo)
    subprocess.check_call(["git", "config", "user.name", "d"], cwd=repo)
    (repo / "seed").write_text("s\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=repo)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=repo)
    wts = list_worktrees(repo)
    assert wts is not None
    assert wts[0] == repo.resolve()


def test_list_worktrees_non_repo_returns_none(tmp_path: Path):
    assert list_worktrees(tmp_path) is None
```

- [ ] **Step 2: Run + commit** — covered by Task 1 Steps 4–5.

---

## Task 3: One-shot escape (`allow_main_write.py`)

**Files:**
- Create: `scripts/harness/allow_main_write.py`
- Test: `tests/harness/test_allow_main_write.py`

**Interfaces:**
- Produces: `write_marker(*, harness_dir: Path, reason: str) -> Path` writing `<harness_dir>/allow-main-write`; `main(argv) -> int`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the one-shot main-write authorization marker."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.harness.allow_main_write import write_marker


def test_write_marker_creates_json(tmp_path: Path):
    harness = tmp_path / ".harness"
    marker = write_marker(harness_dir=harness, reason="quick typo")
    assert marker == harness / "allow-main-write"
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert data["reason"] == "quick typo"
    assert "created_at" in data


def test_write_marker_makes_dir(tmp_path: Path):
    harness = tmp_path / "nope" / ".harness"
    marker = write_marker(harness_dir=harness, reason="r")
    assert marker.exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/harness/test_allow_main_write.py -q`
Expected: FAIL — `ModuleNotFoundError: scripts.harness.allow_main_write`.

- [ ] **Step 3: Create the implementation**

```python
"""Authorize exactly one write to the main worktree.

Writes .harness/allow-main-write. The PreToolUse gate
(scripts.harness.session_gate) consumes it on the next main-tree write
and appends an audit line to .harness/exceptions.log.

Run via Bash (not gated) when you need a one-off direct edit to the main
tree instead of working in a worktree:

    python -m scripts.harness.allow_main_write "fix changelog typo"
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

MARKER_NAME = "allow-main-write"


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_marker(*, harness_dir: Path, reason: str) -> Path:
    harness_dir.mkdir(parents=True, exist_ok=True)
    marker = harness_dir / MARKER_NAME
    marker.write_text(
        json.dumps(
            {"schema": 1, "reason": reason, "created_at": _now_iso()},
            indent=2, sort_keys=True,
        ),
        encoding="utf-8",
    )
    return marker


def main(argv: list[str]) -> int:
    reason = " ".join(argv[1:]).strip() or "(no reason given)"
    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    marker = write_marker(harness_dir=cwd / ".harness", reason=reason)
    print(f"Authorized ONE main-tree write (reason: {reason}).")
    print(f"Marker: {marker}")
    print("It is consumed by the next main-tree write and logged to "
          ".harness/exceptions.log. Retry your edit now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/harness/test_allow_main_write.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/harness/allow_main_write.py tests/harness/test_allow_main_write.py
git commit -m "feat(gate): one-shot audited escape for main-tree writes"
```

---

## Task 4: Cleanup backend (`finish_work.py`) + skill rename

**Files:**
- Create: `scripts/harness/finish_work.py`
- Create: `skills/leash-finish-work/SKILL.md`
- Delete: `scripts/harness/session_end.py`, `skills/leash-session-end/SKILL.md`, `tests/harness/test_session_end.py`
- Test: `tests/harness/test_finish_work.py`

**Interfaces:**
- Produces:
  - `FinishWorkError(RuntimeError)`
  - `resolve_worktree(*, repo_root: Path, slug: str | None = None, worktree_path: str | None = None) -> Path`
  - `finish_work(*, repo_root: Path, slug: str | None = None, worktree_path: str | None = None, keep_branch: bool = False) -> str` (returns the deleted/kept branch name)
  - `main(argv) -> int`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the stateless leash-finish-work backend."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.harness.finish_work import finish_work, FinishWorkError


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "d@d"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "d"], cwd=path)
    (path / "seed").write_text("seed\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=path)


def _add_worktree(repo: Path, slug: str, branch: str) -> Path:
    wt = repo / ".worktrees" / slug
    subprocess.check_call(
        ["git", "worktree", "add", str(wt), "-b", branch, "main"], cwd=repo)
    return wt


def test_removes_merged_clean_worktree(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    wt = _add_worktree(repo, "feat-x", "feat/x")
    # branch has no new commits → trivially merged into main
    branch = finish_work(repo_root=repo, slug="feat-x")
    assert branch == "feat/x"
    assert not wt.exists()


def test_refuses_dirty_worktree(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    wt = _add_worktree(repo, "feat-x", "feat/x")
    (wt / "dirty.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(FinishWorkError, match="uncommitted"):
        finish_work(repo_root=repo, slug="feat-x")
    assert wt.exists()


def test_refuses_unmerged_branch(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    wt = _add_worktree(repo, "feat-x", "feat/x")
    (wt / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=wt)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=wt)
    with pytest.raises(FinishWorkError, match="unmerged"):
        finish_work(repo_root=repo, slug="feat-x")


def test_keep_branch_skips_merge_check(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    wt = _add_worktree(repo, "feat-x", "feat/x")
    (wt / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=wt)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=wt)
    branch = finish_work(repo_root=repo, slug="feat-x", keep_branch=True)
    assert branch == "feat/x"
    assert not wt.exists()
    # branch still present
    out = subprocess.run(["git", "branch"], cwd=repo, capture_output=True, text=True).stdout
    assert "feat/x" in out


def test_refuses_main_worktree(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    with pytest.raises(FinishWorkError):
        finish_work(repo_root=repo, worktree_path=str(repo))


def test_requires_a_name(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    with pytest.raises(FinishWorkError, match="name the worktree"):
        finish_work(repo_root=repo)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/harness/test_finish_work.py -q`
Expected: FAIL — `ModuleNotFoundError: scripts.harness.finish_work`.

- [ ] **Step 3: Create the implementation**

```python
"""leash-finish-work: remove a .worktrees/<slug> worktree + its branch.

Stateless (no lockfiles). Counterpart to /leash-start-work. Refuses on a
dirty worktree or an unmerged branch unless --keep-branch. Never uses
`git worktree remove --force` or `git branch -D` — work is never silently
discarded.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


class FinishWorkError(RuntimeError):
    pass


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise FinishWorkError(
            f"git {' '.join(args)} failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    return proc.stdout


def _current_branch(worktree: Path) -> str:
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree).strip()


def _worktree_dirty(worktree: Path) -> bool:
    return bool(_git(["status", "--porcelain"], cwd=worktree).strip())


def _branch_is_merged(repo: Path, branch: str) -> bool:
    out = _git(["branch", "--merged"], cwd=repo)
    # Strip `*` (current) and `+` (checked out in a linked worktree) markers.
    merged = {b.strip().lstrip("*+ ").strip() for b in out.splitlines()}
    return branch in merged


def resolve_worktree(
    *, repo_root: Path, slug: str | None = None, worktree_path: str | None = None
) -> Path:
    if worktree_path:
        return Path(worktree_path).resolve()
    if slug:
        return (repo_root / ".worktrees" / slug).resolve()
    raise FinishWorkError("name the worktree: pass a slug or --path")


def finish_work(
    *,
    repo_root: Path,
    slug: str | None = None,
    worktree_path: str | None = None,
    keep_branch: bool = False,
) -> str:
    wt = resolve_worktree(repo_root=repo_root, slug=slug, worktree_path=worktree_path)
    if wt == repo_root.resolve():
        raise FinishWorkError("refusing to remove the main worktree")
    if not wt.exists():
        raise FinishWorkError(f"worktree not found: {wt}")
    branch = _current_branch(wt)
    if branch in ("main", "master"):
        raise FinishWorkError(f"worktree {wt} is on {branch}; refusing")
    if _worktree_dirty(wt):
        raise FinishWorkError(
            f"worktree {wt} has uncommitted changes; commit or stash first"
        )
    if not keep_branch and not _branch_is_merged(repo_root, branch):
        raise FinishWorkError(
            f"branch {branch} is unmerged; merge it first or pass --keep-branch"
        )
    _git(["worktree", "remove", str(wt)], cwd=repo_root)
    if not keep_branch:
        _git(["branch", "-d", branch], cwd=repo_root)
    return branch


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("slug", nargs="?", default=None,
                   help="slug under .worktrees/ to finish")
    p.add_argument("--path", dest="worktree_path", default=None,
                   help="explicit worktree path (overrides slug)")
    p.add_argument(
        "--repo-root", type=Path,
        default=Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()),
    )
    p.add_argument("--keep-branch", action="store_true")
    args = p.parse_args(argv[1:])
    try:
        branch = finish_work(
            repo_root=args.repo_root.resolve(),
            slug=args.slug,
            worktree_path=args.worktree_path,
            keep_branch=args.keep_branch,
        )
    except FinishWorkError as exc:
        sys.stderr.write(f"leash-finish-work: {exc}\n")
        return 1
    kept = " (branch kept)" if args.keep_branch else ""
    print(f"Finished work on {branch}; worktree removed{kept}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Create the skill** `skills/leash-finish-work/SKILL.md`

```markdown
---
name: leash-finish-work
description: Use to clean up a .worktrees/<slug> worktree created by /leash-start-work. Refuses on a dirty worktree or an unmerged branch unless --keep-branch. Removes the worktree and deletes the branch (unless kept).
---

# leash-finish-work

## When to use

You finished a change started with `/leash-start-work` and the branch is
merged (or has an open PR you want to keep). This removes the worktree
directory and, by default, the merged branch. Counterpart to
`/leash-start-work`.

## How

1. Make sure the worktree is committed and, unless you pass `--keep-branch`,
   that its branch is merged into `main`/`master`.

2. Run (from the main checkout), naming the slug:

   ```bash
   python -m scripts.harness.finish_work <slug>
   ```

   or point at an explicit path:

   ```bash
   python -m scripts.harness.finish_work --path .worktrees/<slug>
   ```

3. The script:
   - refuses to touch the main worktree
   - refuses if the worktree has uncommitted changes (commit or stash first)
   - refuses if the branch is unmerged (merge it, or pass `--keep-branch`)
   - runs `git worktree remove`, then `git branch -d <type>/<slug>` (only
     `-d`, never `-D`) unless `--keep-branch`

## Flags

- `--keep-branch` — remove the worktree directory but keep the branch
  (useful when a PR is still open).

## Constraints

- Never `--force`. If the script refuses, fix the underlying issue;
  `git worktree remove --force` / `git branch -D` would silently discard
  work and are out of scope.
```

- [ ] **Step 5: Delete the old backend, skill, and test**

```bash
git rm scripts/harness/session_end.py skills/leash-session-end/SKILL.md tests/harness/test_session_end.py
```

- [ ] **Step 6: Run tests to verify pass**

Run: `python -m pytest tests/harness/test_finish_work.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/harness/finish_work.py skills/leash-finish-work/SKILL.md tests/harness/test_finish_work.py
git commit -m "feat(leash): leash-finish-work replaces leash-session-end (stateless cleanup)"
```

---

## Task 5: Delete the session-detection machinery

**Files:**
- Delete: `scripts/harness/session_lockfile.py`, `scripts/harness/session_start.py`, `scripts/harness/session_new.py`, `scripts/harness/list_sessions.py`
- Delete: `skills/leash-session-new/SKILL.md`
- Delete: `tests/harness/test_session_lockfile.py`, `tests/harness/test_session_start.py`, `tests/harness/test_session_new.py`, `tests/harness/test_list_sessions.py`, `tests/test_session_new.py`

**Interfaces:** none produced; this removes dead code now that the gate is stateless.

- [ ] **Step 1: Confirm no remaining importers**

Run: `grep -rn "session_lockfile\|session_start\|session_new\|list_sessions" scripts/ tests/ --include="*.py"`
Expected: matches ONLY in the files being deleted this task and in `scripts/harness/cycle_done.py` / `dogfood_session.py` / `smoke_e2e.py` (handled in Tasks 6–7). If any other file imports them, stop and resolve first.

- [ ] **Step 2: Delete the files**

```bash
git rm scripts/harness/session_lockfile.py scripts/harness/session_start.py \
       scripts/harness/session_new.py scripts/harness/list_sessions.py \
       skills/leash-session-new/SKILL.md \
       tests/harness/test_session_lockfile.py tests/harness/test_session_start.py \
       tests/harness/test_session_new.py tests/harness/test_list_sessions.py \
       tests/test_session_new.py
```

- [ ] **Step 3: Run the full unit suite (expect only known-pending failures)**

Run: `python -m pytest tests/ -q`
Expected: failures confined to `cycle_done` (still imports `session_lockfile`), `smoke`, `test_docs`, `test_templates` — all fixed in Tasks 6–8. No `session_*`/`list_sessions` collection errors.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(leash): delete session-detection machinery (lockfiles, election, leash-session-new)"
```

---

## Task 6: Strip the session sweep from `cycle_done.py`

**Files:**
- Modify: `scripts/harness/cycle_done.py`
- Delete: `tests/harness/test_cycle_done_session_sweep.py`

**Interfaces:**
- Removes: `sweep_session_worktrees`, `_find_lockfile_for_worktree`, and the `from scripts.harness import session_lockfile` import.
- Keeps: `advise_merged_worktrees`, `_worktree_branches` (still used by the advisory).

- [ ] **Step 1: Remove the lockfile import**

Delete this line near the top of `scripts/harness/cycle_done.py`:

```python
from scripts.harness import session_lockfile as sl  # noqa: E402
```

- [ ] **Step 2: Delete `_find_lockfile_for_worktree` and `sweep_session_worktrees`**

Remove the entire `def _find_lockfile_for_worktree(...)` function (around lines 135–147) and the entire `def sweep_session_worktrees(...)` function (around lines 149–197). Leave `_worktree_branches` and `advise_merged_worktrees` intact.

- [ ] **Step 3: Remove the sweep call in the main flow**

In the `main` flow (around lines 260–268), delete the `try/except` block that calls `sweep_session_worktrees(...)`:

```python
        try:
            swept = sweep_session_worktrees(repo_root=REPO_ROOT)
            if swept:
                print(f"sweep: removed {len(swept)} session worktree(s)", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"sweep: skipped ({exc})", file=sys.stderr)
```

Keep the `advise_merged_worktrees` loop that follows it.

- [ ] **Step 4: Delete the sweep test**

```bash
git rm tests/harness/test_cycle_done_session_sweep.py
```

- [ ] **Step 5: Verify cycle_done imports cleanly and its remaining tests pass**

Run: `python -c "import scripts.harness.cycle_done"` then `python -m pytest tests/harness/test_cycle_done.py -q`
Expected: import OK (no `session_lockfile` error); cycle_done tests PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/harness/cycle_done.py
git commit -m "refactor(cycle_done): drop session-worktree sweep, keep advisory"
```

---

## Task 7: Rewrite the dogfood + smoke e2e

**Files:**
- Create: `scripts/dogfood_worktree_gate.py`
- Delete: `scripts/dogfood_session.py`
- Modify: `scripts/smoke_e2e.py`

**Interfaces:**
- Consumes: `decide`, `list_worktrees` from `scripts.harness.session_gate`; `write_marker` from `scripts.harness.allow_main_write`.

- [ ] **Step 1: Create `scripts/dogfood_worktree_gate.py`**

```python
#!/usr/bin/env python3
"""Dogfood the worktree gate on a throwaway repo.

Steps:
  1. init a git repo (main worktree).
  2. Gate an Edit targeting the main tree -> assert DENY (names leash-start-work).
  3. Add a linked worktree; gate an Edit inside it -> assert ALLOW.
  4. Plant the one-shot marker; gate a main-tree Edit -> assert ALLOW, marker
     consumed, exceptions.log appended. A second main-tree Edit -> assert DENY.
  5. Teardown.

Exits 0 only if every step asserted clean. Used by smoke_e2e.py and as the
verify command for the dogfood task.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.harness.session_gate import decide, list_worktrees  # noqa: E402
from scripts.harness.allow_main_write import write_marker  # noqa: E402


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "d@d"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "d"], cwd=path)
    (path / "seed").write_text("seed\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=path)


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="dol-wtgate-"))
    repo = parent / "throwaway"
    try:
        _init_repo(repo)
        harness = repo / ".harness"
        marker = harness / "allow-main-write"
        log = harness / "exceptions.log"

        wts = list_worktrees(repo)
        assert wts is not None and wts[0] == repo.resolve(), "main worktree first"

        d_main = decide(
            tool_name="Edit", tool_input={"file_path": str(repo / "README.md")},
            worktrees=wts, marker_path=marker, log_path=log,
        )
        assert not d_main.allow, "gate must deny main-tree write"
        assert "/leash-start-work" in d_main.reason

        wt = repo / ".worktrees" / "feat-x"
        subprocess.check_call(
            ["git", "worktree", "add", str(wt), "-b", "feat/x", "main"], cwd=repo)
        wts2 = list_worktrees(repo)
        d_wt = decide(
            tool_name="Edit", tool_input={"file_path": str(wt / "y.py")},
            worktrees=wts2, marker_path=marker, log_path=log,
        )
        assert d_wt.allow, f"gate must allow inside worktree: {d_wt.reason}"

        write_marker(harness_dir=harness, reason="dogfood")
        d_escape = decide(
            tool_name="Edit", tool_input={"file_path": str(repo / "README.md")},
            worktrees=wts2, marker_path=marker, log_path=log,
        )
        assert d_escape.allow, "one-shot marker must allow"
        assert not marker.exists(), "marker must be consumed"
        assert log.exists() and "main-write" in log.read_text(encoding="utf-8")

        d_again = decide(
            tool_name="Edit", tool_input={"file_path": str(repo / "README.md")},
            worktrees=wts2, marker_path=marker, log_path=log,
        )
        assert not d_again.allow, "second main write must deny after consume"

        print("WORKTREE-GATE DOGFOOD PASS")
        return 0
    except AssertionError as exc:
        print(f"WORKTREE-GATE DOGFOOD FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Delete the old dogfood**

```bash
git rm scripts/dogfood_session.py
```

- [ ] **Step 3: Update `smoke_e2e.py` — replace the session-leash step**

In `scripts/smoke_e2e.py`, replace the `_exercise_session_leash` function:

```python
def _exercise_session_leash() -> None:
    """Run the session-leash dogfood script as a self-contained step."""
    rc = subprocess.call(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "dogfood_session.py")],
    )
    assert rc == 0, f"dogfood_session.py exit {rc}"
```

with:

```python
def _exercise_worktree_gate() -> None:
    """Run the worktree-gate dogfood script as a self-contained step."""
    rc = subprocess.call(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "dogfood_worktree_gate.py")],
    )
    assert rc == 0, f"dogfood_worktree_gate.py exit {rc}"
```

Then in `main`, replace step 9's body:

```python
        # 9 — exercise the session leash on a throwaway repo
        try:
            _exercise_session_leash()
            step(9, "session-leash: deny->worktree->allow path", True)
        except Exception as exc:  # noqa: BLE001
            step(9, "session-leash: deny->worktree->allow path", False, str(exc))
```

with:

```python
        # 9 — exercise the worktree gate on a throwaway repo
        try:
            _exercise_worktree_gate()
            step(9, "worktree-gate: main-deny -> wt-allow -> escape", True)
        except Exception as exc:  # noqa: BLE001
            step(9, "worktree-gate: main-deny -> wt-allow -> escape", False, str(exc))
```

Step 10 (`_exercise_session_hooks_subprocess`) stays — it reads hook commands from the template and runs them; after Task 8 the template has only the `PreToolUse` gate command, which this step still validates. Update its docstring/label wording from "session-leash hooks" to "harness hooks" (cosmetic):

In `main`, change the step 10 label string `"session-leash hooks: subprocess invocation"` to `"harness hooks: subprocess invocation"` (both occurrences in the try/except).

- [ ] **Step 4: Run the dogfood and the smoke e2e**

Run: `python scripts/dogfood_worktree_gate.py` then `python scripts/smoke_e2e.py`
Expected: `WORKTREE-GATE DOGFOOD PASS`; then `SMOKE PASS` with steps 9 and 10 OK.

- [ ] **Step 5: Commit**

```bash
git add scripts/dogfood_worktree_gate.py scripts/smoke_e2e.py
git commit -m "test(e2e): dogfood the worktree gate, replace session-leash dogfood"
```

---

## Task 8: Templates, README, docs, CHANGELOG

**Files:**
- Modify: `templates/settings.json.tmpl`, `templates/CLAUDE.md.tmpl`, `templates/AGENTS.md.tmpl`
- Modify: `README.md`, `tests/test_docs.py`, `CHANGELOG.md`
- Modify: `skills/leash-start-work/SKILL.md`, `skills/bootstrap-dev-leash/SKILL.md`

**Interfaces:** none (docs + config). `tests/test_docs.py` + `tests/test_templates.py` must pass after edits.

- [ ] **Step 1: `templates/settings.json.tmpl` — drop the `SessionStart` block**

Remove the entire `"SessionStart": [ ... ]` entry (the object running `python -m scripts.harness.session_start`), leaving `"PreToolUse"` as the only key under `"hooks"`. Resulting `hooks`:

```json
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python -m scripts.harness.session_gate"
          }
        ]
      }
    ]
  }
```

(The `Bash(python -m scripts.harness.*)` permission already covers `allow_main_write` and `finish_work`.)

- [ ] **Step 2: `templates/CLAUDE.md.tmpl` — replace "Concurrent sessions"**

Replace the `## Concurrent sessions` section (lines ~47–53) with:

```markdown
## Worktree leash (main is read-only)

The harness installs a **worktree leash**: a `PreToolUse` gate denies any
`Edit`/`Write`/`MultiEdit`/`NotebookEdit` whose target is in the **main
worktree**. All work happens in a linked worktree — run `/leash-start-work`
to create one (`.worktrees/<slug>` on `<type>/<slug>` from `main`), then
edit there. This makes concurrent sessions safe by construction: each works
in its own worktree, nobody edits the shared main tree. Clean up with
`/leash-finish-work`.

For a one-off direct edit to the main tree, authorize a single write:
`python -m scripts.harness.allow_main_write "<reason>"` (logged to
`.harness/exceptions.log`), then retry the edit.
```

- [ ] **Step 3: `templates/AGENTS.md.tmpl` — replace "Concurrent sessions"**

Replace the `### Concurrent sessions` section (lines ~157–162) with:

```markdown
### Worktree leash (main is read-only)

A `PreToolUse` gate denies writes (`Edit`/`Write`/`MultiEdit`/`NotebookEdit`)
whose target is in the **main worktree**. Begin every change with
`/leash-start-work` (creates `.worktrees/<slug>` on `<type>/<slug>` from
`main`) and edit inside that worktree. Concurrent Claude Code sessions are
safe by construction — each has its own worktree; none may touch the main
tree. Finish with `/leash-finish-work`. For a one-off main-tree edit, run
`python -m scripts.harness.allow_main_write "<reason>"` (audited in
`.harness/exceptions.log`) and retry.
```

Also update the cross-reference in the "Parallel work (worktrees)" section: change the sentence "This is distinct from the reactive session leash below, which fires only when two Claude Code sessions collide." to "The worktree leash below makes this the *only* way to write — the main tree is read-only."

- [ ] **Step 4: `README.md` — rewrite the "Session leash" section**

Replace the entire `## Session leash` section (lines ~88–112) with:

```markdown
## Worktree leash

The **main worktree is read-only** to write tools. A `PreToolUse` gate
denies any `Edit`/`Write`/`MultiEdit`/`NotebookEdit` whose target resolves
into the main worktree; all work happens in a linked worktree created by
`/leash-start-work` (`.worktrees/<slug>` on a `<type>/<slug>` branch from
`main`). Clean up with `/leash-finish-work`.

This makes concurrent Claude Code sessions safe **by construction**: each
session works on its own branch in its own worktree, and none of them can
edit the shared main tree — so two sessions can never clobber each other's
WIP. There is no session detection, no lockfiles, and no PID election (the
previous design's election mis-elected two primaries on Windows, where PIDs
are not monotonic).

The gate is stateless: it runs `git worktree list` and matches the target
to the longest-prefix worktree. For a one-off direct edit to the main tree,
authorize a single write with
`python -m scripts.harness.allow_main_write "<reason>"`; the gate consumes
the authorization on the next main-tree write and logs it to
`.harness/exceptions.log`. The main tree is expected to mirror the remote —
you keep it synced with ordinary `git fetch`/`pull`/merge.

`dev-on-leash` dogfoods this on itself: see
`scripts/dogfood_worktree_gate.py`, run from `scripts/smoke_e2e.py`, which
asserts the gate denies a main-tree edit, allows an edit inside a worktree,
and honors a one-shot escape exactly once.
```

- [ ] **Step 5: `README.md` — update the trust-model bullets**

In the "Trust model" section, replace the three `**Session leash...**` fragments (lines ~142–159) so they describe the worktree leash:

- Enforced bullet: `**Worktree leash:** the PreToolUse gate denies writes whose target is in the main worktree; bypass requires editing/removing the hook line in `.claude/settings.json` (a visible audit event).`
- By-convention bullet: `**Worktree leash:** `Bash` is outside the gate matcher (so `/leash-start-work` can run `git worktree add` and the one-shot escape can be authorized); a determined session could `> file` into the main tree. The one-shot escape is itself an audited, deliberate convention.`
- Escape-hatch bullet: `**Worktree leash:** `python -m scripts.harness.allow_main_write "<reason>"` authorizes a single main-tree write and logs it to `.harness/exceptions.log` (same pattern as `cycle_done --force`).`

Also update the "Parallel work with worktrees (opt-in)" section's closing line "This is distinct from the **session leash**, which reactively creates a sibling worktree only when two Claude Code sessions collide." to: "The worktree leash makes this the only path to writing — the main tree is read-only, so every change starts here."

- [ ] **Step 6: `tests/test_docs.py` — update README assertions**

Replace `test_readme_has_session_leash_section` and `test_readme_trust_model_names_session_leash` (lines ~35–47) with:

```python
def test_readme_has_worktree_leash_section():
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Worktree leash" in text
    assert "/leash-start-work" in text
    assert "/leash-finish-work" in text
    assert "allow_main_write" in text


def test_readme_trust_model_names_worktree_leash():
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    lower = text.lower()
    assert "worktree leash" in lower
```

(If `REPO_ROOT`/`trust_block` helpers differ in the actual file, keep the existing variable names; only the section title and skill names change. Read the file first and adapt the two function bodies.)

- [ ] **Step 7: `CHANGELOG.md` — add a breaking-change entry**

Add under the latest unreleased/next heading (match the file's existing heading style):

```markdown
### Changed
- **BREAKING:** the session leash is replaced by a **worktree leash**. The
  main worktree is now read-only to write tools; all work happens in a
  linked worktree via `/leash-start-work`, cleaned up with
  `/leash-finish-work`. Removed: `SessionStart` detection, per-session
  lockfiles (`.harness/sessions/`), PID election, and the
  `/leash-session-new` + `/leash-session-end` skills. A one-shot audited
  escape (`python -m scripts.harness.allow_main_write`) permits occasional
  direct main-tree writes. Re-bootstrap existing projects to drop the
  `SessionStart` hook from `.claude/settings.json`.
```

- [ ] **Step 8: `skills/leash-start-work/SKILL.md` — reframe as the single mandatory path**

- In "When to use", replace the paragraph stating the skill is **voluntary** ("This skill is **voluntary**. Nothing forces it (unlike `/leash-session-new`...)") with:

```markdown
This skill is the **single, mandatory** path to begin a change. The worktree
leash makes the main worktree read-only to write tools, so you cannot edit
in the main checkout — start here, then edit inside `.worktrees/<slug>`.
```

- In the line "Do NOT use this to escape a session-leash block — that is `/leash-session-new`.", delete it (that skill no longer exists).
- In "Cleanup", change the manual `git worktree remove .worktrees/<slug>` guidance to point at the skill: "When the branch is merged, run `/leash-finish-work <slug>` (refuses on dirty/unmerged work)." Keep the `cycle_done.py` advisory mention.
- Replace the remaining `/leash-session-new` reference in "Constraints" ("same stance as `/leash-session-new`") with "(start from `main`, never copy WIP)".

- [ ] **Step 9: `skills/bootstrap-dev-leash/SKILL.md` — migration note**

Add a short note (in the section describing what bootstrap writes into `.claude/settings.json`) that re-running bootstrap on an existing project re-renders `settings.json` from `templates/settings.json.tmpl`, which **no longer registers a `SessionStart` hook** — so re-bootstrapping migrates a project off the old session leash. If bootstrap merges (rather than overwrites) settings, instruct it to remove any existing `SessionStart` entry that runs `scripts.harness.session_start`. (Read the skill to match its existing wording; keep edits minimal.)

- [ ] **Step 10: Run the doc/template tests + grep for stragglers**

Run: `python -m pytest tests/test_docs.py tests/test_templates.py -q`
Then: `grep -rn "leash-session-new\|leash-session-end\|session_start\|session_lockfile\|dogfood_session\|## Session leash" README.md templates/ skills/ docs/follow-ups.md`
Expected: doc/template tests PASS; grep returns no live references (historical mentions inside `docs/superpowers/specs/` and `docs/plans/` are fine — those are dated records).

- [ ] **Step 11: Commit**

```bash
git add templates/ README.md tests/test_docs.py CHANGELOG.md skills/leash-start-work/SKILL.md skills/bootstrap-dev-leash/SKILL.md
git commit -m "docs(leash): document worktree leash, retire session-leash references"
```

---

## Task 9: Full verification gate

**Files:** none (verification only).

- [ ] **Step 1: Full unit suite**

Run: `python -m pytest tests/ -q`
Expected: PASS, no collection errors, no references to deleted modules.

- [ ] **Step 2: End-to-end smoke**

Run: `python scripts/smoke_e2e.py`
Expected: `SMOKE PASS` with all 10 steps OK.

- [ ] **Step 3: Dogfood (load-bearing)**

Run: `python scripts/dogfood_worktree_gate.py`
Expected: `WORKTREE-GATE DOGFOOD PASS`.

- [ ] **Step 4: Stale-reference sweep**

Run: `grep -rn "session_lockfile\|session_start\|session_new\|list_sessions\|leash-session" scripts/ tests/ templates/ skills/ README.md`
Expected: no matches outside dated `docs/` records.

- [ ] **Step 5: Final commit (if any verification fixups were needed)**

```bash
git add -A
git commit -m "chore(leash): verification fixups for worktree-mandatory leash"
```

---

## Self-Review

**Spec coverage:**
- Stateless git gate (spec §1) → Task 1, 2. ✓
- One-shot audited escape (spec §2) → Task 3 (writer) + Task 1 (gate consumes/logs) + Task 2/7 (tests). ✓
- `leash-start-work` single path (spec §3) → Task 8 Step 8. ✓
- `leash-finish-work` rename (spec §4) → Task 4. ✓
- Deletions + settings template (spec §5) → Task 4 (session_end), Task 5 (lockfile/start/new/list), Task 6 (cycle_done sweep), Task 8 Step 1 (SessionStart). ✓
- Migration / re-bootstrap (spec §5) → Task 8 Step 9 + CHANGELOG Step 7. ✓
- Trust model (spec §6) → Task 8 Step 5. ✓
- Testing + dogfood + inventory (spec §7) → Tasks 2, 3, 4, 7, 9. ✓
- README obligation (memory `feedback-plan-includes-readme`) → Task 8 Steps 4–6. ✓
- Dogfood load-bearing (memory `feedback-dogfood`) → Task 7 + Task 9 Step 3. ✓

**Placeholder scan:** Doc-edit tasks (8.6, 8.9) say "read the file first and adapt" only where the exact current variable names/wording can't be reproduced verbatim from grep output — the *what* and *where* are concrete. No `TBD`/`TODO`/"implement later".

**Type consistency:** `decide(...)` keyword args match between Task 1 (definition), Task 2 (tests), and Task 7 (dogfood): `tool_name, tool_input, worktrees, marker_path, log_path, gate_pid`. `list_worktrees(cwd) -> list[Path] | None`, main-worktree-first, used consistently. `finish_work(*, repo_root, slug, worktree_path, keep_branch) -> str` matches between Task 4 definition and its tests. Marker filename `allow-main-write` and log filename `exceptions.log` consistent across gate, allow_main_write, dogfood.
