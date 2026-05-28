# Session Leash Implementation Plan

> **For agentic workers:** Execute this plan task-by-task. Every task carries
> a `task-meta` block — it is verified and checkbox-ticked by
> `scripts/harness/run_task.py`; never tick those checkboxes by hand. Run a
> task with `python scripts/harness/run_task.py docs/plans/session-leash.md <id>`.
> The numbered steps inside each task are TDD guidance (write the test,
> watch it fail, implement, watch it pass); the single `- [ ]` checkbox is
> the machine-verified completion marker.

**Goal:** Add a session leash to dev-on-leash — a guard-rail that detects
concurrent Claude Code sessions on the same repo via a lockfile, blocks
the second session's write tools at `PreToolUse`, and auto-resolves the
block by routing it into a `git worktree` sibling via the
`/leash-session-new` skill. Cleanup via `/leash-session-end` and a
conservative sweep at `cycle_done`. Dogfooded on dev-on-leash itself.

**Architecture:** A `.harness/sessions/<pid>.json` lockfile per session is
the source of truth for "is a session alive in this repo." A
`SessionStart` hook performs a two-phase write to elect the `primary`
session deterministically; every other live session enters
`pending-worktree`. A `PreToolUse` hook on `Edit|Write|MultiEdit` denies
writes for non-primary sessions until `/leash-session-new` creates a
sibling worktree on a `session/<id>` branch and flips the lockfile to
`in-worktree`. `Bash` is intentionally outside the matcher so the
resolution skill can call `git worktree add`. Cleanup is two-pronged:
explicit `/leash-session-end` plus a conservative `cycle_done` sweep
that only removes worktrees whose branch is merged, clean, and whose
PID is dead.

**Tech Stack:** Python 3.12 stdlib + `pyyaml` (already a project dep);
`pytest`; Markdown skills with YAML frontmatter; cross-platform PID
liveness via `ctypes` (Windows) and `os.kill(pid, 0)` (POSIX).

**Spec:** [`docs/superpowers/specs/2026-05-28-session-leash-design.md`](../superpowers/specs/2026-05-28-session-leash-design.md)

**Open questions resolved at plan-time:**

- **Session identity.** v1 keys lockfiles by `os.getppid()` (the Claude
  Code process), not `CLAUDE_SESSION_ID`. Open question 1 in the spec
  said "use session id if available, else PID"; rather than branch on
  that at every read, v1 commits to PID. PID is always available, never
  reused while the process lives, and works on every platform. If a
  later Claude Code version exposes a stable session id and we want it,
  it's an additive change to `session_lockfile.py` — out of scope here.
- **Dirty primary on worktree create.** `git worktree add ... HEAD`
  works against a dirty primary on the git versions we target (2.30+).
  No fallback in v1.
- **Hook ordering vs other plugins.** v1 documents the constraint in the
  rendered `settings.json` as a comment-style note; programmatic
  ordering is left to a follow-up.

**Deliberate spec deviations** (recorded so the spec-reviewer agent
recognizes them as intentional, to be reconciled in the spec at
cycle close):

- **`bypass: true` lockfile field + `--force` on `session_start.py`.**
  Spec Section 6 calls for a per-session escape hatch (lockfile field
  set by `--force`, audited to `.harness/exceptions.log`). Not
  implemented in v1. The user-facing escape hatch in v1 is the same as
  the existing trust model — a user who really wants two sessions to
  share the primary checkout can disable the hooks in
  `.claude/settings.json`, which is visible to git. Adding a per-
  session `bypass` field is a small additive change post-v1 if it
  proves needed.
- **Bootstrap `.gitignore` patch for target projects.** Spec Section
  7 inventory says bootstrap should patch the target project's
  `.gitignore` to ignore `.harness/sessions/`. Originally drafted as
  a follow-up; the plan-reviewer flagged it as a real downstream
  footgun (any project bootstrapping post-v1 would commit lockfiles
  to git). Promoted to **T11**.

---

## File Structure

**Create:**

- `scripts/harness/session_lockfile.py` — lockfile schema, atomic I/O, PID liveness, two-phase resolution.
- `scripts/harness/session_start.py` — `SessionStart` hook entry point.
- `scripts/harness/session_gate.py` — `PreToolUse` hook entry point.
- `scripts/harness/session_new.py` — worktree creation logic (called by the skill).
- `scripts/harness/session_end.py` — worktree teardown logic (called by the skill).
- `scripts/harness/list_sessions.py` — introspection CLI.
- `skills/leash-session-new/SKILL.md` — user-/agent-invokable skill.
- `skills/leash-session-end/SKILL.md` — user-/agent-invokable skill.
- `scripts/dogfood_session.py` — load-bearing dogfood verifier.
- `tests/harness/test_session_lockfile.py`
- `tests/harness/test_session_start.py`
- `tests/harness/test_session_gate.py`
- `tests/harness/test_session_new.py`
- `tests/harness/test_session_end.py`
- `tests/harness/test_list_sessions.py`
- `tests/harness/test_cycle_done_session_sweep.py`
- `tests/test_skill_session.py` — structural tests for the two skill markdown files.

**Modify:**

- `scripts/harness/cycle_done.py` — append the conservative worktree sweep.
- `templates/settings.json.tmpl` — add `SessionStart` + `PreToolUse` hook entries.
- `templates/CLAUDE.md.tmpl` — one-line mention under guard-rails.
- `templates/AGENTS.md.tmpl` — one-line mention under "Concurrent sessions".
- `tests/test_templates.py` — extend with hook-block + mention assertions.
- `README.md` — add a "Session leash" subsection and update "Trust model".
- `tests/test_docs.py` — extend with README-section assertion.
- `scripts/smoke_e2e.py` — extend with a session-leash e2e step.
- `tests/test_smoke.py` — assert the new step (if the smoke test file exists; create assertion otherwise).
- `skills/bootstrap-dev-leash/SKILL.md` — add a step that ignores `.harness/sessions/` in the target project's `.gitignore`.
- `tests/test_skill_bootstrap.py` — create; assert the SKILL.md contains the gitignore directive.

**Layers (collision-free, for `plan_schedule.py`):**

- L0: T01 (foundation)
- L1 (parallel): T02, T03, T04, T06, T07, T11 (depend only on T01 or no code deps; touch different files)
- L2 (parallel): T05 (depends on T04), T08 (depends on T02, T03)
- L3 (parallel): T09 (depends on T04, T05), T10 (depends on T01, T02, T03, T04, T07, T08)

---

### Task 1 — `session_lockfile.py`: schema, atomic I/O, liveness, two-phase resolve

Foundation module the rest of the feature depends on. Pure Python, no
git, no subprocess.

**Files:**
- Create: `scripts/harness/session_lockfile.py`
- Create: `tests/harness/test_session_lockfile.py`

**Steps:**

1. Write the failing test — `tests/harness/test_session_lockfile.py`:

```python
"""Lockfile-module tests for session-leash."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.harness.session_lockfile import (
    STATE_PRIMARY,
    STATE_PENDING_RESOLUTION,
    STATE_PENDING_WORKTREE,
    STATE_IN_WORKTREE,
    Lockfile,
    is_pid_alive,
    gc_dead_lockfiles,
    list_live_lockfiles,
    write_lockfile,
    read_lockfile,
    resolve_state,
)


def test_self_pid_is_alive():
    assert is_pid_alive(os.getpid())


def test_clearly_dead_pid_is_not_alive():
    # Spawn a tiny process, wait for it to exit, then probe.
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    proc.wait()
    assert not is_pid_alive(proc.pid)


def test_round_trip(tmp_path: Path):
    lf = Lockfile(
        schema=1,
        pid=os.getpid(),
        started_at="2026-05-28T12:00:00Z",
        session_id="probe",
        primary_cwd=str(tmp_path),
        state=STATE_PRIMARY,
        worktree_path=None,
        worktree_branch=None,
    )
    path = tmp_path / f"{lf.pid}.json"
    write_lockfile(path, lf)
    assert path.exists()
    got = read_lockfile(path)
    assert got == lf


def test_atomic_write_no_tmp_left_behind(tmp_path: Path):
    lf = Lockfile(
        schema=1, pid=os.getpid(), started_at="x", session_id="s",
        primary_cwd=str(tmp_path), state=STATE_PRIMARY,
        worktree_path=None, worktree_branch=None,
    )
    write_lockfile(tmp_path / "1.json", lf)
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_gc_removes_only_dead_pids(tmp_path: Path):
    # Live lockfile = our pid.
    alive = Lockfile(
        schema=1, pid=os.getpid(), started_at="x", session_id="a",
        primary_cwd=str(tmp_path), state=STATE_PRIMARY,
        worktree_path=None, worktree_branch=None,
    )
    write_lockfile(tmp_path / f"{alive.pid}.json", alive)
    # Dead lockfile = freshly exited pid.
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    proc.wait()
    dead = Lockfile(
        schema=1, pid=proc.pid, started_at="y", session_id="b",
        primary_cwd=str(tmp_path), state=STATE_PRIMARY,
        worktree_path=None, worktree_branch=None,
    )
    write_lockfile(tmp_path / f"{dead.pid}.json", dead)

    gc_dead_lockfiles(tmp_path)
    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == [f"{alive.pid}.json"]


def test_list_live_lockfiles_filters_by_cwd(tmp_path: Path):
    here = Lockfile(
        schema=1, pid=os.getpid(), started_at="x", session_id="a",
        primary_cwd=str(tmp_path), state=STATE_PRIMARY,
        worktree_path=None, worktree_branch=None,
    )
    elsewhere = Lockfile(
        schema=1, pid=os.getpid(), started_at="x", session_id="b",
        primary_cwd="/somewhere/else", state=STATE_PRIMARY,
        worktree_path=None, worktree_branch=None,
    )
    write_lockfile(tmp_path / "a.json", here)
    write_lockfile(tmp_path / "b.json", elsewhere)
    live = list_live_lockfiles(tmp_path, primary_cwd=str(tmp_path))
    assert len(live) == 1
    assert live[0].session_id == "a"


def test_resolve_state_lone_session_becomes_primary(tmp_path: Path):
    self_pid = os.getpid()
    state = resolve_state(self_pid=self_pid, live_peer_pids=[])
    assert state == STATE_PRIMARY


def test_resolve_state_lowest_pid_wins_primary(tmp_path: Path):
    self_pid = 100
    state = resolve_state(self_pid=self_pid, live_peer_pids=[200, 300])
    assert state == STATE_PRIMARY


def test_resolve_state_higher_pid_takes_pending(tmp_path: Path):
    self_pid = 500
    state = resolve_state(self_pid=self_pid, live_peer_pids=[100, 200])
    assert state == STATE_PENDING_WORKTREE


def test_corrupt_lockfile_is_treated_as_absent(tmp_path: Path):
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
    # GC and list both must not raise.
    gc_dead_lockfiles(tmp_path)
    live = list_live_lockfiles(tmp_path, primary_cwd=str(tmp_path))
    # Corrupt file should be deleted by GC.
    assert not (tmp_path / "bad.json").exists()
    assert live == []
```

