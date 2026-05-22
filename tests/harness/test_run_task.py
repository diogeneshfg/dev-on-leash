import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_TASK = REPO_ROOT / "scripts" / "harness" / "run_task.py"

SUCCESS_CMD = 'python -c "pass"'
FAILURE_CMD = 'python -c "raise SystemExit(1)"'


def write_plan(tmp_path: Path, verify_cmd: str) -> Path:
    p = tmp_path / "plan.md"
    p.write_text(
        textwrap.dedent(
            f"""
        ### Task 1

        - [ ] **Step 1: do the thing**

        <!-- task-meta
        id: T01
        touches: [foo.py]
        depends: []
        verify: '{verify_cmd}'
        -->
    """
        ),
        encoding="utf-8",
    )
    return p


def test_verify_success_ticks_checkbox(tmp_path):
    plan = write_plan(tmp_path, SUCCESS_CMD)
    r = subprocess.run(
        [sys.executable, str(RUN_TASK), str(plan), "T01"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    text = plan.read_text()
    assert "- [x]" in text


def test_verify_failure_keeps_checkbox_unticked(tmp_path):
    plan = write_plan(tmp_path, FAILURE_CMD)
    r = subprocess.run(
        [sys.executable, str(RUN_TASK), str(plan), "T01"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1
    assert "- [ ]" in plan.read_text()
    assert "- [x]" not in plan.read_text()


def test_unknown_task_id_errors(tmp_path):
    plan = write_plan(tmp_path, SUCCESS_CMD)
    r = subprocess.run(
        [sys.executable, str(RUN_TASK), str(plan), "T99"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2
    assert "T99" in r.stderr


def test_ticks_correct_checkbox_in_plan_with_fenced_code_blocks(tmp_path):
    # Regression: _strip_fenced_blocks blanks fenced lines to "", which shifts
    # character offsets. _tick_checkbox_in_region must work on line indices instead.
    plan = tmp_path / "plan.md"
    plan.write_text(
        textwrap.dedent("""
        ### Task 1

        ```python
        # a large fenced block that shifts character offsets downstream
        def f():
            return "lots of text here to desync offsets"
        ```

        - [ ] **Task 1 complete**

        <!-- task-meta
        id: T01
        touches: [a.py]
        depends: []
        verify: python -c "pass"
        -->

        ### Task 2

        ```python
        x = 1
        ```

        - [ ] **Task 2 complete**

        <!-- task-meta
        id: T02
        touches: [b.py]
        depends: []
        verify: python -c "pass"
        -->
    """),
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(RUN_TASK), str(plan), "T02"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    text = plan.read_text(encoding="utf-8")
    assert "- [x] **Task 2 complete**" in text
    assert "- [ ] **Task 1 complete**" in text


def test_id_substring_in_prose_does_not_misroute(tmp_path):
    # Regression: task lookup must use the parsed task-meta id, not a substring
    # scan. Prose mentioning another task's id must not misroute the tick.
    plan = tmp_path / "plan.md"
    plan.write_text(
        textwrap.dedent('''
        ### Task 1

        This task is unrelated to id: T02 mentioned here in prose.

        - [ ] **Task 1 complete**

        <!-- task-meta
        id: T01
        touches: [a.py]
        depends: []
        verify: python -c "pass"
        -->

        ### Task 2

        - [ ] **Task 2 complete**

        <!-- task-meta
        id: T02
        touches: [b.py]
        depends: []
        verify: python -c "pass"
        -->
    '''),
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(RUN_TASK), str(plan), "T01"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    text = plan.read_text(encoding="utf-8")
    assert "- [x] **Task 1 complete**" in text
    assert "- [ ] **Task 2 complete**" in text


def test_does_not_tick_checkbox_inside_fenced_block(tmp_path):
    # A `- [ ]` inside a fenced code block within a task body must never be
    # flipped — only the real checkbox (which survives _strip_fenced_blocks).
    plan = tmp_path / "plan.md"
    plan.write_text(
        textwrap.dedent("""
        ### Task 1

        ```markdown
        Example plan line:
        - [ ] **Step inside fence (must not be ticked)**
        ```

        - [ ] **Real step**

        <!-- task-meta
        id: T01
        touches: [a.py]
        depends: []
        verify: python -c "pass"
        -->
    """),
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(RUN_TASK), str(plan), "T01"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    text = plan.read_text(encoding="utf-8")
    assert "- [x] **Real step**" in text
    assert "- [ ] **Step inside fence (must not be ticked)**" in text
