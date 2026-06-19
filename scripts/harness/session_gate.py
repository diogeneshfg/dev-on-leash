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