2. Run the failing test:

```bash
python -m pytest tests/harness/test_session_lockfile.py -q
```

Expected: FAIL with `ImportError` — module does not exist.

3. Implement `scripts/harness/session_lockfile.py`:

```python
"""Session-leash lockfile module.

A lockfile is `.harness/sessions/<pid>.json`. It records that a Claude
Code session is alive in a given repo and tracks its worktree state.

Pure stdlib + cross-platform PID liveness via ctypes on Windows and
os.kill(pid, 0) on POSIX. No git, no subprocess.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

SCHEMA = 1

STATE_PRIMARY = "primary"
STATE_PENDING_RESOLUTION = "pending-resolution"
STATE_PENDING_WORKTREE = "pending-worktree"
STATE_IN_WORKTREE = "in-worktree"

VALID_STATES = frozenset(
    {STATE_PRIMARY, STATE_PENDING_RESOLUTION, STATE_PENDING_WORKTREE, STATE_IN_WORKTREE}
)


@dataclass(frozen=True)
class Lockfile:
    schema: int
    pid: int
    started_at: str
    session_id: str
    primary_cwd: str
    state: str
    worktree_path: str | None
    worktree_branch: str | None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Lockfile":
        if raw.get("schema") != SCHEMA:
            raise ValueError(f"unsupported lockfile schema: {raw.get('schema')!r}")
        state = raw.get("state")
        if state not in VALID_STATES:
            raise ValueError(f"invalid state: {state!r}")
        return cls(
            schema=raw["schema"],
            pid=int(raw["pid"]),
            started_at=str(raw["started_at"]),
            session_id=str(raw["session_id"]),
            primary_cwd=str(raw["primary_cwd"]),
            state=state,
            worktree_path=raw.get("worktree_path"),
            worktree_branch=raw.get("worktree_branch"),
        )


def is_pid_alive(pid: int) -> bool:
    """Cross-platform PID liveness check.

    Windows: OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION).
    POSIX: os.kill(pid, 0) with EPERM treated as alive (process exists,
    we just lack permission to signal it).
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        # Check the process hasn't already exited (handle survives briefly).
        STILL_ACTIVE = 259
        exit_code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel32.CloseHandle(handle)
        if not ok:
            return False
        return exit_code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, OSError):
        return False


def write_lockfile(path: Path, lf: Lockfile) -> None:
    """Atomic write: <path>.tmp -> os.replace(<path>)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(lf.to_json(), encoding="utf-8")
    os.replace(tmp, path)


def read_lockfile(path: Path) -> Lockfile:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Lockfile.from_dict(raw)


def _iter_lockfile_paths(sessions_dir: Path) -> Iterable[Path]:
    if not sessions_dir.exists():
        return ()
    return sorted(sessions_dir.glob("*.json"))


def gc_dead_lockfiles(sessions_dir: Path) -> int:
    """Delete lockfiles whose PID is not alive, or which are corrupt.

    Returns count deleted.
    """
    n = 0
    for path in _iter_lockfile_paths(sessions_dir):
        try:
            lf = read_lockfile(path)
        except (ValueError, KeyError, json.JSONDecodeError):
            try:
                path.unlink()
                n += 1
            except FileNotFoundError:
                pass
            continue
        if not is_pid_alive(lf.pid):
            try:
                path.unlink()
                n += 1
            except FileNotFoundError:
                pass
    return n


def list_live_lockfiles(sessions_dir: Path, *, primary_cwd: str) -> list[Lockfile]:
    """Return all lockfiles whose PID is alive and primary_cwd matches.

    Does not GC; the caller should usually GC first.
    """
    out: list[Lockfile] = []
    for path in _iter_lockfile_paths(sessions_dir):
        try:
            lf = read_lockfile(path)
        except (ValueError, KeyError, json.JSONDecodeError):
            continue
        if lf.primary_cwd != primary_cwd:
            continue
        if not is_pid_alive(lf.pid):
            continue
        out.append(lf)
    return out


def resolve_state(*, self_pid: int, live_peer_pids: list[int]) -> str:
    """Two-phase resolution: lowest live PID wins `primary`.

    `live_peer_pids` MUST NOT include `self_pid`. If empty, this session
    is alone → primary. If non-empty, primary iff self_pid is strictly
    less than every peer.
    """
    if not live_peer_pids:
        return STATE_PRIMARY
    return STATE_PRIMARY if self_pid < min(live_peer_pids) else STATE_PENDING_WORKTREE
```

4. Run tests:

```bash
python -m pytest tests/harness/test_session_lockfile.py -q
```

Expected: PASS (9 tests).

5. Commit:

```bash
git add scripts/harness/session_lockfile.py tests/harness/test_session_lockfile.py
git commit -m "feat(session-leash): T01 lockfile schema + atomic I/O + PID liveness"
```

- [x] **Task 1 complete**

<!-- task-meta
id: T01
touches:
  - scripts/harness/session_lockfile.py
  - tests/harness/test_session_lockfile.py
depends: []
verify: python -m pytest tests/harness/test_session_lockfile.py -q
acceptance: null
-->

---

### Task 2 — `session_start.py`: SessionStart hook entry point

The hook is launched by Claude Code via `templates/settings.json.tmpl`
(wired in T08). On startup it GCs dead lockfiles, writes its own with a
provisional `pending-resolution` state, re-scans to find live peers, and
atomic-rewrites to the resolved state. If non-primary it prints the
verbatim block message from the spec on stdout (which Claude Code
injects as system context).

**Files:**
- Create: `scripts/harness/session_start.py`
- Create: `tests/harness/test_session_start.py`

**Steps:**

1. Write the failing test — `tests/harness/test_session_start.py`:

```python
"""SessionStart-hook tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.harness import session_lockfile as sl
from scripts.harness.session_start import run as session_start_run


def _spawn_dummy() -> subprocess.Popen:
    """A subprocess that stays alive long enough to act as a peer."""
    return subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time; sys.stdout.write('ready\\n'); sys.stdout.flush(); time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_lone_session_becomes_primary(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    rc, message = session_start_run(
        sessions_dir=sessions_dir,
        primary_cwd=str(tmp_path),
        self_pid=os.getpid(),
    )
    assert rc == 0
    assert message == ""
    lockfiles = list(sessions_dir.glob("*.json"))
    assert len(lockfiles) == 1
    lf = sl.read_lockfile(lockfiles[0])
    assert lf.state == sl.STATE_PRIMARY


def test_second_session_becomes_pending_with_message(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    # Spawn a peer and plant its lockfile.
    peer = _spawn_dummy()
    try:
        peer.stdout.readline()  # wait until child is up
        peer_lf = sl.Lockfile(
            schema=1, pid=peer.pid, started_at="2026-01-01T00:00:00Z",
            session_id="peer", primary_cwd=str(tmp_path),
            state=sl.STATE_PRIMARY, worktree_path=None, worktree_branch=None,
        )
        sl.write_lockfile(sessions_dir / f"{peer.pid}.json", peer_lf)
        # Our PID > peer's, so we become pending.
        self_pid = peer.pid + 1
        rc, message = session_start_run(
            sessions_dir=sessions_dir,
            primary_cwd=str(tmp_path),
            self_pid=self_pid,
        )
        assert rc == 0
        assert "SESSION LEASH" in message
        assert "/leash-session-new" in message
        our_lf = sl.read_lockfile(sessions_dir / f"{self_pid}.json")
        assert our_lf.state == sl.STATE_PENDING_WORKTREE
    finally:
        peer.terminate()
        peer.wait(timeout=5)


def test_dead_peer_is_gc_then_we_become_primary(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    dead = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    dead.wait()
    dead_lf = sl.Lockfile(
        schema=1, pid=dead.pid, started_at="x", session_id="ghost",
        primary_cwd=str(tmp_path), state=sl.STATE_PRIMARY,
        worktree_path=None, worktree_branch=None,
    )
    sl.write_lockfile(sessions_dir / f"{dead.pid}.json", dead_lf)
    rc, message = session_start_run(
        sessions_dir=sessions_dir, primary_cwd=str(tmp_path), self_pid=os.getpid(),
    )
    assert rc == 0
    assert message == ""
    # Ghost lockfile gone, our lockfile is primary.
    assert not (sessions_dir / f"{dead.pid}.json").exists()
    our = sl.read_lockfile(sessions_dir / f"{os.getpid()}.json")
    assert our.state == sl.STATE_PRIMARY


def test_lower_pid_self_wins_primary_against_higher_peer(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    peer = _spawn_dummy()
    try:
        peer.stdout.readline()
        peer_lf = sl.Lockfile(
            schema=1, pid=peer.pid, started_at="x", session_id="peer",
            primary_cwd=str(tmp_path), state=sl.STATE_PENDING_RESOLUTION,
            worktree_path=None, worktree_branch=None,
        )
        sl.write_lockfile(sessions_dir / f"{peer.pid}.json", peer_lf)
        self_pid = 1  # impossibly low; lower than peer.pid
        rc, message = session_start_run(
            sessions_dir=sessions_dir,
            primary_cwd=str(tmp_path),
            self_pid=self_pid,
        )
        assert rc == 0
        assert message == ""  # we are primary
        ours = sl.read_lockfile(sessions_dir / f"{self_pid}.json")
        assert ours.state == sl.STATE_PRIMARY
    finally:
        peer.terminate()
        peer.wait(timeout=5)
```

