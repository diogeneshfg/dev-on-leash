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


def test_violation_reported_once_with_nested_dirs(project):
    """A violation under a nested directory is reported once, not multiple times."""
    _compile(project)
    nested = project / "src" / "a" / "sub" / "deeper"
    nested.mkdir(parents=True)
    (nested / "bad.py").write_text("import requests\n", encoding="utf-8")
    script = project / ".harness" / "checks" / "pattern-no_requests_in_a.py"
    result = subprocess.run(
        [sys.executable, str(script)], cwd=project, capture_output=True, text=True
    )
    assert result.returncode != 0
    # Count how many violation lines mention "bad.py" — must be exactly 1.
    occurrences = result.stdout.count("bad.py")
    assert occurrences == 1, f"violation reported {occurrences} times:\n{result.stdout}"


@pytest.fixture
def py_project(tmp_path):
    proj = tmp_path / "py_proj"
    (proj / ".harness").mkdir(parents=True)
    shutil.copy(FIXTURES / "py.yaml", proj / ".harness" / "architecture.yaml")
    (proj / ".harness" / "gates").write_text("# Gates\n", encoding="utf-8")
    (proj / "pyproject.toml").write_text(
        '[project]\nname="myapp"\nversion="0"\n', encoding="utf-8"
    )
    for layer in ("domain", "application", "infrastructure"):
        (proj / "src" / "myapp" / layer).mkdir(parents=True)
        (proj / "src" / "myapp" / layer / "__init__.py").write_text("", encoding="utf-8")
    return proj


def test_python_adapter_writes_importlinter_ini(py_project):
    _compile(py_project)
    ini = py_project / ".harness" / "importlinter.ini"
    assert ini.exists()
    text = ini.read_text(encoding="utf-8")
    assert "GENERATED" in text
    assert "[importlinter]" in text
    assert "domain" in text and "infrastructure" in text


def test_python_adapter_appends_gate_line(py_project):
    _compile(py_project)
    gates = (py_project / ".harness" / "gates").read_text(encoding="utf-8")
    assert "python -m importlinter" in gates
    assert "# arch-leash:py_edges" in gates


def test_python_adapter_forbids_domain_to_infrastructure(py_project):
    """The implicit forbidden edge `domain -> infrastructure` must appear as a contract."""
    _compile(py_project)
    ini = (py_project / ".harness" / "importlinter.ini").read_text(encoding="utf-8")
    # Each forbidden contract is named by edge: "domain__to__infrastructure"
    assert "domain__to__infrastructure" in ini


def test_python_adapter_skipped_when_no_pyproject(project):
    """The generic fixture has no pyproject.toml; importlinter.ini must NOT be emitted."""
    _compile(project)
    assert not (project / ".harness" / "importlinter.ini").exists()
    gates = (project / ".harness" / "gates").read_text(encoding="utf-8")
    assert "importlinter" not in gates


def test_python_adapter_skips_unresolvable_layer(tmp_path):
    proj = tmp_path / "edge_proj"
    (proj / ".harness").mkdir(parents=True)
    (proj / ".harness" / "architecture.yaml").write_text(
        """version: 1
style: Edge
layers:
  - {name: top, paths: [src/**]}
  - {name: core, paths: [src/core/**]}
allowed_dependencies:
  - {from: top, to: [core]}
patterns: []
review_rules: []
""",
        encoding="utf-8",
    )
    (proj / ".harness" / "gates").write_text("# Gates\n", encoding="utf-8")
    (proj / "pyproject.toml").write_text('[project]\nname="x"\nversion="0"\n', encoding="utf-8")
    (proj / "src" / "core").mkdir(parents=True)

    result = _compile(proj)
    assert result.returncode == 0, result.stderr
    ini = (proj / ".harness" / "importlinter.ini").read_text(encoding="utf-8")
    # The only candidate forbidden pair is core->top, and `top` resolves to ''
    # (empty root). The contract must NOT be emitted with blank modules.
    assert "core__to__top" not in ini
