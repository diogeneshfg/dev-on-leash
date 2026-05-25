# Architecture Leash Implementation Plan

> **For agentic workers:** Execute this plan task-by-task. Every task carries
> a `task-meta` block — it is verified and checkbox-ticked by
> `scripts/harness/run_task.py`; never tick those checkboxes by hand. Run a
> task with `python scripts/harness/run_task.py docs/plans/architecture-leash.md <id>`.
> The numbered steps inside each task are TDD guidance (write the test, watch
> it fail, implement, watch it pass); the single `- [ ]` checkbox is the
> machine-verified completion marker.

**Goal:** Add an architecture leash to dev-on-leash — a new
`compose-architecture-leash` skill that interviews the user in prose,
extracts a structured `.harness/architecture.yaml` via subagent, compiles it
into mechanical gates (Python `import-linter`, JS/TS `dependency-cruiser`,
generic grep) and a project-local `architecture-reviewer` agent, with a
re-run mode picker (add / revise / re-describe). Dogfooded on dev-on-leash
itself.

**Architecture:** Layered enforcement. A `.harness/architecture.yaml` is the
source of truth; `scripts/harness/compile_architecture.py` is a deterministic
compiler that emits per-language tool configs, generic grep gates, and the
reviewer agent's system prompt — all carrying a `# GENERATED` header and a
`# arch-leash:<id>` traceability tag so re-compile cleanly prunes removed
rules. Mechanical rules become `.harness/gates` lines (hard CI block).
Judgment rules live in the reviewer agent (advisory).

**Tech Stack:** Python 3.12, `pyyaml`, `pytest`; Markdown skills with YAML
frontmatter; cross-platform Python generated check scripts.

**Spec:** `docs/superpowers/specs/2026-05-25-architecture-leash-design.md`

**Deliberate spec deviation:** The spec (Section 3 point 3) calls for emitting
`pattern-<id>.sh` + `pattern-<id>.ps1` pairs. During plan-time we confirmed
that `cycle_done.py` runs gates via `subprocess.call(cmd, shell=True)`, which
hits `cmd.exe` on Windows — so a `sh ...` gate line breaks on Windows where
`sh` isn't on PATH. Existing project pattern (`check_regression.{sh,ps1,py}`)
already keeps a `.py` sibling specifically to be the cross-platform gate. So
this plan emits **only** `pattern-<id>.py` (gates run it with
`python .harness/checks/pattern-<id>.py`). The spec will be amended at cycle
close to reflect this; the deviation is recorded here so the spec-reviewer
agent recognizes it as intentional.

---

## File Structure

**Create:**

