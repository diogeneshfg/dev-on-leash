import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
RECHECK = REPO_ROOT / "scripts" / "harness" / "recheck_plan.py"

PASS_CMD = 'python -c "pass"'
FAIL_CMD = 'python -c "raise SystemExit(1)"'


def _plan(tmp_path: Path, checkbox: str, verify_cmd: str) -> Path:
    p = tmp_path / "plan.md"
    p.write_text(
        textwrap.dedent(
            f"""
        ### Task 1

        - [{checkbox}] **Task 1 complete**

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


def _run(plan: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RECHECK), str(plan)],
        capture_output=True,
        text=True,
    )


def test_ticked_task_that_reverifies_passes(tmp_path):
    r = _run(_plan(tmp_path, "x", PASS_CMD))
    assert r.returncode == 0, r.stderr


def test_ticked_task_that_fails_reverify_is_rejected(tmp_path):
    # A checkbox flipped to [x] without the work done: verify fails -> reject.
    r = _run(_plan(tmp_path, "x", FAIL_CMD))
    assert r.returncode == 1, r.stderr
    assert "T01" in r.stderr


def test_unticked_task_is_not_reverified(tmp_path):
    # An unticked task must NOT be re-verified, even if its verify would fail.
    r = _run(_plan(tmp_path, " ", FAIL_CMD))
    assert r.returncode == 0, r.stderr


def test_ticked_checkbox_inside_fenced_block_is_ignored(tmp_path):
    # A `- [x]` inside a fenced code block must NOT count as a ticked task.
    # _strip_fenced_blocks blanks the fenced line, so the only real status
    # checkbox is the out-of-fence `- [ ]` (unticked). The failing verify must
    # therefore never run, and recheck_plan.py must exit 0.
    plan = tmp_path / "plan.md"
    plan.write_text(
        textwrap.dedent(
            f"""
        ### Task 1

        ```markdown
        Example of a completed step:
        - [x] **Step inside fence (must not count as ticked)**
        ```

        - [ ] **Task 1 complete**

        <!-- task-meta
        id: T01
        touches: [foo.py]
        depends: []
        verify: '{FAIL_CMD}'
        -->
    """
        ),
        encoding="utf-8",
    )
    r = _run(plan)
    assert r.returncode == 0, r.stderr


def test_missing_plan_file_is_usage_error(tmp_path):
    r = _run(tmp_path / "nope.md")
    assert r.returncode == 2
