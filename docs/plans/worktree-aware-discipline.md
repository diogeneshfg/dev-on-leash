# Worktree-Aware Branch Discipline Implementation Plan

> **For agentic workers:** Execute this plan task-by-task. A task that carries a `task-meta` block is verified and checkbox-ticked by `scripts/harness/run_task.py` — never tick those by hand. Tasks without a `task-meta` block are human-run. (Execution skills such as superpowers `subagent-driven-development` work well here but are optional.)

**Goal:** Make git worktrees a first-class, opt-in part of the branch-discipline workflow — bootstrap-time `.gitignore` opt-in, a voluntary `leash-start-work` skill that delegates the worktree mechanism, and an advisory `cycle_done` cleanup reminder for proactive worktrees.

**Architecture:** Add a *proactive* worktree path (`.worktrees/<slug>` on `<type>/<slug>` branches, branched from `main`) alongside the existing *reactive* session-leash worktrees, which stay untouched. dev-on-leash owns the convention, `.gitignore` ownership, and guardrails; it delegates the actual `git worktree add` to `EnterWorktree` / `superpowers:using-git-worktrees` with a documented fallback. Cleanup of proactive worktrees is advisory-only (a printed reminder), because they are developer-owned feature branches that may have an open PR.

**Tech Stack:** Python 3 (harness scripts + pytest), Markdown skill/template/doc files. Spec: [docs/superpowers/specs/2026-06-08-worktree-aware-discipline-design.md](docs/superpowers/specs/2026-06-08-worktree-aware-discipline-design.md).

---

## File Structure

**Create:**
- `skills/leash-start-work/SKILL.md` — the new voluntary proactive-worktree skill.
- `tests/test_skill_start_work.py` — structural assertions for the new skill.
- `tests/harness/test_cycle_done_advise.py` — tests for the advisory cleanup reminder.

**Modify:**
- `scripts/harness/cycle_done.py` — generalize `_worktree_branches`; add `advise_merged_worktrees`; call it from `main()`.
- `skills/bootstrap-dev-leash/SKILL.md` — add the opt-in worktree interview item (Step 2) and the `.worktrees/` gitignore patch (Step 3c).
- `tests/test_skill_bootstrap.py` — assert the skill documents the `.worktrees/` opt-in.
- `templates/AGENTS.md.tmpl` — document the proactive branch+worktree start path.
- `templates/CLAUDE.md.tmpl` — mention `/leash-start-work` near the Concurrent-sessions note.
- `tests/test_templates.py` — assert the templates document the start path.
- `tests/test_docs.py` — assert the README documents the workflow.
- `README.md` — add the worktree-aware workflow section.
- `.gitignore` — dogfood: add `.worktrees/` to this repo's own ignore file.

---

### Task 1 — `cycle_done` advisory cleanup reminder

**Files:**
- Modify: `scripts/harness/cycle_done.py`
- Test: `tests/harness/test_cycle_done_advise.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/harness/test_cycle_done_advise.py`:

```python
"""cycle_done advisory-reminder tests for proactive <type>/<slug> worktrees."""
from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.harness.cycle_done import advise_merged_worktrees


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "t@t"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "t"], cwd=path)
    (path / "README").write_text("seed\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=path)


def _add_worktree(repo: Path, rel_dir: str, branch: str) -> Path:
    wt = repo / rel_dir
    subprocess.check_call(
        ["git", "worktree", "add", str(wt), "-b", branch, "main"], cwd=repo,
    )
    return wt


def test_advises_merged_feature_worktree_without_removing(tmp_path: Path):
    repo = tmp_path / "p"
    _init_git_repo(repo)
    wt = _add_worktree(repo, ".worktrees/foo", "feat/foo")
    # A fresh branch off main with no extra commits is already merged.
    reminders = advise_merged_worktrees(repo_root=repo)
    assert any("feat/foo" in r for r in reminders), reminders
    assert any(str(wt) in r for r in reminders), reminders
    # Advisory only: the worktree is NOT removed.
    assert wt.exists()


def test_no_advice_for_unmerged_feature_worktree(tmp_path: Path):
    repo = tmp_path / "p"
    _init_git_repo(repo)
    wt = _add_worktree(repo, ".worktrees/bar", "feat/bar")
    (wt / "x.txt").write_text("hi\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=wt)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=wt)
    reminders = advise_merged_worktrees(repo_root=repo)
    assert not any("feat/bar" in r for r in reminders), reminders


def test_no_advice_for_main_checkout(tmp_path: Path):
    # The primary checkout (on main, no "/" in branch name) must never be
    # advised for removal.
    repo = tmp_path / "p"
    _init_git_repo(repo)
    reminders = advise_merged_worktrees(repo_root=repo)
    assert reminders == [], reminders


def test_ignores_session_worktrees(tmp_path: Path):
    # session/* worktrees are auto-swept elsewhere; advisory must skip them.
    repo = tmp_path / "p"
    _init_git_repo(repo)
    _add_worktree(repo, ".worktrees/sess", "session/abc123")
    reminders = advise_merged_worktrees(repo_root=repo)
    assert not any("session/abc123" in r for r in reminders), reminders
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/harness/test_cycle_done_advise.py -q
```

