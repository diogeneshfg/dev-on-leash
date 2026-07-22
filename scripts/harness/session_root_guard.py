"""SessionStart hook: warn when a session is rooted inside a linked worktree.

Claude Code keys session history to the directory the session is rooted
in. `.worktrees/<slug>` is disposable — `/leash-finish-work` removes it —
so a session rooted there loses its history the moment the worktree goes
away (observed in the field: orphaned `<project>--worktrees-<slug>`
entries under `~/.claude/projects`).

The leash never requires moving the session: the write gate
(`session_gate.py`) resolves targets absolutely and allows writes into
any linked worktree from any cwd. Sessions therefore stay rooted in the
main checkout; this guard catches the ones that did not.

Stateless and git-based, like the write gate. Silent on the happy path;
prints a warning (SessionStart stdout becomes session context) when the
session cwd resolves inside a linked worktree. Always exits 0.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from scripts.harness.session_gate import list_worktrees

WARNING_TEMPLATE = (
    "SESSION LEASH WARNING: this session is rooted inside the linked "
    "worktree {linked} — a disposable directory. Claude Code keys session "
    "history to the session's root, so this session's history will be "
    "LOST when /leash-finish-work removes the worktree. Start sessions "
    "from the main checkout instead: {main}. The worktree leash allows "
    "edits inside .worktrees/<slug> from there — the session never needs "
    "to move."
)


def classify(*, cwd: Path, worktrees: list[Path] | None) -> str | None:
    """Warning message if `cwd` is inside a linked worktree, else None.

    Component-aware containment (Path.is_relative_to), longest match wins
    so a linked worktree nested inside the main tree is matched over main.
    """
    if not worktrees:
        return None
    try:
        cwd = cwd.resolve()
    except (OSError, ValueError):
        return None
    main_wt = worktrees[0]
    best: Path | None = None
    best_len = -1
    for wt in worktrees:
        if cwd == wt or cwd.is_relative_to(wt):
            if len(wt.parts) > best_len:
                best = wt
                best_len = len(wt.parts)
    if best is None or best == main_wt:
        return None
    return WARNING_TEMPLATE.format(linked=best, main=main_wt)


def parse_payload(text: str) -> dict:
    """Parse hook stdin: dict on success, {} on anything else.

    Tolerates a leading BOM — Windows shells piping into the hook can
    prepend one, and a BOM must degrade to the fail-silent path, not a
    crash."""
    try:
        payload = json.loads(text.lstrip("﻿") or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def main(argv: list[str]) -> int:
    payload = parse_payload(sys.stdin.read())
    raw_cwd = payload.get("cwd")
    cwd = Path(raw_cwd) if isinstance(raw_cwd, str) and raw_cwd else Path(os.getcwd())
    msg = classify(cwd=cwd, worktrees=list_worktrees(cwd))
    if msg:
        sys.stdout.write(msg)
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