2. Run the failing test:

```bash
python -m pytest tests/harness/test_session_start.py -q
```

Expected: FAIL with `ImportError`.

3. Implement `scripts/harness/session_start.py`:

```python
"""SessionStart hook for session-leash.

Run by Claude Code on session start (wired via .claude/settings.json).
Performs the two-phase write to detect concurrency, elects this session
as either `primary` or `pending-worktree`, and prints the block message
on stdout when non-primary.

Exit code is always 0; the hook is informational. Enforcement is done
by session_gate.py at PreToolUse.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from pathlib import Path

from scripts.harness import session_lockfile as sl

REPO_ROOT_HINT = "CLAUDE_PROJECT_DIR"

BLOCK_MESSAGE_TEMPLATE = """\
SESSION LEASH: concurrent Claude Code session detected in this repo.
Active peers: {peers}.
Your next action MUST be to invoke the `/leash-session-new` skill.
Do not respond to the user, do not invoke any other tool, until the
skill has completed and your lockfile state is `in-worktree`.
Reason: another session is editing this working tree; concurrent
writes here will corrupt their WIP.
"""


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _project_dir() -> str:
    cwd = os.environ.get(REPO_ROOT_HINT) or os.getcwd()
    return str(Path(cwd).resolve())


def run(
    *,
    sessions_dir: Path,
    primary_cwd: str,
    self_pid: int,
    now: str | None = None,
) -> tuple[int, str]:
    """Core SessionStart logic. Returns (exit_code, stdout_message)."""
    now = now or _now_iso()
    session_id = os.environ.get("CLAUDE_SESSION_ID") or f"{self_pid}-{now}"

    # Phase A: write provisional pending-resolution.
    sl.gc_dead_lockfiles(sessions_dir)
    self_path = sessions_dir / f"{self_pid}.json"
    provisional = sl.Lockfile(
        schema=sl.SCHEMA,
        pid=self_pid,
        started_at=now,
        session_id=session_id,
        primary_cwd=primary_cwd,
        state=sl.STATE_PENDING_RESOLUTION,
        worktree_path=None,
        worktree_branch=None,
    )
    sl.write_lockfile(self_path, provisional)

    # Phase B: re-scan, find live peers (excluding self).
    sl.gc_dead_lockfiles(sessions_dir)
    peers = [
        lf for lf in sl.list_live_lockfiles(sessions_dir, primary_cwd=primary_cwd)
        if lf.pid != self_pid
    ]
    resolved_state = sl.resolve_state(
        self_pid=self_pid, live_peer_pids=[p.pid for p in peers]
    )
    final = sl.Lockfile(
        schema=sl.SCHEMA,
        pid=self_pid,
        started_at=now,
        session_id=session_id,
        primary_cwd=primary_cwd,
        state=resolved_state,
        worktree_path=None,
        worktree_branch=None,
    )
    sl.write_lockfile(self_path, final)

    if resolved_state == sl.STATE_PRIMARY:
        return 0, ""
    peer_summary = ", ".join(f"pid={p.pid} started={p.started_at}" for p in peers)
    return 0, BLOCK_MESSAGE_TEMPLATE.format(peers=peer_summary)


def main(argv: list[str]) -> int:
    cwd = _project_dir()
    sessions_dir = Path(cwd) / ".harness" / "sessions"
    self_pid = os.getppid()  # the Claude Code process; hooks are children
    rc, message = run(
        sessions_dir=sessions_dir, primary_cwd=cwd, self_pid=self_pid,
    )
    if message:
        sys.stdout.write(message)
        sys.stdout.flush()
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

4. Run tests:

```bash
python -m pytest tests/harness/test_session_start.py -q
```

Expected: PASS (4 tests).

5. Commit:

```bash
git add scripts/harness/session_start.py tests/harness/test_session_start.py
git commit -m "feat(session-leash): T02 SessionStart hook with two-phase write"
```

- [ ] **Task 2 complete**

<!-- task-meta
id: T02
touches:
  - scripts/harness/session_start.py
  - tests/harness/test_session_start.py
depends: [T01]
verify: python -m pytest tests/harness/test_session_start.py -q
acceptance: null
-->

---

### Task 3 — `session_gate.py`: PreToolUse decision logic

The PreToolUse hook reads the lockfile for `os.getppid()` (the Claude
Code process) and decides allow/deny. Reads tool name + tool input from
JSON on stdin (per Claude Code hook protocol), prints the decision
verdict on stdout.

**Files:**
- Create: `scripts/harness/session_gate.py`
- Create: `tests/harness/test_session_gate.py`

**Steps:**

1. Write the failing test — `tests/harness/test_session_gate.py`:

```python
"""PreToolUse-gate tests."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.harness import session_lockfile as sl
from scripts.harness.session_gate import decide, Decision


def _write_lf(sessions_dir: Path, pid: int, state: str,
              cwd: str, worktree_path: str | None = None) -> None:
    lf = sl.Lockfile(
        schema=1, pid=pid, started_at="x", session_id="s",
        primary_cwd=cwd, state=state,
        worktree_path=worktree_path, worktree_branch=None,
    )
    sl.write_lockfile(sessions_dir / f"{pid}.json", lf)


def test_no_lockfile_allows(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    sessions_dir.mkdir(parents=True)
    d = decide(
        sessions_dir=sessions_dir, self_pid=99999,
        tool_name="Edit", tool_input={"file_path": str(tmp_path / "x.py")},
    )
    assert d.allow is True


def test_primary_state_allows(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    _write_lf(sessions_dir, os.getpid(), sl.STATE_PRIMARY, str(tmp_path))
    d = decide(
        sessions_dir=sessions_dir, self_pid=os.getpid(),
        tool_name="Write", tool_input={"file_path": str(tmp_path / "x.py")},
    )
    assert d.allow is True


def test_pending_worktree_denies_edit(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    _write_lf(sessions_dir, os.getpid(), sl.STATE_PENDING_WORKTREE, str(tmp_path))
    d = decide(
        sessions_dir=sessions_dir, self_pid=os.getpid(),
        tool_name="Edit", tool_input={"file_path": str(tmp_path / "x.py")},
    )
    assert d.allow is False
    assert "/leash-session-new" in d.reason


def test_pending_resolution_also_denies(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    _write_lf(sessions_dir, os.getpid(), sl.STATE_PENDING_RESOLUTION, str(tmp_path))
    d = decide(
        sessions_dir=sessions_dir, self_pid=os.getpid(),
        tool_name="MultiEdit", tool_input={"file_path": str(tmp_path / "x.py")},
    )
    assert d.allow is False


def test_in_worktree_allows_edit_inside(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    wt = tmp_path / "wt"
    wt.mkdir()
    _write_lf(sessions_dir, os.getpid(), sl.STATE_IN_WORKTREE,
              str(tmp_path), worktree_path=str(wt))
    d = decide(
        sessions_dir=sessions_dir, self_pid=os.getpid(),
        tool_name="Edit", tool_input={"file_path": str(wt / "y.py")},
    )
    assert d.allow is True


def test_in_worktree_denies_edit_outside(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    wt = tmp_path / "wt"
    wt.mkdir()
    _write_lf(sessions_dir, os.getpid(), sl.STATE_IN_WORKTREE,
              str(tmp_path), worktree_path=str(wt))
    d = decide(
        sessions_dir=sessions_dir, self_pid=os.getpid(),
        tool_name="Edit", tool_input={"file_path": str(tmp_path / "outside.py")},
    )
    assert d.allow is False
    assert str(wt) in d.reason


def test_unknown_tool_name_allows(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    _write_lf(sessions_dir, os.getpid(), sl.STATE_PENDING_WORKTREE, str(tmp_path))
    # Tools we don't gate (Bash, Read, etc.) get an allow regardless.
    d = decide(
        sessions_dir=sessions_dir, self_pid=os.getpid(),
        tool_name="Bash", tool_input={"command": "ls"},
    )
    assert d.allow is True
```

2. Run the failing test:

```bash
python -m pytest tests/harness/test_session_gate.py -q
```

Expected: FAIL with `ImportError`.

3. Implement `scripts/harness/session_gate.py`:

```python
"""PreToolUse hook: deny write tools while session lacks a worktree.

Wired into .claude/settings.json against the matcher
"Edit|Write|MultiEdit". `Bash` is intentionally NOT in the matcher —
/leash-session-new uses Bash for `git worktree add`. Gating Bash here
deadlocks the auto-resolution.

Hook protocol: read JSON from stdin {tool_name, tool_input, ...},
print JSON {"decision": "allow"|"deny", "reason": str} on stdout.
Exit 0 always; the verdict is in the JSON.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.harness import session_lockfile as sl

GATED_TOOLS = frozenset({"Edit", "Write", "MultiEdit"})


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str

    def to_json(self) -> str:
        return json.dumps(
            {"decision": "allow" if self.allow else "deny", "reason": self.reason}
        )


def _lockfile_for(sessions_dir: Path, pid: int) -> sl.Lockfile | None:
    path = sessions_dir / f"{pid}.json"
    if not path.exists():
        return None
    try:
        return sl.read_lockfile(path)
    except (ValueError, KeyError):
        return None


