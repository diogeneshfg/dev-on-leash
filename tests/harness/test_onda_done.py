import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
ONDA_DONE = REPO_ROOT / "scripts" / "harness" / "onda_done.py"


def write_plan(tmp_path: Path, all_done: bool) -> Path:
    p = tmp_path / "plan.md"
    box = "x" if all_done else " "
    p.write_text(
        textwrap.dedent(f"""
        ### Task 1

        - [{box}] **Step 1: do**

        <!-- task-meta
        id: T01
        touches: [a]
        depends: []
        verify: "true"
        -->
    """),
        encoding="utf-8",
    )
    return p


def test_exit_1_when_pending_tasks(tmp_path):
    plan = write_plan(tmp_path, all_done=False)
    r = subprocess.run(
        [sys.executable, str(ONDA_DONE), "--plan", str(plan), "--skip-suite"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1
    assert "pending" in r.stderr.lower()


def test_exit_0_when_all_clear(tmp_path):
    plan = write_plan(tmp_path, all_done=True)
    env = {
        **__import__("os").environ,
        "HARNESS_CHANGELOG_PATH": str(tmp_path / "CHANGELOG.md"),
    }
    r = subprocess.run(
        [sys.executable, str(ONDA_DONE), "--plan", str(plan), "--skip-suite"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0


def test_changelog_appended_on_green_close(tmp_path):
    plan = write_plan(tmp_path, all_done=True)
    changelog = tmp_path / "CHANGELOG.md"
    env = {
        **__import__("os").environ,
        "HARNESS_CHANGELOG_PATH": str(changelog),
    }
    r = subprocess.run(
        [sys.executable, str(ONDA_DONE), "--plan", str(plan), "--skip-suite"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert changelog.exists()
    text = changelog.read_text(encoding="utf-8")
    assert "Onda closed" in text
    assert plan.stem in text


def test_changelog_append_is_idempotent(tmp_path):
    plan = write_plan(tmp_path, all_done=True)
    changelog = tmp_path / "CHANGELOG.md"
    env = {
        **__import__("os").environ,
        "HARNESS_CHANGELOG_PATH": str(changelog),
    }
    cmd = [sys.executable, str(ONDA_DONE), "--plan", str(plan), "--skip-suite"]
    subprocess.run(cmd, env=env, capture_output=True, text=True)
    subprocess.run(cmd, env=env, capture_output=True, text=True)
    text = changelog.read_text(encoding="utf-8")
    assert text.count(f"— {plan.stem}") == 1


def test_force_logs_exception(tmp_path):
    plan = write_plan(tmp_path, all_done=False)
    audit = tmp_path / "exceptions.log"
    env = {**__import__("os").environ, "HARNESS_EXCEPTIONS_PATH": str(audit)}
    r = subprocess.run(
        [
            sys.executable,
            str(ONDA_DONE),
            "--plan",
            str(plan),
            "--skip-suite",
            "--force",
            "-m",
            "deferred per discussion",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "deferred per discussion" in audit.read_text()