- `scripts/harness/validate_architecture.py` — schema validator for `architecture.yaml`.
- `scripts/harness/compile_architecture.py` — the compiler (generic + Python + JS/TS adapters).
- `agents/architecture-extractor.md` — plugin-scoped subagent (`dev-on-leash:architecture-extractor`).
- `templates/architecture.yaml.tmpl` — minimal starter spec.
- `templates/architecture-reviewer.md.tmpl` — templated reviewer-agent system prompt.
- `skills/compose-architecture-leash/SKILL.md` — the user-invokable skill.
- `tests/test_validate_architecture.py` — validator tests.
- `tests/test_compile_architecture.py` — compiler tests (all three adapters).
- `tests/test_agents.py` — extractor agent frontmatter test (file appended if it exists; created if not).
- `tests/test_templates.py` — reviewer template + AGENTS.md template tests (file appended if it exists; created if not).
- `tests/test_skill_compose.py` — structural tests for the skill markdown.
- `tests/fixtures/architecture/` — fixture YAMLs and tiny throwaway project trees.
- `scripts/dogfood_architecture.py` — dogfood verifier (asserts artifacts exist, asserts a deliberate-violation gate exits non-zero).
- `.harness/architecture.yaml` — created by running the skill on dev-on-leash in T11.
- `agents/architecture-reviewer.md` — generated in T11 (target-local copy in dev-on-leash's own repo).
- `.harness/checks/pattern-*.py` — generated in T11.
- `.harness/importlinter.ini` — generated in T11.

**Modify:**

- `templates/AGENTS.md.tmpl` — add the `OPTIONAL:ARCHITECTURE` block (stub form).
- `scripts/smoke_e2e.py` — extend with an architecture-leash e2e step.
- `AGENTS.md` (dev-on-leash's own) — populated by the skill in T11.
- `.harness/gates` — appended with arch-leash lines in T11.

**Layers (collision-free, for `plan_schedule.py`):**

- L0 (parallel): T01, T02, T03, T04
- L1: T05 (depends on T01)
- L2: T06 (depends on T05; same file as T05)
- L3: T07 (depends on T06; same file as T05)
- L4: T08 (depends on T01–T07)
- L5 (parallel): T09 (depends on T08), T10 (depends on T07)
- L6: T11 (depends on everything)

---

### Task 1 — `validate_architecture.py`: schema validator

Pure-Python validator for `.harness/architecture.yaml`. Foundation that the
compiler depends on. No I/O beyond reading the YAML.

**Files:**
- Create: `scripts/harness/validate_architecture.py`
- Test: `tests/test_validate_architecture.py`

**Steps:**

1. Write the failing test — `tests/test_validate_architecture.py`:

```python
"""Schema-validator tests for architecture.yaml."""
import pytest
from scripts.harness.validate_architecture import (
    ArchitectureSchemaError,
    parse_architecture,
)


def test_minimal_spec_parses():
    data = parse_architecture(
        """
version: 1
layers:
  - {name: domain, paths: [src/myapp/domain/**]}
allowed_dependencies: []
""".strip()
    )
    assert data.version == 1
    assert data.layers[0].name == "domain"
    assert data.allowed_dependencies == []
    assert data.patterns == []
    assert data.review_rules == []


def test_missing_version_rejected():
    with pytest.raises(ArchitectureSchemaError, match="version"):
        parse_architecture("layers: []\nallowed_dependencies: []")


def test_unknown_layer_in_edge_rejected():
    with pytest.raises(ArchitectureSchemaError, match="unknown layer"):
        parse_architecture(
            """
version: 1
layers: [{name: domain, paths: [src/**]}]
allowed_dependencies: [{from: domain, to: [ghost]}]
""".strip()
        )


def test_duplicate_rule_id_rejected():
    with pytest.raises(ArchitectureSchemaError, match="duplicate id"):
        parse_architecture(
            """
version: 1
layers: [{name: a, paths: [src/a/**]}, {name: b, paths: [src/b/**]}]
allowed_dependencies: []
patterns:
  - {id: dup, layer: a, forbidden_imports: [x]}
  - {id: dup, layer: b, forbidden_imports: [y]}
""".strip()
        )
```

2. Run `python -m pytest tests/test_validate_architecture.py -q` — expect
   FAIL (`ImportError` — module does not exist).

3. Implement `scripts/harness/validate_architecture.py`:

```python
"""Schema validator for .harness/architecture.yaml.

Pure Python, no external deps beyond pyyaml. Parses YAML and returns
typed dataclasses; raises ArchitectureSchemaError on any violation. The
compiler depends on this module and never re-validates fields itself.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import yaml


class ArchitectureSchemaError(ValueError):
    pass


@dataclass(frozen=True)
class Layer:
    name: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class Edge:
    src: str
    dst: tuple[str, ...]


@dataclass(frozen=True)
class Pattern:
    id: str
    layer: str
    forbidden_imports: tuple[str, ...] = ()
    required_imports: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class ReviewRule:
    id: str
    applies_to: str
    rule: str


@dataclass(frozen=True)
class Architecture:
    version: int
    style: str
    layers: tuple[Layer, ...]
    allowed_dependencies: tuple[Edge, ...]
    patterns: tuple[Pattern, ...]
    review_rules: tuple[ReviewRule, ...]


def _require(d: dict, key: str, ctx: str) -> Any:
    if key not in d:
        raise ArchitectureSchemaError(f"{ctx}: missing required key {key!r}")
    return d[key]


def parse_architecture(text: str) -> Architecture:
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ArchitectureSchemaError("top-level must be a mapping")
    version = _require(raw, "version", "root")
    if version != 1:
        raise ArchitectureSchemaError(f"unsupported version: {version!r}")
    style = raw.get("style", "")
    layers_raw = raw.get("layers", [])
    if not isinstance(layers_raw, list):
        raise ArchitectureSchemaError("layers must be a list")
    layers: list[Layer] = []
    for i, l in enumerate(layers_raw):
        name = _require(l, "name", f"layers[{i}]")
        paths = _require(l, "paths", f"layers[{i}]")
        if not isinstance(paths, list) or not paths:
            raise ArchitectureSchemaError(f"layers[{i}].paths must be non-empty list")
        layers.append(Layer(name=name, paths=tuple(paths)))
    layer_names = {l.name for l in layers}
    if len(layer_names) != len(layers):
        raise ArchitectureSchemaError("duplicate layer name")
    edges: list[Edge] = []
    for i, e in enumerate(raw.get("allowed_dependencies", []) or []):
        src = _require(e, "from", f"allowed_dependencies[{i}]")
        dst = _require(e, "to", f"allowed_dependencies[{i}]")
        if isinstance(dst, str):
            dst = [dst]
        for n in (src, *dst):
            if n not in layer_names:
                raise ArchitectureSchemaError(f"unknown layer {n!r} in edge")
        edges.append(Edge(src=src, dst=tuple(dst)))
    seen_ids: set[str] = set()
    patterns: list[Pattern] = []
    for i, p in enumerate(raw.get("patterns", []) or []):
        pid = _require(p, "id", f"patterns[{i}]")
        if pid in seen_ids:
            raise ArchitectureSchemaError(f"duplicate id {pid!r}")
        seen_ids.add(pid)
        layer = _require(p, "layer", f"patterns[{i}]")
        if layer not in layer_names:
            raise ArchitectureSchemaError(f"patterns[{i}]: unknown layer {layer!r}")
        patterns.append(
            Pattern(
                id=pid,
                layer=layer,
                forbidden_imports=tuple(p.get("forbidden_imports", []) or []),
                required_imports=tuple(p.get("required_imports", []) or []),
                reason=p.get("reason", "") or "",
            )
        )
    rules: list[ReviewRule] = []
    for i, r in enumerate(raw.get("review_rules", []) or []):
        rid = _require(r, "id", f"review_rules[{i}]")
        if rid in seen_ids:
            raise ArchitectureSchemaError(f"duplicate id {rid!r}")
        seen_ids.add(rid)
        applies = _require(r, "applies_to", f"review_rules[{i}]")
        if applies not in layer_names:
            raise ArchitectureSchemaError(
                f"review_rules[{i}]: unknown layer {applies!r}"
            )
        rules.append(
            ReviewRule(id=rid, applies_to=applies, rule=_require(r, "rule", f"review_rules[{i}]"))
        )
    return Architecture(
        version=version,
        style=style,
        layers=tuple(layers),
        allowed_dependencies=tuple(edges),
        patterns=tuple(patterns),
        review_rules=tuple(rules),
    )
```

4. Run `python -m pytest tests/test_validate_architecture.py -q` — expect PASS.

5. Commit:

```bash
git add scripts/harness/validate_architecture.py tests/test_validate_architecture.py
git commit -m "feat(arch-leash): add architecture.yaml schema validator"
```

- [x] **Task 1 complete**

<!-- task-meta
id: T01
touches:
  - scripts/harness/validate_architecture.py
  - tests/test_validate_architecture.py
depends: []
verify: python -m pytest tests/test_validate_architecture.py -q
acceptance: null
-->

---

### Task 2 — `architecture-extractor` subagent

The plugin-scoped subagent that converts free-form architecture prose into a
proposed `architecture.yaml`. This task only creates the agent definition
file (frontmatter + system prompt); the skill that dispatches it ships in T08.

**Files:**
- Create: `agents/architecture-extractor.md`
- Modify or create: `tests/test_agents.py` (append the new test if file exists)

**Steps:**

1. Write the failing test — append to `tests/test_agents.py` (create if absent):

```python
"""Tests for plugin-scoped agent definitions."""
import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _frontmatter(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} missing frontmatter"
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end])


def test_architecture_extractor_definition():
    fm = _frontmatter(ROOT / "agents" / "architecture-extractor.md")
    assert fm["name"] == "architecture-extractor"
    assert set(fm["tools"]) == {"Read", "Glob", "Grep"}
    assert "extract" in fm["description"].lower()
```

2. Run `python -m pytest tests/test_agents.py::test_architecture_extractor_definition -q`
   — expect FAIL (file does not exist).

3. Create `agents/architecture-extractor.md`:

```markdown
---
name: architecture-extractor
description: Extracts a structured architecture.yaml from free-form prose describing a project's architecture. Returns a proposed spec plus a rationale per rule; never writes files.
tools: [Read, Glob, Grep]
---

# architecture-extractor

You convert a user's free-form description of their project's architecture
into a structured `architecture.yaml` spec that conforms to the schema below.

## Inputs you will receive

1. The user's prose description.
2. The schema (see `templates/task-schema.md` for format conventions and the
   compose-architecture-leash skill for the full architecture.yaml schema).
3. The project's top-level file tree (browse it with `Glob` to ground layer
   path globs in directories that actually exist).

## What you must produce

A single YAML document that conforms to the architecture.yaml schema
(`version: 1`, `style`, `layers`, `allowed_dependencies`, `patterns`,
`review_rules`), wrapped in a fenced block, **followed by** a "Rationale"
section with one bullet per rule explaining why you inferred it.

## Hard rules

- Tools: `Read`, `Glob`, `Grep` only. No `Bash`, no writes.
- Never invent layers the user did not describe. If the user said "domain
  and infrastructure", do not add an "application" layer because Clean
  Architecture usually has one.
- Ground every layer's path glob in a directory that exists in the project.
  Use `Glob` to verify. If a layer has no obvious matching directory, leave
  the path as `[]` and note it in the rationale.
- Every rule gets a stable, snake_case `id`. Use ids derived from intent
  (`domain_pure`, `use_cases_are_classes`) — not numeric counters.
- If the user describes a judgment-level rule ("use cases should be
  classes"), put it in `review_rules`, NOT `patterns`. Patterns are only for
  grep-checkable strings.
- Output the YAML in deterministic order: layers in declaration order, edges
  sorted by `from` then `to[0]`, patterns sorted by `id`, review_rules
  sorted by `id`. This is what lets re-runs produce stable diffs.

## Delta-only mode (when invoked for `add` re-runs)

If the dispatch message includes the marker `MODE: ADD`, return only the
*new* entries as a YAML fragment that the calling skill will merge.
Do not include any existing `layers`/`patterns`/`review_rules` ids. The
calling skill is responsible for merging; you must never restate existing
state.
```

4. Run `python -m pytest tests/test_agents.py::test_architecture_extractor_definition -q`
   — expect PASS.

5. Commit:

```bash
git add agents/architecture-extractor.md tests/test_agents.py
git commit -m "feat(arch-leash): add architecture-extractor subagent"
```

- [x] **Task 2 complete**

<!-- task-meta
id: T02
touches:
  - agents/architecture-extractor.md
  - tests/test_agents.py
depends: []
verify: python -m pytest tests/test_agents.py::test_architecture_extractor_definition -q
acceptance: null
-->

---

### Task 3 — `architecture-reviewer.md.tmpl` template

The templated system prompt for the project-local reviewer agent. Compiled
into the target repo by the compiler, with placeholders replaced by content
derived from `architecture.yaml`.

**Files:**
- Create: `templates/architecture-reviewer.md.tmpl`
- Modify or create: `tests/test_templates.py` (append the new test if file exists)

**Steps:**

1. Write the failing test — append to `tests/test_templates.py` (create if absent):

```python
"""Tests for plugin templates."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_architecture_reviewer_template_placeholders():
    path = ROOT / "templates" / "architecture-reviewer.md.tmpl"
    text = path.read_text(encoding="utf-8")
    for placeholder in (
        "{{ARCHITECTURE_STYLE}}",
        "{{ARCHITECTURE_LAYER_TABLE}}",
        "{{ARCHITECTURE_EDGE_LIST}}",
        "{{ARCHITECTURE_REVIEW_RULES}}",
    ):
        assert placeholder in text, f"template missing {placeholder}"
    assert text.startswith("---\n"), "template needs YAML frontmatter"
    assert "tools: [Read, Glob, Grep]" in text, "reviewer must be read-only"
```

2. Run `python -m pytest tests/test_templates.py::test_architecture_reviewer_template_placeholders -q`
   — expect FAIL.

3. Create `templates/architecture-reviewer.md.tmpl`:

```markdown
---
name: architecture-reviewer
description: Reviews changes against the project's declared architecture (architecture.yaml). Flags forbidden dependency edges and judgment-rule violations. Advisory only — does not block CI.
tools: [Read, Glob, Grep]
---

<!-- GENERATED by scripts/harness/compile_architecture.py from .harness/architecture.yaml -->
<!-- Edit architecture.yaml and recompile; hand edits here will be overwritten. -->

# architecture-reviewer

You review code changes against this project's declared architecture:
**{{ARCHITECTURE_STYLE}}**.

## Layers

{{ARCHITECTURE_LAYER_TABLE}}

## Allowed dependency edges (every other edge is forbidden)

{{ARCHITECTURE_EDGE_LIST}}

## Judgment rules to enforce

{{ARCHITECTURE_REVIEW_RULES}}

## How to review

For each changed file in the diff:

1. Identify which layer it belongs to by its path glob. If it does not match
   any layer, say so explicitly — that itself is a finding.
2. Flag any import or call that crosses a forbidden edge. Cite `file:line`.
3. Flag any violation of a judgment rule whose `applies_to` matches the
   file's layer. Cite `file:line`.
4. Do NOT propose fixes. Do NOT edit code. You have read-only tools.

## Output

Either:

- `PASS` (no findings), or
- a Markdown list of findings, each in the form
  `- [<rule-id>] <file>:<line> — <one-line explanation>`.

Be terse. The reader is the engineer who wrote the change; they don't need a
preamble.
```

4. Run `python -m pytest tests/test_templates.py::test_architecture_reviewer_template_placeholders -q`
   — expect PASS.

5. Commit:

```bash
git add templates/architecture-reviewer.md.tmpl tests/test_templates.py
git commit -m "feat(arch-leash): add architecture-reviewer template"
```

- [x] **Task 3 complete**

<!-- task-meta
id: T03
touches:
  - templates/architecture-reviewer.md.tmpl
  - tests/test_templates.py
depends: []
verify: python -m pytest tests/test_templates.py::test_architecture_reviewer_template_placeholders -q
acceptance: null
-->

---

### Task 4 — `AGENTS.md.tmpl` gets the `OPTIONAL:ARCHITECTURE` block

Add a stub-form `OPTIONAL:ARCHITECTURE` block to `templates/AGENTS.md.tmpl`.
Bootstrap renders the stub; `compose-architecture-leash` later replaces it
with content from `architecture.yaml`. Per the spec (Section 5), the markers
are KEPT in the rendered file so the compiler can find its block.

**Files:**
- Modify: `templates/AGENTS.md.tmpl`
- Modify: `tests/test_templates.py`

**Steps:**

1. Write the failing test — append to `tests/test_templates.py`:

```python
def test_agents_template_has_architecture_block():
    text = (ROOT / "templates" / "AGENTS.md.tmpl").read_text(encoding="utf-8")
    assert "<!-- OPTIONAL:ARCHITECTURE -->" in text
    assert "<!-- /OPTIONAL:ARCHITECTURE -->" in text
    open_idx = text.index("<!-- OPTIONAL:ARCHITECTURE -->")
    close_idx = text.index("<!-- /OPTIONAL:ARCHITECTURE -->")
    body = text[open_idx:close_idx]
    assert "compose-architecture-leash" in body
    assert "## Architecture" in body
```

2. Run `python -m pytest tests/test_templates.py::test_agents_template_has_architecture_block -q`
   — expect FAIL.

3. In `templates/AGENTS.md.tmpl`, after the existing `OPTIONAL:DOMAIN_RULES`
   and `OPTIONAL:UI_RULES` blocks, append:

```markdown

<!-- OPTIONAL:ARCHITECTURE -->
## Architecture

Architecture leash not yet configured — run `compose-architecture-leash` to
set it up. Once configured, the structured spec lives in
[`.harness/architecture.yaml`](.harness/architecture.yaml) and this section
is regenerated from it. The `<!-- OPTIONAL:ARCHITECTURE -->` markers above
and below this paragraph are kept on purpose: the compiler finds its
territory by those markers, so do not delete them.
<!-- /OPTIONAL:ARCHITECTURE -->
```

4. Run `python -m pytest tests/test_templates.py::test_agents_template_has_architecture_block -q`
   — expect PASS.

5. Commit:

```bash
git add templates/AGENTS.md.tmpl tests/test_templates.py
git commit -m "feat(arch-leash): add OPTIONAL:ARCHITECTURE stub to AGENTS template"
```

- [x] **Task 4 complete**

<!-- task-meta
id: T04
touches:
  - templates/AGENTS.md.tmpl
  - tests/test_templates.py
depends: []
verify: python -m pytest tests/test_templates.py::test_agents_template_has_architecture_block -q
acceptance: null
-->

---

### Task 5 — `compile_architecture.py`: generic adapter + traceability

First slice of the compiler. Generates the generic grep-based check scripts
under `.harness/checks/` and appends matching lines to `.harness/gates`,
each tagged with `# arch-leash:<id>`. No Python/JS adapters yet.

**Files:**
- Create: `scripts/harness/compile_architecture.py`
- Create: `tests/fixtures/architecture/min.yaml`
- Create: `tests/test_compile_architecture.py`

**Steps:**

1. Create the fixture — `tests/fixtures/architecture/min.yaml`:

```yaml
version: 1
style: "Test"
layers:
  - {name: a, paths: [src/a/**]}
  - {name: b, paths: [src/b/**]}
allowed_dependencies:
  - {from: a, to: [b]}
patterns:
  - {id: no_requests_in_a, layer: a, forbidden_imports: [requests]}
review_rules: []
```

2. Write the failing test — `tests/test_compile_architecture.py`:

```python
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
```

3. Run `python -m pytest tests/test_compile_architecture.py -q` — expect
   FAIL (compiler does not exist).

4. Implement `scripts/harness/compile_architecture.py` (generic adapter
   only — Python and JS/TS land in T06/T07):

```python
"""Compile .harness/architecture.yaml into gates and check scripts.

Deterministic. No model calls. Re-runnable: every run produces the same
output for the same input. Files emitted carry a GENERATED header so the
compiler knows what it owns; gate lines carry `# arch-leash:<id>` so
removed rules can be pruned cleanly.

Check scripts are emitted as Python (.py) so cycle_done.py — which runs
gates through `subprocess.call(cmd, shell=True)` — can execute them on
Windows, macOS, and Linux without a shell dependency on PATH.
"""
from __future__ import annotations
import json as _json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from scripts.harness.validate_architecture import (
    Architecture,
    Pattern,
    parse_architecture,
)

GENERATED_HEADER_PY = (
    '"""GENERATED by scripts/harness/compile_architecture.py from .harness/architecture.yaml.\n'
    "Edit architecture.yaml and recompile; hand edits here will be overwritten.\n"
    '"""\n'
)


def _emit_pattern_py(pattern: Pattern, arch: Architecture) -> str:
    layer = next(l for l in arch.layers if l.name == pattern.layer)
    forbidden = list(pattern.forbidden_imports)
    globs = list(layer.paths)
    return (
        GENERATED_HEADER_PY
        + f"# Rule: {pattern.id} — forbids {forbidden!r} in layer {pattern.layer!r}\n"
        + "from __future__ import annotations\n"
        + "import pathlib\n"
        + "import re\n"
        + "import sys\n\n"
        + f"FORBIDDEN = {forbidden!r}\n"
        + f"GLOBS = {globs!r}\n"
        + f"RULE_ID = {pattern.id!r}\n\n"
        + "def main() -> int:\n"
        + "    root = pathlib.Path.cwd()\n"
        + "    pat = re.compile(r'(?:^|\\b)(?:import|from)\\s+(' + '|'.join(re.escape(n) for n in FORBIDDEN) + r')\\b')\n"
        + "    violations: list[str] = []\n"
        + "    for glob in GLOBS:\n"
        + "        for path in root.glob(glob):\n"
        + "            if not path.is_file():\n"
        + "                continue\n"
        + "            try:\n"
        + "                text = path.read_text(encoding='utf-8')\n"
        + "            except (OSError, UnicodeDecodeError):\n"
        + "                continue\n"
        + "            for lineno, line in enumerate(text.splitlines(), 1):\n"
        + "                if pat.search(line):\n"
        + "                    violations.append(f\"{path}:{lineno}: {line.strip()}\")\n"
        + "    if violations:\n"
        + "        print(f\"arch-leash: rule {RULE_ID} violated:\")\n"
        + "        for v in violations:\n"
        + "            print(f\"  {v}\")\n"
        + "        return 1\n"
        + "    return 0\n\n"
        + "if __name__ == '__main__':\n"
        + "    raise SystemExit(main())\n"
    )


def _gates_without_arch_lines(text: str) -> list[str]:
    return [
        line for line in text.splitlines(keepends=False)
        if "# arch-leash:" not in line
    ]


def compile_architecture(root: pathlib.Path) -> None:
    arch_path = root / ".harness" / "architecture.yaml"
    arch = parse_architecture(arch_path.read_text(encoding="utf-8"))
    checks_dir = root / ".harness" / "checks"
    checks_dir.mkdir(parents=True, exist_ok=True)

    # Drop any previously-generated check files; we regenerate every time.
    for existing in checks_dir.glob("pattern-*.py"):
        if "GENERATED by scripts/harness/compile_architecture.py" in existing.read_text(encoding="utf-8"):
            existing.unlink()

    new_gate_lines: list[str] = []
    for pattern in arch.patterns:
        script_path = checks_dir / f"pattern-{pattern.id}.py"
        script_path.write_text(_emit_pattern_py(pattern, arch), encoding="utf-8")
        new_gate_lines.append(
            f"python .harness/checks/pattern-{pattern.id}.py  # arch-leash:{pattern.id}"
        )

    gates_path = root / ".harness" / "gates"
    existing = gates_path.read_text(encoding="utf-8") if gates_path.exists() else "# Gates\n"
    kept = _gates_without_arch_lines(existing)
    if kept and kept[-1] != "":
        kept.append("")
    out = "\n".join(kept + new_gate_lines) + "\n"
    gates_path.write_text(out, encoding="utf-8")


def main() -> int:
    compile_architecture(pathlib.Path.cwd())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

5. Run `python -m pytest tests/test_compile_architecture.py -q` — expect PASS.

6. Commit:

```bash
git add scripts/harness/compile_architecture.py tests/test_compile_architecture.py tests/fixtures/architecture/min.yaml
git commit -m "feat(arch-leash): compiler generic adapter + traceability"
```

- [x] **Task 5 complete**

<!-- task-meta
id: T05
touches:
  - scripts/harness/compile_architecture.py
  - tests/test_compile_architecture.py
  - tests/fixtures/architecture/min.yaml
depends: [T01]
verify: python -m pytest tests/test_compile_architecture.py -q
acceptance: null
-->

---

### Task 6 — Python adapter (`import-linter`)

Detects the target project as Python (presence of `pyproject.toml` or
`setup.py`) and emits `.harness/importlinter.ini` with one `forbidden`
contract per implicit forbidden edge — that is, every layer pair that is
NOT in `allowed_dependencies`. Appends `python -m importlinter --config
.harness/importlinter.ini` to `.harness/gates`.

**Files:**
- Modify: `scripts/harness/compile_architecture.py`
- Modify: `tests/test_compile_architecture.py`
- Create: `tests/fixtures/architecture/py.yaml`

**Steps:**

1. Create the fixture — `tests/fixtures/architecture/py.yaml`:

```yaml
version: 1
style: "Clean Architecture"
layers:
  - {name: domain, paths: [src/myapp/domain/**]}
  - {name: application, paths: [src/myapp/application/**]}
  - {name: infrastructure, paths: [src/myapp/infrastructure/**]}
allowed_dependencies:
  - {from: application, to: [domain]}
  - {from: infrastructure, to: [application, domain]}
patterns: []
review_rules: []
```

2. Write the failing test — append to `tests/test_compile_architecture.py`:

```python
import shutil


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
```

3. Run the new tests — expect FAIL (no Python adapter yet).

4. Extend `scripts/harness/compile_architecture.py`. Add at module scope:

```python
GENERATED_HEADER_INI = (
    "; GENERATED by scripts/harness/compile_architecture.py from .harness/architecture.yaml\n"
    "; Edit architecture.yaml and recompile; hand edits here will be overwritten.\n"
)


def _detect_python(root: pathlib.Path) -> bool:
    return (root / "pyproject.toml").exists() or (root / "setup.py").exists()


def _layer_module_root(layer_paths: tuple[str, ...]) -> str:
    """Derive a Python dotted package from a glob like 'src/myapp/domain/**'."""
    for p in layer_paths:
        parts = [seg for seg in p.replace("\\", "/").split("/") if seg and seg != "**"]
        if parts and parts[0] == "src":
            parts = parts[1:]
        if parts:
            return ".".join(parts)
    return ""


def _emit_importlinter_ini(arch: Architecture) -> str:
    allowed: dict[str, set[str]] = {l.name: set() for l in arch.layers}
    for edge in arch.allowed_dependencies:
        allowed[edge.src].update(edge.dst)
    names = [l.name for l in arch.layers]
    forbidden_pairs: list[tuple[str, str]] = [
        (a, b)
        for a in names
        for b in names
        if a != b and b not in allowed[a]
    ]
    out = [GENERATED_HEADER_INI, "[importlinter]\nroot_packages =\n"]
    for layer in arch.layers:
        root = _layer_module_root(layer.paths)
        if root:
            out.append(f"    {root}\n")
    out.append("\n")
    for a, b in forbidden_pairs:
        a_root = _layer_module_root(next(l.paths for l in arch.layers if l.name == a))
        b_root = _layer_module_root(next(l.paths for l in arch.layers if l.name == b))
        out.append(
            f"[importlinter:contract:{a}__to__{b}]\n"
            f"name = {a} must not import {b}\n"
            f"type = forbidden\n"
            f"source_modules =\n    {a_root}\n"
            f"forbidden_modules =\n    {b_root}\n\n"
        )
    return "".join(out)
```

   Then in `compile_architecture()`, after the generic-pattern loop, add:

```python
    if _detect_python(root):
        ini_path = root / ".harness" / "importlinter.ini"
        ini_path.write_text(_emit_importlinter_ini(arch), encoding="utf-8")
        new_gate_lines.append(
            "python -m importlinter --config .harness/importlinter.ini  # arch-leash:py_edges"
        )
```

   (Re-build the `out` string after this so the new gate line is included.)

5. Run `python -m pytest tests/test_compile_architecture.py -q` — expect all PASS.

6. Commit:

```bash
git add scripts/harness/compile_architecture.py tests/test_compile_architecture.py tests/fixtures/architecture/py.yaml
git commit -m "feat(arch-leash): Python adapter via import-linter"
```

- [x] **Task 6 complete**

<!-- task-meta
id: T06
touches:
  - scripts/harness/compile_architecture.py
  - tests/test_compile_architecture.py
  - tests/fixtures/architecture/py.yaml
depends: [T05]
verify: python -m pytest tests/test_compile_architecture.py -q
acceptance: null
-->

---

### Task 7 — JS/TS adapter (`dependency-cruiser`)

Detects the target as JS/TS (presence of `package.json`) and emits
`.harness/dependency-cruiser.json` with `forbidden` rules derived from the
implicit-forbidden edges. Appends a depcruise gate line.

**Files:**
- Modify: `scripts/harness/compile_architecture.py`
- Modify: `tests/test_compile_architecture.py`
- Create: `tests/fixtures/architecture/js.yaml`

**Steps:**

1. Create the fixture — `tests/fixtures/architecture/js.yaml`:

```yaml
version: 1
style: "Layered MVC"
layers:
  - {name: model, paths: [src/model/**]}
  - {name: view,  paths: [src/view/**]}
  - {name: controller, paths: [src/controller/**]}
allowed_dependencies:
  - {from: controller, to: [model, view]}
  - {from: view, to: [model]}
patterns: []
review_rules: []
```

2. Write the failing test — append to `tests/test_compile_architecture.py`:

```python
import json


@pytest.fixture
def js_project(tmp_path):
    proj = tmp_path / "js_proj"
    (proj / ".harness").mkdir(parents=True)
    shutil.copy(FIXTURES / "js.yaml", proj / ".harness" / "architecture.yaml")
    (proj / ".harness" / "gates").write_text("# Gates\n", encoding="utf-8")
    (proj / "package.json").write_text('{"name":"x","version":"0.0.0"}', encoding="utf-8")
    for layer in ("model", "view", "controller"):
        (proj / "src" / layer).mkdir(parents=True)
    return proj


def test_js_adapter_emits_dependency_cruiser_json(js_project):
    _compile(js_project)
    cfg = js_project / ".harness" / "dependency-cruiser.json"
    assert cfg.exists()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    # depcruise allows an array of rules under "forbidden"
    rule_names = {r["name"] for r in data["forbidden"]}
    # model must not depend on view (no edge model -> view declared)
    assert "model__to__view" in rule_names


def test_js_adapter_appends_gate_line(js_project):
    _compile(js_project)
    gates = (js_project / ".harness" / "gates").read_text(encoding="utf-8")
    assert "depcruise" in gates
    assert "# arch-leash:js_edges" in gates
```

3. Run — expect FAIL.

4. Extend `scripts/harness/compile_architecture.py`. Add:

```python
import json as _json


def _detect_js(root: pathlib.Path) -> bool:
    return (root / "package.json").exists()


def _emit_dependency_cruiser(arch: Architecture) -> str:
    allowed: dict[str, set[str]] = {l.name: set() for l in arch.layers}
    for edge in arch.allowed_dependencies:
        allowed[edge.src].update(edge.dst)
    names = [l.name for l in arch.layers]
    forbidden = []
    layer_glob = {l.name: l.paths[0] for l in arch.layers}
    for a in names:
        for b in names:
            if a == b or b in allowed[a]:
                continue
            forbidden.append(
                {
                    "name": f"{a}__to__{b}",
                    "comment": f"{a} must not import {b}",
                    "severity": "error",
                    "from": {"path": layer_glob[a]},
                    "to": {"path": layer_glob[b]},
                }
            )
    payload = {
        "_generated_by": "scripts/harness/compile_architecture.py",
        "forbidden": forbidden,
    }
    return _json.dumps(payload, indent=2) + "\n"
```

   Then in `compile_architecture()`, after the Python-adapter block:

```python
    if _detect_js(root):
        cfg_path = root / ".harness" / "dependency-cruiser.json"
        cfg_path.write_text(_emit_dependency_cruiser(arch), encoding="utf-8")
        new_gate_lines.append(
            "npx --no -- depcruise --config .harness/dependency-cruiser.json src  # arch-leash:js_edges"
        )
```

5. Run `python -m pytest tests/test_compile_architecture.py -q` — expect all PASS.

6. Commit:

```bash
git add scripts/harness/compile_architecture.py tests/test_compile_architecture.py tests/fixtures/architecture/js.yaml
git commit -m "feat(arch-leash): JS/TS adapter via dependency-cruiser"
```

- [x] **Task 7 complete**

<!-- task-meta
id: T07
touches:
  - scripts/harness/compile_architecture.py
  - tests/test_compile_architecture.py
  - tests/fixtures/architecture/js.yaml
depends: [T06]
verify: python -m pytest tests/test_compile_architecture.py -q
acceptance: null
-->

---

### Task 8 — `compose-architecture-leash` skill (first-run flow)

The user-invokable skill. This task delivers the first-run flow only;
re-run modes land in T09. The skill is a Markdown spec that Claude Code
reads at runtime — its "correctness" at this level is structural (the
right sections, the right invocations of subagents and the compiler).

**Files:**
- Create: `skills/compose-architecture-leash/SKILL.md`
- Create: `tests/test_skill_compose.py`

**Steps:**

1. Write the failing test — `tests/test_skill_compose.py`:

```python
"""Structural tests for compose-architecture-leash SKILL.md."""
import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "compose-architecture-leash" / "SKILL.md"


def _frontmatter(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end]), text[end + 5 :]


def test_skill_frontmatter():
    fm, _ = _frontmatter(SKILL)
    assert fm["name"] == "compose-architecture-leash"
    assert "architecture" in fm["description"].lower()


def test_first_run_flow_sections():
    _, body = _frontmatter(SKILL)
    for needle in (
        "Precondition",
        "Detect language stack",
        "Prose interview",
        "architecture-extractor",
        "Confirm-and-edit",
        "compile_architecture.py",
        "OPTIONAL:ARCHITECTURE",
        "Report",
    ):
        assert needle in body, f"first-run section missing: {needle}"


def test_skill_refuses_when_bootstrap_missing():
    _, body = _frontmatter(SKILL)
    assert "CLAUDE.md" in body and "AGENTS.md" in body
    assert "bootstrap-dev-leash" in body
```

2. Run `python -m pytest tests/test_skill_compose.py -q` — expect FAIL.

3. Create `skills/compose-architecture-leash/SKILL.md`:

```markdown
---
name: compose-architecture-leash
description: Use to declare a project's architecture and turn it into enforced guard-rails. Interviews the user in prose, extracts a structured .harness/architecture.yaml via subagent, compiles it into mechanical gates (import-linter for Python, dependency-cruiser for JS/TS, grep fallback elsewhere) and a project-local architecture-reviewer agent. Re-runnable (add / revise / re-describe).
---

# compose-architecture-leash

This skill runs **inside a target project** (not inside the dev-on-leash
plugin repo). The user invokes it after `bootstrap-dev-leash` has been run.
It declares an architecture and turns it into enforced guard-rails.

## When to use

The user wants to add or change architectural enforcement on top of the
existing harness — phrasings like "put the architecture on leash", "set up
clean architecture rules", "add architecture guard-rails", "the
architecture changed, refresh the leash".

## Precondition

Refuse to run if `CLAUDE.md` or `AGENTS.md` is missing from the target —
that means `bootstrap-dev-leash` was not run. Tell the user to run
bootstrap first.

If `.harness/architecture.yaml` already exists, switch to **re-run mode**
(see the re-run section).

## Step 1 — Detect language stack

Read `.claude/settings.json`'s allowlist and `.harness/gates` to infer the
project's stack:

- `pyproject.toml` or `setup.py` present → Python adapter will fire.
- `package.json` present → JS/TS adapter will fire.
- Both: both fire.
- Neither: only the generic grep adapter fires.

No user question. Bootstrap already captured the stack.

## Step 2 — Prose interview

Ask the user a single open question:

> "Describe your project's architecture and the rules you want enforced.
> Layers, who depends on what, what's banned where, what shape
> use-cases/entities/etc. should take. Plain English is fine — be as long
> or as short as you want."

Do NOT offer multiple-choice presets. The declaration model is free-form
prose by design (see spec).

## Step 3 — Subagent extraction

Dispatch the plugin subagent `dev-on-leash:architecture-extractor` with:

- the user's prose,
- a short reminder of the `architecture.yaml` schema (version, style,
  layers, allowed_dependencies, patterns, review_rules),
- the target project's top-level file tree (or instruction to discover it
  via `Glob`).

The subagent returns a proposed YAML body plus a "Rationale" section.

## Step 4 — Confirm-and-edit loop

Show the user the proposed YAML + rationale. Offer three responses:

- **accept** → proceed to Step 5.
- **edit** → ask which field to change, dispatch the extractor again with
  the user's correction and the previous proposal as context, re-show.
- **start over** → re-ask the prose interview.

## Step 5 — Write, compile, re-render AGENTS.md

Once accepted:

1. Write the YAML to `.harness/architecture.yaml`.
2. Run `python scripts/harness/compile_architecture.py` in the target.
   This emits `.harness/checks/pattern-*.sh|ps1`, `.harness/importlinter.ini`
   (if Python), `.harness/dependency-cruiser.json` (if JS/TS), and appends
   `# arch-leash:<id>`-tagged gate lines to `.harness/gates`.
3. Replace the body of the `OPTIONAL:ARCHITECTURE` block in `AGENTS.md`
   between its markers with a human-readable summary derived from the
   YAML: `{{ARCHITECTURE_STYLE}}`, a Markdown table of layers, a bullet
   list of allowed edges, a bullet list of the new gates, and a pointer to
   `architecture.yaml` as the source of truth. Keep the
   `<!-- OPTIONAL:ARCHITECTURE -->` markers in place — the compiler
   identifies its territory by them.
4. Write the project-local reviewer agent to `agents/architecture-reviewer.md`
   from `templates/architecture-reviewer.md.tmpl`, substituting
   `{{ARCHITECTURE_STYLE}}`, `{{ARCHITECTURE_LAYER_TABLE}}`,
   `{{ARCHITECTURE_EDGE_LIST}}`, `{{ARCHITECTURE_REVIEW_RULES}}`.
5. Apply the same diff-and-confirm rule as bootstrap whenever about to
   overwrite a file that may have been hand-edited.

## Step 6 — Report

Summarize, in three or four lines:

- Files created / modified.
- Number of new gate lines and which adapter(s) fired.
- The single command to recompile after a hand-edit of
  `architecture.yaml`: `python scripts/harness/compile_architecture.py`.

## Re-run mode (placeholder — populated in T09)

If `.harness/architecture.yaml` already exists, prompt the user to pick
**add** / **revise** / **re-describe** and follow the corresponding flow.
The details of each mode are added by T09.
```

4. Run `python -m pytest tests/test_skill_compose.py -q` — expect PASS.

5. Commit:

```bash
git add skills/compose-architecture-leash/SKILL.md tests/test_skill_compose.py
git commit -m "feat(arch-leash): compose-architecture-leash skill (first-run flow)"
```

- [x] **Task 8 complete**

<!-- task-meta
id: T08
touches:
  - skills/compose-architecture-leash/SKILL.md
  - tests/test_skill_compose.py
depends: [T01, T02, T03, T04, T05, T06, T07]
verify: python -m pytest tests/test_skill_compose.py -q
acceptance: null
-->

---

### Task 9 — Re-run modes (add / revise / re-describe)

Replaces the placeholder section in the skill with the three re-run flows.

**Files:**
- Modify: `skills/compose-architecture-leash/SKILL.md`
- Modify: `tests/test_skill_compose.py`

**Steps:**

1. Write the failing test — append to `tests/test_skill_compose.py`:

```python
def test_rerun_modes_present():
    _, body = _frontmatter(SKILL)
    for needle in (
        "Re-run mode picker",
        "Mode: add",
        "Mode: revise",
        "Mode: re-describe",
        "MODE: ADD",  # delta marker the extractor recognizes
        "architecture.yaml.bak-",
    ):
        assert needle in body, f"re-run section missing: {needle}"


def test_add_mode_uses_delta_strict_merge():
    _, body = _frontmatter(SKILL)
    # The spec commits to strict merge: extractor returns only the fragment,
    # the SKILL performs the merge. Make sure that wording survives.
    assert "fragment" in body.lower()
    assert "skill performs the merge" in body.lower()
```

2. Run — expect FAIL.

3. Replace the "Re-run mode (placeholder ...)" section of
   `skills/compose-architecture-leash/SKILL.md` with:

```markdown
## Re-run mode picker

When `.harness/architecture.yaml` already exists, ask the user one
multiple-choice question:

- **add** — describe a new architectural aspect to layer on top.
- **revise** — change one or more existing rules by id.
- **re-describe** — re-extract the whole spec from a fresh description.

### Mode: add

1. Prompt: "What aspect do you want to add? Describe just the addition."
2. Dispatch `dev-on-leash:architecture-extractor` with the message header
   `MODE: ADD` so the extractor returns ONLY the new entries as a YAML
   fragment. The extractor must not restate or rewrite any existing entry.
3. The **skill performs the merge** into `architecture.yaml` — the
   subagent never touches the existing file. Validate the merged YAML with
   `scripts/harness/validate_architecture.py` before writing.
4. Show a YAML diff (the new entries highlighted) plus rationale.
5. Confirm-and-edit loop, then recompile and re-render AGENTS.md as in
   first-run Step 5.

### Mode: revise

1. Show the current `architecture.yaml` as a numbered list of rules, each
   labeled with its stable `id`.
2. Prompt: "Which rule(s) by id, and what should change?"
3. Dispatch the extractor with just those rules and the user's correction.
   It returns the rewritten entries; everything else in the YAML is
   preserved byte-for-byte by the skill.
4. Confirm-and-edit loop, then write / compile / re-render.

### Mode: re-describe

1. Same prose interview as first-run.
2. Dispatch the extractor with the full prose.
3. Side-by-side diff between old and new YAML, organized by rule id —
   added, removed, modified — with a rationale per change.
4. Confirm-and-edit loop. The user can accept all, accept selectively by
   id, or start over.
5. On accept: save the old YAML to
   `.harness/architecture.yaml.bak-<UTC ISO timestamp>` (one backup only;
   overwrites any prior `.bak-` for this run — git is the real history).
   Then write the new YAML, recompile, re-render.

## Invariants across all three modes

- The compiler only runs if `architecture.yaml` actually changed.
- Every generated gate line carries `# arch-leash:<id>`. Orphaned lines
  (from removed rules) are pruned on the next compile.
- `agents/architecture-reviewer.md` is FULLY regenerated each compile.
- The `OPTIONAL:ARCHITECTURE` block in `AGENTS.md` is FULLY regenerated
  between its markers.
- Same diff-and-confirm rule as bootstrap applies before overwriting any
  hand-editable file.
```

4. Run `python -m pytest tests/test_skill_compose.py -q` — expect PASS.

5. Commit:

```bash
git add skills/compose-architecture-leash/SKILL.md tests/test_skill_compose.py
git commit -m "feat(arch-leash): re-run modes (add/revise/re-describe)"
```

- [x] **Task 9 complete**

<!-- task-meta
id: T09
touches:
  - skills/compose-architecture-leash/SKILL.md
  - tests/test_skill_compose.py
depends: [T08]
verify: python -m pytest tests/test_skill_compose.py -q
acceptance: null
-->

---

### Task 10 — E2E smoke step in `scripts/smoke_e2e.py`

Extend the existing end-to-end smoke test to drive the architecture leash
once through: drop in a synthetic `architecture.yaml`, compile, plant a
deliberate violation, run a gate, assert it exits non-zero, remove the
violation, assert the gate exits zero.

**Files:**
- Modify: `scripts/smoke_e2e.py`
- Modify: `tests/test_smoke.py` (create if absent — it's a structural test that the smoke script grew the new section).

**Steps:**

1. Write the failing test — append to or create `tests/test_smoke.py`:

```python
"""Structural assertions on scripts/smoke_e2e.py."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_smoke_e2e_includes_architecture_step():
    text = (ROOT / "scripts" / "smoke_e2e.py").read_text(encoding="utf-8")
    assert "compile_architecture" in text
    assert "architecture.yaml" in text
    # Deliberate-violation step that exercises a gate:
    assert "ARCH-LEASH-VIOLATION" in text
```

2. Run `python -m pytest tests/test_smoke.py::test_smoke_e2e_includes_architecture_step -q`
   — expect FAIL.

3. Read the current `scripts/smoke_e2e.py` to find a clean insertion point
   (after the existing harness loop runs, before final assertions). Add a
   new helper section:

```python
# === ARCH-LEASH-VIOLATION: exercise the architecture leash ===
def _exercise_architecture(tmp: pathlib.Path) -> None:
    arch = tmp / ".harness" / "architecture.yaml"
    arch.write_text(
        """version: 1
style: Smoke
layers:
  - {name: a, paths: [src/a/**]}
  - {name: b, paths: [src/b/**]}
allowed_dependencies:
  - {from: a, to: [b]}
patterns:
  - {id: smoke_no_requests, layer: a, forbidden_imports: [requests]}
review_rules: []
""",
        encoding="utf-8",
    )
    (tmp / "src" / "a").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "b").mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "harness" / "compile_architecture.py")],
        cwd=tmp,
        check=True,
    )
    # Plant a violation and assert the gate exits non-zero.
    violator = tmp / "src" / "a" / "bad.py"
    violator.write_text("import requests\n", encoding="utf-8")
    bad = subprocess.run(
        [sys.executable, ".harness/checks/pattern-smoke_no_requests.py"],
        cwd=tmp,
        capture_output=True,
        text=True,
    )
    assert bad.returncode != 0, "gate should reject violation"
    violator.unlink()
    good = subprocess.run(
        [sys.executable, ".harness/checks/pattern-smoke_no_requests.py"],
        cwd=tmp,
        capture_output=True,
        text=True,
    )
    assert good.returncode == 0, "gate should pass when clean"
```

   Call `_exercise_architecture(tmp)` at the appropriate point in the
   script's main flow (after the existing harness checks pass, before
   teardown).

4. Run `python scripts/smoke_e2e.py` locally — expect exit 0.

5. Run `python -m pytest tests/test_smoke.py -q` — expect PASS.

6. Commit:

```bash
git add scripts/smoke_e2e.py tests/test_smoke.py
git commit -m "test(arch-leash): e2e smoke step exercises the new gates"
```

- [x] **Task 10 complete**

<!-- task-meta
id: T10
touches:
  - scripts/smoke_e2e.py
  - tests/test_smoke.py
depends: [T07]
verify: python -m pytest tests/test_smoke.py::test_smoke_e2e_includes_architecture_step -q && python scripts/smoke_e2e.py
acceptance: null
-->

---

### Task 11 — Dogfood on dev-on-leash itself

Per the load-bearing dogfood requirement (memory: `feedback-dogfood`,
spec Section 7). Apply `compose-architecture-leash` to dev-on-leash's own
repo, commit the artifacts, exercise re-run modes, and add a verifier
script that asserts the artifacts exist and a known-bad scenario is
rejected by the gates.

**Files:**
- Create: `.harness/architecture.yaml` (this repo)
- Create: `.harness/importlinter.ini` (this repo, generated)
- Create: `.harness/checks/pattern-*.py` (this repo, generated)
- Create: `agents/architecture-reviewer.md` (this repo, generated — distinct
  from the plugin's `templates/architecture-reviewer.md.tmpl`)
- Modify: `AGENTS.md` (this repo, `OPTIONAL:ARCHITECTURE` block populated)
- Modify: `.harness/gates` (this repo, arch-leash lines appended)
- Create: `scripts/dogfood_architecture.py` (verifier)

**Steps:**

1. Run the skill on this repo. Treat dev-on-leash as the target. Use this
   prose as the architecture description (compresses the project's actual
   shape):

   > "dev-on-leash has three layers. The **harness** layer is
   > `scripts/harness/**` — pure-Python utilities that drive the
   > task/plan/cycle workflow. The **plugin-interface** layer is
   > `agents/**` and `skills/**` and `templates/**` — markdown surfaces
   > the user invokes via Claude Code. The **support** layer is `tests/**`
   > and `docs/**` and `scripts/init.*` and `scripts/smoke_e2e.py`.
   >
   > Allowed edges: support → harness, plugin-interface → (nothing —
   > markdown does not import). Harness must not depend on
   > plugin-interface or anything network-y; specifically, the harness
   > layer is forbidden from importing `requests`, `httpx`, or `urllib3`
   > (we never want the harness phoning home). Tests may import anything.
   >
   > Judgment rules: agents files (`agents/*.md`) must declare a read-only
   > tools allowlist — no `Bash` or `Edit` — except for `verification-gate`
   > which legitimately needs `Bash`."

2. Inspect the proposed YAML, accept (or edit if obviously wrong), write
   it to `.harness/architecture.yaml`. Compile.

3. Hand-verify the artifacts produced:
   - `.harness/architecture.yaml` exists and validates
     (`python -c "from scripts.harness.validate_architecture import parse_architecture; parse_architecture(open('.harness/architecture.yaml').read())"`).
   - `.harness/importlinter.ini` exists with the expected contracts.
   - `.harness/checks/` contains pattern scripts for each forbidden-import
     rule.
   - `.harness/gates` has new `# arch-leash:` lines.
   - `AGENTS.md` `OPTIONAL:ARCHITECTURE` block was populated (markers
     still present).
   - `agents/architecture-reviewer.md` exists with the rendered system
     prompt.

4. **Exercise `add` mode.** Re-run the skill, pick `add`, describe one new
   rule: "Patterns in the harness layer must not import `subprocess` from
   `scripts/harness/_common.py` — it's allowed everywhere else." Confirm
   the diff shows only the addition, confirm `architecture.yaml`'s
   existing entries are byte-identical (`git diff` shows only additions).

5. **Exercise `revise` mode.** Pick a rule by id and revise its `reason`
   field. Confirm only that rule changed.

6. Write the dogfood verifier — `scripts/dogfood_architecture.py`:

```python
"""Asserts the architecture leash is in place on this repo and that gates
fire on a deliberate violation. Run as part of T11's verify command.
"""
from __future__ import annotations
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _require(path: pathlib.Path, desc: str) -> None:
    if not path.exists():
        print(f"MISSING: {desc} ({path})", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    _require(ROOT / ".harness" / "architecture.yaml", "architecture spec")
    _require(ROOT / "agents" / "architecture-reviewer.md", "reviewer agent")
    gates = (ROOT / ".harness" / "gates").read_text(encoding="utf-8")
    if "# arch-leash:" not in gates:
        print("MISSING: arch-leash gate lines in .harness/gates", file=sys.stderr)
        return 1

    # Pick the first arch-leash check script and exercise it with a
    # deliberate violation in a temp file inside the harness layer.
    checks = list((ROOT / ".harness" / "checks").glob("pattern-*.py"))
    if not checks:
        print("MISSING: at least one pattern check", file=sys.stderr)
        return 1
    script = checks[0]
    # Read the FORBIDDEN list literal from the generated script.
    text = script.read_text(encoding="utf-8")
    import re
    import ast

    m = re.search(r"^FORBIDDEN = (.+)$", text, re.MULTILINE)
    if not m:
        print(f"unable to extract FORBIDDEN from {script}", file=sys.stderr)
        return 1
    forbidden = ast.literal_eval(m.group(1))
    if not forbidden:
        print(f"FORBIDDEN list empty in {script}", file=sys.stderr)
        return 1
    needle = forbidden[0]
    violator = ROOT / "scripts" / "harness" / "_arch_leash_violator.py"
    violator.write_text(f"import {needle}\n", encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, str(script)], cwd=ROOT, capture_output=True
        )
        if result.returncode == 0:
            print(f"FAIL: gate {script.name} accepted a violation", file=sys.stderr)
            return 1
    finally:
        violator.unlink(missing_ok=True)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

7. Commit everything (the generated artifacts and the verifier):

```bash
git add .harness/architecture.yaml .harness/importlinter.ini .harness/checks/ .harness/gates agents/architecture-reviewer.md AGENTS.md scripts/dogfood_architecture.py
git commit -m "dogfood(arch-leash): apply leash to dev-on-leash itself"
```

8. Run the verifier locally: `python scripts/dogfood_architecture.py` —
   expect `OK`.

- [x] **Task 11 complete**

<!-- task-meta
id: T11
touches:
  - .harness/architecture.yaml
  - .harness/importlinter.ini
  - .harness/gates
  - agents/architecture-reviewer.md
  - AGENTS.md
  - scripts/dogfood_architecture.py
depends: [T01, T02, T03, T04, T05, T06, T07, T08, T09, T10]
verify: python scripts/dogfood_architecture.py
acceptance: null
-->

---

## Done criteria

- All eleven tasks ticked by `run_task.py` (not by hand).
- `python scripts/harness/recheck_plan.py docs/plans/architecture-leash.md`
  passes — every ticked task re-verifies cleanly.
- `python scripts/smoke_e2e.py` exits 0.
- `python scripts/dogfood_architecture.py` exits 0 with the new violator
  scenario.
- `pyproject.toml` version is bumped (post-merge concern; not a task here —
  the `harness-hardening` plan established the rhythm of bumping at cycle
  close).