Expected: FAIL — `ImportError: cannot import name 'advise_merged_worktrees' from 'scripts.harness.cycle_done'`.

- [ ] **Step 3: Generalize `_worktree_branches` to accept a prefix filter**

In `scripts/harness/cycle_done.py`, replace the existing `_worktree_branches` function (currently hardcoded to `session/`) with a prefix-parameterized version. The default keeps `sweep_session_worktrees` behavior byte-for-byte identical:

```python
def _worktree_branches(
    repo: Path, *, prefix: str | None = "session/"
) -> list[tuple[Path, str]]:
    """Parse `git worktree list --porcelain` into (path, branch) pairs.

    With `prefix` set (default `"session/"`), returns only worktrees whose
    branch starts with it. With `prefix=None`, returns every branched
    worktree.
    """
    out = _git_out(["worktree", "list", "--porcelain"], repo)
    results: list[tuple[Path, str]] = []
    path: Path | None = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):])
        elif line.startswith("branch refs/heads/") and path is not None:
            branch = line[len("branch refs/heads/"):]
            if prefix is None or branch.startswith(prefix):
                results.append((path, branch))
            path = None
        elif line == "":
            path = None
    return results
```

- [ ] **Step 4: Add the `advise_merged_worktrees` function**

In `scripts/harness/cycle_done.py`, add this function immediately after `sweep_session_worktrees`:

```python
def advise_merged_worktrees(*, repo_root: Path) -> list[str]:
    """Advisory reminders for merged proactive `<type>/<slug>` worktrees.

    Unlike `session/*` worktrees (auto-removed by sweep_session_worktrees),
    proactive worktrees created by `leash-start-work` are developer-owned
    feature branches that may have an open PR. We never remove them — we
    only return a reminder string per merged one. Branches without a `/`
    (e.g. the primary `main`/`master` checkout) and `session/*` branches
    are skipped.
    """
    reminders: list[str] = []
    merged_raw = _git_out(["branch", "--merged"], repo_root)
    merged = {b.strip().lstrip("*+ ").strip() for b in merged_raw.splitlines()}
    for wt_path, branch in _worktree_branches(repo_root, prefix=None):
        if branch.startswith("session/"):
            continue  # auto-swept by sweep_session_worktrees
        if "/" not in branch:
            continue  # main/master and other non-namespaced branches
        if branch not in merged:
            continue
        reminders.append(
            f"reminder: branch {branch} is merged — run "
            f"`git worktree remove {wt_path}` to clean up"
        )
    return reminders
```

- [ ] **Step 5: Call the advisory from `main()` after the session sweep**

In `scripts/harness/cycle_done.py`, inside `main()`, locate the existing `try/except` that calls `sweep_session_worktrees` (inside the `if all(results):` block). Immediately after that `except` clause, add a second guarded block:

```python
        try:
            for msg in advise_merged_worktrees(repo_root=REPO_ROOT):
                print(msg, file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"advise: skipped ({exc})", file=sys.stderr)
```

(Place it so it runs only when `all(results)` is true, after the sweep block and before `return 0`. Never changes the return code.)

- [ ] **Step 6: Run the test to verify it passes**

```bash
python -m pytest tests/harness/test_cycle_done_advise.py -q
```

Expected: PASS (4 passed).

- [ ] **Step 7: Run the existing sweep tests to verify no regression**

```bash
python -m pytest tests/harness/test_cycle_done_session_sweep.py tests/harness/test_cycle_done.py -q
```

Expected: PASS — the `prefix="session/"` default keeps the sweep unchanged.

- [ ] **Step 8: Commit**

```bash
git add scripts/harness/cycle_done.py tests/harness/test_cycle_done_advise.py
git commit -m "feat(cycle-done): advisory reminder for merged proactive worktrees"
```

<!-- task-meta
id: T01
touches:
  - scripts/harness/cycle_done.py
  - tests/harness/test_cycle_done_advise.py
depends: []
verify: python -m pytest tests/harness/test_cycle_done_advise.py tests/harness/test_cycle_done_session_sweep.py -q
acceptance: null
-->

---

### Task 2 — Bootstrap: opt-in `.worktrees/` gitignore patch

**Files:**
- Modify: `skills/bootstrap-dev-leash/SKILL.md`
- Test: `tests/test_skill_bootstrap.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_skill_bootstrap.py`:

```python
def test_skill_documents_worktrees_optin():
    text = SKILL_PATH.read_text(encoding="utf-8")
    # The skill must offer the opt-in .worktrees/ layout and, when accepted,
    # patch .gitignore under the existing # dev-on-leash heading.
    assert ".worktrees/" in text
    assert "# dev-on-leash" in text


def test_skill_worktrees_optin_is_conditional():
    text = SKILL_PATH.read_text(encoding="utf-8").lower()
    # It is opt-in: the skill must frame it as a yes/no choice, not an
    # unconditional patch.
    assert "opt-in" in text or "if the user answered" in text or "if yes" in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_skill_bootstrap.py -q
```

Expected: FAIL — `assert ".worktrees/" in text` fails (the string is not yet in the skill).

- [ ] **Step 3: Add the interview item**

In `skills/bootstrap-dev-leash/SKILL.md`, in the Step 2 interview table, add a row after item 11 (Coverage targets):

```
| 12 | Parallel-work worktree layout? | `AskUserQuestion` (yes / no) | keep or drop the `.worktrees/` gitignore patch (Step 3c) |
```

Then add a note under "Notes on specific items:":

```
- **Worktree layout (item 12):** if yes, Step 3c also adds `.worktrees/` to
  `.gitignore`. This standardizes the proactive parallel-work layout used by
  the `leash-start-work` skill. If no, make no `.worktrees/` change — the skill
  still works but will warn the directory is not ignored. This is opt-in and
  never weakens branch discipline; it only makes N mandatory branches livable
  at once.
```

- [ ] **Step 4: Extend Step 3c with the conditional `.worktrees/` patch**

In `skills/bootstrap-dev-leash/SKILL.md`, in the "Step 3c — Patch the target project's `.gitignore`" section, after the existing block that ensures `.harness/exceptions.log` and `.harness/sessions/` are present, add:

```
If the user opted in to the worktree layout (interview item 12), also ensure
`.worktrees/` is present, under the same `# dev-on-leash` heading:

​```
.worktrees/
​```

This is the proactive parallel-work directory created by `leash-start-work`;
ignoring it keeps worktree checkouts out of commits. Idempotent — an exact
match anywhere in the file counts as present; never duplicate. If the user
declined item 12, make no `.worktrees/` change.
```

(Use a real triple-backtick fence in the skill; the zero-width characters above are only to display the fence inside this plan.)

- [ ] **Step 5: Update the Step 5 report bullet**

In `skills/bootstrap-dev-leash/SKILL.md`, in "Step 5 — Report", add a bullet:

```
- Whether the `.worktrees/` parallel-work layout was standardized (interview
  item 12) — if so, `.worktrees/` was added to `.gitignore`.
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
python -m pytest tests/test_skill_bootstrap.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add skills/bootstrap-dev-leash/SKILL.md tests/test_skill_bootstrap.py
git commit -m "feat(bootstrap): opt-in .worktrees/ gitignore layout"
```

<!-- task-meta
id: T02
touches:
  - skills/bootstrap-dev-leash/SKILL.md
  - tests/test_skill_bootstrap.py
depends: []
verify: python -m pytest tests/test_skill_bootstrap.py -q
acceptance: null
-->

---

### Task 3 — New skill: `leash-start-work`

**Files:**
- Create: `skills/leash-start-work/SKILL.md`
- Test: `tests/test_skill_start_work.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_skill_start_work.py`:

```python
"""Structural assertions for the leash-start-work skill markdown."""
from __future__ import annotations

from pathlib import Path

SKILL_PATH = Path("skills/leash-start-work/SKILL.md")


def test_skill_file_exists():
    assert SKILL_PATH.exists()


def test_skill_has_frontmatter_name():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: leash-start-work" in text


def test_documents_type_slug_convention():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "<type>/<slug>" in text
    for t in ("feat", "fix", "refactor", "docs", "chore"):
        assert t in text


def test_branches_from_main():
    text = SKILL_PATH.read_text(encoding="utf-8")
    # The worktree branch is created from main/master, not HEAD.
    assert "git worktree add .worktrees/" in text
    assert "main" in text


def test_delegates_to_worktree_tooling():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "EnterWorktree" in text
    assert "using-git-worktrees" in text
    # Documented fallback command when neither is available.
    assert "git worktree add .worktrees/<slug> -b <type>/<slug> main" in text


def test_warns_when_not_ignored():
    text = SKILL_PATH.read_text(encoding="utf-8").lower()
    assert ".gitignore" in text
    assert "warn" in text or "not ignored" in text


def test_refuses_main():
    text = SKILL_PATH.read_text(encoding="utf-8").lower()
    # Never land work on main/master — branch discipline.
    assert "never" in text or "refuse" in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_skill_start_work.py -q
```

Expected: FAIL — `test_skill_file_exists` fails (file does not exist yet).

- [ ] **Step 3: Create the skill file**

Create `skills/leash-start-work/SKILL.md`:

```markdown
---
name: leash-start-work
description: Use to start a new change in its own git worktree — "start a feature", "work on X in parallel", "new branch+worktree". Picks a <type>/<slug> branch off main, delegates the worktree creation to native/superpowers tooling, and keeps you on the disciplined path without the stash-dance.
---

# leash-start-work

## When to use

You want to begin a new change — a feature, fix, refactor — and keep it
isolated in its own working directory so you can run several branches in
parallel without the stash-dance (dirty tree blocking `git checkout`, IDE
reindexing, debugger resets). This is the *proactive* worktree path: the
physical version of the mandatory "branch first, edit after" rule.

This skill is **voluntary**. Nothing forces it (unlike `/leash-session-new`,
which the session-leash hook forces when two sessions collide). A developer
who does not need parallelism can still just `git checkout -b <type>/<name>`.

Do NOT use this to escape a session-leash block — that is `/leash-session-new`.

## How

1. **Pick the branch name.** Choose `type` ∈ `feat | fix | refactor | docs |
   chore` and a short kebab-case `slug`. The branch is `<type>/<slug>`; the
   worktree directory is `.worktrees/<slug>` (no type prefix on the dir).
   Validate the slug; **refuse** anything that would land on `main`/`master` —
   branch discipline is mandatory and never overridden here.

2. **Branch from `main`.** The new branch starts from `main`/`master` (not the
   current `HEAD`), honoring the branch-discipline section of `AGENTS.md`.

3. **Delegate the mechanism — do not reimplement `git worktree`.** In order:
   - If the native `EnterWorktree` tool is available, use it.
   - Else if the `superpowers:using-git-worktrees` skill is installed, use it.
   - Else fall back to the documented command:

     ```
     git worktree add .worktrees/<slug> -b <type>/<slug> main
     ```

     (`type ∈ feat|fix|refactor|docs|chore`)

4. **Warn if not ignored.** If `.worktrees/` is not in the project `.gitignore`
   (bootstrap was declined or never run), warn that the worktree directory is
   not ignored before proceeding, and point at `bootstrap-dev-leash` /
   adding `.worktrees/` under the `# dev-on-leash` heading.

5. **Report.** Print the worktree path and remind that every `Edit`, `Write`,
   and file `Read` for this change now happens under `.worktrees/<slug>`.

## Cleanup

When the branch is merged, remove the worktree:

​```
git worktree remove .worktrees/<slug>
​```

`cycle_done.py` prints an advisory reminder for merged `<type>/<slug>`
worktrees, but never removes them for you — feature branches may have an open
PR, so the human decides.

## Constraints

- This skill owns the **convention + guardrails**, not a worktree engine. It
  never reimplements `git worktree`.
- It does NOT copy uncommitted WIP into the new worktree (same stance as
  `/leash-session-new` — start from `main`).
- It never weakens branch discipline; it makes the disciplined path comfortable
  when several changes are in flight.
```

(Replace the zero-width-prefixed fences in the Cleanup section with real
triple-backtick fences; they are escaped only to display inside this plan.)

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_skill_start_work.py -q
```

Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/leash-start-work/SKILL.md tests/test_skill_start_work.py
git commit -m "feat(skill): add leash-start-work proactive worktree skill"
```

<!-- task-meta
id: T03
touches:
  - skills/leash-start-work/SKILL.md
  - tests/test_skill_start_work.py
depends: []
verify: python -m pytest tests/test_skill_start_work.py -q
acceptance: null
-->

---

### Task 4 — Templates: document the proactive start path

**Files:**
- Modify: `templates/AGENTS.md.tmpl`, `templates/CLAUDE.md.tmpl`
- Test: `tests/test_templates.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
def test_agents_template_documents_worktree_start_path():
    text = (ROOT / "templates" / "AGENTS.md.tmpl").read_text(encoding="utf-8")
    assert ".worktrees/" in text
    assert "leash-start-work" in text
    # The proactive path is distinguished from the reactive session leash.
    assert "<type>/<slug>" in text


def test_claude_template_mentions_start_work():
    text = (ROOT / "templates" / "CLAUDE.md.tmpl").read_text(encoding="utf-8")
    assert "leash-start-work" in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_templates.py -q
```

Expected: FAIL — `.worktrees/` / `leash-start-work` not yet in the templates.

- [ ] **Step 3: Add the parallel-work section to `AGENTS.md.tmpl`**

In `templates/AGENTS.md.tmpl`, immediately before the existing `### Concurrent sessions` subsection (near the end of the file), insert:

```markdown
### Parallel work (worktrees)

Branch discipline is mandatory; worktrees are the **opt-in** ergonomics that
make N mandatory branches livable at once. To start a change in its own
working directory without the stash-dance, invoke `/leash-start-work` (or, by
hand, the same convention):

​```bash
git worktree add .worktrees/<slug> -b <type>/<slug> main   # type ∈ feat|fix|refactor|docs|chore
​```

This is the *physical* form of "branch first, edit after": one folder per
branch, branched from `main`. It does not replace the rule — it makes it
comfortable. When the branch is merged, run `git worktree remove
.worktrees/<slug>`; `cycle_done.py` prints an advisory reminder once it is
merged. This is distinct from the reactive session leash below, which fires
only when two Claude Code sessions collide.
```

(Use real triple-backtick fences; the zero-width-prefixed fences above are only
for display inside this plan.)

- [ ] **Step 4: Add the start-work note to `CLAUDE.md.tmpl`**

In `templates/CLAUDE.md.tmpl`, immediately before the existing `## Concurrent sessions` section, insert:

```markdown
## Parallel work (worktrees)

To start a change in its own working directory (parallel branches without the
stash-dance), invoke `/leash-start-work`. It creates `.worktrees/<slug>` on a
`<type>/<slug>` branch off `main` — the physical form of "branch first, edit
after". Opt-in; it never weakens branch discipline. Remove the worktree after
merge with `git worktree remove .worktrees/<slug>`.

```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python -m pytest tests/test_templates.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/AGENTS.md.tmpl templates/CLAUDE.md.tmpl tests/test_templates.py
git commit -m "feat(templates): document proactive worktree start path"
```

<!-- task-meta
id: T04
touches:
  - templates/AGENTS.md.tmpl
  - templates/CLAUDE.md.tmpl
  - tests/test_templates.py
depends: []
verify: python -m pytest tests/test_templates.py -q
acceptance: null
-->

---

### Task 5 — README: document the workflow

**Files:**
- Modify: `README.md`
- Test: `tests/test_docs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_docs.py` (the file uses `pathlib`; this function is self-contained and does not depend on other helpers in the file):

```python
def test_readme_documents_worktree_workflow():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    text = (root / "README.md").read_text(encoding="utf-8")
    assert "leash-start-work" in text
    assert ".worktrees/" in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_docs.py::test_readme_documents_worktree_workflow -q
```

Expected: FAIL — `leash-start-work` not yet in `README.md`.

- [ ] **Step 3: Add the README section**

In `README.md`, add a section documenting the workflow. Place it after the section that describes the session leash / concurrent sessions (search for "session" to locate it); if no such section exists, append at the end before any license/footer. Content:

```markdown
## Parallel work with worktrees (opt-in)

Branch discipline is mandatory — every change on a new `<type>/<slug>` branch
off `main`. Worktrees make running several of those branches at once
comfortable, without the stash-dance.

- **Bootstrap** offers to standardize a `.worktrees/` layout and adds
  `.worktrees/` to `.gitignore` under the `# dev-on-leash` heading.
- **`/leash-start-work`** starts a change in its own worktree:
  `git worktree add .worktrees/<slug> -b <type>/<slug> main`. It delegates the
  mechanism to `EnterWorktree` / `superpowers:using-git-worktrees` when present.
- **`cycle_done.py`** prints an advisory reminder to `git worktree remove`
  once a `<type>/<slug>` branch is merged (it never removes feature worktrees
  for you).

This is distinct from the **session leash**, which reactively creates a sibling
worktree only when two Claude Code sessions collide on the same repo.
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_docs.py::test_readme_documents_worktree_workflow -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_docs.py
git commit -m "docs(readme): document worktree-aware workflow"
```

<!-- task-meta
id: T05
touches:
  - README.md
  - tests/test_docs.py
depends: []
verify: python -m pytest tests/test_docs.py::test_readme_documents_worktree_workflow -q
acceptance: null
-->

---

### Task 6 — Dogfood on this repo + full verification

**Files:**
- Modify: `.gitignore` (this repo's own)

- [ ] **Step 1: Dogfood the gitignore opt-in on this repo**

dev-on-leash dogfoods its own features. Add `.worktrees/` to this repo's
`.gitignore` under the existing `# Harness runtime` heading (the same group as
`.harness/exceptions.log` and `.harness/sessions/`). The resulting block:

```
# Harness runtime
.harness/exceptions.log
.harness/sessions/
.worktrees/
```

- [ ] **Step 2: Dogfood the advisory reminder end-to-end**

Create a real proactive worktree on this repo, confirm it is gitignored, and
confirm the advisory function reports it. A fresh branch off `main` with no
extra commits is already merged into `main`, so no merge step is needed:

```bash
git worktree add .worktrees/dogfood -b chore/dogfood main
git status --porcelain
```

Expected: `git status` shows **no** entry for `.worktrees/` (it is ignored).

```bash
python -c "from pathlib import Path; from scripts.harness.cycle_done import advise_merged_worktrees; print('\n'.join(advise_merged_worktrees(repo_root=Path('.'))))"
```

Expected: a line like
`reminder: branch chore/dogfood is merged — run \`git worktree remove .../.worktrees/dogfood\` to clean up`.

- [ ] **Step 3: Clean up the dogfood worktree**

```bash
git worktree remove .worktrees/dogfood
git branch -d chore/dogfood
```

Expected: both succeed; `.worktrees/` no longer exists.

- [ ] **Step 4: Run the full test suite**

```bash
python -m pytest -q
```

Expected: PASS — entire suite green, including the four new test files/cases.

- [ ] **Step 5: Commit the dogfood gitignore change**

```bash
git add .gitignore
git commit -m "chore(dogfood): ignore .worktrees/ in this repo"
```

<!-- task-meta
id: T06
touches:
  - .gitignore
depends: [T01, T02, T03, T04, T05]
verify: python -m pytest -q
acceptance: full suite green; manual dogfood smoke (Steps 2-3) confirmed by hand
-->

---

## Closeout

After all tasks pass, close the cycle:

```bash
python scripts/harness/cycle_done.py --plan docs/plans/worktree-aware-discipline.md
```

This verifies no pending checkboxes, runs `.harness/gates`, and appends an
`[Unreleased]` CHANGELOG entry. Consider whether this feature warrants a
version bump in `pyproject.toml` + `.claude-plugin/plugin.json` (they must
stay equal — see `tests/test_meta.py`); a minor bump (0.2.0 → 0.3.0) fits a
new user-facing skill, but that is a release decision, not part of this plan.
```