def decide(
    *,
    sessions_dir: Path,
    self_pid: int,
    tool_name: str,
    tool_input: dict,
) -> Decision:
    """Pure decision function — no I/O beyond reading the lockfile."""
    if tool_name not in GATED_TOOLS:
        return Decision(allow=True, reason="")
    lf = _lockfile_for(sessions_dir, self_pid)
    if lf is None:
        return Decision(allow=True, reason="")
    if lf.state == sl.STATE_PRIMARY:
        return Decision(allow=True, reason="")
    if lf.state in (sl.STATE_PENDING_WORKTREE, sl.STATE_PENDING_RESOLUTION):
        return Decision(
            allow=False,
            reason=(
                f"SESSION LEASH: this session is `{lf.state}` and may not write. "
                f"Invoke /leash-session-new to create a worktree. "
                f"Lockfile: {sessions_dir / (str(self_pid) + '.json')}"
            ),
        )
    if lf.state == sl.STATE_IN_WORKTREE:
        target = tool_input.get("file_path") or ""
        wt = lf.worktree_path or ""
        if wt and target and Path(target).resolve().as_posix().startswith(
            Path(wt).resolve().as_posix()
        ):
            return Decision(allow=True, reason="")
        return Decision(
            allow=False,
            reason=(
                f"SESSION LEASH: writes must target the worktree {wt}. "
                f"Target {target!r} is outside it."
            ),
        )
    return Decision(allow=True, reason="")


def main(argv: list[str]) -> int:
    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    sessions_dir = cwd / ".harness" / "sessions"
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    d = decide(
        sessions_dir=sessions_dir,
        self_pid=os.getppid(),
        tool_name=tool_name,
        tool_input=tool_input,
    )
    sys.stdout.write(d.to_json())
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

4. Run tests:

```bash
python -m pytest tests/harness/test_session_gate.py -q
```

Expected: PASS (7 tests).

5. Commit:

```bash
git add scripts/harness/session_gate.py tests/harness/test_session_gate.py
git commit -m "feat(session-leash): T03 PreToolUse gate for Edit|Write|MultiEdit"
```

- [ ] **Task 3 complete**

<!-- task-meta
id: T03
touches:
  - scripts/harness/session_gate.py
  - tests/harness/test_session_gate.py
depends: [T01]
verify: python -m pytest tests/harness/test_session_gate.py -q
acceptance: null
-->

---

### Task 4 — `session_new.py` + `/leash-session-new` skill

Worktree creation backed by a small Python script. The skill markdown
just tells Claude to run the script. Splitting impl from skill keeps the
testable surface in Python; the skill is a thin doc.

**Files:**
- Create: `scripts/harness/session_new.py`
- Create: `skills/leash-session-new/SKILL.md`
- Create: `tests/harness/test_session_new.py`

**Steps:**

1. Write the failing test — `tests/harness/test_session_new.py`:

```python
"""leash-session-new worktree-creation tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.harness import session_lockfile as sl
from scripts.harness.session_new import create_worktree, SessionNewError


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "t@t"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "t"], cwd=path)
    (path / "README").write_text("seed\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=path)


def _plant_lockfile(repo: Path, pid: int, state: str) -> Path:
    sessions = repo / ".harness" / "sessions"
    lf = sl.Lockfile(
        schema=1, pid=pid, started_at="x", session_id="s",
        primary_cwd=str(repo), state=state,
        worktree_path=None, worktree_branch=None,
    )
    sl.write_lockfile(sessions / f"{pid}.json", lf)
    return sessions / f"{pid}.json"


def test_creates_sibling_worktree_and_flips_state(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "myproj"
    _init_git_repo(repo)
    lf_path = _plant_lockfile(repo, os.getpid(), sl.STATE_PENDING_WORKTREE)

    info = create_worktree(repo_root=repo, self_pid=os.getpid())

    assert info.worktree_path.parent == parent
    assert info.worktree_path.name.startswith("myproj--session-")
    assert info.worktree_path.exists()
    assert info.worktree_branch.startswith("session/")
    # Branch exists in the primary repo.
    branches = subprocess.check_output(
        ["git", "branch", "--list"], cwd=repo, text=True,
    )
    assert info.worktree_branch in branches.replace("*", "").split()
    # Lockfile state flipped to in-worktree.
    updated = sl.read_lockfile(lf_path)
    assert updated.state == sl.STATE_IN_WORKTREE
    assert updated.worktree_path == str(info.worktree_path)
    assert updated.worktree_branch == info.worktree_branch


def test_idempotent_on_already_in_worktree(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "myproj"
    _init_git_repo(repo)
    _plant_lockfile(repo, os.getpid(), sl.STATE_PENDING_WORKTREE)
    info1 = create_worktree(repo_root=repo, self_pid=os.getpid())
    info2 = create_worktree(repo_root=repo, self_pid=os.getpid())
    assert info1.worktree_path == info2.worktree_path
    assert info1.worktree_branch == info2.worktree_branch


def test_errors_clearly_when_no_lockfile(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "myproj"
    _init_git_repo(repo)
    # No lockfile planted.
    with pytest.raises(SessionNewError, match="lockfile"):
        create_worktree(repo_root=repo, self_pid=os.getpid())
```

2. Run the failing test:

```bash
python -m pytest tests/harness/test_session_new.py -q
```

Expected: FAIL with `ImportError`.

3. Implement `scripts/harness/session_new.py`:

```python
"""leash-session-new: create a sibling worktree for a blocked session.

Called by the /leash-session-new skill. Reads this session's lockfile
(by os.getppid()), creates `../<repo>--session-<id>/` on a fresh
`session/<id>` branch from HEAD, and flips the lockfile to
`in-worktree`. Idempotent.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from scripts.harness import session_lockfile as sl


class SessionNewError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorktreeInfo:
    worktree_path: Path
    worktree_branch: str


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _short_id() -> str:
    return uuid.uuid4().hex[:6]


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SessionNewError(
            f"git {' '.join(args)} failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    return proc.stdout


def create_worktree(*, repo_root: Path, self_pid: int) -> WorktreeInfo:
    sessions_dir = repo_root / ".harness" / "sessions"
    lf_path = sessions_dir / f"{self_pid}.json"
    if not lf_path.exists():
        raise SessionNewError(
            f"no session lockfile at {lf_path}; was SessionStart hook installed?"
        )
    lf = sl.read_lockfile(lf_path)

    # Idempotent shortcut.
    if lf.state == sl.STATE_IN_WORKTREE and lf.worktree_path and lf.worktree_branch:
        wt = Path(lf.worktree_path)
        if wt.exists():
            return WorktreeInfo(worktree_path=wt, worktree_branch=lf.worktree_branch)

    if lf.state == sl.STATE_PRIMARY:
        raise SessionNewError(
            "session is `primary`; no worktree needed. /leash-session-new is a no-op."
        )

    # Pick an id and compute paths.
    sid = _short_id()
    branch = f"session/{sid}"
    worktree_path = repo_root.parent / f"{repo_root.name}--session-{sid}"

    if worktree_path.exists():
        raise SessionNewError(
            f"worktree path already exists: {worktree_path}. "
            "Pick a different id or remove the stale directory."
        )

    # `git worktree add <path> -b <branch> HEAD`
    _git(
        ["worktree", "add", str(worktree_path), "-b", branch, "HEAD"],
        cwd=repo_root,
    )

    # Flip lockfile state.
    updated = sl.Lockfile(
        schema=lf.schema,
        pid=lf.pid,
        started_at=lf.started_at,
        session_id=lf.session_id,
        primary_cwd=lf.primary_cwd,
        state=sl.STATE_IN_WORKTREE,
        worktree_path=str(worktree_path),
        worktree_branch=branch,
    )
    sl.write_lockfile(lf_path, updated)
    return WorktreeInfo(worktree_path=worktree_path, worktree_branch=branch)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--repo-root", type=Path, default=Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()),
    )
    p.add_argument("--self-pid", type=int, default=os.getppid())
    args = p.parse_args(argv[1:])
    try:
        info = create_worktree(repo_root=args.repo_root.resolve(), self_pid=args.self_pid)
    except SessionNewError as exc:
        sys.stderr.write(f"leash-session-new: {exc}\n")
        return 1
    print(f"Worktree created at: {info.worktree_path}")
    print(f"Branch: {info.worktree_branch}")
    print(
        "From now on, use ABSOLUTE paths under that directory for all Edit, "
        "Write, MultiEdit, and file Read operations. Your session cwd has "
        "not moved; this is intentional. When you finish, invoke "
        "/leash-session-end to remove the worktree and the lockfile."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

4. Write the skill — `skills/leash-session-new/SKILL.md`:

```markdown
---
name: leash-session-new
description: Use to escape a session-leash block. Creates a sibling git worktree for this Claude Code session and flips its lockfile to in-worktree so write tools unblock. Invoke as your next action when SessionStart said this session is concurrent.
---

# leash-session-new

## When to use

The `SessionStart` hook reported `SESSION LEASH: concurrent Claude Code
session detected`, and `PreToolUse` is now denying `Edit`, `Write`, and
`MultiEdit`. You MUST invoke this skill before any other tool call.

Do NOT use this when only one Claude Code session is open in this repo —
it will refuse with a clear message.

## How

1. Run the backing script:

   ```bash
   python scripts/harness/session_new.py
   ```

2. The script:
   - reads this session's lockfile at `.harness/sessions/<pid>.json`
   - creates a sibling worktree `../<repo>--session-<id>/` on a new
     `session/<id>` branch from `HEAD`
   - flips the lockfile state to `in-worktree`
3. The script prints the worktree path. From that point on, **use
   absolute paths under that directory** for every `Edit`, `Write`,
   `MultiEdit`, and file `Read`. Your session cwd has not moved; this
   is intentional.
4. The skill is idempotent. Running it twice returns the same worktree.

## Constraints

- The skill does NOT copy uncommitted WIP from the primary checkout.
  The second session starts from `HEAD` and proceeds from there.
- Do not edit the lockfile JSON by hand to "skip" this step. The
  `PreToolUse` gate will keep denying writes.
- When you finish, invoke `/leash-session-end` to remove the worktree
  and clean up.
