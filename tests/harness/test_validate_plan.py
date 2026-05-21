import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE = REPO_ROOT / "scripts" / "harness" / "validate_plan.py"


def run_cli(plan_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATE), str(plan_path)],
        capture_output=True,
        text=True,
    )


def write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "plan.md"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_exits_0_for_valid_plan(tmp_path):
    plan = write(
        tmp_path,
        """
        ### Task 1

        <!-- task-meta
        id: T01
        touches: [a.py]
        depends: []
        verify: "true"
        -->
    """,
    )
    r = run_cli(plan)
    assert r.returncode == 0, r.stderr


def test_exits_1_for_invalid_plan(tmp_path):
    plan = write(
        tmp_path,
        """
        ### Task 1

        <!-- task-meta
        id: BAD
        touches: [a.py]
        depends: []
        verify: "true"
        -->
    """,
    )
    r = run_cli(plan)
    assert r.returncode == 1
    assert "T\\d{2,3}" in r.stderr or "BAD" in r.stderr


def test_warns_when_ui_task_has_no_acceptance(tmp_path, capsys):
    plan = write(
        tmp_path,
        """
        ### Task 1

        <!-- task-meta
        id: T01
        touches: [packages/web/src/presentation/Foo.tsx]
        depends: []
        verify: cd packages/web && npm test
        -->
    """,
    )
    r = run_cli(plan)
    assert r.returncode == 0
    assert "WARN" in r.stderr and "acceptance" in r.stderr
