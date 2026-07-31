# Multi-root Workspaces + `workflow: branch` Mode Implementation Plan

> **For agentic workers:** Execute this plan task-by-task. A task that carries a `task-meta` block is verified and checkbox-ticked by `scripts/harness/run_task.py` — never tick those by hand. Tasks without a `task-meta` block are human-run. (Execution skills such as superpowers `subagent-driven-development` work well here but are optional.)

**Goal:** One Claude session driving several sibling repos (VS Code multi-root workspace) no longer creates work in the wrong repo or edits unprotected sibling repos: every harness entry point resolves the *target* repo mechanically (validated `--repo-root`, ambiguity refusal for sibling/child layouts, `--git-common-dir`-based path resolution), and repos may opt into `workflow: branch` — plain disciplined checkouts instead of worktrees — via `.harness/branches.yaml`.

**Architecture:** A new shared resolver (`scripts/harness/repo_resolve.py`) answers "which repo owns this path?" using nearest-existing-ancestor + `git rev-parse --git-common-dir` (the only mechanism that distinguishes main from linked worktrees) and hosts the shared CLI helpers (`resolve_cli_repo_root`, `echo_context`) so every CLI shares one validation + echo path. `branches.py` gains a `workflow` key. `session_gate.py` is rewritten to judge each write by the **target file's** repo and that repo's mode — but only for **leash-managed** repos (main worktree has `.harness/`); all other repos stay untouched, exactly like today. Config is always read from the main worktree, never from a linked checkout.

**Tech Stack:** Python 3.12+ (pyyaml already a dependency), pytest, git CLI, Markdown skills/templates. Spec: [docs/superpowers/specs/2026-07-30-multi-root-branch-mode-design.md](../superpowers/specs/2026-07-30-multi-root-branch-mode-design.md) (rev 2 + post-plan-critique refinements: leash-managed gate scope; tracked-only dirty checks in branch mode).

## Global Constraints

- Missing `.harness/branches.yaml` ⇒ behavior identical to today, plus `workflow == "worktree"`; every existing test keeps passing. A `workflow:` key with an empty value ⇒ the default (`worktree`), matching `_resolve`'s None handling — never an error.
- **Gate scope:** the write gate enforces only on repos whose main worktree contains a `.harness/` directory (leash-managed). Any other repo — cloned dependency, scratch checkout — is allowed, as today. Never make unrelated repos read-only, and never create `.harness/exceptions.log` inside them.
- Malformed config in CLIs is a **hard error**; in the gate it is a **deny with the config error as reason** — never fail-open, never silent.
- `workflow` accepts exactly `worktree` or `branch`; any other non-empty value is a hard `BranchConfigError`.
- Path comparisons never use naive string equality: always `Path.resolve()` + `os.path.normcase`.
- `--repo-root` must resolve to a **main-worktree toplevel**: subdirectory, non-repo, workspace folder, and linked worktree are all refusals with actionable messages.
- Ambiguity refusal (no explicit `--repo-root`): fires when the default root is not a toplevel but has direct-child git repos, OR is a toplevel with sibling dirs containing `.harness/branches.yaml`. **Documented limitation:** this heuristic covers sibling/child layouts only; a `.code-workspace` mixing folders from unrelated parents is not detectable — the SKILL.md therefore mandates always passing `--repo-root` in any multi-root workspace (the workspace-manifest alternative stays deferred per the spec).
- Branch-mode gate is an **allow-list**: main-tree writes allowed only when that repo's HEAD is on `<type>/<slug>` (`^(feat|fix|refactor|docs|chore)/[a-z0-9][a-z0-9-]*$`). Detached, unborn, protected, and non-conforming HEADs are denied. Linked-worktree targets are allowed in both modes.
- New-file writes into not-yet-existing directories resolve via the nearest **existing** ancestor — never the git-failure fail-open path. Fail-open (git binary unusable) is logged (`gate-failopen`), as today.
- **Dirty checks in branch mode (start AND finish): tracked changes only** (porcelain lines not starting `??`). Untracked files warn, never block — in both directions; a scratch `.env` must not brick the mode.
- Branch-mode `finish_work` ends on **`merge_target`** (user decision: never `prod`/`base`). `git branch -D` only after `prove_merged` proof (or skipped under `--keep-branch`); every `-D` audited to `.harness/finish_audit.log`.
- Every CLI run (`start_work`, `finish_work`, `allow_main_write`) echoes: `repo: <path> | config: <.harness/branches.yaml | default> | base: <base> | mode: <workflow>`.
- Offline never blocks: fetch failure ⇒ warn + local refs (unchanged).
- The suite must be green after **every** task (no deliberately-red commits).
- TDD: every code change lands with its test in the same task. Implementation runs in `.worktrees/multi-root-branch-mode` on branch `feat/multi-root-branch-mode` (already created). One commit per task minimum.
- All paths below are relative to the repo root; inside the worktree they live under `.worktrees/multi-root-branch-mode/`.

---

## File Structure

**Create:**
- `scripts/harness/repo_resolve.py` — shared path→repo resolver, `--repo-root` validation, ambiguity detection, CLI helpers (`resolve_cli_repo_root`, `echo_context`). Single source of truth for "which repo owns this path".
- `tests/harness/test_repo_resolve.py`

**Modify:**
- `scripts/harness/branches.py` + `tests/harness/test_branches.py` — `workflow` key, `WORK_BRANCH_RE` moves here.
- `scripts/harness/start_work.py` + `tests/harness/test_start_work.py` — validated root, echo line, branch mode, mode-appropriate slug message.
- `scripts/harness/session_gate.py` + `tests/harness/test_session_gate.py` + `scripts/dogfood_worktree_gate.py` — target-repo resolution, leash-managed scope, per-mode rules, mode-aware messages, malformed-config deny, per-repo marker. (`list_worktrees` is **kept** — `session_root_guard.py` imports it.)
- `scripts/harness/allow_main_write.py` + `tests/harness/test_allow_main_write.py` — validated `--repo-root` + echo.
- `scripts/harness/finish_work.py` + `tests/harness/test_finish_work.py` — branch mode CLI, tracked-only dirty check, ends on `merge_target`, echo.
- `skills/leash-start-work/SKILL.md`, `skills/leash-finish-work/SKILL.md`, `templates/CLAUDE.md.tmpl`, `skills/bootstrap-dev-leash/SKILL.md` + `tests/test_skill_start_work.py`, `tests/test_templates.py`, `tests/test_skill_bootstrap.py` — both modes documented.
- `README.md`, `CHANGELOG.md`, `tests/test_docs.py`, `skills/leash-update/SKILL.md` — user docs + migration/rollout order.

---

### Task 1 — `repo_resolve.py`: shared path→repo resolver

**Files:**
- Create: `scripts/harness/repo_resolve.py`
- Test: `tests/harness/test_repo_resolve.py` (create)

**Interfaces:**
- Produces (later tasks import these exact names from `scripts.harness.repo_resolve`):
  - `class RepoResolveError(RuntimeError)`
  - `@dataclass(frozen=True) class RepoInfo: main_worktree: Path; toplevel: Path; is_linked: bool`
  - `paths_equal(a: Path, b: Path) -> bool`
  - `nearest_existing_dir(path: Path) -> Path | None`
  - `resolve_repo(path: Path) -> RepoInfo | None` — `None` ⇔ genuinely not in a git repo (or bare/submodule-style layout, see comment); **raises `RepoResolveError`** when the git binary itself is unusable (OSError), so callers can distinguish "outside a repo" from "git broken" and keep the fail-open log.
  - `validate_repo_root(path: Path) -> Path` (returns the main-worktree toplevel or raises `RepoResolveError`)
  - `workspace_candidates(root: Path) -> list[Path]` (non-empty ⇔ ambiguity refusal must fire)

- [ ] **Step 1: Write the failing tests**

Create `tests/harness/test_repo_resolve.py`:

