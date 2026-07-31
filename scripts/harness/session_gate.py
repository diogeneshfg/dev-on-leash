"""PreToolUse hook: judge a write by its TARGET file's repo and mode.

Stateless and git-based. The gate resolves the repo that owns the write
target (not the session cwd), then applies that repo's own workflow
mode from `.harness/branches.yaml`:

- worktree mode: the main worktree is read-only; write from a linked
  worktree (created by /leash-start-work) instead.
- branch mode: writes are only allowed while HEAD is on a conforming
  <type>/<slug> work branch.

Scope: only leash-managed repos (main worktree contains a `.harness/`
directory) are gated at all; every other repo — a cloned dependency, a
sibling project without the harness — is left completely untouched,
never mutated. A one-shot marker (.harness/allow-main-write) in the
TARGET repo authorizes exactly one write there and is consumed + logged
to that repo's .harness/exceptions.log.

Malformed `.harness/branches.yaml` fails CLOSED (denied, with the
parse error as the reason) — a broken config must not silently disable
the gate. Only when git itself is unusable does the gate fail open,
and that is audited to the project dir's exceptions.log.

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

from scripts.harness.branches import (
    BranchConfigError,
    WORK_BRANCH_RE,
    load_branch_config,
)
from scripts.harness.repo_resolve import RepoResolveError, resolve_repo

GATED_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

MARKER_NAME = "allow-main-write"
EXCEPTIONS_LOG = "exceptions.log"

DENY_MESSAGE_WORKTREE = (
    "SESSION LEASH: this repo's main worktree is read-only. Start your "
    "change in a worktree with /leash-start-work (pass --repo-root for "
    "this repo), then write there. To make a one-off write to the main "
    "tree, run:\n"
    '  python -m scripts.harness.allow_main_write "<reason>" '
    "--repo-root <this repo>\n"
    "and retry — it authorizes exactly one main-tree write and is logged."
)


def deny_message_branch(head: str | None) -> str:
    where = f"HEAD is on {head!r}" if head else "HEAD is detached/unborn"
    return (
        f"SESSION LEASH (branch mode): {where}, not on a <type>/<slug> "
        "work branch. Start your change with /leash-start-work "
        "(pass --repo-root for this repo), then retry. For a one-off "
        "write here, run:\n"
        '  python -m scripts.harness.allow_main_write "<reason>" '
        "--repo-root <this repo>\n"
        "and retry — it authorizes exactly one write and is logged."
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


def _append_log(log_path: Path, *, kind: str, gate_pid: int, target: Path | None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{_now_iso()}  {kind}  pid={gate_pid}  target={target}\n"
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def _head_branch(repo_root: Path) -> str | None:
    """Current branch name; None on detached or unborn HEAD."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse",
             "--abbrev-ref", "HEAD"],
            capture_output=True, text=True,
        )
    except (OSError, ValueError):
        return None
    name = proc.stdout.strip()
    if proc.returncode != 0 or not name or name == "HEAD":
        return None
    return name


def _consume_marker(repo_root: Path, target: Path, gate_pid: int) -> bool:
    marker = repo_root / ".harness" / MARKER_NAME
    if not marker.exists():
        return False
    try:
        marker.unlink()
    except FileNotFoundError:
        pass
    _append_log(repo_root / ".harness" / EXCEPTIONS_LOG,
                kind="main-write", gate_pid=gate_pid, target=target)
    return True


def _failopen_log(target: Path | None, gate_pid: int) -> None:
    base = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    try:
        _append_log(base / ".harness" / EXCEPTIONS_LOG,
                    kind="gate-failopen", gate_pid=gate_pid, target=target)
    except OSError:
        pass


def decide(*, tool_name: str, tool_input: dict, gate_pid: int = 0) -> Decision:
    """Judge a write by the TARGET file's repo and that repo's mode.

    Scope: only leash-managed repos (main worktree has .harness/) are
    gated; every other repo behaves exactly as before this gate existed.
    """
    if tool_name not in GATED_TOOLS:
        return Decision(allow=True, reason="")
    target = _resolve_target(tool_input)
    if target is None:
        return Decision(allow=True, reason="")
    try:
        info = resolve_repo(target)
    except RepoResolveError:
        _failopen_log(target, gate_pid)          # git unusable: fail open, audited
        return Decision(allow=True, reason="")
    if info is None:
        return Decision(allow=True, reason="")   # outside any repo
    if info.is_linked:
        return Decision(allow=True, reason="")   # linked worktree: both modes
    main_wt = info.main_worktree
    if not (main_wt / ".harness").is_dir():
        return Decision(allow=True, reason="")   # not leash-managed: untouched
    try:
        cfg = load_branch_config(main_wt)
    except BranchConfigError as exc:
        # Fail CLOSED: one broken YAML must not silently disable the gate.
        return Decision(allow=False, reason=(
            f"SESSION LEASH: cannot judge this write — {exc}. "
            "Fix .harness/branches.yaml and retry."
        ))
    if cfg.workflow == "branch":
        head = _head_branch(main_wt)
        if head is not None and WORK_BRANCH_RE.match(head):
            return Decision(allow=True, reason="")
        if _consume_marker(main_wt, target, gate_pid):
            return Decision(allow=True, reason="one-shot write authorized")
        return Decision(allow=False, reason=deny_message_branch(head))
    # worktree mode: the main tree is read-only
    if _consume_marker(main_wt, target, gate_pid):
        return Decision(allow=True, reason="one-shot main-tree write authorized")
    return Decision(allow=False, reason=DENY_MESSAGE_WORKTREE)


def main(argv: list[str]) -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    d = decide(tool_name=tool_name, tool_input=tool_input, gate_pid=os.getppid())
    sys.stdout.write(d.to_json())
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
