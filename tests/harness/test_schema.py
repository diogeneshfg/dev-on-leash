import textwrap
from pathlib import Path

import pytest

from scripts.harness.schema import SchemaError, TaskMeta, parse_plan

pytestmark = pytest.mark.unit


def write_plan(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "plan.md"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_parses_single_task(tmp_path):
    plan = write_plan(
        tmp_path,
        """
        ### Task 1 — Example

        <!-- task-meta
        id: T01
        touches: [foo.py]
        depends: []
        verify: pytest tests/test_foo.py
        acceptance: null
        -->
    """,
    )
    tasks = parse_plan(plan)
    assert len(tasks) == 1
    assert tasks[0] == TaskMeta(
        id="T01",
        touches=["foo.py"],
        depends=[],
        verify="pytest tests/test_foo.py",
        acceptance=None,
    )


def test_rejects_task_without_meta(tmp_path):
    plan = write_plan(
        tmp_path,
        """
        ### Task 1 — Bare

        (no task-meta block here)
    """,
    )
    with pytest.raises(SchemaError, match="missing task-meta"):
        parse_plan(plan)


def test_rejects_duplicate_ids(tmp_path):
    plan = write_plan(
        tmp_path,
        """
        ### Task 1

        <!-- task-meta
        id: T01
        touches: [a]
        depends: []
        verify: "true"
        -->

        ### Task 2

        <!-- task-meta
        id: T01
        touches: [b]
        depends: []
        verify: "true"
        -->
    """,
    )
    with pytest.raises(SchemaError, match="duplicate id"):
        parse_plan(plan)


def test_rejects_unknown_depends(tmp_path):
    plan = write_plan(
        tmp_path,
        """
        ### Task 1

        <!-- task-meta
        id: T01
        touches: [a]
        depends: [T99]
        verify: "true"
        -->
    """,
    )
    with pytest.raises(SchemaError, match="unknown depends.*T99"):
        parse_plan(plan)


def test_rejects_dependency_cycle(tmp_path):
    plan = write_plan(
        tmp_path,
        """
        ### A

        <!-- task-meta
        id: T01
        touches: [a]
        depends: [T02]
        verify: "true"
        -->

        ### B

        <!-- task-meta
        id: T02
        touches: [b]
        depends: [T01]
        verify: "true"
        -->
    """,
    )
    with pytest.raises(SchemaError, match="cycle"):
        parse_plan(plan)


def test_rejects_empty_touches(tmp_path):
    plan = write_plan(
        tmp_path,
        """
        ### Task 1

        <!-- task-meta
        id: T01
        touches: []
        depends: []
        verify: "true"
        -->
    """,
    )
    with pytest.raises(SchemaError, match="touches.*empty"):
        parse_plan(plan)


def test_ignores_task_meta_inside_fenced_code_blocks(tmp_path):
    # A plan that documents the schema by showing an example task-meta block
    # INSIDE a fenced code block must not have that example counted as a real task.
    plan = write_plan(
        tmp_path,
        """
        ### Task 1 — Real

        Here is an example of the schema:

        ```html
        <!-- task-meta
        id: T99
        touches: [example.py]
        depends: []
        verify: "true"
        -->
        ```

        And the real meta:

        <!-- task-meta
        id: T01
        touches: [real.py]
        depends: []
        verify: "true"
        -->
    """,
    )
    tasks = parse_plan(plan)
    assert [t.id for t in tasks] == ["T01"]


def test_strips_gfm_4backtick_outer_with_3backtick_inner(tmp_path):
    # Realistic case: schema-reference task wraps a markdown example in a 4-backtick
    # outer fence, with 3-backtick inner fences. The outer fence must not be closed
    # by an inner 3-backtick close line.
    plan_text = (
        "### Task 1 — Doc\n\n"
        "````markdown\n"
        "# example\n"
        "```html\n"
        '<!-- task-meta\nid: T77\ntouches: [x]\ndepends: []\nverify: "true"\n-->\n'
        "```\n"
        "more text\n"
        "````\n\n"
        '<!-- task-meta\nid: T01\ntouches: [real.py]\ndepends: []\nverify: "true"\n-->\n'
    )
    plan_path = tmp_path / "plan.md"
    plan_path.write_text(plan_text, encoding="utf-8")
    tasks = parse_plan(plan_path)
    assert [t.id for t in tasks] == ["T01"]
