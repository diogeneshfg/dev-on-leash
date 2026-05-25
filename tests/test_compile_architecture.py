"""Compiler tests — generic adapter, idempotency, gate tagging."""
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "architecture"


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".harness").mkdir(parents=True)
    shutil.copy(FIXTURES / "min.yaml", proj / ".harness" / "architecture.yaml")
    (proj / ".harness" / "gates").write_text("# Gates\n", encoding="utf-8")
    (proj / "src" / "a").mkdir(parents=True)
    (proj / "src" / "b").mkdir(parents=True)
    return proj


def _compile(proj):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "harness" / "compile_architecture.py")],
        cwd=proj,
        capture_output=True,
        text=True,
    )


def test_compile_emits_grep_script_and_gate(project):
    result = _compile(project)
    assert result.returncode == 0, result.stderr
    check = project / ".harness" / "checks" / "pattern-no_requests_in_a.py"
    assert check.exists()
    text = check.read_text(encoding="utf-8")
    assert "GENERATED" in text
    assert "requests" in text
    gates = (project / ".harness" / "gates").read_text(encoding="utf-8")
    assert "# arch-leash:no_requests_in_a" in gates
    assert "pattern-no_requests_in_a.py" in gates
    # Cross-platform: the gate line must invoke python, not sh/pwsh.
    assert "python" in gates


def test_check_script_runs_clean_on_no_violation(project):
    _compile(project)
    script = project / ".harness" / "checks" / "pattern-no_requests_in_a.py"
    result = subprocess.run(
        [sys.executable, str(script)], cwd=project, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_script_fails_on_violation(project):
    _compile(project)
    (project / "src" / "a" / "bad.py").write_text("import requests\n", encoding="utf-8")
    script = project / ".harness" / "checks" / "pattern-no_requests_in_a.py"
    result = subprocess.run(
        [sys.executable, str(script)], cwd=project, capture_output=True, text=True
    )
    assert result.returncode != 0, "check should reject forbidden import"


def test_compile_is_idempotent(project):
    _compile(project)
    gates_first = (project / ".harness" / "gates").read_text(encoding="utf-8")
    _compile(project)
    gates_second = (project / ".harness" / "gates").read_text(encoding="utf-8")
    assert gates_first == gates_second


def test_removing_rule_prunes_gate(project):
    _compile(project)
    arch = project / ".harness" / "architecture.yaml"
    arch.write_text(
        arch.read_text(encoding="utf-8").replace(
            "- {id: no_requests_in_a, layer: a, forbidden_imports: [requests]}",
            "",
        ),
        encoding="utf-8",
    )
    _compile(project)
    gates = (project / ".harness" / "gates").read_text(encoding="utf-8")
    assert "no_requests_in_a" not in gates
