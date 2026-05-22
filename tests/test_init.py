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
