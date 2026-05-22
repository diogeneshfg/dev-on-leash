# Harness Hardening Implementation Plan

> **For agentic workers:** Execute this plan task-by-task. Every task carries a
> `task-meta` block — it is verified and checkbox-ticked by
> `scripts/harness/run_task.py`; never tick those checkboxes by hand. Run a
> task with `python scripts/harness/run_task.py docs/plans/harness-hardening.md <id>`.
> The numbered steps inside each task are TDD guidance (write the test, watch
> it fail, implement, watch it pass); the single `- [ ]` checkbox is the
> machine-verified completion marker.

**Goal:** Make dev-on-leash's discipline enforceable (every ticked task is
independently re-verifiable), fix the plan-parser inconsistencies with one
coherent region model, and make the documentation describe what the tool
actually does.

**Architecture:** A single region-based plan parser in `schema.py` becomes the
shared foundation for `run_task.py` and a new `recheck_plan.py`. `recheck_plan`
re-runs the `verify` command of every ticked task — a hand-flipped checkbox
fails its own verify, so it cannot survive CI or an opt-in pre-commit hook.
Documentation is corrected to match.

**Tech Stack:** Python 3.12, `pyyaml`, `pytest`; POSIX `sh` + PowerShell init
scripts; GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-05-22-harness-hardening-design.md`

---

## File Structure

**Create:**
- `scripts/harness/recheck_plan.py` — re-verify every ticked task in a plan.
- `tests/harness/test_recheck_plan.py` — tests for `recheck_plan.py`.
- `templates/hooks/pre-commit` — opt-in git hook running `recheck_plan` on staged plans.
- `templates/ci-snippet.md` — copy-pasteable CI snippet for adopting projects.
- `tests/test_meta.py` — version-consistency test.
- `tests/test_init.py` — asserts `init.{sh,ps1}` copy the pre-commit hook.
- `tests/test_ci_wiring.py` — asserts CI/bootstrap reference `recheck_plan`.
- `tests/test_docs.py` — asserts README/plugin.json framing is honest.

**Modify:**
- `scripts/harness/schema.py` — add the region model; unify the heading regex.
- `scripts/harness/run_task.py` — tick by bound region instead of substring scan.
- `tests/harness/test_schema.py` — region-model tests.
- `tests/harness/test_run_task.py` — id-misroute regression test.
- `scripts/init.sh`, `scripts/init.ps1` — copy the hook into `.harness/hooks/`.
- `scripts/smoke_e2e.py` — add a `recheck_plan` bypass-detection step.
- `.github/workflows/ci.yml` — add a "re-verify ticked tasks" step.
- `skills/bootstrap-dev-leash/SKILL.md` — offer hook install; mention CI snippet.
- `pyproject.toml` — bump version `0.1.0` → `0.2.0`.
- `README.md`, `.claude-plugin/plugin.json` — honest framing + Trust model.

**Layers (collision-free):** L0 = T01, T02, T07 (parallel) · L1 = T03 ·
L2 = T04, T05 (parallel) · L3 = T06.

---

## Task 1 — Version sync

Make `pyproject.toml` and `plugin.json` agree on the version, and add a test
that keeps them in sync.

**Files:**
- Create: `tests/test_meta.py`
- Modify: `pyproject.toml`

**Steps:**

1. Write the failing test — `tests/test_meta.py`:

```python
"""Repo-metadata consistency checks."""
import json
import pathlib
import re

import pytest

pytestmark = pytest.mark.unit

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert m, "version not found in pyproject.toml"
    return m.group(1)


