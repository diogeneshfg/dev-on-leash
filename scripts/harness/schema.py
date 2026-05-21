"""Task-meta schema: dataclass + plan parser + validation errors."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

TASK_META_RE = re.compile(r"<!--\s*task-meta\s*\n(.*?)\n-->", re.DOTALL)
TASK_ID_RE = re.compile(r"^T\d{2,3}$")
# Fenced code blocks hold illustrative task-meta examples (in the schema reference doc
# and plan template) that must NOT be counted as real tasks. We respect the GFM rule:
# a fence of N backticks closes only when a line of >= N backticks appears at col 0.
FENCE_OPEN_RE = re.compile(r"^(`{3,})")
FENCE_CLOSE_RE = re.compile(r"^(`{3,})\s*$")


class SchemaError(ValueError):
    """Raised when a plan file violates the task-meta schema."""


@dataclass(frozen=True)
class TaskMeta:
    id: str
    touches: list[str]
    depends: list[str] = field(default_factory=list)
    verify: str = ""
    acceptance: str | None = None


def _parse_block(body: str, plan_path: Path) -> TaskMeta:
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError as e:
        raise SchemaError(f"{plan_path}: invalid YAML in task-meta: {e}") from e
    if not isinstance(data, dict):
        raise SchemaError(f"{plan_path}: task-meta must be a mapping, got {type(data).__name__}")

    required = {"id", "touches", "depends", "verify"}
    missing = required - data.keys()
    if missing:
        raise SchemaError(f"{plan_path}: task-meta missing required fields: {sorted(missing)}")

    tid = data["id"]
    if not isinstance(tid, str) or not TASK_ID_RE.match(tid):
        raise SchemaError(f"{plan_path}: task id {tid!r} must match T\\d{{2,3}}")

    touches = data["touches"]
    if not isinstance(touches, list) or not touches:
        raise SchemaError(f"{plan_path}: task {tid} touches must be a non-empty list")
    if not all(isinstance(t, str) for t in touches):
        raise SchemaError(f"{plan_path}: task {tid} touches must be all strings")

    depends = data["depends"]
    if not isinstance(depends, list) or not all(isinstance(d, str) for d in depends):
        raise SchemaError(f"{plan_path}: task {tid} depends must be a list of strings")

    verify = data["verify"]
    if not isinstance(verify, str) or not verify.strip():
        raise SchemaError(f"{plan_path}: task {tid} verify must be a non-empty string")

    acceptance = data.get("acceptance")
    if acceptance is not None and not isinstance(acceptance, str):
        raise SchemaError(f"{plan_path}: task {tid} acceptance must be string or null")

    return TaskMeta(id=tid, touches=touches, depends=depends, verify=verify, acceptance=acceptance)


def _detect_cycle(tasks: list[TaskMeta]) -> None:
    by_id = {t.id: t for t in tasks}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {t.id: WHITE for t in tasks}

    def visit(tid: str) -> None:
        if color[tid] == GRAY:
            raise SchemaError(f"dependency cycle detected at {tid}")
        if color[tid] == BLACK:
            return
        color[tid] = GRAY
        for dep in by_id[tid].depends:
            visit(dep)
        color[tid] = BLACK

    for t in tasks:
        visit(t.id)


def _strip_fenced_blocks(text: str) -> str:
    """Replace fenced code blocks with blank lines (preserves line numbers).

    A fence opens with a run of N (>=3) backticks at column 0. It closes at the
    next line whose leading backtick run length is >= N. Same-line blank replacement
    keeps later diagnostics ("line 78") accurate.
    """
    lines = text.split("\n")
    out = list(lines)
    i = 0
    while i < len(lines):
        m = FENCE_OPEN_RE.match(lines[i])
        if not m:
            i += 1
            continue
        fence_len = len(m.group(1))
        j = i + 1
        while j < len(lines):
            cm = FENCE_CLOSE_RE.match(lines[j])
            if cm and len(cm.group(1)) >= fence_len:
                break
            j += 1
        for k in range(i, min(j + 1, len(lines))):
            out[k] = ""
        i = j + 1
    return "\n".join(out)


def parse_plan(plan_path: Path) -> list[TaskMeta]:
    raw = plan_path.read_text(encoding="utf-8")
    text = _strip_fenced_blocks(raw)

    headings = re.findall(r"^###\s+Task\b.*$", text, re.MULTILINE)
    blocks = TASK_META_RE.findall(text)
    if len(blocks) < len(headings):
        raise SchemaError(f"{plan_path}: {len(headings)} task headings but only {len(blocks)} task-meta blocks — missing task-meta")

    tasks = [_parse_block(b, plan_path) for b in blocks]

    seen: set[str] = set()
    for t in tasks:
        if t.id in seen:
            raise SchemaError(f"{plan_path}: duplicate id {t.id}")
        seen.add(t.id)

    for t in tasks:
        unknown = [d for d in t.depends if d not in seen]
        if unknown:
            raise SchemaError(f"{plan_path}: task {t.id} has unknown depends: {unknown}")

    _detect_cycle(tasks)
    return tasks
