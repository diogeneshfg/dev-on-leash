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
