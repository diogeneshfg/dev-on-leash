# Antagonist Critics Implementation Plan

> **For agentic workers:** Execute this plan task-by-task. A task that carries a `task-meta` block is verified and checkbox-ticked by `scripts/harness/run_task.py` — never tick those by hand. Tasks without a `task-meta` block are human-run. (Execution skills such as superpowers `subagent-driven-development` work well here but are optional.)

**Goal:** Opt-in bootstrap feature: after every spec/plan creation and before user review, the session agent dispatches one antagonist-critic subagent per model configured in `.harness/critics.json` (e.g. Opus + Fable) to refute the document; the agent resolves what it can and justifies the rest.

**Architecture:** A stateless `PostToolUse` hook (`critic_reminder.py`) injects an advisory reminder whenever a spec/plan markdown file is written and `.harness/critics.json` declares models. The hook ships **unconditionally** in `settings.json.tmpl` (no JSON optional blocks exist) and is inert without the config file — `.harness/critics.json` is the single source of truth for on/off and the model list. Prose protocol lives in an `OPTIONAL:ANTAGONIST_CRITICS` block in `AGENTS.md.tmpl`; a new read-only `antagonist-critic` plugin agent carries the fixed adversarial prompt. Init scripts switch to per-file add-only harness copy so re-bootstrap delivers the new hook to existing projects.

**Tech Stack:** Python 3.12+ (stdlib-only hook + pytest; matches `pyproject.toml` `requires-python`), POSIX sh + PowerShell 5.1 (init scripts), Markdown templates/skills. Spec: [docs/superpowers/specs/2026-07-22-antagonist-critics-design.md](../superpowers/specs/2026-07-22-antagonist-critics-design.md).

## Global Constraints

- The hook must **always exit 0**, including on internal error or garbage stdin — it informs, never blocks.
- Path matching is **component-aware** (`pathlib` parts), never substring/glob on the raw string — worktree-nested (`.worktrees/<slug>/docs/plans/x.md`) and Windows backslash paths must match; `node_modules`, `.venv`, `site-packages`, `fixtures` components must not.
- `.harness/critics.json` absent → hook emits nothing. Malformed or `models` empty → treated as off + one-line warning in context.
- Init scripts must remain **add-only**: never overwrite an existing destination file.
- The fixed discipline prose in templates is untouched — this adds an optional block only.
- TDD: every code change lands with its test in the same task. Commits per task on the feature branch (implementation runs in a `.worktrees/<slug>` worktree per branch discipline).

---

## File Structure

**Create:**
- `scripts/harness/critic_reminder.py` — the PostToolUse reminder hook.
- `tests/harness/test_critic_reminder.py` — hook unit tests.
- `agents/antagonist-critic.md` — read-only adversarial critic agent.
- `.harness/critics.json` — dogfood config for this repo.

**Modify:**
- `scripts/init.sh`, `scripts/init.ps1` — per-file add-only harness copy.
- `tests/test_init.py` — per-file copy tests.
- `templates/settings.json.tmpl` — unconditional PostToolUse hook entry.
- `templates/AGENTS.md.tmpl` — `OPTIONAL:ANTAGONIST_CRITICS` block.
- `tests/test_templates.py` — block + hook + JSON-validity render tests.
- `tests/test_agents.py` — antagonist-critic frontmatter test.
- `skills/bootstrap-dev-leash/SKILL.md` — interview item 13, critics.json write step, migration note.
- `tests/test_skill_bootstrap.py` — skill documents the critics opt-in.
- `README.md` + `tests/test_docs.py` — user-facing docs.

**Create (dogfood):**
- `.claude/settings.json` — this repo currently has none; Task 7 creates it.

---

### Task 1 — `critic_reminder.py` hook

**Files:**
- Create: `scripts/harness/critic_reminder.py`
- Test: `tests/harness/test_critic_reminder.py` (create)

**Interfaces:**
- Produces: `is_spec_or_plan(path: Path) -> bool`; `load_models(config_path: Path) -> tuple[list[str] | None, str | None]` (returns `(models, warning)`); `build_context(target: Path, models: list[str]) -> str`; `find_config(start: Path) -> Path | None`; `main() -> int`. Module runnable as `python -m scripts.harness.critic_reminder`.

- [ ] **Step 1: Write the failing tests**

Create `tests/harness/test_critic_reminder.py`:

