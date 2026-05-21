import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEDULE = REPO_ROOT / "scripts" / "harness" / "plan_schedule.py"


def run_cli(plan_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCHEDULE), str(plan_path)],
        capture_output=True,
        text=True,
    )


def write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "plan.md"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_layers_printed_for_a_diamond_dag(tmp_path):
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
        ### Task 2
        <!-- task-meta
        id: T02
        touches: [b.py]
        depends: [T01]
        verify: "true"
        -->
        ### Task 3
        <!-- task-meta
        id: T03
        touches: [c.py]
        depends: [T01]
        verify: "true"
        -->
        ### Task 4
        <!-- task-meta
        id: T04
        touches: [d.py]
        depends: [T02, T03]
        verify: "true"
        -->
    """,
    )
    r = run_cli(plan)
    assert r.returncode == 0, r.stderr
    assert "Layer 0: T01" in r.stdout
    assert "Layer 1 (parallel): T02, T03" in r.stdout
    assert "Layer 2: T04" in r.stdout


def test_exit_1_on_same_layer_touches_collision(tmp_path):
    plan = write(
        tmp_path,
        """
        ### Task 1
        <!-- task-meta
        id: T01
        touches: [shared.py]
        depends: []
        verify: "true"
        -->
        ### Task 2
        <!-- task-meta
        id: T02
        touches: [shared.py]
        depends: []
        verify: "true"
        -->
    """,
    )
    r = run_cli(plan)
    assert r.returncode == 1
    assert "COLLISION" in r.stderr and "shared.py" in r.stderr


def test_exit_2_when_plan_missing(tmp_path):
    r = run_cli(tmp_path / "nope.md")
    assert r.returncode == 2


def test_exit_1_on_dependency_cycle(tmp_path):
    plan = write(
        tmp_path,
        """
        ### Task 1
        <!-- task-meta
        id: T01
        touches: [a.py]
        depends: [T02]
        verify: "true"
        -->
        ### Task 2
        <!-- task-meta
        id: T02
        touches: [b.py]
        depends: [T01]
        verify: "true"
        -->
    """,
    )
    r = run_cli(plan)
    assert r.returncode == 1
    assert "cycle" in r.stderr.lower()


def test_exit_1_on_unknown_dependency(tmp_path):
    plan = write(
        tmp_path,
        """
        ### Task 1
        <!-- task-meta
        id: T01
        touches: [a.py]
        depends: [T99]
        verify: "true"
        -->
    """,
    )
    r = run_cli(plan)
    assert r.returncode == 1
    assert "T99" in r.stderr