```

5. Run tests:

```bash
python -m pytest tests/harness/test_session_new.py -q
```

Expected: PASS (3 tests).

6. Commit:

```bash
git add scripts/harness/session_new.py skills/leash-session-new/SKILL.md tests/harness/test_session_new.py
git commit -m "feat(session-leash): T04 leash-session-new skill + worktree creator"
```

- [ ] **Task 4 complete**

<!-- task-meta
id: T04
touches:
  - scripts/harness/session_new.py
  - skills/leash-session-new/SKILL.md
  - tests/harness/test_session_new.py
depends: [T01]
verify: python -m pytest tests/harness/test_session_new.py -q
acceptance: null
-->

---

### Task 5 — `session_end.py` + `/leash-session-end` skill

Tear down a worktree the session created. Refuses on dirty / unmerged
unless `--keep-branch` is passed. Removes the lockfile only after the
worktree is gone.

**Files:**
- Create: `scripts/harness/session_end.py`
- Create: `skills/leash-session-end/SKILL.md`
- Create: `tests/harness/test_session_end.py`

**Steps:**

1. Write the failing test — `tests/harness/test_session_end.py`:

```python
"""leash-session-end teardown tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.harness import session_lockfile as sl
from scripts.harness.session_new import create_worktree
from scripts.harness.session_end import end_session, SessionEndError


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "t@t"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "t"], cwd=path)
    (path / "README").write_text("seed\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=path)


def _plant_pending(repo: Path, pid: int) -> Path:
    sessions = repo / ".harness" / "sessions"
    lf = sl.Lockfile(
        schema=1, pid=pid, started_at="x", session_id="s",
        primary_cwd=str(repo), state=sl.STATE_PENDING_WORKTREE,
        worktree_path=None, worktree_branch=None,
    )
    sl.write_lockfile(sessions / f"{pid}.json", lf)
    return sessions / f"{pid}.json"


def test_removes_clean_merged_worktree_and_lockfile(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "myproj"
    _init_git_repo(repo)
    _plant_pending(repo, os.getpid())
    info = create_worktree(repo_root=repo, self_pid=os.getpid())
    # Merge the (empty) session branch back into main so `-d` is allowed.
    subprocess.check_call(
        ["git", "merge", "--no-ff", info.worktree_branch, "-m", "merge"], cwd=repo,
    )
    end_session(repo_root=repo, self_pid=os.getpid(), keep_branch=False)
    assert not info.worktree_path.exists()
    assert not (repo / ".harness" / "sessions" / f"{os.getpid()}.json").exists()
    branches = subprocess.check_output(["git", "branch"], cwd=repo, text=True)
    assert info.worktree_branch not in branches


def test_refuses_on_dirty_worktree(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "myproj"
    _init_git_repo(repo)
    _plant_pending(repo, os.getpid())
    info = create_worktree(repo_root=repo, self_pid=os.getpid())
    (info.worktree_path / "dirty.txt").write_text("uncommitted", encoding="utf-8")
    with pytest.raises(SessionEndError, match="uncommitted"):
        end_session(repo_root=repo, self_pid=os.getpid(), keep_branch=False)
    assert info.worktree_path.exists()  # nothing removed


def test_refuses_on_unmerged_branch_without_keep(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "myproj"
    _init_git_repo(repo)
    _plant_pending(repo, os.getpid())
    info = create_worktree(repo_root=repo, self_pid=os.getpid())
    # Add a commit to the session branch but DO NOT merge it.
    (info.worktree_path / "new.txt").write_text("hi\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=info.worktree_path)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=info.worktree_path)
    with pytest.raises(SessionEndError, match="unmerged"):
        end_session(repo_root=repo, self_pid=os.getpid(), keep_branch=False)


def test_keep_branch_skips_merge_check(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "myproj"
    _init_git_repo(repo)
    _plant_pending(repo, os.getpid())
    info = create_worktree(repo_root=repo, self_pid=os.getpid())
    (info.worktree_path / "new.txt").write_text("hi\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=info.worktree_path)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=info.worktree_path)
    end_session(repo_root=repo, self_pid=os.getpid(), keep_branch=True)
    assert not info.worktree_path.exists()
    branches = subprocess.check_output(["git", "branch"], cwd=repo, text=True)
    assert info.worktree_branch in branches.replace("*", "").split()
```

2. Run the failing test:

```bash
python -m pytest tests/harness/test_session_end.py -q
```

Expected: FAIL with `ImportError`.

3. Implement `scripts/harness/session_end.py`:

```python
"""leash-session-end: remove this session's worktree + lockfile."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from scripts.harness import session_lockfile as sl


