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
HEADING_RE = re.compile(r"^#{2,}\s+Task\b.*$", re.MULTILINE)


class SchemaError(ValueError):
    """Raised when a plan file violates the task-meta schema."""


@dataclass(frozen=True)
class TaskMeta:
    id: str
    touches: list[str]
    depends: list[str] = field(default_factory=list)
    verify: str = ""
    acceptance: str | None = None


@dataclass(frozen=True)
class TaskRegion:
    """A `## Task` heading and the (optional) task-meta block bound to it.

    Line indices are 0-based and refer to the fence-stripped plan text, whose
    line count matches the raw text. `meta is None` marks a human-run task.
    """
    heading_line: int
    end_line: int  # exclusive: next heading's line, or EOF
    meta: TaskMeta | None


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


def _line_index(text: str, offset: int) -> int:
    """0-based index of the line containing character `offset`."""
    return text.count("\n", 0, offset)


def parse_regions(plan_path: Path) -> list[TaskRegion]:
    """Split a plan into task regions, each bound to at most one task-meta block.

    A task heading is an H2-or-deeper (`##`+) Markdown heading whose text
    starts with `Task`. A region starts at such a heading and runs to the next
    one (or EOF). Zero task-meta blocks in a region -> a human-run task
    (`meta is None`). Two or more -> SchemaError. A task-meta block outside
    every region -> SchemaError. Fenced example blocks are stripped first, so
    illustrative task-meta inside code fences is never counted.
    """
    raw = plan_path.read_text(encoding="utf-8")
    stripped = _strip_fenced_blocks(raw)
    total_lines = stripped.count("\n") + 1

    heading_lines = [
        _line_index(stripped, m.start()) for m in HEADING_RE.finditer(stripped)
    ]
    bounds = [
        (
            heading_lines[i],
            heading_lines[i + 1] if i + 1 < len(heading_lines) else total_lines,
        )
        for i in range(len(heading_lines))
    ]
    blocks = [
        (_line_index(stripped, m.start()), m.group(1))
        for m in TASK_META_RE.finditer(stripped)
    ]

    regions: list[TaskRegion] = []
    for start, end in bounds:
        inside = [(ln, body) for ln, body in blocks if start <= ln < end]
        if len(inside) > 1:
            raise SchemaError(
                f"{plan_path}: task heading at line {start + 1} has "
                f"{len(inside)} task-meta blocks; expected at most 1"
            )
        meta = _parse_block(inside[0][1], plan_path) if inside else None
        regions.append(TaskRegion(heading_line=start, end_line=end, meta=meta))

    for ln, _ in blocks:
        if not any(s <= ln < e for s, e in bounds):
            raise SchemaError(
                f"{plan_path}: task-meta block at line {ln + 1} is not inside "
                "any '## Task' heading"
            )
    return regions


def parse_plan(plan_path: Path) -> list[TaskMeta]:
    tasks = [r.meta for r in parse_regions(plan_path) if r.meta is not None]

    seen: set[str] = set()
    for t in tasks:
        if t.id in seen:
            raise SchemaError(f"{plan_path}: duplicate id {t.id}")
        seen.add(t.id)

    for t in tasks:
        unknown = [d for d in t.depends if d not in seen]
        if unknown:
            raise SchemaError(
                f"{plan_path}: task {t.id} has unknown depends: {unknown}"
            )

    _detect_cycle(tasks)
    return tasks