```python
"""critic_reminder: PostToolUse advisory hook for spec/plan writes."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.harness.critic_reminder import (
    build_context,
    find_config,
    is_spec_or_plan,
    load_models,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


# --- is_spec_or_plan: component-aware matching -------------------------------

@pytest.mark.parametrize("p", [
    "docs/plans/foo.md",
    ".worktrees/feat-x/docs/plans/foo.md",
    "docs/superpowers/specs/2026-07-22-x-design.md",
    "/proj/docs/plans/foo.md",
    # Backslash splitting is platform-independent (_parts), so this case
    # must run — and pass — on POSIX CI too, not only on Windows.
    r"C:\proj\docs\plans\foo.md",
])
def test_matches_spec_and_plan_paths(p):
    assert is_spec_or_plan(Path(p))


@pytest.mark.parametrize("p", [
    "docs/plans/foo.txt",                      # not .md
    "src/plans/foo.md",                        # plans not under docs/
    "docs/notes/foo.md",                       # neither plans nor specs
    "node_modules/pkg/specs/foo.md",           # excluded component
    "tests/fixtures/docs/plans/foo.md",        # excluded component
    ".venv/lib/site-packages/x/specs/a.md",    # excluded component
])
def test_rejects_non_spec_plan_paths(p):
    assert not is_spec_or_plan(Path(p))


# --- load_models -------------------------------------------------------------

def test_load_models_absent_is_off(tmp_path):
    models, warning = load_models(tmp_path / "critics.json")
    assert models is None and warning is None


def test_load_models_valid(tmp_path):
    cfg = tmp_path / "critics.json"
    cfg.write_text('{"models": ["opus", "fable"]}', encoding="utf-8")
    models, warning = load_models(cfg)
    assert models == ["opus", "fable"] and warning is None


@pytest.mark.parametrize("body", ["not json {", '{"models": []}', '{"models": "opus"}', "[]"])
def test_load_models_malformed_warns(tmp_path, body):
    cfg = tmp_path / "critics.json"
    cfg.write_text(body, encoding="utf-8")
    models, warning = load_models(cfg)
    assert models is None
    assert warning and "critics.json" in warning


# --- find_config: ancestor walk from the written file ------------------------

def test_find_config_walks_ancestors(tmp_path):
    (tmp_path / ".harness").mkdir()
    cfg = tmp_path / ".harness" / "critics.json"
    cfg.write_text('{"models": ["opus"]}', encoding="utf-8")
    target = tmp_path / "docs" / "plans" / "p.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    assert find_config(target) == cfg


def test_find_config_none_when_absent(tmp_path):
    target = tmp_path / "docs" / "plans" / "p.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    assert find_config(target) is None


def test_find_config_stops_at_repo_boundary(tmp_path):
    # A config ABOVE an intervening .git (e.g. a stray ~/.harness) must
    # never leak into the repo below it.
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "critics.json").write_text(
        '{"models": ["opus"]}', encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    target = repo / "docs" / "plans" / "p.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    assert find_config(target) is None


# --- build_context -----------------------------------------------------------

def test_build_context_names_models_and_protocol():
    ctx = build_context(Path("docs/plans/p.md"), ["opus", "fable"])
    assert "opus" in ctx and "fable" in ctx
    assert "antagonist" in ctx.lower()
    assert "one round" in ctx.lower()


# --- end-to-end via subprocess: exit 0 always, correct JSON ------------------

def _run_hook(stdin: str) -> subprocess.CompletedProcess:
    # cwd is the plugin repo so `-m scripts.harness...` resolves; the hook
    # itself only looks at the target file's ancestors, never at cwd.
    return subprocess.run(
        [sys.executable, "-m", "scripts.harness.critic_reminder"],
        input=stdin, capture_output=True, text=True,
        cwd=str(ROOT),
    )


def _payload(file_path: str, tool: str = "Write") -> str:
    return json.dumps({"tool_name": tool, "tool_input": {"file_path": file_path}})


def test_hook_emits_context_for_plan_write(tmp_path):
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "critics.json").write_text(
        '{"models": ["opus", "fable"]}', encoding="utf-8")
    target = tmp_path / "docs" / "plans" / "p.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    r = _run_hook(_payload(str(target)))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PostToolUse"
    assert "opus" in hso["additionalContext"]


def test_hook_silent_without_config(tmp_path):
    target = tmp_path / "docs" / "plans" / "p.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    r = _run_hook(_payload(str(target)))
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_hook_silent_for_unwatched_tool():
    r = _run_hook(_payload("docs/plans/p.md", tool="Bash"))
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_hook_exit_zero_on_garbage_stdin():
    r = _run_hook("not json at all {{{")
    assert r.returncode == 0


def test_hook_warns_on_malformed_config(tmp_path):
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "critics.json").write_text("{broken", encoding="utf-8")
    target = tmp_path / "docs" / "plans" / "p.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    r = _run_hook(_payload(str(target)))
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert "critics.json" in out["hookSpecificOutput"]["additionalContext"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/harness/test_critic_reminder.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.harness.critic_reminder'`