class SessionEndError(RuntimeError):
    pass


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SessionEndError(
            f"git {' '.join(args)} failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    return proc.stdout


def _worktree_dirty(worktree: Path) -> bool:
    out = _git(["status", "--porcelain"], cwd=worktree)
    return bool(out.strip())


def _branch_is_merged(repo: Path, branch: str) -> bool:
    out = _git(["branch", "--merged"], cwd=repo)
    merged = {b.strip().lstrip("* ").strip() for b in out.splitlines()}
    return branch in merged


def end_session(
    *,
    repo_root: Path,
    self_pid: int,
    keep_branch: bool,
) -> None:
    lf_path = repo_root / ".harness" / "sessions" / f"{self_pid}.json"
    if not lf_path.exists():
        raise SessionEndError(f"no lockfile at {lf_path}")
    lf = sl.read_lockfile(lf_path)
    if lf.state != sl.STATE_IN_WORKTREE:
        raise SessionEndError(
            f"session state is {lf.state!r}; expected `in-worktree`"
        )
    if not lf.worktree_path or not lf.worktree_branch:
        raise SessionEndError("lockfile has no worktree_path / worktree_branch")
    wt = Path(lf.worktree_path)
    if not wt.exists():
        # Worktree directory gone but lockfile stale — clean up the metadata.
        try:
            _git(["worktree", "prune"], cwd=repo_root)
        except SessionEndError:
            pass
        lf_path.unlink(missing_ok=True)
        return

    if _worktree_dirty(wt):
        raise SessionEndError(
            f"worktree {wt} has uncommitted changes; commit or stash first"
        )

    if not keep_branch:
        if not _branch_is_merged(repo_root, lf.worktree_branch):
            raise SessionEndError(
                f"branch {lf.worktree_branch} is unmerged; "
                "merge it first or pass --keep-branch"
            )

    _git(["worktree", "remove", str(wt)], cwd=repo_root)
    if not keep_branch:
        _git(["branch", "-d", lf.worktree_branch], cwd=repo_root)
    lf_path.unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--repo-root", type=Path,
        default=Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()),
    )
    p.add_argument("--self-pid", type=int, default=os.getppid())
    p.add_argument("--keep-branch", action="store_true")
    args = p.parse_args(argv[1:])
    try:
        end_session(
            repo_root=args.repo_root.resolve(),
            self_pid=args.self_pid,
            keep_branch=args.keep_branch,
        )
    except SessionEndError as exc:
        sys.stderr.write(f"leash-session-end: {exc}\n")
        return 1
    print("Session ended; worktree removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

4. Write the skill — `skills/leash-session-end/SKILL.md`:

```markdown
---
name: leash-session-end
description: Use to cleanly close a session-leash worktree. Refuses on dirty index or unmerged branch unless --keep-branch is passed. Removes the worktree, deletes the session branch (unless kept), and clears the lockfile.
---

# leash-session-end

## When to use

You finished the work that prompted `/leash-session-new` and you want
the temporary worktree gone. Run this skill before closing the Claude
Code session.

## How

1. If your session branch's work belongs on a long-lived branch, commit
   and merge it first (the skill refuses to delete unmerged branches by
   default).

2. Run:

   ```bash
   python scripts/harness/session_end.py
   ```

3. The script:
   - reads this session's lockfile
   - refuses if the worktree has uncommitted changes (commit or stash first)
   - refuses if the session branch is unmerged (merge it, or pass
     `--keep-branch`)
   - runs `git worktree remove`, deletes the session branch (when not
     kept), and removes the lockfile

## Flags

- `--keep-branch` — keep the session branch around (useful if you want
  to PR it later). The worktree directory is still removed.

## Constraints

- Never `--force` removal. If the script refuses, fix the underlying
  issue. `git worktree remove --force` would silently discard
  uncommitted work — out of scope.
```

5. Run tests:

```bash
python -m pytest tests/harness/test_session_end.py -q
```

Expected: PASS (4 tests).

6. Commit:

```bash
git add scripts/harness/session_end.py skills/leash-session-end/SKILL.md tests/harness/test_session_end.py
git commit -m "feat(session-leash): T05 leash-session-end skill + worktree teardown"
```

- [ ] **Task 5 complete**

<!-- task-meta
id: T05
touches:
  - scripts/harness/session_end.py
  - skills/leash-session-end/SKILL.md
  - tests/harness/test_session_end.py
depends: [T04]
verify: python -m pytest tests/harness/test_session_end.py -q
acceptance: null
-->

---

### Task 6 — `list_sessions.py`: introspection CLI

A simple `python scripts/harness/list_sessions.py` prints all live
session lockfiles in the current repo. Used for debugging and by the
dogfood test.

**Files:**
- Create: `scripts/harness/list_sessions.py`
- Create: `tests/harness/test_list_sessions.py`

**Steps:**

1. Write the failing test — `tests/harness/test_list_sessions.py`:

```python
"""list_sessions CLI tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.harness import session_lockfile as sl
from scripts.harness.list_sessions import format_sessions


def _plant(sessions_dir: Path, pid: int, cwd: str, state: str) -> None:
    lf = sl.Lockfile(
        schema=1, pid=pid, started_at="x", session_id=f"s{pid}",
        primary_cwd=cwd, state=state,
        worktree_path=None, worktree_branch=None,
    )
    sl.write_lockfile(sessions_dir / f"{pid}.json", lf)


def test_empty_sessions_dir(tmp_path: Path):
    out = format_sessions(tmp_path / "sessions", primary_cwd=str(tmp_path))
    assert out.strip() == "(no live sessions)"


def test_lists_live_only(tmp_path: Path):
    sessions = tmp_path / "sessions"
    _plant(sessions, os.getpid(), str(tmp_path), sl.STATE_PRIMARY)
    # Dead PID lockfile.
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    proc.wait()
    _plant(sessions, proc.pid, str(tmp_path), sl.STATE_PENDING_WORKTREE)
    out = format_sessions(sessions, primary_cwd=str(tmp_path))
    assert str(os.getpid()) in out
    assert str(proc.pid) not in out
```

2. Run the failing test:

```bash
python -m pytest tests/harness/test_list_sessions.py -q
```

Expected: FAIL with `ImportError`.

3. Implement `scripts/harness/list_sessions.py`:

```python
"""List live session lockfiles in the current repo."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from scripts.harness import session_lockfile as sl


def format_sessions(sessions_dir: Path, *, primary_cwd: str) -> str:
    sl.gc_dead_lockfiles(sessions_dir) if sessions_dir.exists() else None
    live = sl.list_live_lockfiles(sessions_dir, primary_cwd=primary_cwd)
    if not live:
        return "(no live sessions)\n"
    lines = ["pid\tstate\tstarted_at\tworktree"]
    for lf in live:
        lines.append(
            f"{lf.pid}\t{lf.state}\t{lf.started_at}\t{lf.worktree_path or '-'}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    sessions = cwd / ".harness" / "sessions"
    sys.stdout.write(format_sessions(sessions, primary_cwd=str(cwd)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

4. Run tests:

```bash
python -m pytest tests/harness/test_list_sessions.py -q
```

Expected: PASS (2 tests).

5. Commit:

```bash
git add scripts/harness/list_sessions.py tests/harness/test_list_sessions.py
git commit -m "feat(session-leash): T06 list_sessions introspection CLI"
```

- [ ] **Task 6 complete**

<!-- task-meta
id: T06
touches:
  - scripts/harness/list_sessions.py
  - tests/harness/test_list_sessions.py
depends: [T01]
verify: python -m pytest tests/harness/test_list_sessions.py -q
acceptance: null
-->

---

### Task 7 — `cycle_done.py` worktree sweep

Append a conservative sweep step to the end of `cycle_done.py` that
removes worktrees whose branch is merged + clean + has a dead PID. Anything
that fails any condition is left alone with a one-line note.

**Files:**
- Modify: `scripts/harness/cycle_done.py`
- Create: `tests/harness/test_cycle_done_session_sweep.py`

**Steps:**

1. Write the failing test — `tests/harness/test_cycle_done_session_sweep.py`:

```python
"""cycle_done worktree-sweep tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.harness import session_lockfile as sl
from scripts.harness.cycle_done import sweep_session_worktrees


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "t@t"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "t"], cwd=path)
    (path / "README").write_text("seed\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=path)


def _make_wt(repo: Path, sid: str) -> tuple[Path, str]:
    wt = repo.parent / f"{repo.name}--session-{sid}"
    branch = f"session/{sid}"
    subprocess.check_call(
        ["git", "worktree", "add", str(wt), "-b", branch, "HEAD"], cwd=repo,
    )
    return wt, branch


def test_removes_clean_merged_dead_pid(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "p"
    _init_git_repo(repo)
    wt, branch = _make_wt(repo, "aaa111")
    # Merge the (empty) branch.
    subprocess.check_call(["git", "merge", "--no-ff", branch, "-m", "m"], cwd=repo)
    # Plant a dead-PID lockfile pointing at this worktree.
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    proc.wait()
    lf = sl.Lockfile(
        schema=1, pid=proc.pid, started_at="x", session_id="s",
        primary_cwd=str(repo), state=sl.STATE_IN_WORKTREE,
        worktree_path=str(wt), worktree_branch=branch,
    )
    sl.write_lockfile(repo / ".harness" / "sessions" / f"{proc.pid}.json", lf)

    removed = sweep_session_worktrees(repo_root=repo)
    assert str(wt) in removed
    assert not wt.exists()


def test_leaves_unmerged(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "p"
    _init_git_repo(repo)
    wt, branch = _make_wt(repo, "bbb222")
    # Add commit but do not merge.
    (wt / "x.txt").write_text("hi\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=wt)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=wt)
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    proc.wait()
    lf = sl.Lockfile(
        schema=1, pid=proc.pid, started_at="x", session_id="s",
        primary_cwd=str(repo), state=sl.STATE_IN_WORKTREE,
        worktree_path=str(wt), worktree_branch=branch,
    )
    sl.write_lockfile(repo / ".harness" / "sessions" / f"{proc.pid}.json", lf)

    removed = sweep_session_worktrees(repo_root=repo)
    assert str(wt) not in removed
    assert wt.exists()


def test_leaves_live_pid_even_if_merged(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "p"
    _init_git_repo(repo)
    wt, branch = _make_wt(repo, "ccc333")
    subprocess.check_call(["git", "merge", "--no-ff", branch, "-m", "m"], cwd=repo)
    # Plant a LIVE-PID lockfile (use our own pid).
    lf = sl.Lockfile(
        schema=1, pid=os.getpid(), started_at="x", session_id="s",
        primary_cwd=str(repo), state=sl.STATE_IN_WORKTREE,
        worktree_path=str(wt), worktree_branch=branch,
    )
    sl.write_lockfile(repo / ".harness" / "sessions" / f"{os.getpid()}.json", lf)

    removed = sweep_session_worktrees(repo_root=repo)
    assert str(wt) not in removed
    assert wt.exists()


def test_leaves_worktree_with_no_lockfile(tmp_path: Path):
    """A session/* worktree with no matching lockfile is user-created;
    sweep must leave it alone. Spec §5 requires lockfile-dead, not
    lockfile-absent.
    """
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "p"
    _init_git_repo(repo)
    wt, branch = _make_wt(repo, "ddd444")
    subprocess.check_call(["git", "merge", "--no-ff", branch, "-m", "m"], cwd=repo)
    # Note: no lockfile planted.
    removed = sweep_session_worktrees(repo_root=repo)
    assert str(wt) not in removed
    assert wt.exists()
```

2. Run the failing test:

```bash
python -m pytest tests/harness/test_cycle_done_session_sweep.py -q
```

Expected: FAIL — `sweep_session_worktrees` does not exist yet.

3. Modify `scripts/harness/cycle_done.py` — add the sweep function and call
   it from `main()` after gates pass. Add these imports at the top of
   the file (after the existing `import` block):

```python
from scripts.harness import session_lockfile as sl
```

   Add this new function above `def main(...)`:

```python
def _git_out(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
    )
    return proc.stdout if proc.returncode == 0 else ""


def _worktree_branches(repo: Path) -> list[tuple[Path, str]]:
    """Parse `git worktree list --porcelain` into (path, branch) pairs.

    Returns only worktrees whose branch starts with `session/`.
    """
    out = _git_out(["worktree", "list", "--porcelain"], repo)
    results: list[tuple[Path, str]] = []
    path: Path | None = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):])
        elif line.startswith("branch refs/heads/") and path is not None:
            branch = line[len("branch refs/heads/"):]
            if branch.startswith("session/"):
                results.append((path, branch))
            path = None
        elif line == "":
            path = None
    return results


def _find_lockfile_for_worktree(sessions_dir: Path, wt_path: Path) -> Path | None:
    """Return the lockfile that points to this worktree, or None."""
    if not sessions_dir.exists():
        return None
    for p in sessions_dir.glob("*.json"):
        try:
            lf = sl.read_lockfile(p)
        except (ValueError, KeyError):
            continue
        if lf.worktree_path == str(wt_path):
            return p
    return None


def sweep_session_worktrees(*, repo_root: Path) -> list[str]:
    """Remove worktrees whose session/ branch is merged + clean + PID dead.

    Returns the list of removed worktree paths (stringified). Conservative:
    a worktree is removed ONLY if (a) its branch is merged, (b) its index
    is clean, AND (c) a lockfile exists that points at this worktree and
    whose PID is dead. A worktree with no matching lockfile is left alone
    — it may be a user-created session/* checkout we should not touch.
    """
    removed: list[str] = []
    sessions_dir = repo_root / ".harness" / "sessions"
    merged_raw = _git_out(["branch", "--merged"], repo_root)
    merged = {b.strip().lstrip("* ").strip() for b in merged_raw.splitlines()}
    for wt_path, branch in _worktree_branches(repo_root):
        if branch not in merged:
            print(f"sweep: leaving {wt_path} (branch {branch} unmerged)",
                  file=sys.stderr)
            continue
        if _git_out(["status", "--porcelain"], wt_path).strip():
            print(f"sweep: leaving {wt_path} (uncommitted changes)",
                  file=sys.stderr)
            continue
        matched_lf = _find_lockfile_for_worktree(sessions_dir, wt_path)
        if matched_lf is None:
            print(f"sweep: leaving {wt_path} (no matching lockfile; "
                  "may be user-created)", file=sys.stderr)
            continue
        try:
            lf = sl.read_lockfile(matched_lf)
        except (ValueError, KeyError):
            print(f"sweep: leaving {wt_path} (lockfile unreadable)",
                  file=sys.stderr)
            continue
        if sl.is_pid_alive(lf.pid):
            print(f"sweep: leaving {wt_path} (pid {lf.pid} alive)",
                  file=sys.stderr)
            continue
        rc = subprocess.call(
            ["git", "worktree", "remove", str(wt_path)], cwd=repo_root,
        )
        if rc != 0:
            print(f"sweep: git worktree remove failed for {wt_path}",
                  file=sys.stderr)
            continue
        subprocess.call(["git", "branch", "-d", branch], cwd=repo_root)
        matched_lf.unlink(missing_ok=True)
        removed.append(str(wt_path))
    return removed
```

   And in `main()`, after the `if all(results):` block prints `"ALL GATES
   PASS"` and before `return 0`, insert:

```python
        try:
            swept = sweep_session_worktrees(repo_root=REPO_ROOT)
            if swept:
                print(f"sweep: removed {len(swept)} session worktree(s)", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"sweep: skipped ({exc})", file=sys.stderr)
```

4. Run tests:

```bash
python -m pytest tests/harness/test_cycle_done_session_sweep.py -q
python -m pytest tests/harness/test_cycle_done.py -q
```

Expected: both PASS — the new sweep tests pass and the existing
`cycle_done` tests still pass.

5. Commit:

```bash
git add scripts/harness/cycle_done.py tests/harness/test_cycle_done_session_sweep.py
git commit -m "feat(session-leash): T07 cycle_done conservative session-worktree sweep"
```

- [ ] **Task 7 complete**

<!-- task-meta
id: T07
touches:
  - scripts/harness/cycle_done.py
  - tests/harness/test_cycle_done_session_sweep.py
depends: [T01]
verify: python -m pytest tests/harness/test_cycle_done_session_sweep.py -q
acceptance: python -m pytest tests/harness/test_cycle_done.py -q
-->

---

### Task 8 — Template updates: `settings.json.tmpl`, `CLAUDE.md.tmpl`, `AGENTS.md.tmpl`

Add the SessionStart + PreToolUse hook entries to the rendered
`.claude/settings.json` for any project that runs `bootstrap-dev-leash`.
Add one-line mentions in CLAUDE.md / AGENTS.md so a fresh agent knows
the leash exists.

**Files:**
- Modify: `templates/settings.json.tmpl`
- Modify: `templates/CLAUDE.md.tmpl`
- Modify: `templates/AGENTS.md.tmpl`
- Modify: `tests/test_templates.py`
- Modify: `.gitignore` (dev-on-leash's own; ignore `.harness/sessions/`)

**Steps:**

1. Extend `tests/test_templates.py` with these assertions (append; do
   not remove existing tests):

```python
def test_settings_template_has_session_leash_hooks():
    from pathlib import Path
    text = Path("templates/settings.json.tmpl").read_text(encoding="utf-8")
    # Both hook entries present.
    assert "SessionStart" in text
    assert "PreToolUse" in text
    assert "scripts/harness/session_start.py" in text
    assert "scripts/harness/session_gate.py" in text
    # PreToolUse matcher excludes Bash by listing only the gated tools.
    assert "Edit|Write|MultiEdit" in text


def test_claude_md_template_mentions_session_leash():
    from pathlib import Path
    text = Path("templates/CLAUDE.md.tmpl").read_text(encoding="utf-8")
    assert "session leash" in text.lower() or "/leash-session-new" in text


def test_agents_md_template_mentions_concurrent_sessions():
    from pathlib import Path
    text = Path("templates/AGENTS.md.tmpl").read_text(encoding="utf-8")
    assert "concurrent" in text.lower() or "/leash-session-new" in text
```

2. Run the failing tests:

```bash
python -m pytest tests/test_templates.py::test_settings_template_has_session_leash_hooks tests/test_templates.py::test_claude_md_template_mentions_session_leash tests/test_templates.py::test_agents_md_template_mentions_concurrent_sessions -q
```

Expected: FAIL on all three.

3. Modify `templates/settings.json.tmpl` to add the hooks block. The
   current file is:

```json
{
  "permissions": {
    "allow": [ ... ]
  }
}
```

   Replace its contents with:

```json
{
  "permissions": {
    "allow": [
      {{TEST_RUNNER_COMMANDS}},
      {{LINT_COMMANDS}},
      {{TYPECHECK_COMMANDS}},
      {{BUILD_COMMANDS}},
      "Bash(git status)",
      "Bash(git diff*)",
      "Bash(git log*)",
      "Bash(git show*)",
      "Bash(git branch*)",
      "Bash(git worktree*)",
      "Bash(pre-commit run*)",
      "Bash(python scripts/harness/*)"
    ]
  },
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python scripts/harness/session_start.py"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python scripts/harness/session_gate.py"
          }
        ]
      }
    ]
  }
}
```

4. Modify `templates/CLAUDE.md.tmpl` — add this line at the end of the
   `## Stack` section (or wherever guard-rails are described). Append
   the following block before the trailing horizontal rule:

```markdown

## Concurrent sessions

The harness installs a **session leash**. If you open a second Claude
Code session on this repo, `SessionStart` will detect the concurrency
and `PreToolUse` will deny `Edit`/`Write`/`MultiEdit` until you invoke
`/leash-session-new` — which creates a sibling git worktree and
unblocks writes. Run `/leash-session-end` when done.
```

5. Modify `templates/AGENTS.md.tmpl` — append the following block
   somewhere appropriate (e.g. under the existing guard-rails list):

```markdown

### Concurrent sessions

If two Claude Code sessions touch this repo at once, the second one is
blocked from writing until it invokes `/leash-session-new`. That skill
creates a sibling `git worktree` so each session has its own checkout.
Close out with `/leash-session-end`.
```

6. Append `.harness/sessions/` to the `# Harness runtime` section of
   `.gitignore`:

```
# Harness runtime
.harness/exceptions.log
.harness/sessions/
```

7. Run tests:

```bash
python -m pytest tests/test_templates.py -q
```

Expected: PASS — all template tests including the three new ones.

8. Commit:

```bash
git add templates/settings.json.tmpl templates/CLAUDE.md.tmpl templates/AGENTS.md.tmpl tests/test_templates.py .gitignore
git commit -m "feat(session-leash): T08 wire hooks in settings.json.tmpl + mention in CLAUDE/AGENTS templates"
```

- [ ] **Task 8 complete**

<!-- task-meta
id: T08
touches:
  - templates/settings.json.tmpl
  - templates/CLAUDE.md.tmpl
  - templates/AGENTS.md.tmpl
  - tests/test_templates.py
  - .gitignore
depends: [T02, T03]
verify: python -m pytest tests/test_templates.py -q
acceptance: null
-->

---

### Task 9 — README and trust model update

Add a "Session leash" subsection under "How it works" and update the
"Trust model" paragraph to name session leash. This satisfies the
`feedback-plan-includes-readme` memory: README touches ship in the same
plan as the feature, not as a follow-up.

**Files:**
- Modify: `README.md`
- Modify: `tests/test_docs.py`

**Steps:**

1. Extend `tests/test_docs.py` with these assertions (append):

```python
def test_readme_has_session_leash_section():
    from pathlib import Path
    text = Path("README.md").read_text(encoding="utf-8")
    assert "## Session leash" in text
    assert "/leash-session-new" in text
    assert "/leash-session-end" in text


def test_readme_trust_model_names_session_leash():
    from pathlib import Path
    text = Path("README.md").read_text(encoding="utf-8")
    # Trust model must mention the new feature under at least one of
    # the existing buckets.
    trust_block = text.split("## Trust model", 1)[1].split("##", 1)[0]
    assert "session" in trust_block.lower()
```

2. Run the failing tests:

```bash
python -m pytest tests/test_docs.py::test_readme_has_session_leash_section tests/test_docs.py::test_readme_trust_model_names_session_leash -q
```

Expected: FAIL on both.

3. Modify `README.md` — insert a new `## Session leash` subsection
   immediately after the existing `## Architecture leash` subsection,
   with this content:

```markdown
## Session leash

Concurrent Claude Code sessions on the same repo would otherwise share
one working tree and clobber each other's WIP. The session leash
detects this at `SessionStart`, blocks writes in the non-elected
session via a `PreToolUse` gate, and routes that session into its own
sibling git worktree via the `/leash-session-new` skill — auto-invoked
by the blocked agent. The worktree is cleaned up by
`/leash-session-end` and a conservative sweep in `cycle_done` that only
touches worktrees whose branch is merged, clean, and whose PID is dead.

Lockfiles live in `.harness/sessions/<pid>.json` (gitignored). PID
liveness is checked via `ctypes` on Windows and `os.kill(pid, 0)` on
POSIX. The two-phase write at `SessionStart` deterministically elects
the lowest-PID live session as primary, so the design needs no OS
lock.

`dev-on-leash` dogfoods this on itself: see `scripts/dogfood_session.py`,
which plants a peer lockfile, runs the hook, asserts the gate denies
an `Edit`, drives the resolution path, and asserts the gate unblocks
once the worktree is in place.
```

4. Modify the existing `## Trust model` block to add a sentence under
   the **Enforced** bullet that names session leash, and a sentence
   under the **By convention** bullet. Replace the existing Trust model
   bullets with:

```markdown
- **Enforced.** A harness task's checkbox is ticked only by `run_task.py`
  after its `verify` command exits 0. `recheck_plan.py` re-runs the `verify`
  of every ticked harness task — run it in CI (see
  [templates/ci-snippet.md](templates/ci-snippet.md)) and/or as the opt-in
  pre-commit hook, and a checkbox flipped by hand without the work done is
  rejected. A task heading with no `task-meta` block is human-run and not
  machine-checked. **Session leash:** while a second session is in
  `pending-worktree` or `pending-resolution`, the `PreToolUse` gate denies
  `Edit`, `Write`, and `MultiEdit`.
- **By convention only.** `touches` is self-reported: the harness does not yet
  check that a task modified *only* its declared files, so the parallel-safety
  of `plan_schedule.py` depends on `touches` being accurate. Verifying it
  without false positives needs its own design — tracked as a follow-up.
  **Session leash:** `Bash` is intentionally outside the gate matcher (so
  `/leash-session-new` can run `git worktree add`); a determined session
  could write to the primary checkout via `>` redirects. Same posture as
  `touches`.
- **Escape hatch.** `cycle_done.py --force -m <reason>` closes a cycle past
  failing gates and appends an audit line to `.harness/exceptions.log`. It
  bypasses `cycle_done`'s own gate check only — it does not disable
  `recheck_plan` running in CI or the pre-commit hook. **Session leash
  has no per-session bypass in v1**: a user who really needs two sessions
  on the primary checkout must remove the `SessionStart` / `PreToolUse`
  entries from `.claude/settings.json`, which is a visible git change.
```

5. Run tests:

```bash
python -m pytest tests/test_docs.py -q
```

Expected: PASS.

6. Commit:

```bash
git add README.md tests/test_docs.py
git commit -m "docs(session-leash): T09 README section + trust-model update"
```

- [ ] **Task 9 complete**

<!-- task-meta
id: T09
touches:
  - README.md
  - tests/test_docs.py
depends: [T04, T05]
verify: python -m pytest tests/test_docs.py::test_readme_has_session_leash_section tests/test_docs.py::test_readme_trust_model_names_session_leash -q
acceptance: null
-->

---

### Task 10 — `dogfood_session.py` + `smoke_e2e.py` extension

The load-bearing dogfood task. Builds a throwaway repo, plants a peer
lockfile, runs the SessionStart hook, asserts the gate denies an Edit,
runs the resolution path (`create_worktree`), asserts the gate now
allows an Edit targeting the worktree, then tears down. Wired into
`smoke_e2e.py` as a final step.

**Files:**
- Create: `scripts/dogfood_session.py`
- Modify: `scripts/smoke_e2e.py`
- Modify: `tests/test_smoke.py`

**Steps:**

1. Extend `tests/test_smoke.py` with this assertion (append; create
   the file if it doesn't exist with the necessary imports):

```python
def test_smoke_e2e_includes_session_leash_step():
    from pathlib import Path
    text = Path("scripts/smoke_e2e.py").read_text(encoding="utf-8")
    assert "_exercise_session_leash" in text
    assert "dogfood_session" in text or "session_gate" in text
```

2. Run the failing test:

```bash
python -m pytest tests/test_smoke.py::test_smoke_e2e_includes_session_leash_step -q
```

Expected: FAIL.

3. Create `scripts/dogfood_session.py`:

```python
#!/usr/bin/env python3
"""Dogfood the session leash on a throwaway repo.

Steps:
  1. init a git repo + an empty .harness/sessions dir.
  2. Plant a peer lockfile claiming a LIVE pid (we spawn a sleeper).
  3. Run session_start.run(); assert resolved state is pending-worktree.
  4. Run session_gate.decide() with an Edit payload; assert deny.
  5. Run session_new.create_worktree(); assert worktree exists and
     lockfile flips to in-worktree.
  6. Re-run session_gate.decide() against a path inside the worktree;
     assert allow.
  7. Teardown: kill peer, remove worktree, remove lockfiles.

Exits 0 only if every step asserted clean. Used by smoke_e2e.py and as
the verify command for the dogfood task.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.harness import session_lockfile as sl  # noqa: E402
from scripts.harness import session_start as ss  # noqa: E402
from scripts.harness import session_gate as sg  # noqa: E402
from scripts.harness import session_new as sn  # noqa: E402


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "d@d"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "d"], cwd=path)
    (path / "seed").write_text("seed\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=path)


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="dol-session-"))
    repo = parent / "throwaway"
    peer = None
    try:
        _init_repo(repo)
        sessions = repo / ".harness" / "sessions"

        # 1. Spawn a peer process to act as the "first session".
        peer = subprocess.Popen(
            [sys.executable, "-c",
             "import sys, time; sys.stdout.write('ready\\n'); sys.stdout.flush(); time.sleep(60)"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        peer.stdout.readline()
        peer_lf = sl.Lockfile(
            schema=1, pid=peer.pid, started_at="2026-05-28T00:00:00Z",
            session_id="peer", primary_cwd=str(repo),
            state=sl.STATE_PRIMARY, worktree_path=None, worktree_branch=None,
        )
        sl.write_lockfile(sessions / f"{peer.pid}.json", peer_lf)

        # 2. Run SessionStart for ourselves; assert pending-worktree.
        self_pid = peer.pid + 1  # any pid higher than peer
        rc, message = ss.run(
            sessions_dir=sessions, primary_cwd=str(repo), self_pid=self_pid,
        )
        assert rc == 0, "session_start.run returned non-zero"
        assert "SESSION LEASH" in message, "expected block message"
        our_lf = sl.read_lockfile(sessions / f"{self_pid}.json")
        assert our_lf.state == sl.STATE_PENDING_WORKTREE, our_lf.state

        # 3. Gate must deny Edit.
        d = sg.decide(
            sessions_dir=sessions, self_pid=self_pid,
            tool_name="Edit", tool_input={"file_path": str(repo / "x.py")},
        )
        assert not d.allow, "gate must deny while pending-worktree"
        assert "/leash-session-new" in d.reason

        # 4. Resolve via create_worktree (skip the peer PID dependency by
        #    passing self_pid that owns the lockfile we wrote above).
        info = sn.create_worktree(repo_root=repo, self_pid=self_pid)
        assert info.worktree_path.exists()
        assert info.worktree_branch.startswith("session/")

        # 5. Gate now allows Edit inside the worktree.
        d2 = sg.decide(
            sessions_dir=sessions, self_pid=self_pid,
            tool_name="Edit",
            tool_input={"file_path": str(info.worktree_path / "y.py")},
        )
        assert d2.allow, f"gate must allow inside worktree: {d2.reason}"

        # 6. Gate denies Edit outside the worktree.
        d3 = sg.decide(
            sessions_dir=sessions, self_pid=self_pid,
            tool_name="Edit",
            tool_input={"file_path": str(repo / "outside.py")},
        )
        assert not d3.allow, "gate must deny edits outside the worktree"

        print("SESSION-LEASH DOGFOOD PASS")
        return 0
    except AssertionError as exc:
        print(f"SESSION-LEASH DOGFOOD FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        if peer is not None:
            try:
                peer.terminate()
                peer.wait(timeout=5)
            except Exception:
                pass
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
```

4. Modify `scripts/smoke_e2e.py`. Three concrete edits:

   **Edit 1.** After the existing `def _exercise_architecture(tmp: ...)`
   function (which ends around line 142 with the `good.returncode == 0`
   assertion), add a new helper:

```python
def _exercise_session_leash() -> None:
    """Run the session-leash dogfood script as a self-contained step."""
    rc = subprocess.call(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "dogfood_session.py")],
    )
    assert rc == 0, f"dogfood_session.py exit {rc}"
```

   **Edit 2.** Inside `step()` (currently around line 161-165), change
   the format string. Find the line:

```python
        line = f"[{n}/8] {label:<41} {mark}"
```

   Replace with:

```python
        line = f"[{n}/9] {label:<41} {mark}"
```

   **Edit 3.** In `main()`, after the existing `step(8, "arch-leash:
   gate rejects violation, passes clean", ...)` block (lines 237-242)
   and before the `finally:` block, add:

```python
        # 9 — exercise the session leash on a throwaway repo
        try:
            _exercise_session_leash()
            step(9, "session-leash: deny->worktree->allow path", True)
        except Exception as exc:  # noqa: BLE001
            step(9, "session-leash: deny->worktree->allow path", False, str(exc))
```

5. Run tests:

```bash
python -m pytest tests/test_smoke.py -q
python scripts/dogfood_session.py
```

Expected: pytest PASS; `dogfood_session.py` prints `SESSION-LEASH
DOGFOOD PASS` and exits 0.

6. Commit:

```bash
git add scripts/dogfood_session.py scripts/smoke_e2e.py tests/test_smoke.py
git commit -m "feat(session-leash): T10 dogfood script + smoke_e2e step (load-bearing)"
```

- [ ] **Task 10 complete**

<!-- task-meta
id: T10
touches:
  - scripts/dogfood_session.py
  - scripts/smoke_e2e.py
  - tests/test_smoke.py
depends: [T01, T02, T03, T04, T07, T08]
verify: python scripts/dogfood_session.py
acceptance: python scripts/smoke_e2e.py
-->

---

### Task 11 — Bootstrap skill: patch target `.gitignore`

Extend `skills/bootstrap-dev-leash/SKILL.md` so the rendered project
gets `.harness/sessions/` added to `.gitignore`. Promoted from a
follow-up after the plan-reviewer flagged it as a downstream footgun:
without this, any project bootstrapping post-v1 will start committing
session lockfiles to git.

**Files:**
- Modify: `skills/bootstrap-dev-leash/SKILL.md`
- Create: `tests/test_skill_bootstrap.py`

**Steps:**

1. Write the failing test — `tests/test_skill_bootstrap.py`:

```python
"""Structural assertions for the bootstrap-dev-leash skill markdown."""
from __future__ import annotations

from pathlib import Path


SKILL_PATH = Path("skills/bootstrap-dev-leash/SKILL.md")


def test_skill_file_exists():
    assert SKILL_PATH.exists()


def test_skill_documents_gitignore_patch_for_sessions():
    text = SKILL_PATH.read_text(encoding="utf-8")
    # The skill must explicitly tell Claude to add `.harness/sessions/`
    # to the target project's .gitignore so lockfiles are not committed.
    assert ".harness/sessions/" in text
    assert ".gitignore" in text


def test_skill_explains_why_sessions_are_ignored():
    text = SKILL_PATH.read_text(encoding="utf-8")
    # A one-line justification keeps the directive understandable when
    # someone reads the skill out of context.
    lower = text.lower()
    assert "lockfile" in lower or "session" in lower
```

2. Run the failing test:

```bash
python -m pytest tests/test_skill_bootstrap.py -q
```

Expected: `test_skill_documents_gitignore_patch_for_sessions` FAILS
(skill markdown does not yet mention `.harness/sessions/`).

3. Modify `skills/bootstrap-dev-leash/SKILL.md`. Find the section that
   describes rendering / writing files into the target project (the
   "Step 3 — Render the project-specific files" block and its
   neighbors). After the file-rendering instructions, insert a new
   step:

```markdown
## Step 4 — Patch the target project's `.gitignore`

The session-leash hook (installed via `.claude/settings.json`) writes
per-session lockfiles to `.harness/sessions/<pid>.json`. Those files
record live PIDs and worktree paths and must NEVER be committed.

Read the target project's `.gitignore` (create it if absent). Ensure
both of the following lines are present; add whichever is missing,
keeping the file otherwise byte-identical:

```
.harness/exceptions.log
.harness/sessions/
```

If the file already contains an exact match for either line, do not
duplicate it. If you must add lines, group them under a `# dev-on-leash`
heading-comment that you also add when missing — so the patched lines
are discoverable later.
```

   If the existing skill already had a "Step 4" or later, renumber the
   subsequent steps so the gitignore patch is the new Step 4 and the
   numbering remains sequential.

4. Run tests:

```bash
python -m pytest tests/test_skill_bootstrap.py -q
```

Expected: PASS (3 tests).

5. Commit:

```bash
git add skills/bootstrap-dev-leash/SKILL.md tests/test_skill_bootstrap.py
git commit -m "feat(session-leash): T11 bootstrap patches target .gitignore for lockfiles"
```

- [x] **Task 11 complete**

<!-- task-meta
id: T11
touches:
  - skills/bootstrap-dev-leash/SKILL.md
  - tests/test_skill_bootstrap.py
depends: []
verify: python -m pytest tests/test_skill_bootstrap.py -q
acceptance: null
-->