```python
"""Tests for the shared path->repo resolver."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.harness.repo_resolve import (
    RepoResolveError,
    nearest_existing_dir,
    paths_equal,
    resolve_repo,
    validate_repo_root,
    workspace_candidates,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.check_call(["git", *args], cwd=repo)


def _init_repo(path: Path, default: str = "main") -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", default)
    _git(path, "config", "user.email", "d@d")
    _git(path, "config", "user.name", "d")
    (path / "seed").write_text("seed\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "seed")


def _add_worktree(repo: Path, slug: str, branch: str) -> Path:
    wt = repo / ".worktrees" / slug
    _git(repo, "worktree", "add", "-b", branch, str(wt), "main")
    return wt


# --- paths_equal / nearest_existing_dir -------------------------------------

def test_paths_equal_normalizes_case_per_platform(tmp_path: Path):
    d = tmp_path / "Repo"
    d.mkdir()
    import os
    same = paths_equal(d, Path(str(d).upper()))
    # On Windows normcase folds case -> equal; on POSIX they differ.
    assert same == (os.path.normcase("A") == os.path.normcase("a"))


def test_nearest_existing_dir_walks_up_through_missing_leaves(tmp_path: Path):
    missing = tmp_path / "a" / "b" / "c" / "new.py"
    assert nearest_existing_dir(missing) == tmp_path


def test_nearest_existing_dir_for_existing_file_is_its_parent(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_text("x", encoding="utf-8")
    assert nearest_existing_dir(f) == tmp_path


# --- resolve_repo ------------------------------------------------------------

def test_resolve_repo_main_worktree(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    info = resolve_repo(repo / "seed")
    assert info is not None
    assert paths_equal(info.main_worktree, repo)
    assert paths_equal(info.toplevel, repo)
    assert info.is_linked is False


def test_resolve_repo_linked_worktree(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    wt = _add_worktree(repo, "sluga", "feat/sluga")
    info = resolve_repo(wt / "seed")
    assert info is not None
    assert info.is_linked is True
    assert paths_equal(info.main_worktree, repo)
    assert paths_equal(info.toplevel, wt)


def test_resolve_repo_new_path_in_new_subdir(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    info = resolve_repo(repo / "newdir" / "deeper" / "new.py")
    assert info is not None
    assert paths_equal(info.main_worktree, repo)


def test_resolve_repo_outside_any_repo(tmp_path: Path):
    assert resolve_repo(tmp_path / "plain.txt") is None


def test_resolve_repo_git_unusable_raises(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "no-such-dir"))
    with pytest.raises(RepoResolveError):
        resolve_repo(tmp_path)


# --- validate_repo_root -------------------------------------------------------

def test_validate_accepts_main_toplevel(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    assert paths_equal(validate_repo_root(repo), repo)


def test_validate_refuses_subdirectory(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    (repo / "sub").mkdir()
    with pytest.raises(RepoResolveError, match="toplevel"):
        validate_repo_root(repo / "sub")


def test_validate_refuses_non_repo(tmp_path: Path):
    with pytest.raises(RepoResolveError, match="not inside a git repository"):
        validate_repo_root(tmp_path)


def test_validate_refuses_linked_worktree(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    wt = _add_worktree(repo, "sluga", "feat/sluga")
    with pytest.raises(RepoResolveError, match="linked worktree"):
        validate_repo_root(wt)


# --- workspace_candidates -----------------------------------------------------

def test_candidates_parent_folder_layout(tmp_path: Path):
    # session rooted at the workspace folder itself
    _init_repo(tmp_path / "repo-a")
    _init_repo(tmp_path / "repo-b")
    got = workspace_candidates(tmp_path)
    assert [p.name for p in got] == ["repo-a", "repo-b"]


def test_candidates_leash_managed_siblings(tmp_path: Path):
    # session rooted in one of several leash-managed sibling repos
    a = tmp_path / "repo-a"
    b = tmp_path / "repo-b"
    _init_repo(a)
    _init_repo(b)
    for r in (a, b):
        (r / ".harness").mkdir()
        (r / ".harness" / "branches.yaml").write_text("base: main\n", encoding="utf-8")
    got = workspace_candidates(a)
    assert [p.name for p in got] == ["repo-a", "repo-b"]


def test_no_candidates_for_plain_siblings(tmp_path: Path):
    # sibling repos WITHOUT .harness must not trigger the refusal
    a = tmp_path / "repo-a"
    _init_repo(a)
    _init_repo(tmp_path / "repo-b")
    assert workspace_candidates(a) == []


def test_no_candidates_single_repo(tmp_path: Path):
    a = tmp_path / "only"
    _init_repo(a)
    assert workspace_candidates(a) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/harness/test_repo_resolve.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.harness.repo_resolve'`

- [ ] **Step 3: Write the implementation**

Create `scripts/harness/repo_resolve.py`:

```python
"""Shared path->repo resolver for multi-root workspaces.

Answers "which repo owns this path?" for every harness entry point.
Uses `git rev-parse --git-common-dir` because `--show-toplevel` alone
cannot distinguish a linked worktree from a main worktree, nor find the
main repo from inside a linked one. New (not-yet-created) paths resolve
via their nearest EXISTING ancestor so file-creating writes never fall
into a git-failure path. All comparisons are normcase-resolved — never
naive string equality (Windows case-insensitivity).

`resolve_repo` returns None for "not in a git repo" and RAISES
RepoResolveError when the git binary is unusable — callers keep their
own fail-open policy (and its audit log) for the latter.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class RepoResolveError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepoInfo:
    main_worktree: Path
    toplevel: Path
    is_linked: bool


def paths_equal(a: Path, b: Path) -> bool:
    try:
        ra, rb = a.resolve(), b.resolve()
    except (OSError, ValueError):
        return False
    return os.path.normcase(str(ra)) == os.path.normcase(str(rb))


def nearest_existing_dir(path: Path) -> Path | None:
    """The deepest existing directory at-or-above `path`, else None."""
    try:
        p = path.resolve()
    except (OSError, ValueError):
        return None
    if p.is_dir():
        return p
    for parent in p.parents:
        if parent.is_dir():
            return parent
    return None


def resolve_repo(path: Path) -> RepoInfo | None:
    """RepoInfo for the repo owning `path`; None when outside any repo.

    None also covers bare repos and submodule/--separate-git-dir layouts
    (common dir not named `.git` — no main worktree we can trust).
    Raises RepoResolveError when git itself cannot run.
    """
    anchor = nearest_existing_dir(path)
    if anchor is None:
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(anchor), "rev-parse",
             "--show-toplevel", "--git-common-dir"],
            capture_output=True, text=True,
        )
    except OSError as exc:
        raise RepoResolveError(f"git is unusable: {exc}") from exc
    if proc.returncode != 0:
        return None
    lines = proc.stdout.splitlines()
    if len(lines) < 2:
        return None
    toplevel = Path(lines[0]).resolve()
    common_raw = Path(lines[1])
    # --git-common-dir may print a path relative to the git -C cwd.
    common = (common_raw if common_raw.is_absolute()
              else anchor / common_raw).resolve()
    if common.name != ".git":
        return None
    main_worktree = common.parent
    return RepoInfo(
        main_worktree=main_worktree,
        toplevel=toplevel,
        is_linked=not paths_equal(toplevel, main_worktree),
    )


def validate_repo_root(path: Path) -> Path:
    """`path` must be a main-worktree toplevel; returns it resolved."""
    resolved = path.resolve()
    info = resolve_repo(resolved)
    if info is None:
        raise RepoResolveError(
            f"{resolved} is not inside a git repository"
        )
    if info.is_linked:
        raise RepoResolveError(
            f"{resolved} is (inside) a linked worktree; --repo-root must be "
            f"the main checkout: {info.main_worktree}"
        )
    if not paths_equal(info.toplevel, resolved):
        raise RepoResolveError(
            f"{resolved} is not a repository toplevel (that repo's toplevel "
            f"is {info.toplevel}); pass the repo root itself"
        )
    return info.main_worktree


def _is_git_repo_dir(p: Path) -> bool:
    return p.is_dir() and (p / ".git").exists()


def workspace_candidates(root: Path) -> list[Path]:
    """Candidate target repos when `root` sits in a multi-root layout.

    Non-empty result == the caller must refuse to run without an
    explicit --repo-root. Two layouts (a heuristic — a .code-workspace
    mixing unrelated parents is NOT detectable; skills mandate an
    explicit --repo-root in any multi-root workspace):
    - `root` is not itself a repo toplevel but has direct-child repos
      (session rooted at the workspace folder);
    - `root` IS a toplevel but sibling dirs are leash-managed (contain
      .harness/branches.yaml) — the field-test layout. Plain sibling
      repos without .harness never trigger this.
    """
    try:
        resolved = root.resolve()
    except (OSError, ValueError):
        return []
    info = resolve_repo(resolved)
    is_toplevel = info is not None and not info.is_linked and paths_equal(
        info.toplevel, resolved
    )
    if not is_toplevel:
        try:
            children = sorted(
                (p for p in resolved.iterdir() if _is_git_repo_dir(p)),
                key=lambda p: os.path.normcase(str(p)),
            )
        except OSError:
            return []
        return children
    try:
        siblings = [
            p for p in resolved.parent.iterdir()
            if p.is_dir() and not paths_equal(p, resolved)
            and (p / ".harness" / "branches.yaml").is_file()
        ]
    except OSError:
        return []
    if not siblings:
        return []
    return sorted([resolved, *siblings],
                  key=lambda p: os.path.normcase(str(p)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/harness/test_repo_resolve.py -x -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add scripts/harness/repo_resolve.py tests/harness/test_repo_resolve.py
git commit -m "feat(harness): shared path->repo resolver for multi-root workspaces"
```

<!-- task-meta
id: T01
touches:
  - scripts/harness/repo_resolve.py
  - tests/harness/test_repo_resolve.py
depends: []
verify: python -m pytest tests/harness/test_repo_resolve.py -x -q
acceptance: null
-->

---

### Task 2 — `branches.py`: `workflow` key + `WORK_BRANCH_RE`

**Files:**
- Modify: `scripts/harness/branches.py`
- Modify: `scripts/harness/start_work.py` (only the `BRANCH_RE` import swap)
- Test: `tests/harness/test_branches.py` (extend)

**Interfaces:**
- Produces:
  - `BranchConfig` gains field `workflow: str` (`"worktree"` or `"branch"`)
  - `WORK_BRANCH_RE = re.compile(r"^(feat|fix|refactor|docs|chore)/([a-z0-9][a-z0-9-]*)$")` exported from `scripts.harness.branches` (moved from `start_work.py`; `start_work` re-imports it)

- [ ] **Step 1: Write the failing tests**

