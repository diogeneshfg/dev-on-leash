"""Authorize exactly one write to a target repository.

Writes .harness/allow-main-write. The PreToolUse gate
(scripts.harness.session_gate) consumes it on the next main-tree write
and appends an audit line to .harness/exceptions.log.

Supports multi-root workspaces via --repo-root. When not passed and
the workspace contains multiple repos, raises RepoResolveError listing
candidates.

Run via Bash (not gated) when you need a one-off direct edit to the main
tree instead of working in a worktree:

    python -m scripts.harness.allow_main_write "fix changelog typo"
    python -m scripts.harness.allow_main_write "typo" --repo-root /path/to/repo
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
    import argparse

    from scripts.harness.branches import BranchConfigError, load_branch_config
    from scripts.harness.repo_resolve import (
        RepoResolveError,
        echo_context,
        resolve_cli_repo_root,
    )

    p = argparse.ArgumentParser()
    p.add_argument("reason", nargs="*", default=[])
    p.add_argument("--repo-root", type=Path, default=None)
    args = p.parse_args(argv[1:])
    reason = " ".join(args.reason).strip() or "(no reason given)"
    try:
        root = resolve_cli_repo_root(args.repo_root)
        cfg = load_branch_config(root)
    except (RepoResolveError, BranchConfigError) as exc:
        sys.stderr.write(f"allow-main-write: {exc}\n")
        return 1
    print(echo_context(root, cfg, cfg.base))
    marker = write_marker(harness_dir=root / ".harness", reason=reason)
    print(f"Authorized ONE write in {root} (reason: {reason}).")
    print(f"Marker: {marker}")
    print("It is consumed by the next gated write in that repo and logged "
          "to .harness/exceptions.log. Retry your edit now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
