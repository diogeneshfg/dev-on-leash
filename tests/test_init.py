"""init.{sh,ps1} copy the project-agnostic layer, including the pre-commit hook."""
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _run_init(target: Path) -> subprocess.CompletedProcess:
    if os.name == "nt":
        cmd = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(PLUGIN_ROOT / "scripts" / "init.ps1"), str(target),
        ]
    else:
        cmd = ["sh", str(PLUGIN_ROOT / "scripts" / "init.sh"), str(target)]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_init_copies_precommit_hook(tmp_path):
    r = _run_init(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    hook = tmp_path / ".harness" / "hooks" / "pre-commit"
    assert hook.exists(), "init must copy .harness/hooks/pre-commit"
    assert "recheck_plan.py" in hook.read_text(encoding="utf-8")


def test_init_adds_missing_harness_file_without_clobbering(tmp_path):
    # First run: full copy.
    r1 = _run_init(tmp_path)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    gate = tmp_path / "scripts" / "harness" / "session_gate.py"
    assert gate.exists()
    # Simulate an older install: delete one file, locally modify another.
    reminder = tmp_path / "scripts" / "harness" / "critic_reminder.py"
    reminder.unlink()
    gate.write_text("# locally modified\n", encoding="utf-8")
    # Second run: restores the missing file, preserves the modified one.
    r2 = _run_init(tmp_path)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert reminder.exists(), "re-init must add missing harness files"
    assert gate.read_text(encoding="utf-8") == "# locally modified\n", \
        "re-init must never overwrite an existing harness file"


def test_init_copies_critic_reminder(tmp_path):
    r = _run_init(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "scripts" / "harness" / "critic_reminder.py").exists()


def test_init_never_copies_bytecode(tmp_path):
    r = _run_init(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    harness = tmp_path / "scripts" / "harness"
    assert not (harness / "__pycache__").exists()
    assert not list(harness.glob("*.pyc"))