def _plugin_version() -> str:
    data = json.loads(
        (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    return data["version"]


def test_pyproject_and_plugin_versions_match():
    assert _pyproject_version() == _plugin_version()
```

2. Run `python -m pytest tests/test_meta.py -q` — expect FAIL
   (`'0.1.0' == '0.2.0'` mismatch).

3. In `pyproject.toml`, change `version = "0.1.0"` to `version = "0.2.0"`.

4. Run `python -m pytest tests/test_meta.py -q` — expect PASS.

- [x] **Task 1 complete**

<!-- task-meta
id: T01
touches:
  - pyproject.toml
  - tests/test_meta.py
depends: []
verify: python -m pytest tests/test_meta.py -q
acceptance: null
-->

## Task 2 — Region-based plan model

Replace the implicit heading/block pairing with one region model used by both
`schema.py` and `run_task.py`. Unify the heading regex to `^#{2,}\s+Task\b`
(H2 or H3). A region with two-plus `task-meta` blocks errors; a region with
none is an allowed human-run task; a block outside every region errors.
`run_task` ticks the checkbox inside the region bound to the requested id —
no substring `id:` scan.

**Files:**
- Modify: `scripts/harness/schema.py`
- Modify: `scripts/harness/run_task.py`
- Test: `tests/harness/test_schema.py`, `tests/harness/test_run_task.py`

**Steps:**

1. Update `tests/harness/test_schema.py`. Replace `test_rejects_task_without_meta`
   with the lenient-behavior test below, and add three region-model tests. No
   import changes are needed — all four tests use the already-imported
   `parse_plan`, `SchemaError`, and the `write_plan` helper.

```python
def test_task_heading_without_meta_is_human_run(tmp_path):
    # A task heading with no task-meta block is a human-run task: the harness
    # returns no TaskMeta for it rather than erroring. See templates/task-schema.md.
    plan = write_plan(
        tmp_path,
        """
        ### Task 1 — Bare

        (no task-meta block here)
    """,
    )
    assert parse_plan(plan) == []


def test_rejects_two_meta_blocks_in_one_region(tmp_path):
    plan = write_plan(
        tmp_path,
        """
        ### Task 1

        <!-- task-meta
        id: T01
        touches: [a]
        depends: []
        verify: "true"
        -->

        <!-- task-meta
        id: T02
        touches: [b]
        depends: []
        verify: "true"
        -->
    """,
    )
    with pytest.raises(SchemaError, match="task-meta blocks"):
        parse_plan(plan)


def test_rejects_meta_block_outside_any_heading(tmp_path):
    plan = write_plan(
        tmp_path,
        """
        Intro prose, no task heading yet.

        <!-- task-meta
        id: T01
        touches: [a]
        depends: []
        verify: "true"
        -->
    """,
    )
    with pytest.raises(SchemaError, match="not inside any"):
        parse_plan(plan)


def test_parses_h2_task_heading(tmp_path):
    # H2 headings must be recognised identically to H3.
    plan = write_plan(
        tmp_path,
        """
        ## Task 1 — H2 heading

        <!-- task-meta
        id: T01
        touches: [foo.py]
        depends: []
        verify: "true"
        -->
    """,
    )
    tasks = parse_plan(plan)
    assert [t.id for t in tasks] == ["T01"]
```

2. Run `python -m pytest tests/harness/test_schema.py -q` — expect FAIL
   (`parse_regions` does not exist; `test_task_heading_without_meta_is_human_run`
   still raises under the old code).

3. In `scripts/harness/schema.py`, add the heading regex constant immediately
   after `FENCE_CLOSE_RE`. The `dataclass` and `field` imports are already
   present:

```python
HEADING_RE = re.compile(r"^#{2,}\s+Task\b.*$", re.MULTILINE)
```

4. Add the `TaskRegion` dataclass directly after the `TaskMeta` dataclass:

```python
@dataclass(frozen=True)
class TaskRegion:
    """A `## Task` heading and the (optional) task-meta block bound to it.

    Line indices are 0-based and refer to the fence-stripped plan text, whose
    line count matches the raw text. `meta is None` marks a human-run task.
    """
    heading_line: int
    end_line: int  # exclusive: next heading's line, or EOF
    meta: TaskMeta | None
```

5. Add the region parser after `_strip_fenced_blocks`, and rewrite
   `parse_plan` to build on it. Replace the entire existing `parse_plan`
   function (the `def parse_plan` through its `return tasks`) with:

```python
def _line_index(text: str, offset: int) -> int:
    """0-based index of the line containing character `offset`."""
    return text.count("\n", 0, offset)


def parse_regions(plan_path: Path) -> list[TaskRegion]:
    """Split a plan into task regions, each bound to at most one task-meta block.

    A region starts at a `## `/`### Task` heading and runs to the next such
    heading (or EOF). Zero task-meta blocks in a region -> a human-run task
    (`meta is None`). Two or more -> SchemaError. A task-meta block outside
    every region -> SchemaError. Fenced example blocks are stripped first, so
    illustrative task-meta inside code fences is never counted.
    """
    raw = plan_path.read_text(encoding="utf-8")
    stripped = _strip_fenced_blocks(raw)
    total_lines = stripped.count("\n") + 1

    heading_lines = [
        _line_index(stripped, m.start()) for m in HEADING_RE.finditer(stripped)
    ]
    bounds = [
        (
            heading_lines[i],
            heading_lines[i + 1] if i + 1 < len(heading_lines) else total_lines,
        )
        for i in range(len(heading_lines))
    ]
    blocks = [
        (_line_index(stripped, m.start()), m.group(1))
        for m in TASK_META_RE.finditer(stripped)
    ]

    regions: list[TaskRegion] = []
    for start, end in bounds:
        inside = [(ln, body) for ln, body in blocks if start <= ln < end]
        if len(inside) > 1:
            raise SchemaError(
                f"{plan_path}: task heading at line {start + 1} has "
                f"{len(inside)} task-meta blocks; expected at most 1"
            )
        meta = _parse_block(inside[0][1], plan_path) if inside else None
        regions.append(TaskRegion(heading_line=start, end_line=end, meta=meta))

    for ln, _ in blocks:
        if not any(s <= ln < e for s, e in bounds):
            raise SchemaError(
                f"{plan_path}: task-meta block at line {ln + 1} is not inside "
                "any '## Task' heading"
            )
    return regions


def parse_plan(plan_path: Path) -> list[TaskMeta]:
    tasks = [r.meta for r in parse_regions(plan_path) if r.meta is not None]

    seen: set[str] = set()
    for t in tasks:
        if t.id in seen:
            raise SchemaError(f"{plan_path}: duplicate id {t.id}")
        seen.add(t.id)

    for t in tasks:
        unknown = [d for d in t.depends if d not in seen]
        if unknown:
            raise SchemaError(
                f"{plan_path}: task {t.id} has unknown depends: {unknown}"
            )

    _detect_cycle(tasks)
    return tasks
```

6. Run `python -m pytest tests/harness/test_schema.py -q` — expect PASS
   (all old tests plus the four new ones).

7. Replace the whole of `scripts/harness/run_task.py` with the region-based
   version:

```python
#!/usr/bin/env python3
"""Execute one task's verify command. On success, tick the first checkbox in the task body.

Usage:
    python scripts/harness/run_task.py <plan.md> <task_id>
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.harness.schema import TaskRegion, _strip_fenced_blocks, parse_regions

REPO_ROOT = Path(__file__).resolve().parents[2]


def _tick_checkbox_in_region(plan_text: str, region: TaskRegion) -> str:
    """Flip the first real `- [ ]` inside `region` to `- [x]`.

    Lines blank in the fence-stripped text were inside a fenced block (or
    genuinely empty) and are skipped — an example checkbox in a code fence is
    never ticked. Operates on line indices: `_strip_fenced_blocks` preserves
    line count, and `region`'s indices come from the same stripping.
    """
    lines = plan_text.split("\n")
    stripped_lines = _strip_fenced_blocks(plan_text).split("\n")
    for j in range(region.heading_line, min(region.end_line, len(lines))):
        if not stripped_lines[j].strip():
            continue
        new_line, n = re.subn(r"- \[ \]", "- [x]", lines[j], count=1)
        if n:
            lines[j] = new_line
            return "\n".join(lines)
    return plan_text


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: run_task.py <plan.md> <task_id>", file=sys.stderr)
        return 2
    plan_path = Path(argv[1])
    task_id = argv[2]
    regions = parse_regions(plan_path)
    region = next(
        (r for r in regions if r.meta is not None and r.meta.id == task_id),
        None,
    )
    if region is None:
        print(f"error: task {task_id} not found in {plan_path}", file=sys.stderr)
        return 2
    task = region.meta
    print(f"[harness] running verify for {task_id}: {task.verify}", file=sys.stderr)
    # verify commands assume repo-root CWD; force it so invocation location
    # does not change semantics.
    rc = subprocess.call(task.verify, shell=True, cwd=REPO_ROOT)
    if rc != 0:
        print(f"[harness] verify FAILED (exit {rc}); checkbox left unticked", file=sys.stderr)
        return 1
    new_text = _tick_checkbox_in_region(
        plan_path.read_text(encoding="utf-8"), region
    )
    plan_path.write_text(new_text, encoding="utf-8")
    print(f"[harness] {task_id} OK; checkbox ticked", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

8. Add the id-misroute regression test to `tests/harness/test_run_task.py`:

```python
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
```

9. Run `python -m pytest tests/harness/test_schema.py tests/harness/test_run_task.py -q`
   — expect PASS (all existing run_task tests plus the new regression test).

- [x] **Task 2 complete**

<!-- task-meta
id: T02
touches:
  - scripts/harness/schema.py
  - scripts/harness/run_task.py
  - tests/harness/test_schema.py
  - tests/harness/test_run_task.py
depends: []
verify: python -m pytest tests/harness/test_schema.py tests/harness/test_run_task.py -q
acceptance: null
-->

## Task 3 — recheck_plan.py: re-verify every ticked task

A new harness script that re-runs the `verify` command of every task whose
checkbox is `- [x]`. A box ticked without the work done fails its own verify.
Nothing is trusted but the plan file and the source tree.

**Files:**
- Create: `scripts/harness/recheck_plan.py`
- Test: `tests/harness/test_recheck_plan.py`

**Steps:**

1. Write the failing test — `tests/harness/test_recheck_plan.py`:

```python
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


def test_missing_plan_file_is_usage_error(tmp_path):
    r = _run(tmp_path / "nope.md")
    assert r.returncode == 2
```

2. Run `python -m pytest tests/harness/test_recheck_plan.py -q` — expect FAIL
   (`recheck_plan.py` does not exist).

3. Create `scripts/harness/recheck_plan.py`:

```python
#!/usr/bin/env python3
"""Re-verify every ticked task in a plan.

run_task.py ticks a task's checkbox only after its `verify` command exits 0.
This script independently re-runs `verify` for every task whose checkbox is
already `- [x]`. A box ticked without the work actually done fails its own
verify here — so a hand-edited tick cannot survive CI or the pre-commit hook.
Nothing is trusted but the plan file and the source tree.

Usage:
    python scripts/harness/recheck_plan.py <plan.md>

Exit codes:
    0 - every ticked task re-verified (or the plan has no ticked tasks)
    1 - at least one ticked task failed to re-verify
    2 - usage error / plan file missing / schema error
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.harness.schema import (
    SchemaError,
    TaskRegion,
    _strip_fenced_blocks,
    parse_regions,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _region_is_ticked(plan_text: str, region: TaskRegion) -> bool:
    """True if the first real checkbox in `region` is `- [x]`.

    Mirrors run_task.py: the first checkbox not blanked by _strip_fenced_blocks
    is the task's status box. No checkbox at all -> treated as not ticked.
    """
    lines = plan_text.split("\n")
    stripped = _strip_fenced_blocks(plan_text).split("\n")
    for j in range(region.heading_line, min(region.end_line, len(lines))):
        if not stripped[j].strip():
            continue
        if re.search(r"- \[x\]", lines[j]):
            return True
        if re.search(r"- \[ \]", lines[j]):
            return False
    return False


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: recheck_plan.py <plan.md>", file=sys.stderr)
        return 2
    plan_path = Path(argv[1])
    if not plan_path.exists():
        print(f"error: {plan_path} does not exist", file=sys.stderr)
        return 2
    try:
        regions = parse_regions(plan_path)
    except SchemaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    plan_text = plan_path.read_text(encoding="utf-8")
    ticked = [
        r
        for r in regions
        if r.meta is not None and _region_is_ticked(plan_text, r)
    ]
    if not ticked:
        print("OK: no ticked tasks to re-verify", file=sys.stderr)
        return 0

    failures: list[str] = []
    for r in ticked:
        print(f"[recheck] {r.meta.id}: {r.meta.verify}", file=sys.stderr)
        rc = subprocess.call(r.meta.verify, shell=True, cwd=REPO_ROOT)
        if rc == 0:
            print(f"OK: {r.meta.id} re-verified", file=sys.stderr)
        else:
            print(
                f"FAIL: {r.meta.id} is ticked but verify exited {rc}",
                file=sys.stderr,
            )
            failures.append(r.meta.id)

    if failures:
        print(
            f"REJECTED: {len(failures)} ticked task(s) failed re-verify: {failures}",
            file=sys.stderr,
        )
        return 1
    print(f"ALL CLEAR: {len(ticked)} ticked task(s) re-verified", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

4. Run `python -m pytest tests/harness/test_recheck_plan.py -q` — expect PASS.

- [x] **Task 3 complete**

<!-- task-meta
id: T03
touches:
  - scripts/harness/recheck_plan.py
  - tests/harness/test_recheck_plan.py
depends: [T02]
verify: python -m pytest tests/harness/test_recheck_plan.py -q
acceptance: null
-->

## Task 4 — Opt-in pre-commit hook

Ship a pre-commit hook that runs `recheck_plan` on staged plan files. The init
scripts copy it into `.harness/hooks/` (a tracked location) but do **not**
activate it — activation is opt-in (handled by the bootstrap skill, Task 6).

**Files:**
- Create: `templates/hooks/pre-commit`
- Modify: `scripts/init.sh`, `scripts/init.ps1`
- Test: `tests/test_init.py`

**Steps:**

1. Write the failing test — `tests/test_init.py`:

```python
"""init.{sh,ps1} copy the project-agnostic layer, including the pre-commit hook."""
import os
import subprocess
import sys
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
```

2. Run `python -m pytest tests/test_init.py -q` — expect FAIL (no hook copied).

3. Create `templates/hooks/pre-commit`:

```sh
#!/bin/sh
# dev-on-leash pre-commit hook — re-verify every ticked task in staged plans.
#
# Opt-in: installed by the bootstrap-dev-leash skill (or manually via
# `git config core.hooksPath .harness/hooks`). It blocks a commit when a plan
# under docs/plans/ has a task checkbox ticked whose `verify` command does not
# actually pass — i.e. a checkbox flipped by hand instead of by run_task.py.
#
# Emergency bypass: git commit --no-verify
set -e

staged_plans=$(git diff --cached --name-only --diff-filter=ACM \
    | grep '^docs/plans/.*\.md$' || true)
[ -z "$staged_plans" ] && exit 0

rc=0
for plan in $staged_plans; do
    python scripts/harness/recheck_plan.py "$plan" || rc=1
done
exit $rc
```

4. In `scripts/init.sh`, add a new section **before** the `# Summary` block
   (after section 5, the `docs/plans/` directory creation):

```sh
# ---------------------------------------------------------------------------
# 6. Copy the opt-in pre-commit hook into .harness/hooks/ (NOT activated)
# ---------------------------------------------------------------------------
SRC_HOOK="$PLUGIN_ROOT/templates/hooks/pre-commit"
DST_HOOKS_DIR="$TARGET/.harness/hooks"
DST_HOOK="$DST_HOOKS_DIR/pre-commit"
if [ -e "$DST_HOOK" ]; then
    printf 'Skipped: .harness/hooks/pre-commit (already exists)\n'
    SKIPPED="$SKIPPED .harness/hooks/pre-commit"
else
    mkdir -p "$DST_HOOKS_DIR"
    cp "$SRC_HOOK" "$DST_HOOK"
    chmod +x "$DST_HOOK" 2>/dev/null || true
    printf 'Copied:  .harness/hooks/pre-commit\n'
    COPIED="$COPIED .harness/hooks/pre-commit"
fi
```

5. In `scripts/init.ps1`, add the equivalent section **before** the
   `# Summary` block (after section 5):

```powershell
# ---------------------------------------------------------------------------
# 6. Copy the opt-in pre-commit hook into .harness/hooks/ (NOT activated)
# ---------------------------------------------------------------------------
$SrcHook     = Join-Path $PluginRoot 'templates\hooks\pre-commit'
$DstHooksDir = Join-Path $Target '.harness\hooks'
$DstHook     = Join-Path $DstHooksDir 'pre-commit'
if (Test-Path -LiteralPath $DstHook) {
    Write-Host 'Skipped: .harness/hooks/pre-commit (already exists)'
    $Skipped.Add('.harness/hooks/pre-commit')
} else {
    if (-not (Test-Path -LiteralPath $DstHooksDir -PathType Container)) {
        New-Item -ItemType Directory -Path $DstHooksDir -Force | Out-Null
    }
    Copy-Item -Path $SrcHook -Destination $DstHook
    Write-Host 'Copied:  .harness/hooks/pre-commit'
    $Copied.Add('.harness/hooks/pre-commit')
}
```

6. Run `python -m pytest tests/test_init.py -q` — expect PASS.

- [x] **Task 4 complete**

<!-- task-meta
id: T04
touches:
  - templates/hooks/pre-commit
  - scripts/init.sh
  - scripts/init.ps1
  - tests/test_init.py
depends: [T03]
verify: python -m pytest tests/test_init.py -q
acceptance: null
-->

## Task 5 — smoke_e2e bypass-detection step

Extend the end-to-end smoke test to prove `recheck_plan` enforcement: after
the normal green run, the genuine plan re-verifies clean; then the source is
broken while a checkbox stays ticked, and `recheck_plan` must reject it.

**Files:**
- Modify: `scripts/smoke_e2e.py`

**Steps:**

1. In `scripts/smoke_e2e.py`, change the step counter in the `step()` helper
   from `[{n}/6]` to `[{n}/7]`:

```python
        line = f"[{n}/7] {label:<41} {mark}"
```

2. Add step 7 immediately after the step-6 block (after the
   `step(6, "cycle_done (.harness/gates) -> CHANGELOG", ok)` line and before
   the `finally:`):

```python
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
```

3. In the module docstring, add `recheck_plan` to the described loop — change
   the `-> cycle_done ...` line to also mention:

```
         -> recheck_plan (every ticked task re-verifies; a hand-ticked
            but-undone task is rejected)
```

4. Run `python scripts/smoke_e2e.py` — expect `SMOKE PASS` with 7 steps,
   step 7 reporting `OK`.

- [x] **Task 5 complete**

<!-- task-meta
id: T05
touches:
  - scripts/smoke_e2e.py
depends: [T03]
verify: python scripts/smoke_e2e.py
acceptance: null
-->

## Task 6 — CI + bootstrap wiring

Wire `recheck_plan` into the plugin's own CI, ship a CI snippet template for
adopting projects, and have the bootstrap skill offer to activate the hook.

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `templates/ci-snippet.md`
- Modify: `skills/bootstrap-dev-leash/SKILL.md`
- Test: `tests/test_ci_wiring.py`

**Steps:**

1. Write the failing test — `tests/test_ci_wiring.py`:

```python
"""CI and bootstrap are wired to the recheck_plan enforcement."""
import pathlib

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_ci_yaml_is_valid_and_rechecks_plans():
    ci = ROOT / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    assert doc, "ci.yml must be valid, non-empty YAML"
    assert "recheck_plan.py" in text


def test_ci_snippet_template_exists():
    snippet = ROOT / "templates" / "ci-snippet.md"
    assert snippet.exists()
    assert "recheck_plan.py" in snippet.read_text(encoding="utf-8")


def test_bootstrap_skill_documents_the_hook():
    text = (ROOT / "skills" / "bootstrap-dev-leash" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "pre-commit" in text
    assert "recheck_plan" in text
```

2. Run `python -m pytest tests/test_ci_wiring.py -q` — expect FAIL.

3. In `.github/workflows/ci.yml`, add a new step at the end of the `steps:`
   list, after the `Validate plans` step:

```yaml
      - name: Re-verify ticked tasks in plans
        run: |
          python -c "
          import subprocess, sys, pathlib

          plans = sorted(pathlib.Path('docs/plans').glob('*.md'))
          if not plans:
              print('No plan files in docs/plans - nothing to re-verify')
              sys.exit(0)
          print(f'Re-verifying {len(plans)} plan(s):', [str(p) for p in plans])

          failed = []
          for p in plans:
              r = subprocess.run(
                  [sys.executable, 'scripts/harness/recheck_plan.py', str(p)],
                  capture_output=True, text=True
              )
              print(f'{p}: exit={r.returncode}')
              if r.stdout:
                  print(r.stdout, end='')
              if r.stderr:
                  print(r.stderr, end='', file=sys.stderr)
              if r.returncode != 0:
                  failed.append(str(p))

          if failed:
              print(f'Re-verify failed for: {failed}', file=sys.stderr)
              sys.exit(1)
          print('All ticked tasks re-verified')
          "
```

4. Create `templates/ci-snippet.md` (4-backtick outer fence so the inner
   `yaml` fence survives — the file content is everything between the outer
   fences):

````markdown
# CI: re-verify ticked tasks

Add this step to your CI workflow so a hand-ticked plan checkbox cannot pass
review. It re-runs the `verify` command of every ticked task in every plan;
a checkbox flipped without the work done fails its own verify.

```yaml
      - name: Re-verify ticked tasks in plans
        run: |
          for plan in docs/plans/*.md; do
            [ -e "$plan" ] || continue
            python scripts/harness/recheck_plan.py "$plan" || exit 1
          done
```
````

5. In `skills/bootstrap-dev-leash/SKILL.md`, add a new step between
   `## Step 4 — Copy the project-agnostic layer` and `## Step 5 — Report`:

```markdown
## Step 4b — Offer the pre-commit hook (opt-in)

The init script copies an opt-in pre-commit hook to
`.harness/hooks/pre-commit`. It runs `scripts/harness/recheck_plan.py` on any
staged plan file and blocks the commit if a ticked task fails to re-verify —
the local half of the enforcement model.

Ask the user (one `AskUserQuestion`, yes/no) whether to activate it now:

- **Yes:** run `git config core.hooksPath .harness/hooks` in the target repo.
  Tell the user the bypass is `git commit --no-verify`, and that
  `core.hooksPath` redirects *all* git hooks to `.harness/hooks/`.
- **No:** leave the hook file in place, unactivated. Tell the user they can
  activate it later with the same `git config` command.

For CI enforcement, point the user at `${CLAUDE_PLUGIN_ROOT}/templates/ci-snippet.md`
— a copy-pasteable step that re-verifies ticked tasks on every push.
```

6. In `skills/bootstrap-dev-leash/SKILL.md` `## Step 5 — Report`, add one
   bullet to the report list:

```markdown
- Whether the pre-commit hook was activated (`git config core.hooksPath`), and
  that the CI snippet in `templates/ci-snippet.md` enforces the same check on push.
```

7. Run `python -m pytest tests/test_ci_wiring.py -q` — expect PASS.

- [x] **Task 6 complete**

<!-- task-meta
id: T06
touches:
  - .github/workflows/ci.yml
  - templates/ci-snippet.md
  - skills/bootstrap-dev-leash/SKILL.md
  - tests/test_ci_wiring.py
depends: [T04, T05]
verify: python -m pytest tests/test_ci_wiring.py -q
acceptance: null
-->

## Task 7 — Honest framing

Make the README and `plugin.json` describe what the tool actually does, add a
Trust model section, and record the deferred `touches`-integrity limitation.

**Files:**
- Modify: `README.md`, `.claude-plugin/plugin.json`
- Test: `tests/test_docs.py`

**Steps:**

1. Write the failing test — `tests/test_docs.py`:

```python
"""README and plugin manifest describe the tool honestly."""
import json
import pathlib

import pytest

pytestmark = pytest.mark.unit

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_readme_has_trust_model_section():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Trust model" in readme


def test_readme_drops_overclaiming_language():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "proven internal harness" not in readme


def test_plugin_description_is_honest():
    desc = json.loads(
        (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )["description"]
    assert "re-verifiable" in desc
    assert "guardrails" not in desc.lower()


def test_followups_records_touches_integrity():
    text = (ROOT / "docs" / "follow-ups.md").read_text(encoding="utf-8")
    assert "touches" in text
```

2. Run `python -m pytest tests/test_docs.py -q` — expect FAIL.

3. In `README.md`, replace lines 1–9 — the `# dev-on-leash` heading through
   the sentence ending "...runs in CI and git hooks." — with:

```markdown
# dev-on-leash

A verify-gated task harness for AI-assisted development, packaged as a
portable **Claude Code plugin**.

`dev-on-leash` turns a Markdown plan into a machine-checked workflow: each
task declares a `verify` command, a task's checkbox is ticked only when that
command passes, and every ticked task can be independently re-verified so a
hand-flipped checkbox cannot survive CI or a pre-commit hook. It ships a
parallel-execution scheduler, a doc-freshness check, an auto-appended
changelog, custom review agents, and a bootstrap skill that scaffolds the
whole setup into any project.
```

4. In `README.md`, add a `## Trust model` section immediately before
   `## Validate the harness`:

```markdown
## Trust model

Be precise about what the harness enforces and what it only assists:

- **Enforced.** A task's checkbox is ticked only by `run_task.py` after its
  `verify` command exits 0. `recheck_plan.py` re-runs the `verify` of every
  ticked task — run it in CI (see `templates/ci-snippet.md`) and/or as the
  opt-in pre-commit hook, and a checkbox flipped by hand without the work
  done is rejected.
- **By convention only.** `touches` is self-reported: the harness does not yet
  check that a task modified *only* its declared files, so the parallel-safety
  of `plan_schedule.py` depends on `touches` being accurate. Verifying it
  without false positives needs its own design — tracked as a follow-up.
- **Escape hatch.** `cycle_done.py --force -m <reason>` closes a cycle past
  failing gates and appends an audit line to `.harness/exceptions.log`.
```

5. In `.claude-plugin/plugin.json`, replace the `description` value with:

```json
  "description": "A verify-gated task harness for AI-assisted development: Markdown plans where every ticked task is independently re-verifiable, with a parallel scheduler, review agents, and a bootstrap skill.",
```

6. Create `docs/follow-ups.md` to record the deferred `touches`-integrity work:

```markdown
# Follow-ups

Known limitations and deferred work, kept here so they are not forgotten.

## touches-integrity checking

`task-meta`'s `touches` list is self-reported. The harness does not verify
that a task modified *only* its declared files, so `plan_schedule.py`'s
parallel-safety guarantee depends on `touches` being accurate.

A check would compare `git diff --name-only` after a task against its declared
`touches`. Doing that without false positives from unrelated concurrent work
in the diff needs its own design. Deferred from the 2026-05-22
harness-hardening effort.
```

7. Run `python -m pytest tests/test_docs.py -q` — expect PASS.

- [ ] **Task 7 complete**

<!-- task-meta
id: T07
touches:
  - README.md
  - .claude-plugin/plugin.json
  - docs/follow-ups.md
  - tests/test_docs.py
depends: []
verify: python -m pytest tests/test_docs.py -q
acceptance: null
-->

## Closing the cycle

When all seven checkboxes are ticked, close the cycle:

```bash
python scripts/harness/validate_plan.py docs/plans/harness-hardening.md
python scripts/harness/cycle_done.py --plan docs/plans/harness-hardening.md
```

`cycle_done` runs `.harness/gates` and appends a `CHANGELOG.md` entry. Then
run the full suite and the smoke test once more as a final check:

```bash
python -m pytest -q
python scripts/smoke_e2e.py
```
