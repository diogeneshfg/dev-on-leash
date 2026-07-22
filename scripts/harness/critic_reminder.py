"""PostToolUse hook: remind the agent to dispatch antagonist critics.

Fires after Edit/Write/MultiEdit/NotebookEdit on a spec/plan markdown
file when the project's .harness/critics.json declares critic models.
Advisory only: it emits hookSpecificOutput.additionalContext and ALWAYS
exits 0 — it informs, it never blocks. .harness/critics.json is the
single source of truth: absent file = feature off; malformed file or an
empty model list = off plus a one-line warning so it gets fixed.

Path matching is component-aware (never substring on the raw string) so
worktree-nested paths (.worktrees/<slug>/docs/plans/x.md) and Windows
backslash paths behave identically. The config is discovered by walking
the written file's ancestors, which resolves to the containing checkout
in linked worktrees without invoking git.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path, PureWindowsPath

WATCHED_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
EXCLUDED_COMPONENTS = frozenset({"node_modules", ".venv", "site-packages", "fixtures"})


def _parts(path: Path) -> tuple[str, ...]:
    """Path components, splitting on both separators regardless of platform."""
    if "\\" in str(path):
        return PureWindowsPath(str(path)).parts
    return path.parts


def is_spec_or_plan(path: Path) -> bool:
    """True for *.md under a docs/plans pair or any specs/ component."""
    parts = _parts(path)
    if not parts or not parts[-1].lower().endswith(".md"):
        return False
    if EXCLUDED_COMPONENTS.intersection(parts):
        return False
    for a, b in zip(parts, parts[1:]):
        if a == "docs" and b == "plans":
            return True
    return "specs" in parts[:-1]


def find_config(start: Path) -> Path | None:
    """Nearest .harness/critics.json within `start`'s own repo.

    Walks the ancestor chain but never past a repo boundary: the first
    ancestor holding a `.git` entry (dir in the main checkout, file in a
    linked worktree) is the last one probed. Without the boundary a stray
    ~/.harness/critics.json would enable critics in every repo below it.
    No .git found at all → treated as no config.
    """
    node = start if start.is_dir() else start.parent
    for ancestor in (node, *node.parents):
        candidate = ancestor / ".harness" / "critics.json"
        if candidate.is_file():
            return candidate
        if (ancestor / ".git").exists():
            return None
    return None


def load_models(config_path: Path) -> tuple[list[str] | None, str | None]:
    """(models, warning). Absent file → (None, None). Bad file → (None, msg)."""
    if not config_path.is_file():
        return None, None
    bad = (
        "ANTAGONIST CRITICS: .harness/critics.json is malformed or lists no "
        "models — antagonist critique is disabled until it is fixed."
    )
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, bad
    models = data.get("models") if isinstance(data, dict) else None
    if (
        isinstance(models, list)
        and models
        and all(isinstance(m, str) and m for m in models)
    ):
        return models, None
    return None, bad


def build_context(target: Path, models: list[str]) -> str:
    names = ", ".join(models)
    return (
        f"ANTAGONIST CRITICS: {target} is a spec/plan document. Before "
        f"presenting it to the user for review, dispatch one antagonist-critic "
        f"subagent per configured model ({names}) in parallel, per the "
        f"AGENTS.md protocol, then resolve what you can and justify the rest. "
        f"One round per presented version — if the critics already ran for "
        f"the version being presented, do not re-dispatch."
    )


def _emit(context: str) -> None:
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": context,
        }
    }))
    sys.stdout.flush()


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    if str(payload.get("tool_name") or "") not in WATCHED_TOOLS:
        return 0
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(raw, str) or not raw:
        return 0
    target = Path(raw)
    if not is_spec_or_plan(target):
        return 0
    try:
        resolved = target.resolve()
    except (OSError, ValueError):
        return 0
    config = find_config(resolved)
    if config is None:
        return 0
    models, warning = load_models(config)
    if warning:
        _emit(warning)
        return 0
    if models:
        _emit(build_context(target, models))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 — a hook crash must never block the write
        raise SystemExit(0)