- [ ] **Step 3: Write the implementation**

Create `scripts/harness/critic_reminder.py`:

```python
"""PostToolUse hook: remind the agent to dispatch antagonist critics.

Fires after Edit/Write/MultiEdit/NotebookEdit on a spec/plan markdown
file when the project's .harness/critics.json declares critic models.
Advisory only: it emits hookSpecificOutput.additionalContext and ALWAYS
exits 0 — it informs, it never blocks. .harness/critics.json is the
single source of truth: absent file = feature off; malformed file or an
empty model list = off plus a one-line warning so it gets fixed.

Path matching is component-aware (never substring on the raw string) so
worktree-nested paths (.worktrees/<slug>/docs/plans/x.md) and Windows
backslash paths behave identically. The config is discovered by walking
the written file's ancestors, which resolves to the containing checkout
in linked worktrees without invoking git.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path, PureWindowsPath

WATCHED_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
EXCLUDED_COMPONENTS = frozenset({"node_modules", ".venv", "site-packages", "fixtures"})


def _parts(path: Path) -> tuple[str, ...]:
    """Path components, splitting on both separators regardless of platform."""
    if "\\" in str(path):
        return PureWindowsPath(str(path)).parts
    return path.parts


def is_spec_or_plan(path: Path) -> bool:
    """True for *.md under a docs/plans pair or any specs/ component."""
    parts = _parts(path)
    if not parts or not parts[-1].lower().endswith(".md"):
        return False
    if EXCLUDED_COMPONENTS.intersection(parts):
        return False
    for a, b in zip(parts, parts[1:]):
        if a == "docs" and b == "plans":
            return True
    return "specs" in parts[:-1]


def find_config(start: Path) -> Path | None:
    """Nearest .harness/critics.json within `start`'s own repo.

    Walks the ancestor chain but never past a repo boundary: the first
    ancestor holding a `.git` entry (dir in the main checkout, file in a
    linked worktree) is the last one probed. Without the boundary a stray
    ~/.harness/critics.json would enable critics in every repo below it.
    No .git found at all → treated as no config.
    """
    node = start if start.is_dir() else start.parent
    for ancestor in (node, *node.parents):
        candidate = ancestor / ".harness" / "critics.json"
        if candidate.is_file():
            return candidate
        if (ancestor / ".git").exists():
            return None
    return None


def load_models(config_path: Path) -> tuple[list[str] | None, str | None]:
    """(models, warning). Absent file → (None, None). Bad file → (None, msg)."""
    if not config_path.is_file():
        return None, None
    bad = (
        "ANTAGONIST CRITICS: .harness/critics.json is malformed or lists no "
        "models — antagonist critique is disabled until it is fixed."
    )
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, bad
    models = data.get("models") if isinstance(data, dict) else None
    if (
        isinstance(models, list)
        and models
        and all(isinstance(m, str) and m for m in models)
    ):
        return models, None
    return None, bad


def build_context(target: Path, models: list[str]) -> str:
    names = ", ".join(models)
    return (
        f"ANTAGONIST CRITICS: {target} is a spec/plan document. Before "
        f"presenting it to the user for review, dispatch one antagonist-critic "
        f"subagent per configured model ({names}) in parallel, per the "
        f"AGENTS.md protocol, then resolve what you can and justify the rest. "
        f"One round per presented version — if the critics already ran for "
        f"the version being presented, do not re-dispatch."
    )


def _emit(context: str) -> None:
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": context,
        }
    }))
    sys.stdout.flush()


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    if str(payload.get("tool_name") or "") not in WATCHED_TOOLS:
        return 0
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(raw, str) or not raw:
        return 0
    target = Path(raw)
    if not is_spec_or_plan(target):
        return 0
    try:
        resolved = target.resolve()
    except (OSError, ValueError):
        return 0
    config = find_config(resolved)
    if config is None:
        return 0
    models, warning = load_models(config)
    if warning:
        _emit(warning)
        return 0
    if models:
        _emit(build_context(target, models))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 — a hook crash must never block the write
        raise SystemExit(0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/harness/test_critic_reminder.py -x -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/harness/critic_reminder.py tests/harness/test_critic_reminder.py
git commit -m "feat(harness): critic_reminder PostToolUse hook for spec/plan writes"
```

