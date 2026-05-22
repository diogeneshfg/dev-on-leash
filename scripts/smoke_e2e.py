#!/usr/bin/env python3
"""End-to-end smoke test for the dev-on-leash harness.

Builds a throwaway repo, installs the project-agnostic layer via
init.{sh,ps1}, and drives a tiny 2-task plan through the whole loop:

    init -> validate_plan -> plan_schedule
         -> run_task (red: no impl, verify fails, checkbox stays unticked)
         -> run_task (green: impl present, verify passes, checkbox ticked)
         -> cycle_done (no pending tasks, CHANGELOG appended)
         -> recheck_plan (every ticked task re-verifies; a hand-ticked
            but-undone task is rejected)

Every step is asserted. Prints a step report and exits 0 on SMOKE PASS,
1 on the first failure. The temp repo is removed on success; pass --keep
(or let it fail) to preserve it for inspection.

Usage:
    python scripts/smoke_e2e.py [--keep]
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]

# --- canned fixture content ------------------------------------------------

PYPROJECT = """\
[tool.pytest.ini_options]
pythonpath = ["."]
"""

TEST_CALC = '''\
def test_add():
    from calc import add
    assert add(2, 3) == 5


def test_mul():
    from calc import mul
    assert mul(2, 3) == 6
'''

CALC_ADD = '''\
def add(a, b):
    return a + b
'''

CALC_ADD_MUL = CALC_ADD + '''

def mul(a, b):
    return a * b
'''

SMOKE_PLAN = """\
# Smoke Test Plan

Minimal plan driven by scripts/smoke_e2e.py.

## Task 1: add()

- [ ] **Task 1 complete**

<!-- task-meta
id: T01
touches:
  - calc.py
  - tests/test_calc.py
depends: []
verify: python -m pytest tests/test_calc.py::test_add -q
acceptance: null
-->

## Task 2: mul()

- [ ] **Task 2 complete**

<!-- task-meta
id: T02
touches:
  - calc.py
depends: [T01]
verify: python -m pytest tests/test_calc.py::test_mul -q
acceptance: null
-->
"""


def _run(cmd: list[str], cwd: str | None = None) -> tuple[int, str]:
    """Run a command; return (returncode, combined stdout+stderr)."""
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, errors="replace"
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main(argv: list[str]) -> int:
    keep = "--keep" in argv[1:]
    repo = Path(tempfile.mkdtemp(prefix="dol-smoke-"))
    harness = repo / "scripts" / "harness"
    plan = repo / "docs" / "plans" / "smoke.md"
    failed = False
    t0 = time.time()

    def step(n: int, label: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        mark = "OK" if ok else "FAIL"
        line = f"[{n}/7] {label:<41} {mark}"
        if detail:
            line += f"  {detail}"
        print(line)
        if not ok:
            failed = True

    try:
        # 1 — install the agnostic layer (also exercises init.{sh,ps1})
        if os.name == "nt":
            init_cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(PLUGIN_ROOT / "scripts" / "init.ps1"), str(repo)]
        else:
            init_cmd = ["sh", str(PLUGIN_ROOT / "scripts" / "init.sh"), str(repo)]
        rc, _ = _run(init_cmd)
        ok = (rc == 0 and (harness / "run_task.py").exists()
              and (repo / "scripts" / "__init__.py").exists())
        step(1, "init -> agnostic layer installed", ok)

        # fixture files
        (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        (repo / "tests").mkdir(exist_ok=True)
        (repo / "tests" / "test_calc.py").write_text(TEST_CALC, encoding="utf-8")
        plan.write_text(SMOKE_PLAN, encoding="utf-8")

        # 2 — validate_plan
        rc, out = _run([sys.executable, str(harness / "validate_plan.py"), str(plan)])
        last = out.strip().splitlines()[-1] if out.strip() else ""
        step(2, "validate_plan smoke.md", rc == 0 and "2 harness task" in out, last)

        # 3 — plan_schedule
        rc, out = _run([sys.executable, str(harness / "plan_schedule.py"), str(plan)])
        step(3, "plan_schedule smoke.md", rc == 0 and "2 task" in out)

        # 4 — run_task with no implementation: verify must FAIL, checkbox stays
        rc, _ = _run([sys.executable, str(harness / "run_task.py"), str(plan), "T01"])
        unticked = "- [ ] **Task 1 complete**" in plan.read_text(encoding="utf-8")
        step(4, "run_task T01 (no impl) -> verify FAIL", rc != 0 and unticked,
             "red, checkbox not ticked")

        # 5 — implement, then run_task again: verify PASSES, checkbox ticked
        (repo / "calc.py").write_text(CALC_ADD, encoding="utf-8")
        rc1, _ = _run([sys.executable, str(harness / "run_task.py"), str(plan), "T01"])
        t01_ticked = "- [x] **Task 1 complete**" in plan.read_text(encoding="utf-8")

        (repo / "calc.py").write_text(CALC_ADD_MUL, encoding="utf-8")
        rc2, _ = _run([sys.executable, str(harness / "run_task.py"), str(plan), "T02"])
        t02_ticked = "- [x] **Task 2 complete**" in plan.read_text(encoding="utf-8")
        step(5, "run_task T01,T02 (impl) -> verify PASS",
             rc1 == 0 and t01_ticked and rc2 == 0 and t02_ticked,
             "green, checkboxes ticked")

        # 6 — cycle_done: no pending tasks + .harness/gates all pass, CHANGELOG appended
        (repo / ".harness").mkdir(exist_ok=True)
        (repo / ".harness" / "gates").write_text(
            "# smoke gate\npython -m pytest tests/test_calc.py -q\n", encoding="utf-8")
        rc, _ = _run([sys.executable, str(harness / "cycle_done.py"),
                      "--plan", str(plan)])
        changelog = repo / "CHANGELOG.md"
        ok = (rc == 0 and changelog.exists()
              and "smoke" in changelog.read_text(encoding="utf-8").lower())
        step(6, "cycle_done (.harness/gates) -> CHANGELOG", ok)

        # 7 — recheck_plan: a genuine plan re-verifies clean; a checkbox left
        #     ticked after its work is undone must be REJECTED.
        recheck = harness / "recheck_plan.py"
        rc_clean, _ = _run([sys.executable, str(recheck), str(plan)])
        # break T02's work (remove mul) while its checkbox stays ticked
        (repo / "calc.py").write_text(CALC_ADD, encoding="utf-8")
        rc_broken, _ = _run([sys.executable, str(recheck), str(plan)])
        step(7, "recheck_plan -> clean OK, hand-tick REJECTED",
             rc_clean == 0 and rc_broken == 1,
             "enforcement: ticked work re-verified")

    finally:
        elapsed = time.time() - t0
        if keep or failed:
            print(f"\ntemp repo kept at: {repo}")
        else:
            shutil.rmtree(repo, ignore_errors=True)

    if failed:
        print(f"\nSMOKE FAIL ({elapsed:.1f}s)")
        return 1
    print(f"\nSMOKE PASS ({elapsed:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