Append to `tests/harness/test_branches.py` (reuse that file's existing `_init_repo`/`_write_cfg` helpers):

```python
# --- workflow key -------------------------------------------------------------

def test_workflow_defaults_to_worktree_when_file_missing(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    assert load_branch_config(repo).workflow == "worktree"


def test_workflow_defaults_to_worktree_when_key_absent(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "base: main\n")
    assert load_branch_config(repo).workflow == "worktree"


def test_workflow_empty_value_defaults_not_errors(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "workflow:\n")
    assert load_branch_config(repo).workflow == "worktree"


def test_workflow_branch_accepted(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "workflow: branch\n")
    assert load_branch_config(repo).workflow == "branch"


def test_workflow_junk_is_hard_error(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "workflow: yolo\n")
    with pytest.raises(BranchConfigError, match="workflow"):
        load_branch_config(repo)


def test_work_branch_re_exported():
    from scripts.harness.branches import WORK_BRANCH_RE
    assert WORK_BRANCH_RE.match("feat/my-slug")
    assert not WORK_BRANCH_RE.match("dev")
    assert not WORK_BRANCH_RE.match("hotfix/x")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/harness/test_branches.py -x -q`
Expected: FAIL — `BranchConfigError: ... unknown key(s): workflow` (and missing attribute/name errors)

- [ ] **Step 3: Implement**

In `scripts/harness/branches.py`:

1. Add near `_REF_RE`:

```python
WORK_BRANCH_RE = re.compile(r"^(feat|fix|refactor|docs|chore)/([a-z0-9][a-z0-9-]*)$")
_ALLOWED_WORKFLOWS = ("worktree", "branch")
```

2. Change `_ALLOWED_KEYS` to `{"base", "merge_target", "long_lived", "workflow"}`.

3. Add `workflow: str` to the `BranchConfig` dataclass.

4. In `load_branch_config`, the missing-file early return gains `workflow="worktree"`; after `_resolve`, add (None handling mirrors `_resolve`'s):

```python
    workflow_raw = raw.get("workflow")
    if workflow_raw is None:
        workflow_raw = "worktree"
    if workflow_raw not in _ALLOWED_WORKFLOWS:
        raise BranchConfigError(
            f"{path}: `workflow: {workflow_raw!r}` must be one of "
            f"{list(_ALLOWED_WORKFLOWS)}"
        )
```

and pass `workflow=workflow_raw` to the returned `BranchConfig`.

5. In `scripts/harness/start_work.py`: delete the local `BRANCH_RE = re.compile(...)` line, add `WORK_BRANCH_RE` to the existing `from scripts.harness.branches import (...)`, rename the two uses (`BRANCH_RE.match` → `WORK_BRANCH_RE.match`), and drop the now-unused `import re`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/harness/test_branches.py tests/harness/test_start_work.py -x -q`
Expected: PASS (start_work suite proves the regex move broke nothing)

- [ ] **Step 5: Commit**

```bash
git add scripts/harness/branches.py scripts/harness/start_work.py tests/harness/test_branches.py
git commit -m "feat(harness): workflow key (worktree|branch) in branches.yaml"
```

<!-- task-meta
id: T02
touches:
  - scripts/harness/branches.py
  - scripts/harness/start_work.py
  - tests/harness/test_branches.py
depends: []
verify: python -m pytest tests/harness/test_branches.py tests/harness/test_start_work.py -x -q
acceptance: null
-->

---

### Task 3 — `repo_resolve.py` CLI helpers + `start_work.py` adoption

**Files:**
- Modify: `scripts/harness/repo_resolve.py`, `scripts/harness/start_work.py`
- Test: `tests/harness/test_repo_resolve.py`, `tests/harness/test_start_work.py` (extend)

**Interfaces:**
- Produces in `scripts.harness.repo_resolve` (T06/T07 import from here — NOT from start_work; every CLI's failure mode is `RepoResolveError`, reported under its own program name):
  - `resolve_cli_repo_root(explicit: Path | None) -> Path` — validates an explicit root, or applies the ambiguity refusal to the default (`CLAUDE_PROJECT_DIR`/cwd). Raises `RepoResolveError`.
  - `echo_context(repo_root: Path, cfg, base: str) -> str` returning `repo: ... | config: ... | base: ... | mode: ...` (each CLI prints it).
- Consumes: `validate_repo_root`, `workspace_candidates` (T01); `cfg.workflow` (T02).

- [ ] **Step 1: Write the failing tests**

Append to `tests/harness/test_repo_resolve.py` (helpers already in the file):

```python
# --- CLI helpers --------------------------------------------------------------

from scripts.harness.repo_resolve import echo_context, resolve_cli_repo_root


def test_cli_explicit_root_validated(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    assert paths_equal(resolve_cli_repo_root(repo), repo)
    (repo / "sub").mkdir()
    with pytest.raises(RepoResolveError, match="toplevel"):
        resolve_cli_repo_root(repo / "sub")


def test_cli_default_ambiguous_siblings_refuses(tmp_path: Path, monkeypatch):
    a, b = tmp_path / "repo-a", tmp_path / "repo-b"
    for r in (a, b):
        _init_repo(r)
        (r / ".harness").mkdir()
        (r / ".harness" / "branches.yaml").write_text("base: main\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(a))
    with pytest.raises(RepoResolveError) as e:
        resolve_cli_repo_root(None)
    assert "repo-a" in str(e.value) and "repo-b" in str(e.value)
    assert "--repo-root" in str(e.value)


def test_cli_default_single_repo_ok(tmp_path: Path, monkeypatch):
    repo = tmp_path / "only"
    _init_repo(repo)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    assert paths_equal(resolve_cli_repo_root(None), repo)


def test_cli_explicit_root_beats_ambiguity(tmp_path: Path, monkeypatch):
    a, b = tmp_path / "repo-a", tmp_path / "repo-b"
    for r in (a, b):
        _init_repo(r)
        (r / ".harness").mkdir()
        (r / ".harness" / "branches.yaml").write_text("base: main\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(a))
    assert paths_equal(resolve_cli_repo_root(a), a)


def test_echo_context_format(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    from scripts.harness.branches import load_branch_config
    cfg = load_branch_config(repo)
    line = echo_context(repo, cfg, "main")
    assert line == f"repo: {repo.resolve()} | config: default | base: main | mode: worktree"
    (repo / ".harness").mkdir()
    (repo / ".harness" / "branches.yaml").write_text(
        "workflow: branch\n", encoding="utf-8")
    cfg = load_branch_config(repo)
    line = echo_context(repo, cfg, "main")
    assert "config: .harness/branches.yaml" in line and "mode: branch" in line
```

Append to `tests/harness/test_start_work.py`:

```python
def test_start_work_prints_echo_line(tmp_path: Path, capsys):
    repo = tmp_path / "r"
    _init_repo(repo)
    start_work(repo_root=repo, branch="feat/echo-check")
    out = capsys.readouterr().out
    assert "repo: " in out and "base: main" in out and "mode: worktree" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/harness/test_repo_resolve.py tests/harness/test_start_work.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'resolve_cli_repo_root'`

- [ ] **Step 3: Implement**

1. Append to `scripts/harness/repo_resolve.py`:

```python
def resolve_cli_repo_root(explicit: Path | None) -> Path:
    """Validated target repo root for a CLI run.

    Explicit --repo-root: validated, always wins. Default root: refused
    when the layout is ambiguous (multi-root workspace) — the refusal
    lists candidates and how to satisfy the gate.
    """
    if explicit is not None:
        return validate_repo_root(explicit)
    default = Path(
        os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    ).resolve()
    candidates = workspace_candidates(default)
    if candidates:
        listing = "\n".join(f"  - {p}" for p in candidates)
        raise RepoResolveError(
            "multiple candidate repos detected (multi-root workspace); "
            "pass --repo-root explicitly. Candidates:\n"
            f"{listing}\n"
            f"(--repo-root {default} keeps the current default)"
        )
    return validate_repo_root(default)


def echo_context(repo_root: Path, cfg, base: str) -> str:
    """One context line every CLI prints: repo | config | base | mode."""
    cfg_path = repo_root / ".harness" / "branches.yaml"
    src = ".harness/branches.yaml" if cfg_path.is_file() else "default"
    return (f"repo: {repo_root.resolve()} | config: {src} | "
            f"base: {base} | mode: {cfg.workflow}")
```

2. In `scripts/harness/start_work.py`:
   - Import: `from scripts.harness.repo_resolve import (RepoResolveError, echo_context, resolve_cli_repo_root)`.
   - In `start_work(...)`, right after the `base` validation block, add `print(echo_context(repo_root, cfg, base))`.
   - In `main()`: `--repo-root` argument gets `default=None`; the call becomes `repo_root=resolve_cli_repo_root(args.repo_root)`, and the existing `except StartWorkError` widens to `except (StartWorkError, RepoResolveError)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/harness/test_repo_resolve.py tests/harness/test_start_work.py -x -q`
Expected: PASS. Existing tests calling `start_work(repo_root=...)` directly are unaffected (validation lives in the CLI path); a lone tmp repo has no candidates.

- [ ] **Step 5: Commit**

```bash
git add scripts/harness/repo_resolve.py scripts/harness/start_work.py tests/harness/test_repo_resolve.py tests/harness/test_start_work.py
git commit -m "feat(harness): shared CLI repo-root resolution + context echo"
```

<!-- task-meta
id: T03
touches:
  - scripts/harness/repo_resolve.py
  - scripts/harness/start_work.py
  - tests/harness/test_repo_resolve.py
  - tests/harness/test_start_work.py
depends: [T01, T02]
verify: python -m pytest tests/harness/test_repo_resolve.py tests/harness/test_start_work.py -x -q
acceptance: null
-->

---

### Task 4 — `start_work.py`: `workflow: branch` mode

**Files:**
- Modify: `scripts/harness/start_work.py`
- Test: `tests/harness/test_start_work.py` (extend)

**Interfaces:**
- Consumes: `cfg.workflow` (T02), start-point resolution already in the file.
- Produces: branch-mode behavior of the same `start_work(...)` entry; returns the repo root (`Path`) in branch mode. Update `start_work`'s docstring: "returns the created worktree path (worktree mode) or the repo root (branch mode)".

- [ ] **Step 1: Write the failing tests**

Append to `tests/harness/test_start_work.py`:

```python
def _cfg_branch_mode(repo: Path, extra: str = "") -> None:
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "branches.yaml").write_text(
        "workflow: branch\n" + extra, encoding="utf-8"
    )


def _head(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
    ).strip()


def test_branch_mode_checks_out_work_branch(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch_mode(repo)
    got = start_work(repo_root=repo, branch="feat/x-one")
    assert got == repo
    assert _head(repo) == "feat/x-one"
    assert not (repo / ".worktrees").exists()


def test_branch_mode_cuts_from_configured_base(tmp_path: Path):
    # the field failure: the branch MUST come off the declared base
    repo = tmp_path / "r"
    _init_repo(repo)
    subprocess.check_call(["git", "branch", "prod"], cwd=repo)
    (repo / "main-only.txt").write_text("m\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=repo)
    subprocess.check_call(["git", "commit", "-q", "-m", "main moves on"], cwd=repo)
    _cfg_branch_mode(repo, "base: prod\nlong_lived: [prod]\n")
    start_work(repo_root=repo, branch="feat/from-prod")
    assert _head(repo) == "feat/from-prod"
    prod_sha = subprocess.check_output(
        ["git", "rev-parse", "prod"], cwd=repo, text=True).strip()
    head_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    assert head_sha == prod_sha        # cut from prod, not from main's tip


def test_branch_mode_behind_base_uses_remote_no_upstream(tmp_path: Path):
    # mirror of the worktree-mode no-track test: stale local base
    origin = tmp_path / "origin"
    _init_repo(origin)
    subprocess.check_call(["git", "branch", "prod"], cwd=origin)
    clone = tmp_path / "clone"
    subprocess.check_call(["git", "clone", "-q", str(origin), str(clone)])
    subprocess.check_call(["git", "config", "user.email", "d@d"], cwd=clone)
    subprocess.check_call(["git", "config", "user.name", "d"], cwd=clone)
    subprocess.check_call(["git", "checkout", "-q", "-b", "prod", "origin/prod"],
                          cwd=clone)
    subprocess.check_call(["git", "checkout", "-q", "main"], cwd=clone)
    # advance origin/prod so the clone's local prod is behind
    subprocess.check_call(["git", "checkout", "-q", "prod"], cwd=origin)
    (origin / "newer.txt").write_text("n\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=origin)
    subprocess.check_call(["git", "commit", "-q", "-m", "newer"], cwd=origin)
    _cfg_branch_mode(clone, "base: prod\nlong_lived: [prod]\n")
    warnings: list[str] = []
    start_work(repo_root=clone, branch="feat/fresh", warn=warnings.append)
    assert _head(clone) == "feat/fresh"
    upstream = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "feat/fresh@{upstream}"],
        cwd=clone, capture_output=True)
    assert upstream.returncode != 0    # --no-track: no upstream set
    assert any("behind" in w for w in warnings)


def test_branch_mode_refuses_tracked_changes(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch_mode(repo)
    (repo / "seed").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(StartWorkError, match="tracked changes"):
        start_work(repo_root=repo, branch="feat/x-one")


def test_branch_mode_untracked_only_warns_not_refuses(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch_mode(repo)
    (repo / "scratch.env").write_text("x\n", encoding="utf-8")
    warnings: list[str] = []
    start_work(repo_root=repo, branch="feat/x-one", warn=warnings.append)
    assert _head(repo) == "feat/x-one"
    assert any("scratch.env" in w for w in warnings)


def test_branch_mode_refuses_when_already_on_work_branch(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch_mode(repo)
    start_work(repo_root=repo, branch="feat/x-one")
    with pytest.raises(StartWorkError, match="already on work branch"):
        start_work(repo_root=repo, branch="feat/x-two")


def test_branch_mode_refuses_existing_branch(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    subprocess.check_call(["git", "branch", "feat/x-one"], cwd=repo)
    _cfg_branch_mode(repo)
    with pytest.raises(StartWorkError, match="already exists"):
        start_work(repo_root=repo, branch="feat/x-one")


def test_protected_slug_message_is_mode_appropriate(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch_mode(repo, "long_lived: [dev]\n")
    with pytest.raises(StartWorkError) as e:
        start_work(repo_root=repo, branch="feat/dev")
    assert ".worktrees" not in str(e.value)     # no false worktree claim
    assert "protected branch" in str(e.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/harness/test_start_work.py -x -q`
Expected: FAIL — branch mode not implemented (a worktree is created; `_head` assert fails).

- [ ] **Step 3: Implement**

In `scripts/harness/start_work.py`:

1. The protected-slug refusal becomes mode-appropriate. It runs after `cfg` is loaded; replace its message construction with:

```python
    if slug in cfg.protected:
        if cfg.workflow == "branch":
            detail = f"branch {branch!r} shadows protected branch {slug!r}"
        else:
            detail = (f"would create .worktrees/{slug}, colliding with "
                      f"protected branch {slug!r}")
        raise StartWorkError(f"slug {slug!r}: {detail}; pick another slug")
```

2. Inside `start_work(...)`, after `start_point, no_track = resolve_start_point(...)` (the echo print from T03 stays above the split), add:

```python
    if cfg.workflow == "branch":
        return _start_branch_mode(
            repo_root=repo_root, branch=branch,
            start_point=start_point, no_track=no_track, warn=warn,
        )
```

and keep the existing worktree tail below it. Move the `.gitignore` `.worktrees/` warning into the worktree-mode tail (branch mode creates no worktree).

3. Add:

```python
def _start_branch_mode(
    *, repo_root: Path, branch: str, start_point: str,
    no_track: bool, warn,
) -> Path:
    status = _run(["status", "--porcelain"], repo_root).stdout.splitlines()
    tracked = [ln for ln in status if ln and not ln.startswith("??")]
    untracked = [ln[3:] for ln in status if ln.startswith("??")]
    if tracked:
        raise StartWorkError(
            "working tree has tracked changes (staged or unstaged); "
            "commit or stash them first — branch mode never carries WIP "
            "into a new branch"
        )
    if untracked:
        warn("untracked files present (they follow you onto the new "
             "branch): " + ", ".join(untracked))
    head = _run(["rev-parse", "--abbrev-ref", "HEAD"], repo_root,
                check=False).stdout.strip()
    if WORK_BRANCH_RE.match(head):
        raise StartWorkError(
            f"already on work branch {head!r} — one demand at a time per "
            "repo in branch mode; finish it first (/leash-finish-work) or "
            "use worktree mode for parallel work"
        )
    if ref_exists(repo_root, f"refs/heads/{branch}"):
        raise StartWorkError(f"branch {branch!r} already exists")
    cmd = ["checkout"]
    if no_track:
        cmd.append("--no-track")
    cmd += ["-b", branch, start_point]
    _run(cmd, repo_root)
    print(f"Checked out {branch} from {start_point} (branch mode)")
    return repo_root
```

4. Update `start_work`'s docstring per the Interfaces note.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/harness/test_start_work.py -x -q`
Expected: PASS (all, including pre-existing worktree-mode tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/harness/start_work.py tests/harness/test_start_work.py
git commit -m "feat(harness): workflow:branch mode in start_work — disciplined checkout, no worktree"
```

<!-- task-meta
id: T04
touches:
  - scripts/harness/start_work.py
  - tests/harness/test_start_work.py
depends: [T03]
verify: python -m pytest tests/harness/test_start_work.py -x -q
acceptance: null
-->

---

### Task 5 — `session_gate.py`: target-repo, leash-managed scope, per-mode rules

**Files:**
- Modify: `scripts/harness/session_gate.py`, `scripts/dogfood_worktree_gate.py`
- Test: `tests/harness/test_session_gate.py` (full rewrite of the decision tests — see Step 1)

**Interfaces:**
- Consumes: `resolve_repo`/`RepoResolveError` (T01), `load_branch_config`/`BranchConfigError`/`WORK_BRANCH_RE` (T02).
- Produces: `decide(*, tool_name: str, tool_input: dict, gate_pid: int = 0) -> Decision` — signature loses `worktrees`/`marker_path`/`log_path` (all derived from the target). `Decision` unchanged. **`list_worktrees` is KEPT unchanged** — `scripts/harness/session_root_guard.py:25` imports it; only `_containing_worktree` is deleted. Message constants: `DENY_MESSAGE_WORKTREE` (updated text below), `deny_message_branch(head: str | None) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/harness/test_session_gate.py` currently has **no** `main()` tests — every test uses the old `decide(worktrees=, marker_path=, log_path=)` signature, and two exercise `list_worktrees`. Rewrite the file: **keep** the module header and the two `list_worktrees` tests verbatim (the function survives); **delete** every old-signature `decide` test (they are superseded by the suite below); **add** the new suite plus one `main()` hook-protocol test (the hook path currently ships untested):

```python
"""Gate tests: multi-repo fixture — the regression test for the field failure."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.harness.session_gate import decide, list_worktrees, main as gate_main


def _git(repo: Path, *args: str) -> None:
    subprocess.check_call(["git", *args], cwd=repo)


def _init_repo(path: Path, default: str = "main") -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", default)
    _git(path, "config", "user.email", "d@d")
    _git(path, "config", "user.name", "d")
    (path / "seed").write_text("seed\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "seed")


def _cfg(repo: Path, text: str) -> None:
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "branches.yaml").write_text(text, encoding="utf-8")


@pytest.fixture()
def workspace(tmp_path: Path):
    """Two sibling leash-managed repos, one per mode; session rooted elsewhere."""
    wt_repo = tmp_path / "repo-worktree"
    br_repo = tmp_path / "repo-branch"
    _init_repo(wt_repo)
    _init_repo(br_repo)
    _cfg(wt_repo, "workflow: worktree\n")
    _cfg(br_repo, "workflow: branch\nlong_lived: [prod, homol, qa, dev]\n"
                  "base: prod\nmerge_target: dev\n")
    for env in ("prod", "homol", "qa", "dev"):
        _git(br_repo, "branch", env)
    return wt_repo, br_repo


def _edit(path: Path):
    return decide(tool_name="Edit", tool_input={"file_path": str(path)})


def test_worktree_repo_main_tree_denied(workspace):
    wt_repo, _ = workspace
    d = _edit(wt_repo / "seed")
    assert not d.allow
    assert "read-only" in d.reason and "--repo-root" in d.reason


def test_worktree_repo_new_subdir_write_denied(workspace):
    # regression: file creation into a not-yet-existing directory
    wt_repo, _ = workspace
    d = decide(tool_name="Write",
               tool_input={"file_path": str(wt_repo / "newdir" / "x.py")})
    assert not d.allow


def test_worktree_repo_linked_worktree_allowed(workspace):
    wt_repo, _ = workspace
    wt = wt_repo / ".worktrees" / "sluga"
    _git(wt_repo, "worktree", "add", "-b", "feat/sluga", str(wt), "main")
    assert _edit(wt / "seed").allow


def test_unmanaged_repo_untouched(tmp_path: Path):
    # a repo WITHOUT .harness (cloned dependency) must never be gated
    plain = tmp_path / "third-party"
    _init_repo(plain)
    assert _edit(plain / "seed").allow
    assert not (plain / ".harness").exists()   # and no .harness side effects


def test_branch_repo_denied_on_protected_branch(workspace):
    _, br_repo = workspace
    _git(br_repo, "checkout", "-q", "dev")
    d = _edit(br_repo / "seed")
    assert not d.allow
    assert "dev" in d.reason and "leash-start-work" in d.reason


def test_branch_repo_denied_on_nonconforming_branch(workspace):
    _, br_repo = workspace
    _git(br_repo, "checkout", "-q", "-b", "experiment")
    assert not _edit(br_repo / "seed").allow


def test_branch_repo_denied_on_detached_head(workspace):
    _, br_repo = workspace
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=br_repo, text=True).strip()
    _git(br_repo, "checkout", "-q", sha)
    assert not _edit(br_repo / "seed").allow


def test_branch_repo_allowed_on_work_branch(workspace):
    _, br_repo = workspace
    _git(br_repo, "checkout", "-q", "-b", "feat/demand-a", "prod")
    assert _edit(br_repo / "seed").allow


def test_branch_repo_linked_worktree_still_allowed(workspace):
    # mixed state: a branch-mode repo with a pre-flip worktree
    _, br_repo = workspace
    wt = br_repo / ".worktrees" / "old"
    _git(br_repo, "worktree", "add", "-b", "feat/old", str(wt), "main")
    _git(br_repo, "checkout", "-q", "dev")
    assert _edit(wt / "seed").allow


def test_malformed_config_denies_with_reason(workspace):
    wt_repo, _ = workspace
    _cfg(wt_repo, "workflow: yolo\n")
    d = _edit(wt_repo / "seed")
    assert not d.allow
    assert "workflow" in d.reason


def test_outside_any_repo_allowed(tmp_path: Path):
    f = tmp_path / "free.txt"
    f.write_text("x", encoding="utf-8")
    assert _edit(f).allow


def test_marker_consumed_in_target_repo(workspace):
    wt_repo, _ = workspace
    marker = wt_repo / ".harness" / "allow-main-write"
    marker.write_text(json.dumps({"schema": 1, "reason": "t"}), encoding="utf-8")
    assert _edit(wt_repo / "seed").allow
    assert not marker.exists()
    assert (wt_repo / ".harness" / "exceptions.log").exists()
    assert not _edit(wt_repo / "seed").allow  # one-shot


def test_marker_works_in_branch_mode_repo(workspace):
    _, br_repo = workspace
    _git(br_repo, "checkout", "-q", "dev")
    marker = br_repo / ".harness" / "allow-main-write"
    marker.write_text(json.dumps({"schema": 1, "reason": "t"}), encoding="utf-8")
    assert _edit(br_repo / "seed").allow
    assert not _edit(br_repo / "seed").allow


def test_main_hook_protocol(workspace, monkeypatch, capsys):
    # the code that actually runs as the PreToolUse hook
    import io, sys
    wt_repo, _ = workspace
    payload = json.dumps({
        "tool_name": "Edit",
        "tool_input": {"file_path": str(wt_repo / "seed")},
    })
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    assert gate_main([]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "deny"
    assert "read-only" in out["reason"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/harness/test_session_gate.py -x -q`
Expected: FAIL — `decide()` rejects the new keyword-only call shape / multi-repo cases misjudged.

- [ ] **Step 3: Implement**

Rewrite the decision core of `scripts/harness/session_gate.py`. Keep `Decision`, `GATED_TOOLS`, `MARKER_NAME`, `EXCEPTIONS_LOG`, `_now_iso`, `_resolve_target`, `_append_log`, **and `list_worktrees`** (imported by `session_root_guard.py`); delete only `_containing_worktree`:

```python
from scripts.harness.branches import (
    BranchConfigError,
    WORK_BRANCH_RE,
    load_branch_config,
)
from scripts.harness.repo_resolve import RepoResolveError, resolve_repo

DENY_MESSAGE_WORKTREE = (
    "SESSION LEASH: this repo's main worktree is read-only. Start your "
    "change in a worktree with /leash-start-work (pass --repo-root for "
    "this repo), then write there. To make a one-off write to the main "
    "tree, run:\n"
    '  python -m scripts.harness.allow_main_write "<reason>" '
    "--repo-root <this repo>\n"
    "and retry — it authorizes exactly one main-tree write and is logged."
)


def deny_message_branch(head: str | None) -> str:
    where = f"HEAD is on {head!r}" if head else "HEAD is detached/unborn"
    return (
        f"SESSION LEASH (branch mode): {where}, not on a <type>/<slug> "
        "work branch. Start your change with /leash-start-work "
        "(pass --repo-root for this repo), then retry. For a one-off "
        "write here, run:\n"
        '  python -m scripts.harness.allow_main_write "<reason>" '
        "--repo-root <this repo>\n"
        "and retry — it authorizes exactly one write and is logged."
    )


def _head_branch(repo_root: Path) -> str | None:
    """Current branch name; None on detached or unborn HEAD."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse",
             "--abbrev-ref", "HEAD"],
            capture_output=True, text=True,
        )
    except (OSError, ValueError):
        return None
    name = proc.stdout.strip()
    if proc.returncode != 0 or not name or name == "HEAD":
        return None
    return name


def _consume_marker(repo_root: Path, target: Path, gate_pid: int) -> bool:
    marker = repo_root / ".harness" / MARKER_NAME
    if not marker.exists():
        return False
    try:
        marker.unlink()
    except FileNotFoundError:
        pass
    _append_log(repo_root / ".harness" / EXCEPTIONS_LOG,
                kind="main-write", gate_pid=gate_pid, target=target)
    return True


def _failopen_log(target: Path | None, gate_pid: int) -> None:
    base = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    try:
        _append_log(base / ".harness" / EXCEPTIONS_LOG,
                    kind="gate-failopen", gate_pid=gate_pid, target=target)
    except OSError:
        pass


def decide(*, tool_name: str, tool_input: dict, gate_pid: int = 0) -> Decision:
    """Judge a write by the TARGET file's repo and that repo's mode.

    Scope: only leash-managed repos (main worktree has .harness/) are
    gated; every other repo behaves exactly as before this gate existed.
    """
    if tool_name not in GATED_TOOLS:
        return Decision(allow=True, reason="")
    target = _resolve_target(tool_input)
    if target is None:
        return Decision(allow=True, reason="")
    try:
        info = resolve_repo(target)
    except RepoResolveError:
        _failopen_log(target, gate_pid)          # git unusable: fail open, audited
        return Decision(allow=True, reason="")
    if info is None:
        return Decision(allow=True, reason="")   # outside any repo
    if info.is_linked:
        return Decision(allow=True, reason="")   # linked worktree: both modes
    main_wt = info.main_worktree
    if not (main_wt / ".harness").is_dir():
        return Decision(allow=True, reason="")   # not leash-managed: untouched
    try:
        cfg = load_branch_config(main_wt)
    except BranchConfigError as exc:
        # Fail CLOSED: one broken YAML must not silently disable the gate.
        return Decision(allow=False, reason=(
            f"SESSION LEASH: cannot judge this write — {exc}. "
            "Fix .harness/branches.yaml and retry."
        ))
    if cfg.workflow == "branch":
        head = _head_branch(main_wt)
        if head is not None and WORK_BRANCH_RE.match(head):
            return Decision(allow=True, reason="")
        if _consume_marker(main_wt, target, gate_pid):
            return Decision(allow=True, reason="one-shot write authorized")
        return Decision(allow=False, reason=deny_message_branch(head))
    # worktree mode: the main tree is read-only
    if _consume_marker(main_wt, target, gate_pid):
        return Decision(allow=True, reason="one-shot main-tree write authorized")
    return Decision(allow=False, reason=DENY_MESSAGE_WORKTREE)
```

`main()` shrinks to: parse stdin JSON, call `decide(tool_name=..., tool_input=..., gate_pid=os.getppid())`, print `d.to_json()`, return 0. Update the module docstring: the gate judges by target-file repo, only for leash-managed repos, supports both workflows, fails closed on malformed config, and fail-opens (audited) only when git itself is unusable.

Rewrite `scripts/dogfood_worktree_gate.py` to the new signature (note `harness.mkdir()` up front — under the leash-managed scope an unmarked repo is not gated at all):

```python
#!/usr/bin/env python3
"""Dogfood the write gate on throwaway repos (both workflow modes)."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.harness.session_gate import decide  # noqa: E402
from scripts.harness.allow_main_write import write_marker  # noqa: E402


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "d@d"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "d"], cwd=path)
    (path / "seed").write_text("seed\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=path)


def _edit(path: Path):
    return decide(tool_name="Edit", tool_input={"file_path": str(path)})


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="dol-wtgate-"))
    repo = parent / "throwaway"
    try:
        _init_repo(repo)
        harness = repo / ".harness"
        harness.mkdir()                      # mark the repo leash-managed
        marker = harness / "allow-main-write"
        log = harness / "exceptions.log"

        d_main = _edit(repo / "README.md")
        assert not d_main.allow, "gate must deny main-tree write"
        assert "/leash-start-work" in d_main.reason

        wt = repo / ".worktrees" / "feat-x"
        subprocess.check_call(
            ["git", "worktree", "add", str(wt), "-b", "feat/x", "main"], cwd=repo)
        d_wt = _edit(wt / "y.py")
        assert d_wt.allow, f"gate must allow inside worktree: {d_wt.reason}"

        write_marker(harness_dir=harness, reason="dogfood")
        d_escape = _edit(repo / "README.md")
        assert d_escape.allow, "one-shot marker must allow"
        assert not marker.exists(), "marker must be consumed"
        assert log.exists() and "main-write" in log.read_text(encoding="utf-8")

        d_again = _edit(repo / "README.md")
        assert not d_again.allow, "second main write must deny after consume"

        # branch mode on a second throwaway repo
        br = parent / "throwaway-branch"
        _init_repo(br)
        (br / ".harness").mkdir()
        (br / ".harness" / "branches.yaml").write_text(
            "workflow: branch\n", encoding="utf-8")
        d_on_main = _edit(br / "seed")
        assert not d_on_main.allow, "branch mode must deny on main"
        subprocess.check_call(
            ["git", "checkout", "-q", "-b", "feat/y", "main"], cwd=br)
        d_on_work = _edit(br / "seed")
        assert d_on_work.allow, f"branch mode must allow on work branch: {d_on_work.reason}"

        print("WORKTREE-GATE DOGFOOD PASS")
        return 0
    except AssertionError as exc:
        print(f"WORKTREE-GATE DOGFOOD FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/harness/test_session_gate.py -x -q` — PASS.
Then the cross-checks this task is responsible for:
- `python -m pytest tests -x -q` — PASS (in particular `tests/harness/test_session_root_guard.py`, which imports `list_worktrees`).
- `python scripts/dogfood_worktree_gate.py` — prints `WORKTREE-GATE DOGFOOD PASS` (this script is executed by `scripts/smoke_e2e.py` step 9, which CI runs — it is *not* covered by pytest, so run it explicitly here).

- [ ] **Step 5: Commit**

```bash
git add scripts/harness/session_gate.py scripts/dogfood_worktree_gate.py tests/harness/test_session_gate.py
git commit -m "feat(harness): session gate judges writes by target repo + workflow mode"
```

<!-- task-meta
id: T05
touches:
  - scripts/harness/session_gate.py
  - scripts/dogfood_worktree_gate.py
  - tests/harness/test_session_gate.py
depends: [T01, T02]
verify: python -m pytest tests/harness/test_session_gate.py tests/harness/test_session_root_guard.py -x -q
acceptance: python scripts/dogfood_worktree_gate.py
-->

---

### Task 6 — `allow_main_write.py`: validated `--repo-root` + echo

**Files:**
- Modify: `scripts/harness/allow_main_write.py`
- Test: `tests/harness/test_allow_main_write.py` (extend — the file **exists** with its own header and `write_marker` tests)

**Interfaces:**
- Consumes: `resolve_cli_repo_root`, `echo_context`, `RepoResolveError` from `scripts.harness.repo_resolve` (T03); `load_branch_config` (T02).
- Produces: `main(argv)` accepts `--repo-root`; marker written to `<target repo>/.harness/allow-main-write` (which T05's gate consumes from the same place); prints the context echo line.

- [ ] **Step 1: Write the failing tests**

Extend `tests/harness/test_allow_main_write.py` — do **not** paste a new file header: add `subprocess` to its existing imports, add `from scripts.harness.allow_main_write import main as amw_main` next to the existing import, and append (reusing/adding the `_init_repo` helper below only if the file lacks one):

```python
def _git_amw(repo: Path, *args: str) -> None:
    subprocess.check_call(["git", *args], cwd=repo)


def _init_amw_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git_amw(path, "init", "-q", "-b", "main")
    _git_amw(path, "config", "user.email", "d@d")
    _git_amw(path, "config", "user.name", "d")
    (path / "seed").write_text("seed\n", encoding="utf-8")
    _git_amw(path, "add", ".")
    _git_amw(path, "commit", "-q", "-m", "seed")


def test_marker_lands_in_target_repo(tmp_path: Path, monkeypatch, capsys):
    session = tmp_path / "session-repo"
    target = tmp_path / "target-repo"
    _init_amw_repo(session)
    _init_amw_repo(target)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(session))
    rc = amw_main(["allow_main_write", "why", "--repo-root", str(target)])
    assert rc == 0
    assert (target / ".harness" / "allow-main-write").exists()
    assert not (session / ".harness" / "allow-main-write").exists()
    out = capsys.readouterr().out
    assert "repo: " in out and "mode: " in out     # context echo


def test_invalid_repo_root_refused(tmp_path: Path):
    rc = amw_main(["allow_main_write", "why", "--repo-root", str(tmp_path)])
    assert rc == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/harness/test_allow_main_write.py -x -q`
Expected: FAIL — `--repo-root` unknown / marker in wrong place / rc 0 on invalid root.

- [ ] **Step 3: Implement**

Rewrite `main()` in `scripts/harness/allow_main_write.py`:

```python
def main(argv: list[str]) -> int:
    import argparse

    from scripts.harness.branches import BranchConfigError, load_branch_config
    from scripts.harness.repo_resolve import (
        RepoResolveError,
        echo_context,
        resolve_cli_repo_root,
    )

    p = argparse.ArgumentParser()
    p.add_argument("reason", nargs="*", default=[])
    p.add_argument("--repo-root", type=Path, default=None)
    args = p.parse_args(argv[1:])
    reason = " ".join(args.reason).strip() or "(no reason given)"
    try:
        root = resolve_cli_repo_root(args.repo_root)
        cfg = load_branch_config(root)
    except (RepoResolveError, BranchConfigError) as exc:
        sys.stderr.write(f"allow-main-write: {exc}\n")
        return 1
    print(echo_context(root, cfg, cfg.base))
    marker = write_marker(harness_dir=root / ".harness", reason=reason)
    print(f"Authorized ONE write in {root} (reason: {reason}).")
    print(f"Marker: {marker}")
    print("It is consumed by the next gated write in that repo and logged "
          "to .harness/exceptions.log. Retry your edit now.")
    return 0
```

Update the module docstring accordingly (mention `--repo-root` and multi-root).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/harness/test_allow_main_write.py -x -q`
Expected: PASS (new + pre-existing `write_marker` tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/harness/allow_main_write.py tests/harness/test_allow_main_write.py
git commit -m "feat(harness): allow_main_write targets an explicit validated repo"
```

<!-- task-meta
id: T06
touches:
  - scripts/harness/allow_main_write.py
  - tests/harness/test_allow_main_write.py
depends: [T03]
verify: python -m pytest tests/harness/test_allow_main_write.py -x -q
acceptance: null
-->

---

### Task 7 — `finish_work.py`: branch mode + validated `--repo-root` + echo

**Files:**
- Modify: `scripts/harness/finish_work.py`
- Test: `tests/harness/test_finish_work.py` (extend)

**Interfaces:**
- Consumes: `resolve_cli_repo_root`/`echo_context`/`RepoResolveError` (T03), `cfg.workflow` + `WORK_BRANCH_RE` (T02), existing `prove_merged`/`_audit_delete`.
- Produces: `finish_branch(*, repo_root: Path, branch: str | None, keep_branch: bool = False, warn=None) -> str` — branch-mode counterpart of `finish_work`; ends with HEAD on `cfg.merge_target` (**never** `base`), returns the finished branch name. `main()` dispatches on `cfg.workflow` and prints the context echo.

- [ ] **Step 1: Write the failing tests**

Append to `tests/harness/test_finish_work.py` (reuse its repo helpers). Note every fixture **commits** `.harness/` — branch mode's dirty check ignores untracked files anyway (tested explicitly), but committed config keeps the fixtures honest:

```python
from scripts.harness.finish_work import FinishWorkError, finish_branch


def _cfg_branch(repo: Path) -> None:
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "branches.yaml").write_text(
        "workflow: branch\nlong_lived: [prod, dev]\nbase: prod\nmerge_target: dev\n",
        encoding="utf-8",
    )
    subprocess.check_call(["git", "add", ".harness"], cwd=repo)
    subprocess.check_call(["git", "commit", "-q", "-m", "cfg"], cwd=repo)


def _seed_envs(repo: Path) -> None:
    subprocess.check_call(["git", "branch", "prod"], cwd=repo)
    subprocess.check_call(["git", "branch", "dev"], cwd=repo)


def _work_then_merge(repo: Path) -> None:
    subprocess.check_call(["git", "checkout", "-q", "-b", "feat/w", "prod"], cwd=repo)
    (repo / "w.txt").write_text("w\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=repo)
    subprocess.check_call(["git", "commit", "-q", "-m", "w"], cwd=repo)
    subprocess.check_call(["git", "checkout", "-q", "dev"], cwd=repo)
    subprocess.check_call(["git", "merge", "-q", "--no-ff", "feat/w"], cwd=repo)
    subprocess.check_call(["git", "checkout", "-q", "feat/w"], cwd=repo)


def _head(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
    ).strip()


def test_finish_branch_defaults_to_head_and_ends_on_merge_target(tmp_path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch(repo)
    _seed_envs(repo)
    _work_then_merge(repo)
    got = finish_branch(repo_root=repo, branch=None)
    assert got == "feat/w"
    assert _head(repo) == "dev"          # merge_target — never prod/base
    out = subprocess.run(["git", "rev-parse", "--verify", "refs/heads/feat/w"],
                         cwd=repo, capture_output=True)
    assert out.returncode != 0           # branch deleted
    assert (repo / ".harness" / "finish_audit.log").exists()


def test_finish_branch_untracked_files_do_not_block(tmp_path):
    # the .env-style scratch file the mode was designed to tolerate
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch(repo)
    _seed_envs(repo)
    _work_then_merge(repo)
    (repo / "scratch.env").write_text("x\n", encoding="utf-8")
    warnings: list[str] = []
    got = finish_branch(repo_root=repo, branch=None, warn=warnings.append)
    assert got == "feat/w"
    assert _head(repo) == "dev"
    assert any("scratch.env" in w for w in warnings)


def test_finish_branch_refuses_unmerged(tmp_path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch(repo)
    _seed_envs(repo)
    subprocess.check_call(["git", "checkout", "-q", "-b", "feat/u", "prod"], cwd=repo)
    (repo / "u.txt").write_text("u\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=repo)
    subprocess.check_call(["git", "commit", "-q", "-m", "u"], cwd=repo)
    with pytest.raises(FinishWorkError, match="unmerged"):
        finish_branch(repo_root=repo, branch=None)


def test_finish_branch_keep_branch(tmp_path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch(repo)
    _seed_envs(repo)
    subprocess.check_call(["git", "checkout", "-q", "-b", "feat/k", "prod"], cwd=repo)
    got = finish_branch(repo_root=repo, branch=None, keep_branch=True)
    assert got == "feat/k"
    assert _head(repo) == "dev"
    out = subprocess.run(["git", "rev-parse", "--verify", "refs/heads/feat/k"],
                         cwd=repo, capture_output=True)
    assert out.returncode == 0           # kept


def test_finish_branch_refuses_tracked_dirty(tmp_path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch(repo)
    _seed_envs(repo)
    _work_then_merge(repo)
    (repo / "seed").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(FinishWorkError, match="tracked changes"):
        finish_branch(repo_root=repo, branch=None)


def test_finish_branch_refuses_head_not_work_branch_and_no_arg(tmp_path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch(repo)
    _seed_envs(repo)
    subprocess.check_call(["git", "checkout", "-q", "dev"], cwd=repo)
    with pytest.raises(FinishWorkError, match="name the branch"):
        finish_branch(repo_root=repo, branch=None)


def test_finish_branch_by_name_from_elsewhere(tmp_path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch(repo)
    _seed_envs(repo)
    _work_then_merge(repo)
    subprocess.check_call(["git", "checkout", "-q", "main"], cwd=repo)
    got = finish_branch(repo_root=repo, branch="feat/w")
    assert got == "feat/w"
    assert _head(repo) == "dev"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/harness/test_finish_work.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'finish_branch'`

- [ ] **Step 3: Implement**

In `scripts/harness/finish_work.py`:

1. Add imports: `WORK_BRANCH_RE` to the `branches` import; `from scripts.harness.repo_resolve import (RepoResolveError, echo_context, resolve_cli_repo_root)`.

2. Add a tracked-only dirty helper (branch mode; the worktree path keeps today's stricter `_worktree_dirty`) and the branch-mode finisher:

```python
def _tracked_dirty_and_untracked(repo_root: Path) -> tuple[bool, list[str]]:
    lines = _git(["status", "--porcelain"], cwd=repo_root).splitlines()
    tracked = [ln for ln in lines if ln and not ln.startswith("??")]
    untracked = [ln[3:] for ln in lines if ln.startswith("??")]
    return bool(tracked), untracked


def finish_branch(
    *, repo_root: Path, branch: str | None, keep_branch: bool = False,
    warn=None,
) -> str:
    warn = warn or (lambda m: print(f"warn: {m}", file=sys.stderr))
    try:
        cfg = load_branch_config(repo_root)
    except BranchConfigError as exc:
        raise FinishWorkError(str(exc)) from exc
    head = _current_branch(repo_root)
    if branch is None:
        if not WORK_BRANCH_RE.match(head):
            raise FinishWorkError(
                f"HEAD is on {head!r}, not a <type>/<slug> work branch; "
                "name the branch to finish: finish_work <type>/<slug>"
            )
        branch = head
    elif not WORK_BRANCH_RE.match(branch):
        raise FinishWorkError(
            f"{branch!r} is not a <type>/<slug> work branch name"
        )
    dirty, untracked = _tracked_dirty_and_untracked(repo_root)
    if dirty:
        raise FinishWorkError(
            "working tree has tracked changes (staged or unstaged); "
            "commit or stash first"
        )
    if untracked:
        warn("untracked files present (they stay in the working tree): "
             + ", ".join(untracked))
    proven: str | None = None
    if not keep_branch:
        proven = prove_merged(repo_root, branch, cfg)
        if proven is None:
            raise FinishWorkError(
                f"branch {branch} is unmerged — not an ancestor of "
                f"{cfg.merge_target} (local or remote-tracking); merge it "
                "first or pass --keep-branch. Note: squash/rebase merges "
                "are not provable — use --keep-branch and delete manually."
            )
    # Prove everything BEFORE any state change.
    sha = _git(["rev-parse", branch], cwd=repo_root).strip()
    # End on merge_target — never base/prod (user decision in the spec).
    _git(["checkout", cfg.merge_target], cwd=repo_root)
    if not keep_branch:
        assert proven is not None
        _git(["branch", "-D", branch], cwd=repo_root)
        _audit_delete(repo_root, branch=branch, sha=sha, proven=proven)
    return branch
```

(No `branch in cfg.protected` guard: `WORK_BRANCH_RE` requires a slash, `cfg.protected` holds bare names — the sets cannot intersect.)

3. Rework `main()`: `--repo-root` default `None`; resolve + load config once, echo, dispatch:

```python
    try:
        repo_root = resolve_cli_repo_root(args.repo_root)
        cfg = load_branch_config(repo_root)
        print(echo_context(repo_root, cfg, cfg.base))
        if cfg.workflow == "branch":
            branch = finish_branch(
                repo_root=repo_root, branch=args.slug,
                keep_branch=args.keep_branch,
            )
            kept = " (branch kept)" if args.keep_branch else ""
            print(f"Finished work on {branch}; now on {cfg.merge_target}{kept}.")
            return 0
        branch = finish_work(
            repo_root=repo_root, slug=args.slug,
            worktree_path=args.worktree_path, keep_branch=args.keep_branch,
        )
    except (FinishWorkError, RepoResolveError, BranchConfigError) as exc:
        sys.stderr.write(f"leash-finish-work: {exc}\n")
        return 1
```

Update the positional argument help: "worktree slug (worktree mode) or `<type>/<slug>` branch (branch mode; defaults to HEAD)". Update the module docstring.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/harness/test_finish_work.py -x -q`
Expected: PASS (including all pre-existing worktree-mode tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/harness/finish_work.py tests/harness/test_finish_work.py
git commit -m "feat(harness): branch-mode finish_work — merge proof, ends on merge_target"
```

<!-- task-meta
id: T07
touches:
  - scripts/harness/finish_work.py
  - tests/harness/test_finish_work.py
depends: [T03]
verify: python -m pytest tests/harness/test_finish_work.py -x -q
acceptance: null
-->

---

### Task 8 — Skills + templates: both modes documented, doc tests updated

**Files:**
- Modify: `skills/leash-start-work/SKILL.md`, `skills/leash-finish-work/SKILL.md`, `templates/CLAUDE.md.tmpl`, `skills/bootstrap-dev-leash/SKILL.md`
- Test: `tests/test_skill_start_work.py`, `tests/test_templates.py`, `tests/test_skill_bootstrap.py` (extend/adjust — README assertions belong to Task 9, keeping every commit green)

**Interfaces:**
- Consumes: CLI surfaces fixed in T03–T07 (`--repo-root`, branch-mode semantics, `merge_target` landing).
- Produces: prose that matches the mechanics; tests pin the load-bearing phrases.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_skill_start_work.py`:

```python
def test_skill_documents_repo_root_and_multi_root():
    text = Path("skills/leash-start-work/SKILL.md").read_text(encoding="utf-8")
    assert "--repo-root" in text
    assert "multi-root" in text.lower()
    assert "workflow: branch" in text
    assert "bootstrapped" in text          # session-root deployment constraint
```

Add to `tests/test_templates.py`:

```python
def test_claude_tmpl_mentions_branch_mode():
    text = Path("templates/CLAUDE.md.tmpl").read_text(encoding="utf-8")
    assert "workflow: branch" in text
```

Add to `tests/test_skill_bootstrap.py`:

```python
def test_bootstrap_interviews_workflow_mode():
    text = Path("skills/bootstrap-dev-leash/SKILL.md").read_text(encoding="utf-8")
    assert "workflow" in text and "branch" in text
```

(Adjust any existing assertions in these files that pin worktree-only phrasing which this task rewrites — change them in the same commit, keeping their intent.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_skill_start_work.py tests/test_templates.py tests/test_skill_bootstrap.py -x -q`
Expected: FAIL on each new assertion.

- [ ] **Step 3: Write the prose**

`skills/leash-start-work/SKILL.md` — canonical invocation becomes:

```
python -m scripts.harness.start_work <type>/<slug> [--base <branch>] [--repo-root <path>]
```

Add a section after "How":

```markdown
## Multi-root workspaces

When the VS Code workspace holds several repos, ALWAYS pass
`--repo-root <target repo>` — determine the demand's target repo FIRST
and never trust the session cwd. The backend mechanically refuses to
run without it when it can detect the layout (sibling leash-managed
repos, or a workspace folder with child repos) and lists the
candidates; layouts it cannot detect (folders from unrelated parents)
are exactly why the explicit flag is mandatory practice. The script
echoes `repo: … | config: … | base: … | mode: …` — read it back and
confirm it matches the demand before editing anything.

Deployment note: the write-gate hook runs from the session-root
project's settings, so the session must be rooted in a leash-
**bootstrapped** repo for the gate to protect the workspace's sibling
repos; keep harness versions aligned with `/leash-update`.

## `workflow: branch` mode

A repo whose `.harness/branches.yaml` declares `workflow: branch` gets a
disciplined checkout instead of a worktree: same base resolution and
refusals, then `git checkout -b <type>/<slug>` in place. One demand at a
time per repo (the backend refuses a second). Edits happen in the normal
project paths; the write gate allows them only while HEAD is on the work
branch. Use worktree mode when a repo needs several parallel demands.
Branch mode assumes ONE session per repo — concurrent sessions on the
same branch-mode repo are not protected against each other.
```

`skills/leash-finish-work/SKILL.md` — add the branch-mode paragraph:

```markdown
## Branch mode

In a `workflow: branch` repo, pass the `<type>/<slug>` branch name (or
nothing, to finish the current HEAD branch). The backend proves the
branch merged into `merge_target`, checks out `merge_target` (never the
base), and deletes the branch — `--keep-branch` for squash/rebase
merges. Tracked changes block; untracked files only warn. Always pass
`--repo-root` in multi-root workspaces.
```

`templates/CLAUDE.md.tmpl` — in the worktree-discipline section, add one paragraph: repos with `workflow: branch` in `.harness/branches.yaml` use disciplined checkouts instead of worktrees; edits are allowed only while HEAD is on a `<type>/<slug>` branch; everything else is denied by the same gate.

`skills/bootstrap-dev-leash/SKILL.md` — add an interview item right after the base-branch question: "Workflow mode: worktree (default; parallel demands per repo) or branch (plain checkouts; one demand per repo, one session per repo — fits multi-root workspaces)?" and write the answer as `workflow: <answer>` into the generated `.harness/branches.yaml`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_skill_start_work.py tests/test_templates.py tests/test_skill_bootstrap.py tests/test_docs.py -x -q`
Expected: PASS — including the untouched `tests/test_docs.py` (its README assertions arrive in T09 together with the README text, so no red commit exists between tasks).

- [ ] **Step 5: Commit**

```bash
git add skills/leash-start-work/SKILL.md skills/leash-finish-work/SKILL.md templates/CLAUDE.md.tmpl skills/bootstrap-dev-leash/SKILL.md tests/test_skill_start_work.py tests/test_templates.py tests/test_skill_bootstrap.py
git commit -m "docs(skills): multi-root --repo-root discipline + workflow:branch mode"
```

<!-- task-meta
id: T08
touches:
  - skills/leash-start-work/SKILL.md
  - skills/leash-finish-work/SKILL.md
  - templates/CLAUDE.md.tmpl
  - skills/bootstrap-dev-leash/SKILL.md
  - tests/test_skill_start_work.py
  - tests/test_templates.py
  - tests/test_skill_bootstrap.py
depends: [T04, T07]
verify: python -m pytest tests/test_skill_start_work.py tests/test_templates.py tests/test_skill_bootstrap.py tests/test_docs.py -x -q
acceptance: null
-->

---

### Task 9 — README + CHANGELOG + leash-update notes

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `skills/leash-update/SKILL.md`
- Test: `tests/test_docs.py` (extend — the README assertion lands here, WITH the README text, in one green commit)

**Interfaces:** none new — prose only.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_docs.py`:

```python
def test_readme_documents_both_workflows():
    text = Path("README.md").read_text(encoding="utf-8")
    assert "workflow: branch" in text
    assert "one session per repo" in text.lower()
    assert "multi-root" in text.lower()
    assert "/leash-update" in text          # migration order note
```

Run: `python -m pytest tests/test_docs.py -x -q` — expected: FAIL on the new test.

- [ ] **Step 2: Write the README section**

Add under the branches-config documentation:

```markdown
### Workflow modes: `worktree` (default) vs `branch`

`.harness/branches.yaml` accepts `workflow: worktree | branch`.

- **worktree** (default): every demand gets `.worktrees/<slug>`; the
  main checkout is read-only. Choose it when one repo carries several
  parallel demands.
- **branch**: `/leash-start-work` does a disciplined `checkout -b` off
  the configured base instead; the write gate allows edits only while
  HEAD is on a `<type>/<slug>` branch. One demand at a time per repo,
  and **one session per repo** — branch mode does not protect two
  concurrent sessions sharing a checkout. `/leash-finish-work` proves
  the merge and lands on `merge_target` (never the base). Tracked
  changes block start/finish; untracked scratch files only warn.

### Multi-root workspaces (several repos, one session)

All harness CLIs take `--repo-root`. In a multi-root workspace, ALWAYS
pass it — the CLIs mechanically refuse to guess when they can detect
the layout (sibling leash-managed repos, or a workspace folder with
child repos) and list the candidates; layouts spanning unrelated
parent folders are not detectable, which is why the explicit flag is
the rule, not the fallback. The write gate judges every edit by the
repo that owns the target file, so sibling leash-managed repos are
protected too; repos without `.harness/` are never touched.
Requirement: the session must be rooted in a leash-bootstrapped repo
(its hook wiring serves the whole workspace); keep harnesses aligned
with `/leash-update`.

**Migration note:** update the harness (`/leash-update`) BEFORE adding
`workflow:` to `.harness/branches.yaml` — older harness scripts hard-fail
on unknown keys.
```

- [ ] **Step 3: CHANGELOG + leash-update**

`CHANGELOG.md`: add an Unreleased entry summarizing — validated `--repo-root` + ambiguity refusal on `start_work`/`finish_work`/`allow_main_write`; write gate judges by target repo (leash-managed repos only) in both modes; `workflow: branch` mode; branch-mode finish lands on `merge_target`; migration order (harness before config key).

`skills/leash-update/SKILL.md`: add a short "0.7.0 notes" line: delivering this release also delivers `scripts/harness/repo_resolve.py` (picked up by the existing `scripts/harness/*.py` glob) and the rewritten `session_gate.py`; remind that the `workflow:` key requires the updated harness first.

- [ ] **Step 4: Run doc tests**

Run: `python -m pytest tests/test_docs.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md skills/leash-update/SKILL.md tests/test_docs.py
git commit -m "docs: workflow modes + multi-root workspace guide and migration order"
```

<!-- task-meta
id: T09
touches:
  - README.md
  - CHANGELOG.md
  - skills/leash-update/SKILL.md
  - tests/test_docs.py
depends: [T08]
verify: python -m pytest tests/test_docs.py -x -q
acceptance: null
-->

---

### Task 10 — Full suite, smoke, dogfood

**Files:**
- No new files; fixes only if the suite finds fallout.

- [ ] **Step 1: Full test suite**

Run: `python -m pytest tests -x -q`
Expected: PASS — zero failures anywhere.

- [ ] **Step 2: Smoke e2e**

Run: `python scripts/smoke_e2e.py`
Expected: PASS — step 9 runs the rewritten `dogfood_worktree_gate.py`; CI (`.github/workflows/ci.yml`) runs this same script, so it must be green before merge.

- [ ] **Step 3: Dogfood in this repo (worktree mode)**

This step is run from the **main-checkout session** (the plan's implementation session lives inside `.worktrees/multi-root-branch-mode`, which `validate_repo_root` rightly refuses as a `--repo-root`). Use the absolute main-checkout path — call it `$MAIN` (`c:\Users\User\Documents\Python Projects\dev-on-leash`):

```
python -m scripts.harness.start_work chore/dogfood-mrbm --repo-root "$MAIN"
python -m scripts.harness.finish_work dogfood-mrbm --keep-branch --repo-root "$MAIN"
git branch -D chore/dogfood-mrbm
```

Confirm: the echo line names `$MAIN`, `mode: worktree`, the right base; the worktree appears and is removed; the branch is deleted by hand at the end. (Both commands carry `--repo-root` — the ambiguity refusal would fire the moment a leash-managed sibling of this repo appears.)

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "test: full-suite fallout fixes for multi-root + branch mode"
```

<!-- task-meta
id: T10
touches:
  - tests
depends: [T05, T06, T09]
verify: python -m pytest tests -x -q
acceptance: python scripts/smoke_e2e.py
-->

---

### Task 11 — Field validation in the real 4-repo workspace (human)

No `task-meta` — this task is run by the human partner with Claude assisting, **before the release is tagged** (spec Delivery requirement: the synthetic fixture alone is the same coverage class that missed the original field failure).

- [ ] Run `/leash-update` in all four project repos (migration order: harness before config).
- [ ] Set `workflow: branch` in each repo's `.harness/branches.yaml` (keeping `base: prod`, `merge_target: dev`, `long_lived: [prod, homol, qa, dev]`).
- [ ] In the multi-root VS Code workspace, run `/leash-start-work` once **without** `--repo-root` — the four repos are siblings, so the ambiguity refusal must fire and list all four.
- [ ] Start one demand per repo with the correct `--repo-root`; confirm each echo line names the right repo, `base: prod`, `mode: branch`.
- [ ] Confirm the gate: an edit attempt in a repo still on `dev` is denied with the branch-mode message; edits on the work branch pass; an edit in a non-leash repo elsewhere on disk is untouched.
- [ ] Merge one demand into `dev`, run `/leash-finish-work` — confirm it lands on `dev` (never `prod`) and deletes the branch.
- [ ] Report anything surprising back into an issue/spec revision before tagging the release.