<!-- task-meta
id: T01
touches:
  - scripts/harness/critic_reminder.py
  - tests/harness/test_critic_reminder.py
depends: []
verify: python -m pytest tests/harness/test_critic_reminder.py -x -q
acceptance: null
-->

---

### Task 2 — Init scripts: per-file add-only harness copy

**Files:**
- Modify: `scripts/init.sh` (section 1, lines ~71–85)
- Modify: `scripts/init.ps1` (section 1, lines ~73–92)
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: `critic_reminder.py` existing in `scripts/harness/` (Task 1).
- Produces: re-running init on a target with an existing `scripts/harness/` copies **missing** files (e.g. the new hook) and never overwrites existing ones.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_init.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_init.py -x -q`
Expected: `test_init_adds_missing_harness_file_without_clobbering` FAILS — the whole-directory skip leaves `critic_reminder.py` missing after the second run.

- [ ] **Step 3: Rewrite section 1 of `scripts/init.sh`**

Replace the entire `if [ -e "$DST_HARNESS" ] ... fi` block (section "1. Copy scripts/harness/") with:

```sh
# ---------------------------------------------------------------------------
# 1. Copy scripts/harness/ — per file, add-only: copy each file that does
#    not exist at the destination; NEVER overwrite an existing file. This
#    lets re-bootstrap deliver newly added harness scripts without
#    clobbering local modifications.
# ---------------------------------------------------------------------------
mkdir -p "$DST_HARNESS"
HARNESS_ADDED=0
HARNESS_KEPT=0
for f in "$SRC_HARNESS"/*; do
    base="$(basename "$f")"
    case "$base" in
        __pycache__|*.pyc) continue ;;
    esac
    [ -f "$f" ] || continue
    if [ -e "$DST_HARNESS/$base" ]; then
        HARNESS_KEPT=$((HARNESS_KEPT + 1))
    else
        cp "$f" "$DST_HARNESS/$base"
        HARNESS_ADDED=$((HARNESS_ADDED + 1))
        COPIED="$COPIED scripts/harness/$base"
    fi
done
printf 'Harness: %s file(s) added, %s existing file(s) left untouched\n' \
    "$HARNESS_ADDED" "$HARNESS_KEPT"
if [ "$HARNESS_KEPT" -gt 0 ]; then
    SKIPPED="$SKIPPED scripts/harness/(existing)"
fi
```

- [ ] **Step 4: Rewrite section 1 of `scripts/init.ps1`**

Replace the entire `if (Test-Path -LiteralPath $DstHarness) { ... } else { ... }` block (section "1. Copy scripts/harness/") with:

```powershell
# ---------------------------------------------------------------------------
# 1. Copy scripts/harness/ -- per file, add-only: copy each file that does
#    not exist at the destination; NEVER overwrite an existing file. This
#    lets re-bootstrap deliver newly added harness scripts without
#    clobbering local modifications.
# ---------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $DstHarness -PathType Container)) {
    New-Item -ItemType Directory -Path $DstHarness -Force | Out-Null
}
$HarnessAdded = 0
$HarnessKept = 0
foreach ($f in Get-ChildItem -LiteralPath $SrcHarness -File) {
    if ($f.Extension -eq '.pyc') { continue }
    $dstFile = Join-Path $DstHarness $f.Name
    if (Test-Path -LiteralPath $dstFile) {
        $HarnessKept++
    } else {
        Copy-Item -LiteralPath $f.FullName -Destination $dstFile
        $HarnessAdded++
        $Copied.Add("scripts/harness/$($f.Name)")
    }
}
Write-Host "Harness: $HarnessAdded file(s) added, $HarnessKept existing file(s) left untouched"
if ($HarnessKept -gt 0) {
    $Skipped.Add('scripts/harness/(existing)')
}
```

(`Get-ChildItem -File` on the top level never descends into `__pycache__`; the harness has no other subdirectories.)

Cross-shell coverage note: `tests/test_init.py::_run_init` branches on `os.name`, so CI (ubuntu) exercises `init.sh` while this Windows dev machine exercises `init.ps1` — each script is tested in exactly one environment. Accepted for now (adding a Windows CI job is out of this plan's scope); run the suite locally on Windows before merging so both paths have been executed somewhere.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_init.py -x -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/init.sh scripts/init.ps1 tests/test_init.py
git commit -m "feat(init): per-file add-only harness copy so re-bootstrap delivers new hooks"
```

<!-- task-meta
id: T02
touches:
  - scripts/init.sh
  - scripts/init.ps1
  - tests/test_init.py
depends: [T01]
verify: python -m pytest tests/test_init.py -x -q
acceptance: null
-->

---

### Task 3 — `antagonist-critic` agent definition

**Files:**
- Create: `agents/antagonist-critic.md`
- Test: `tests/test_agents.py`

**Interfaces:**
- Produces: plugin agent named `antagonist-critic` (tools: Read, Grep, Glob) that the AGENTS.md protocol (Task 4) dispatches with a per-model override.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agents.py`:

```python
def test_antagonist_critic_definition():
    path = ROOT / "agents" / "antagonist-critic.md"
    fm = _frontmatter(path)
    assert fm["name"] == "antagonist-critic"
    assert set(fm["tools"]) == {"Read", "Grep", "Glob"}
    assert "refute" in fm["description"].lower()
    body = path.read_text(encoding="utf-8").lower()
    assert "severity" in body
    assert "do not praise" in body or "must not praise" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents.py -x -q`
Expected: FAIL — file not found.

- [ ] **Step 3: Create `agents/antagonist-critic.md`**

```markdown
---
name: antagonist-critic
description: Adversarial critic that attempts to refute a spec or plan document — false premises, missing scope, ignored risks, unjustified complexity. Dispatched (usually two in parallel on superior models) at the end of spec/plan creation, before user review.
tools: [Read, Grep, Glob]
---

You are an ANTAGONIST CRITIC. You are given the path of a spec or plan
document. Your sole job is to REFUTE it. You do not praise, you do not
balance criticism with compliments, and you do not fix anything.

Method:

1. Read the document in full.
2. Verify its claims against the actual repository — read the files,
   templates, scripts, and tests it references. A claim that contradicts
   the codebase is your highest-value finding.
3. Attack, in order of value: false premises; contradictions with the
   codebase; missing scope; requirements readable two ways; ignored
   risks and alternatives; unjustified complexity; untestable or
   unimplementable requirements.

Output: ONLY a numbered list of objections. Each objection has:

- a severity — BLOCKING, SIGNIFICANT, or MINOR;
- a one-sentence objection;
- a concrete reason with evidence (cite the files you checked).

Rules: do not praise ("must not praise" is absolute). If, after genuine
effort, you cannot refute some section, state explicitly that you tried
and failed to refute it — never invent an objection to fill space. Do
not modify any file.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agents.py -x -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add agents/antagonist-critic.md tests/test_agents.py
git commit -m "feat(agents): antagonist-critic adversarial review agent"
```

<!-- task-meta
id: T03
touches:
  - agents/antagonist-critic.md
  - tests/test_agents.py
depends: []
verify: python -m pytest tests/test_agents.py -x -q
acceptance: null
-->

---

### Task 4 — Templates: AGENTS.md protocol block + settings hook

**Files:**
- Modify: `templates/AGENTS.md.tmpl`
- Modify: `templates/settings.json.tmpl`
- Test: `tests/test_templates.py`

**Interfaces:**
- Consumes: `antagonist-critic` agent name (Task 3); `python -m scripts.harness.critic_reminder` entrypoint (Task 1).
- Produces: `<!-- OPTIONAL:ANTAGONIST_CRITICS -->` markers consumed by bootstrap (Task 5); an unconditional `PostToolUse` hook entry in the settings template.

- [ ] **Step 1: Write the failing tests**

First ensure `import json` is present in the import block at the top of `tests/test_templates.py` (add it if missing). Then append (follow the file's existing read-the-template-as-text pattern):

```python
def test_agents_tmpl_has_antagonist_critics_optional_block():
    text = (ROOT / "templates" / "AGENTS.md.tmpl").read_text(encoding="utf-8")
    assert "<!-- OPTIONAL:ANTAGONIST_CRITICS -->" in text
    assert "<!-- /OPTIONAL:ANTAGONIST_CRITICS -->" in text
    block = text.split("<!-- OPTIONAL:ANTAGONIST_CRITICS -->")[1] \
                .split("<!-- /OPTIONAL:ANTAGONIST_CRITICS -->")[0]
    assert ".harness/critics.json" in block          # single source of truth
    assert "antagonist-critic" in block              # agent to dispatch
    assert "one round" in block.lower()              # per presented version
    assert "{{" not in block                         # no placeholders by design


def test_agents_tmpl_critics_block_is_fully_removable():
    # Spec: "fully removed on opt-out". Rendering is done by the bootstrap
    # skill (an LLM), so what we can pin mechanically is removability: the
    # markers appear exactly once, in order, and excising the marked span
    # leaves a template with no trace of the feature.
    text = (ROOT / "templates" / "AGENTS.md.tmpl").read_text(encoding="utf-8")
    open_m = "<!-- OPTIONAL:ANTAGONIST_CRITICS -->"
    close_m = "<!-- /OPTIONAL:ANTAGONIST_CRITICS -->"
    assert text.count(open_m) == 1 and text.count(close_m) == 1
    start, end = text.index(open_m), text.index(close_m) + len(close_m)
    assert start < end
    removed = text[:start] + text[end:]
    assert "antagonist" not in removed.lower()
    assert "critics.json" not in removed


def test_settings_tmpl_registers_critic_reminder_posttooluse():
    text = (ROOT / "templates" / "settings.json.tmpl").read_text(encoding="utf-8")
    assert "PostToolUse" in text
    assert "scripts.harness.critic_reminder" in text


def test_settings_tmpl_renders_to_valid_json():
    text = (ROOT / "templates" / "settings.json.tmpl").read_text(encoding="utf-8")
    rendered = (
        text.replace("{{TEST_RUNNER_COMMANDS}}", '"Bash(pytest*)"')
            .replace("{{LINT_COMMANDS}}", '"Bash(ruff*)"')
            .replace("{{TYPECHECK_COMMANDS}}", '"Bash(mypy*)"')
            .replace("{{BUILD_COMMANDS}}", '"Bash(make*)"')
    )
    data = json.loads(rendered)
    hooks = data["hooks"]["PostToolUse"]
    assert any(
        "critic_reminder" in h["command"]
        for entry in hooks for h in entry["hooks"]
    )
    matcher = hooks[0]["matcher"]
    for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        assert tool in matcher
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_templates.py -x -q`
Expected: the three new tests FAIL.

- [ ] **Step 3: Add the hook to `templates/settings.json.tmpl`**

Inside the existing `"hooks"` object, after the `"PreToolUse"` array — the closing `]` of `PreToolUse` currently has no trailing comma, so **add a comma after it** — insert:

```json
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python -m scripts.harness.critic_reminder"
          }
        ]
      }
    ]
```

(Unconditional by design: `settings.json.tmpl` has no optional-block mechanism — JSON cannot carry HTML-comment markers. The hook is a fast no-op unless `.harness/critics.json` exists, so conditionality lives entirely in the config file.)

- [ ] **Step 4: Add the optional block to `templates/AGENTS.md.tmpl`**

Insert immediately after the `<!-- /OPTIONAL:UI_RULES -->` closing marker and **before** the `<!-- OPTIONAL:ARCHITECTURE -->` block that follows it, using the same marker convention:

```markdown
<!-- OPTIONAL:ANTAGONIST_CRITICS -->
## Antagonist critics on specs and plans (mandatory when configured)

> **Source of truth:** `.harness/critics.json`. If that file is absent or
> lists no models, this protocol is disabled — delete the file to turn the
> feature off; edit its `models` list to change the critics.

At the end of every spec creation and every plan creation — **before**
asking the user to review the document — dispatch one `antagonist-critic`
subagent per model listed in `.harness/critics.json`, in parallel, using
the Agent tool's `model` override. Point each critic at the document path.
Their sole job is to refute it.

- **One round per presented version.** Substantial edits after a critique
  round re-trigger it; the resolution edits themselves do not.
- **Resolution:** fix every objection you can in the document. For each
  objection you do not fix, record the justification. Present the user the
  refined document plus a criticism → response summary.
- **Failure:** if a critic dispatch fails (model unavailable), say so in
  the summary and proceed with the critics that ran. If ALL critics fail,
  tell the user explicitly that no adversarial review ran — never present
  the document as if it had been critiqued.
- **Scope:** plans live in `docs/plans/`; specs are any `*.md` under a
  `specs/` directory (projects without a spec workflow simply never
  exercise that half). If the session model equals a configured critic
  model, the independence benefit shrinks to fresh-context adversarial
  framing — still run it.
<!-- /OPTIONAL:ANTAGONIST_CRITICS -->
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_templates.py -x -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add templates/AGENTS.md.tmpl templates/settings.json.tmpl tests/test_templates.py
git commit -m "feat(templates): antagonist-critics protocol block + critic_reminder hook"
```

<!-- task-meta
id: T04
touches:
  - templates/AGENTS.md.tmpl
  - templates/settings.json.tmpl
  - tests/test_templates.py
depends: [T01, T03]
verify: python -m pytest tests/test_templates.py -x -q
acceptance: null
-->

---

### Task 5 — Bootstrap skill: interview item 13 + critics.json + migration note

**Files:**
- Modify: `skills/bootstrap-dev-leash/SKILL.md`
- Test: `tests/test_skill_bootstrap.py`

**Interfaces:**
- Consumes: `OPTIONAL:ANTAGONIST_CRITICS` markers (Task 4); `.harness/critics.json` shape `{"models": [...]}` (Task 1's `load_models`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_skill_bootstrap.py`. NOTE: this file defines **no `ROOT` constant** (it reads via a relative `SKILL_PATH`) — the test below resolves its own path and must be pasted exactly as written:

```python
def test_bootstrap_documents_antagonist_critics_opt_in():
    root = Path(__file__).resolve().parents[1]
    text = (root / "skills" / "bootstrap-dev-leash" / "SKILL.md").read_text(
        encoding="utf-8")
    assert "critics.json" in text
    assert "OPTIONAL:ANTAGONIST_CRITICS" in text
    assert "opus" in text and "fable" in text
    # Empty model selection must be treated as opting out (exact phrase
    # from the skill — a bare "no" would match all over the file).
    assert "zero models selected is treated as answering" in text.lower()
```

(If `tests/test_skill_bootstrap.py` does not already import `Path` from `pathlib`, add `from pathlib import Path` to its imports.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skill_bootstrap.py -x -q`
Expected: new test FAILS.

- [ ] **Step 3: Edit `skills/bootstrap-dev-leash/SKILL.md`**

Three edits:

**(a)** Add row 13 to the Step 2 interview table:

```markdown
| 13 | Antagonist critics on specs/plans? | `AskUserQuestion` (yes / no) | keep or drop `OPTIONAL:ANTAGONIST_CRITICS`; write or skip `.harness/critics.json` (Step 3d) |
```

**(b)** Add to the "Notes on specific items" list:

```markdown
- **Antagonist critics (item 13):** if yes, ask a follow-up `AskUserQuestion`
  (multiSelect) for which top-tier models to use as critics — current list:
  `opus`, `fable` — defaulting to both selected. Zero models selected is
  treated as answering "no" to item 13. If yes: keep the
  `OPTIONAL:ANTAGONIST_CRITICS` block in AGENTS.md.tmpl and write
  `.harness/critics.json` in Step 3d. If no: drop the block and write no
  config file. The `critic_reminder` PostToolUse hook is always present in
  the rendered settings.json and is inert without the config file, so this
  choice never touches settings.json. Maintenance note: extend the model
  list here when new top-tier models ship; there is no automatic tier
  discovery. Caveat to relay to the user: if their sessions run on the same
  model as a critic, the independence benefit shrinks to fresh-context
  adversarial framing.
```

Also update the optional-blocks section (Step 3) to list `OPTIONAL:ANTAGONIST_CRITICS` alongside `OPTIONAL:DOMAIN_RULES` / `OPTIONAL:UI_RULES`.

**(c)** Add a new Step 3d after Step 3c:

```markdown
## Step 3d — Write the critics config (item 13 only)

If the user opted in to antagonist critics, write `.harness/critics.json`
with the models they selected:

    {"models": ["opus", "fable"]}

Create `.harness/` if it does not exist. This file is committed project
configuration (do NOT add it to `.gitignore`) and is the feature's single
source of truth: deleting it disables the critics entirely; editing the
`models` list changes which critics run. If the user declined item 13,
write nothing.
```

**(d)** Extend the existing "Migration note" section:

```markdown
Re-running bootstrap also delivers newly added harness files: the init
script copies `scripts/harness/` per file, add-only (existing files are
never overwritten), so an older install gains `critic_reminder.py` on
re-bootstrap, and the re-rendered settings.json registers its PostToolUse
hook. Offer interview item 13 (antagonist critics) to migrating projects
too.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_skill_bootstrap.py -x -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add skills/bootstrap-dev-leash/SKILL.md tests/test_skill_bootstrap.py
git commit -m "feat(bootstrap): antagonist-critics interview item, critics.json, migration note"
```

<!-- task-meta
id: T05
touches:
  - skills/bootstrap-dev-leash/SKILL.md
  - tests/test_skill_bootstrap.py
depends: [T04]
verify: python -m pytest tests/test_skill_bootstrap.py -x -q
acceptance: null
-->

---

### Task 6 — README + docs test

**Files:**
- Modify: `README.md`
- Test: `tests/test_docs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_docs.py` (follow its existing README-assertion pattern):

```python
def test_readme_documents_antagonist_critics():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "antagonist" in text.lower()
    assert ".harness/critics.json" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_docs.py -x -q`
Expected: new test FAILS.

- [ ] **Step 3: Add a README section**

Add under the feature documentation area (near the other harness features), matching the README's existing tone:

```markdown
## Antagonist critics on specs and plans (opt-in)

Bootstrap can enable an adversarial review step: at the end of every spec
and every plan creation — before the document reaches you for review —
the session agent dispatches one `antagonist-critic` subagent per model
listed in `.harness/critics.json` (e.g. Opus and Fable), each prompted
solely to refute the document. The agent fixes what it can and presents
you the refined document plus a criticism → response summary.

- **Configure:** answer yes to the bootstrap interview's antagonist-critics
  question and pick the critic models, or hand-write
  `.harness/critics.json`: `{"models": ["opus", "fable"]}`.
- **Disable:** delete `.harness/critics.json` — it is the single source of
  truth; the `critic_reminder` hook and the AGENTS.md protocol both defer
  to it.
- **Honest scope:** the hook mechanically injects a reminder after every
  spec/plan write; running the critics is protocol (one round per
  presented version), not a hard gate. If every critic dispatch fails, the
  agent must tell you no adversarial review ran.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_docs.py -x -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_docs.py
git commit -m "docs(readme): document opt-in antagonist critics"
```

<!-- task-meta
id: T06
touches:
  - README.md
  - tests/test_docs.py
depends: [T05]
verify: python -m pytest tests/test_docs.py -x -q
acceptance: null
-->

---

### Task 7 — Dogfood on dev-on-leash itself

**Files:**
- Create: `.harness/critics.json`
- Create: `.claude/settings.json` (verified: this repo's `.claude/` is currently empty — there is no existing file to merge with)

- [ ] **Step 1: Write the config**

Create `.harness/critics.json`:

```json
{"models": ["opus", "fable"]}
```

- [ ] **Step 2: Create this repo's `.claude/settings.json`**

The repo has no `.claude/settings.json` today (its other gates are template *outputs* for target projects, deliberately not self-applied — do NOT add `session_gate`/`session_root_guard` here; that is a separate decision this plan must not smuggle in). Create the file with only the critic hook:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python -m scripts.harness.critic_reminder"
          }
        ]
      }
    ]
  }
}
```

Validate: `python -c "import json; json.load(open('.claude/settings.json'))"` → no output, exit 0.

Note: Claude Code snapshots hook config at session start, and this file is authored inside the feature worktree — the live reminder only starts firing in sessions launched after the branch merges to `main`. Step 3 proves the wiring by direct invocation instead.

- [ ] **Step 3: Verify the hook fires end-to-end**

```bash
python -c "import json,subprocess,sys; p=subprocess.run([sys.executable,'-m','scripts.harness.critic_reminder'],input=json.dumps({'tool_name':'Write','tool_input':{'file_path':'docs/plans/antagonist-critics.md'}}),capture_output=True,text=True); out=json.loads(p.stdout); assert 'opus' in out['hookSpecificOutput']['additionalContext']; print('dogfood OK')"
```

Expected: `dogfood OK`

- [ ] **Step 4: Full suite + commit**

Run: `python -m pytest -x -q`
Expected: all PASS

```bash
git add .harness/critics.json .claude/settings.json
git commit -m "chore(dogfood): enable antagonist critics on dev-on-leash itself"
```

(Memory-note evidence: the feature was already dogfooded during design — a 2×Opus critic round against the spec surfaced 2 blocking defects that were folded in before this plan was written. This task makes the mechanism permanent for future specs/plans in this repo.)

<!-- task-meta
id: T07
touches:
  - .harness/critics.json
  - .claude/settings.json
depends: [T01, T06]
verify: |-
  python -c "import json,subprocess,sys; p=subprocess.run([sys.executable,'-m','scripts.harness.critic_reminder'],input=json.dumps({'tool_name':'Write','tool_input':{'file_path':'docs/plans/antagonist-critics.md'}}),capture_output=True,text=True); out=json.loads(p.stdout); assert 'opus' in out['hookSpecificOutput']['additionalContext']"
acceptance: python -m pytest -x -q
-->
