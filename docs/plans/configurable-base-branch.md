# Configurable Base Branch Implementation Plan

> **For agentic workers:** Execute this plan task-by-task. A task that carries a `task-meta` block is verified and checkbox-ticked by `scripts/harness/run_task.py` — never tick those by hand. Tasks without a `task-meta` block are human-run. (Execution skills such as superpowers `subagent-driven-development` work well here but are optional.)

**Goal:** Projects with several long-lived branches (dev/qa/homol/prod) declare them in `.harness/branches.yaml`; `/leash-start-work` starts worktrees from the configured base (with `--base` override and fetch-and-warn freshness) via a new mechanical `start_work.py`, and `/leash-finish-work` deletes branches only after an explicit `merge-base --is-ancestor` proof against the declared `merge_target` (local or remote-tracking), audited to `.harness/finish_audit.log`.

**Architecture:** One config reader (`scripts/harness/branches.py`) is the single source of truth: `base` (where worktrees start), `merge_target` (where work lands — delete-safety), `protected` (`long_lived ∪ {main, master}`). `start_work.py` and `finish_work.py` are the mechanical gates (skills become thin prose over them); `cycle_done.py`'s advisory shares the same `prove_merged` helper so advisory and enforcement agree. Templates gain `{{BASE_BRANCH}}` so rendered discipline prose can never contradict the config. Missing config ⇒ exact current behavior.

**Tech Stack:** Python 3.12+ (pyyaml already a dependency), pytest, git CLI, Markdown skills/templates. Spec: [docs/superpowers/specs/2026-07-22-configurable-base-branch-design.md](../superpowers/specs/2026-07-22-configurable-base-branch-design.md) (rev 2, post antagonist-critic round).

## Global Constraints

- Missing `.harness/branches.yaml` ⇒ behavior identical to today (base = detected `main`/`master`, protected = `{main, master}`); every existing test keeps passing.
- Malformed config is a **hard error naming the file and offending key** — never a silent fallback. Unknown top-level keys fail loud.
- Branch names in config: bare refs only (regex `^[A-Za-z0-9][A-Za-z0-9._-]*$`, no slash, no leading `-`).
- `git branch -D` is allowed **only** after `git merge-base --is-ancestor` proof (or under `--keep-branch` the branch is not deleted at all); every `-D` appends an audit line to `.harness/finish_audit.log`.
- When branching from a remote-tracking ref, always pass `--no-track` — the feature branch must get no upstream.
- Offline work never blocks: fetch failure / no remote ⇒ warn and use local refs. Diverged base (ahead AND behind) ⇒ refuse, never silently pick a side.
- TDD: every code change lands with its test in the same task. Implementation runs in a `.worktrees/<slug>` worktree on branch `feat/configurable-base-branch` (create it with the current `/leash-start-work` before Task 1). One commit per task minimum.
- All file paths below are relative to the repo root; inside the worktree they live under `.worktrees/configurable-base-branch/`.

---

## File Structure

**Create:**
- `scripts/harness/branches.py` — config reader + `prove_merged` helper (single source of truth).
- `scripts/harness/start_work.py` — mechanical worktree creation gate.
- `tests/harness/test_branches.py`, `tests/harness/test_start_work.py` — unit tests.
- `.harness/branches.yaml` — dogfood config for this repo (Task 7).

**Modify:**
- `scripts/harness/finish_work.py` + `tests/harness/test_finish_work.py` — protected set, ancestry proof, audited `-D`.
- `scripts/harness/cycle_done.py` + `tests/harness/test_cycle_done_advise.py` — advisory uses `prove_merged`.
- `skills/leash-start-work/SKILL.md` + `tests/test_skill_start_work.py` — thin wrapper over `start_work.py`.
- `skills/leash-finish-work/SKILL.md` — new deletion semantics.
- `templates/AGENTS.md.tmpl`, `templates/CLAUDE.md.tmpl` + `tests/test_templates.py` — `{{BASE_BRANCH}}` placeholder.
- `skills/bootstrap-dev-leash/SKILL.md` + `tests/test_skill_bootstrap.py` — interview item 13 + `branches.yaml` write step.
- `README.md` + `tests/test_docs.py` — user-facing docs.

---

### Task 1 — `branches.py`: config reader + `prove_merged`

**Files:**
- Create: `scripts/harness/branches.py`
- Test: `tests/harness/test_branches.py` (create)

**Interfaces:**
- Produces (later tasks import these exact names from `scripts.harness.branches`):
  - `class BranchConfigError(RuntimeError)`
  - `@dataclass(frozen=True) class BranchConfig: base: str; merge_target: str; protected: frozenset[str]`
  - `detect_default_branch(repo_root: Path) -> str`
  - `load_branch_config(repo_root: Path) -> BranchConfig`
  - `prove_merged(repo_root: Path, branch: str, cfg: BranchConfig) -> str | None` (returns the proving ref or `None`)

- [ ] **Step 1: Write the failing tests**

Create `tests/harness/test_branches.py`:

```python
"""Tests for the .harness/branches.yaml reader and merge proof."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.harness.branches import (
    BranchConfig,
    BranchConfigError,
    detect_default_branch,
    load_branch_config,
    prove_merged,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.check_call(["git", *args], cwd=repo)


def _init_repo(path: Path, default: str = "main") -> None:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", default)
    _git(path, "config", "user.email", "d@d")
    _git(path, "config", "user.name", "d")
    (path / "seed").write_text("seed\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "seed")


def _write_cfg(repo: Path, text: str) -> None:
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "branches.yaml").write_text(text, encoding="utf-8")


# --- defaults ---------------------------------------------------------------

def test_missing_file_gives_current_behavior(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    cfg = load_branch_config(repo)
    assert cfg.base == "main"
    assert cfg.merge_target == "main"
    assert cfg.protected == frozenset({"main", "master"})


def test_detect_default_branch_master(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo, default="master")
    assert detect_default_branch(repo) == "master"
    assert load_branch_config(repo).base == "master"


# --- valid config -----------------------------------------------------------

def test_full_config(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "base: prod\nmerge_target: dev\nlong_lived: [dev, qa, homol, prod]\n")
    cfg = load_branch_config(repo)
    assert cfg.base == "prod"
    assert cfg.merge_target == "dev"
    assert cfg.protected == frozenset({"dev", "qa", "homol", "prod", "main", "master"})


def test_partial_config_falls_back_to_default(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "long_lived: [dev]\n")
    cfg = load_branch_config(repo)
    assert cfg.base == "main"
    assert cfg.merge_target == "main"
    assert "dev" in cfg.protected


# --- malformed config: hard errors -------------------------------------------

def test_unknown_key_fails_loud(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "base: main\nbogus: 1\n")
    with pytest.raises(BranchConfigError, match="unknown key.*bogus"):
        load_branch_config(repo)


def test_base_not_in_long_lived_rejected(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "base: prod\nlong_lived: [dev]\n")
    with pytest.raises(BranchConfigError, match="base.*prod"):
        load_branch_config(repo)


def test_merge_target_not_in_long_lived_rejected(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "merge_target: qa\nlong_lived: [dev]\n")
    with pytest.raises(BranchConfigError, match="merge_target.*qa"):
        load_branch_config(repo)


@pytest.mark.parametrize("bad", ["feat/x", "-dev", "a b", ""])
def test_bad_ref_names_rejected(tmp_path: Path, bad: str):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, f'long_lived: ["{bad}"]\n')
    with pytest.raises(BranchConfigError):
        load_branch_config(repo)


def test_invalid_yaml_rejected(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "base: [unclosed\n")
    with pytest.raises(BranchConfigError, match="branches.yaml"):
        load_branch_config(repo)


def test_non_mapping_top_level_rejected(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "- just\n- a list\n")
    with pytest.raises(BranchConfigError, match="mapping"):
        load_branch_config(repo)


# --- prove_merged -------------------------------------------------------------

def test_prove_merged_local_target(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _git(repo, "checkout", "-q", "-b", "dev")
    _git(repo, "checkout", "-q", "-b", "feat/x")
    (repo / "f").write_text("x\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "wip")
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "merge", "-q", "--no-ff", "feat/x", "-m", "merge")
    _git(repo, "checkout", "-q", "main")
    _write_cfg(repo, "merge_target: dev\nlong_lived: [dev]\n")
    cfg = load_branch_config(repo)
    # merged into dev, HEAD is on main — proof must still succeed
    assert prove_merged(repo, "feat/x", cfg) == "refs/heads/dev"


def test_prove_merged_remote_tracking_only(tmp_path: Path):
    # origin/dev has the merge; local dev is stale (still at seed)
    origin = tmp_path / "origin"
    _init_repo(origin)
    _git(origin, "checkout", "-q", "-b", "dev")
    _git(origin, "checkout", "-q", "main")

    repo = tmp_path / "r"
    subprocess.check_call(["git", "clone", "-q", str(origin), str(repo)])
    _git(repo, "config", "user.email", "d@d")
    _git(repo, "config", "user.name", "d")
    _git(repo, "checkout", "-q", "-b", "feat/x")
    (repo / "f").write_text("x\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "wip")
    _git(repo, "push", "-q", "origin", "feat/x:dev")  # lands in origin/dev
    _git(repo, "checkout", "-q", "main")
    _git(repo, "fetch", "-q", "origin")
    _write_cfg(repo, "merge_target: dev\nlong_lived: [dev]\n")
    cfg = load_branch_config(repo)
    assert prove_merged(repo, "feat/x", cfg) == "refs/remotes/origin/dev"


def test_prove_merged_unmerged_is_none(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _git(repo, "checkout", "-q", "-b", "feat/x")
    (repo / "f").write_text("x\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "wip")
    _git(repo, "checkout", "-q", "main")
    cfg = load_branch_config(repo)
    assert prove_merged(repo, "feat/x", cfg) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/harness/test_branches.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.harness.branches'`

- [ ] **Step 3: Write the implementation**

Create `scripts/harness/branches.py`:

```python
"""Reader for `.harness/branches.yaml` — multi-branch project config.

Declares where new worktrees start (`base`), where work branches land
(`merge_target`, the delete-safety target) and which long-lived branches
are protected (`long_lived`). `protected` and `merge_target` are
deliberately separate concepts: protection = where you must not work;
merge target = where integration is durable. A missing file reproduces
the classic main/master behavior exactly; a malformed file is a hard
error, never a silent fallback.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG_RELPATH = Path(".harness") / "branches.yaml"
_ALLOWED_KEYS = {"base", "merge_target", "long_lived"}
# Bare branch names only: long-lived branches carry no slash and no
# leading '-'; conservative charset keeps shell/git-arg surprises out.
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class BranchConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class BranchConfig:
    base: str
    merge_target: str
    protected: frozenset[str]


def _git_rc(repo_root: Path, *args: str) -> int:
    return subprocess.run(
        ["git", *args], cwd=str(repo_root), capture_output=True
    ).returncode


def detect_default_branch(repo_root: Path) -> str:
    """`main` if it exists locally, else `master`, else `main`."""
    for name in ("main", "master"):
        if _git_rc(repo_root, "rev-parse", "--verify", "--quiet",
                   f"refs/heads/{name}") == 0:
            return name
    return "main"


def _require_bare_ref(value: object, *, key: str, path: Path) -> str:
    if not isinstance(value, str) or not _REF_RE.match(value):
        raise BranchConfigError(
            f"{path}: `{key}` entries must be bare branch names "
            f"(letters/digits/._-, no slash, no leading '-'); got {value!r}"
        )
    return value


def load_branch_config(repo_root: Path) -> BranchConfig:
    default = detect_default_branch(repo_root)
    path = repo_root / CONFIG_RELPATH
    if not path.exists():
        return BranchConfig(
            base=default,
            merge_target=default,
            protected=frozenset({"main", "master"}),
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise BranchConfigError(f"{path}: invalid YAML: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise BranchConfigError(f"{path}: top level must be a mapping")
    unknown = sorted(set(raw) - _ALLOWED_KEYS)
    if unknown:
        raise BranchConfigError(
            f"{path}: unknown key(s): {', '.join(unknown)} "
            f"(allowed: {', '.join(sorted(_ALLOWED_KEYS))})"
        )

    long_lived_raw = raw.get("long_lived", [])
    if not isinstance(long_lived_raw, list):
        raise BranchConfigError(f"{path}: `long_lived` must be a list")
    long_lived = [
        _require_bare_ref(item, key="long_lived", path=path)
        for item in long_lived_raw
    ]
    allowed = set(long_lived) | {"main", "master"}

    def _resolve(key: str) -> str:
        value = raw.get(key)
        if value is None:
            return default
        name = _require_bare_ref(value, key=key, path=path)
        if name not in allowed:
            raise BranchConfigError(
                f"{path}: `{key}: {name}` must be main/master or listed in "
                f"`long_lived` (declared: {sorted(allowed)})"
            )
        return name

    return BranchConfig(
        base=_resolve("base"),
        merge_target=_resolve("merge_target"),
        protected=frozenset(long_lived) | {"main", "master"},
    )


def _remotes(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "remote"], cwd=str(repo_root), capture_output=True, text=True
    )
    if proc.returncode != 0:
        return []
    return [r for r in proc.stdout.split() if r]


def ref_exists(repo_root: Path, ref: str) -> bool:
    return _git_rc(repo_root, "rev-parse", "--verify", "--quiet", ref) == 0


def prove_merged(repo_root: Path, branch: str, cfg: BranchConfig) -> str | None:
    """Return the ref `branch` is proven merged into, or None.

    Candidates: the local `merge_target` and every remote-tracking copy
    of it. Proof is `git merge-base --is-ancestor` — explicit ancestry,
    not `git branch -d`'s HEAD-relative heuristic (which cannot express
    "merged into dev while HEAD is on main"). Checking remote-tracking
    refs keeps a chronically-stale local target from blocking cleanup of
    genuinely merged branches. Squash/rebase merges produce new SHAs and
    are NOT provable — callers document `--keep-branch` as the escape.
    """
    candidates = [f"refs/heads/{cfg.merge_target}"] + [
        f"refs/remotes/{r}/{cfg.merge_target}" for r in _remotes(repo_root)
    ]
    for ref in candidates:
        if not ref_exists(repo_root, ref):
            continue
        if _git_rc(repo_root, "merge-base", "--is-ancestor", branch, ref) == 0:
            return ref
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/harness/test_branches.py -x -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add scripts/harness/branches.py tests/harness/test_branches.py
git commit -m "feat(harness): branches.py — .harness/branches.yaml reader + prove_merged"
```

<!-- task-meta
id: T01
touches:
  - scripts/harness/branches.py
  - tests/harness/test_branches.py
depends: []
verify: python -m pytest tests/harness/test_branches.py -x -q
acceptance: null
-->

---

### Task 2 — `start_work.py`: mechanical worktree creation

**Files:**
- Create: `scripts/harness/start_work.py`
- Test: `tests/harness/test_start_work.py` (create)

**Interfaces:**
- Consumes: `load_branch_config`, `BranchConfigError`, `ref_exists` from `scripts.harness.branches` (Task 1).
- Produces: `class StartWorkError(RuntimeError)`; `start_work(*, repo_root: Path, branch: str, base_override: str | None = None, warn=...) -> Path` (returns worktree path); `detect_remote(repo_root: Path, base: str) -> str | None`; `resolve_start_point(repo_root: Path, base: str, remote: str | None, warn) -> tuple[str, bool]` (start_point, use_no_track). Runnable as `python -m scripts.harness.start_work <type>/<slug> [--base <branch>]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/harness/test_start_work.py`:

```python
"""Tests for the mechanical leash-start-work backend."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.harness.start_work import StartWorkError, start_work


def _git(repo: Path, *args: str) -> None:
    subprocess.check_call(["git", *args], cwd=repo)


def _git_out(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "d@d")
    _git(path, "config", "user.name", "d")
    (path / "seed").write_text("seed\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "seed")


def _write_cfg(repo: Path, text: str) -> None:
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "branches.yaml").write_text(text, encoding="utf-8")


def _clone(origin: Path, dest: Path) -> None:
    subprocess.check_call(["git", "clone", "-q", str(origin), str(dest)])
    _git(dest, "config", "user.email", "d@d")
    _git(dest, "config", "user.name", "d")


def test_default_no_config_branches_from_main(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    wt = start_work(repo_root=repo, branch="feat/x")
    assert wt == repo / ".worktrees" / "x"
    assert wt.exists()
    head = _git_out(wt, "rev-parse", "--abbrev-ref", "HEAD").strip()
    assert head == "feat/x"


def test_config_base_used(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _git(repo, "branch", "prod")
    _git(repo, "checkout", "-q", "-b", "dev")
    (repo / "ahead").write_text("dev ahead\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "dev ahead")
    _git(repo, "checkout", "-q", "main")
    _write_cfg(repo, "base: prod\nlong_lived: [dev, prod]\n")
    wt = start_work(repo_root=repo, branch="fix/hot")
    # started from prod (== seed), not from dev
    assert not (wt / "ahead").exists()


def test_base_override_wins(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _git(repo, "checkout", "-q", "-b", "dev")
    (repo / "ahead").write_text("dev ahead\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "dev ahead")
    _git(repo, "checkout", "-q", "main")
    _write_cfg(repo, "base: main\nlong_lived: [dev]\n")
    wt = start_work(repo_root=repo, branch="feat/y", base_override="dev")
    assert (wt / "ahead").exists()


def test_base_override_must_be_declared(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _git(repo, "branch", "topic")  # exists but not declared
    with pytest.raises(StartWorkError, match="not a declared branch"):
        start_work(repo_root=repo, branch="feat/z", base_override="topic")


def test_refuses_protected_slug(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "long_lived: [prod]\n")
    with pytest.raises(StartWorkError, match="protected"):
        start_work(repo_root=repo, branch="feat/prod")


def test_refuses_bad_branch_shape(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    with pytest.raises(StartWorkError, match="<type>/<slug>"):
        start_work(repo_root=repo, branch="feature/X_Bad")


def test_refuses_missing_base_ref(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "base: dev\nlong_lived: [dev]\n")  # dev declared, never created
    with pytest.raises(StartWorkError, match="no local branch and no remote-tracking"):
        start_work(repo_root=repo, branch="feat/x")


def test_behind_base_starts_from_remote_with_no_upstream(tmp_path: Path):
    origin = tmp_path / "origin"
    _init_repo(origin)
    repo = tmp_path / "r"
    _clone(origin, repo)
    # origin/main advances after the clone → local main is behind
    (origin / "newer").write_text("newer\n", encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "newer")
    warnings: list[str] = []
    wt = start_work(repo_root=repo, branch="feat/x", warn=warnings.append)
    assert (wt / "newer").exists(), "must start from origin/main, not stale local"
    assert any("behind" in w for w in warnings)
    # --no-track: the feature branch must have no upstream
    rc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "feat/x@{upstream}"],
        cwd=repo, capture_output=True,
    ).returncode
    assert rc != 0, "feature branch must not track origin/main"


def test_diverged_base_refused(tmp_path: Path):
    origin = tmp_path / "origin"
    _init_repo(origin)
    repo = tmp_path / "r"
    _clone(origin, repo)
    # local main gains a commit AND origin/main gains a different one
    (repo / "local").write_text("local\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "local")
    (origin / "remote").write_text("remote\n", encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "remote")
    with pytest.raises(StartWorkError, match="diverged"):
        start_work(repo_root=repo, branch="feat/x")


def test_no_remote_warns_and_proceeds(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    warnings: list[str] = []
    wt = start_work(repo_root=repo, branch="feat/x", warn=warnings.append)
    assert wt.exists()
    assert any("no remote" in w for w in warnings)


def test_warns_when_worktrees_not_ignored(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    warnings: list[str] = []
    start_work(repo_root=repo, branch="feat/x", warn=warnings.append)
    assert any(".worktrees/" in w and "gitignore" in w.lower() for w in warnings)


def test_refuses_existing_worktree_dir(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    start_work(repo_root=repo, branch="feat/x")
    with pytest.raises(StartWorkError, match="already exists"):
        start_work(repo_root=repo, branch="fix/x")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/harness/test_start_work.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.harness.start_work'`

- [ ] **Step 3: Write the implementation**

Create `scripts/harness/start_work.py`:

```python
"""leash-start-work backend: create `.worktrees/<slug>` from the right base.

Mechanical gate for the leash-start-work skill (gates-over-prose): it
validates the `<type>/<slug>` name, resolves the base branch
(`--base` → `.harness/branches.yaml` → detected main/master), does a
fetch-and-warn freshness pass, and creates the worktree without moving
the session. Refusals exit non-zero with a clear message; offline work
never blocks (fetch failures warn and fall back to local refs).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.harness.branches import (
    BranchConfigError,
    load_branch_config,
    ref_exists,
)

BRANCH_RE = re.compile(r"^(feat|fix|refactor|docs|chore)/([a-z0-9][a-z0-9-]*)$")


class StartWorkError(RuntimeError):
    pass


def _run(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise StartWorkError(
            f"git {' '.join(args)} failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    return proc


def detect_remote(repo_root: Path, base: str) -> str | None:
    """The base branch's configured remote, else the sole remote, else
    `origin` if present, else None."""
    cfg = _run(["config", f"branch.{base}.remote"], repo_root, check=False)
    if cfg.returncode == 0 and cfg.stdout.strip():
        return cfg.stdout.strip()
    listing = _run(["remote"], repo_root, check=False)
    remotes = [r for r in listing.stdout.split() if r]
    if len(remotes) == 1:
        return remotes[0]
    if "origin" in remotes:
        return "origin"
    return None


def resolve_start_point(
    repo_root: Path, base: str, remote: str | None, warn,
) -> tuple[str, bool]:
    """Pick the freshest ref for `base`. Returns (start_point, use_no_track).

    Diverged local/remote base is a refusal — never silently pick a side.
    """
    local = f"refs/heads/{base}"
    tracking = f"refs/remotes/{remote}/{base}" if remote else None
    has_local = ref_exists(repo_root, local)
    has_tracking = tracking is not None and ref_exists(repo_root, tracking)
    if not has_local and not has_tracking:
        raise StartWorkError(
            f"base branch {base!r} has no local branch and no remote-tracking "
            "ref — fetch it first or pick another base"
        )
    if not has_local:
        warn(f"base {base!r} exists only as {remote}/{base}; starting there")
        return f"{remote}/{base}", True
    if not has_tracking:
        return base, False
    counts = _run(
        ["rev-list", "--left-right", "--count", f"{local}...{tracking}"],
        repo_root,
    ).stdout.split()
    ahead, behind = int(counts[0]), int(counts[1])
    if ahead and behind:
        raise StartWorkError(
            f"local {base} and {remote}/{base} have diverged "
            f"({ahead} ahead / {behind} behind); reconcile them first — "
            "refusing to silently pick a side"
        )
    if behind:
        warn(f"local {base} is {behind} commit(s) behind {remote}/{base}; "
             f"starting from {remote}/{base}")
        return f"{remote}/{base}", True
    return base, False


def _default_warn(msg: str) -> None:
    print(f"warn: {msg}", file=sys.stderr)


def start_work(
    *,
    repo_root: Path,
    branch: str,
    base_override: str | None = None,
    warn=_default_warn,
) -> Path:
    m = BRANCH_RE.match(branch)
    if not m:
        raise StartWorkError(
            "branch must be <type>/<slug> with type ∈ "
            f"feat|fix|refactor|docs|chore and a kebab-case slug; got {branch!r}"
        )
    slug = m.group(2)
    try:
        cfg = load_branch_config(repo_root)
    except BranchConfigError as exc:
        raise StartWorkError(str(exc)) from exc
    if slug in cfg.protected:
        raise StartWorkError(
            f"slug {slug!r} collides with protected branch {slug!r} "
            f"(would create .worktrees/{slug}); pick another slug"
        )
    base = base_override or cfg.base
    # protected == long_lived ∪ {main, master}: exactly the allowed bases.
    if base not in cfg.protected:
        raise StartWorkError(
            f"base {base!r} is not a declared branch; allowed: "
            f"{sorted(cfg.protected)} (declare it in .harness/branches.yaml)"
        )
    remote = detect_remote(repo_root, base)
    if remote:
        fetched = _run(["fetch", remote, base], repo_root, check=False)
        if fetched.returncode != 0:
            warn(f"git fetch {remote} {base} failed; using local refs")
    else:
        warn("no remote detected; skipping freshness fetch")
    start_point, no_track = resolve_start_point(repo_root, base, remote, warn)
    wt = repo_root / ".worktrees" / slug
    if wt.exists():
        raise StartWorkError(f"worktree already exists: {wt}")
    cmd = ["worktree", "add"]
    if no_track:
        # A remote-tracking start-point would otherwise set the feature
        # branch's upstream to origin/<base>, corrupting `git status`,
        # bare `git pull` and deletion semantics on the feature branch.
        cmd.append("--no-track")
    cmd += ["-b", branch, str(wt), start_point]
    _run(cmd, repo_root)
    gitignore = repo_root / ".gitignore"
    lines = (
        [ln.strip() for ln in gitignore.read_text(encoding="utf-8").splitlines()]
        if gitignore.exists() else []
    )
    if ".worktrees/" not in lines:
        warn(".worktrees/ is not in .gitignore — see bootstrap-dev-leash "
             "Step 3c / add it under the `# dev-on-leash` heading")
    print(f"Created {wt} on {branch} from {start_point}")
    return wt


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("branch", help="<type>/<slug>, type ∈ feat|fix|refactor|docs|chore")
    p.add_argument("--base", dest="base_override", default=None,
                   help="base branch override (must be declared in "
                        ".harness/branches.yaml or be main/master)")
    p.add_argument(
        "--repo-root", type=Path,
        default=Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()),
    )
    args = p.parse_args(argv[1:])
    try:
        start_work(
            repo_root=args.repo_root.resolve(),
            branch=args.branch,
            base_override=args.base_override,
        )
    except StartWorkError as exc:
        sys.stderr.write(f"leash-start-work: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/harness/test_start_work.py -x -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add scripts/harness/start_work.py tests/harness/test_start_work.py
git commit -m "feat(harness): start_work.py — mechanical worktree creation with configurable base"
```

<!-- task-meta
id: T02
touches:
  - scripts/harness/start_work.py
  - tests/harness/test_start_work.py
depends: [T01]
verify: python -m pytest tests/harness/test_start_work.py -x -q
acceptance: null
-->

---

### Task 3 — `finish_work.py`: protected set + ancestry proof + audited `-D`

**Files:**
- Modify: `scripts/harness/finish_work.py`
- Test: `tests/harness/test_finish_work.py` (extend)

**Interfaces:**
- Consumes: `load_branch_config`, `BranchConfigError`, `prove_merged` from `scripts.harness.branches` (Task 1).
- Produces: `finish_work(...)` keeps its exact current signature and return type (`str`, the branch). New audit file: `.harness/finish_audit.log`, one tab-separated line per deletion: `<utc-iso>\tDELETE\tbranch=<b>\tsha=<sha>\tproven=<ref>`.

- [ ] **Step 1: Add the failing tests**

Append to `tests/harness/test_finish_work.py`:

```python
def _write_cfg(repo: Path, text: str) -> None:
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "branches.yaml").write_text(text, encoding="utf-8")


def test_merged_into_declared_target_while_head_on_main(tmp_path: Path):
    """The critic-found blocker: merged into dev, HEAD on main — must
    remove worktree AND delete branch (proof-based -D, not -d)."""
    repo = tmp_path / "r"
    _init_repo(repo)
    subprocess.check_call(["git", "branch", "dev"], cwd=repo)
    wt = _add_worktree(repo, "feat-x", "feat/x")
    (wt / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=wt)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=wt)
    # merge feat/x into dev without touching main's checkout:
    subprocess.check_call(
        ["git", "fetch", ".", "feat/x:dev"], cwd=repo)  # fast-forward dev
    _write_cfg(repo, "merge_target: dev\nlong_lived: [dev]\n")
    branch = finish_work(repo_root=repo, slug="feat-x")
    assert branch == "feat/x"
    assert not wt.exists()
    out = subprocess.run(["git", "branch"], cwd=repo,
                         capture_output=True, text=True).stdout
    assert "feat/x" not in out
    audit = (repo / ".harness" / "finish_audit.log").read_text(encoding="utf-8")
    assert "branch=feat/x" in audit and "proven=refs/heads/dev" in audit


def test_unmerged_into_target_still_refused(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    subprocess.check_call(["git", "branch", "dev"], cwd=repo)
    wt = _add_worktree(repo, "feat-x", "feat/x")
    (wt / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=wt)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=wt)
    _write_cfg(repo, "merge_target: dev\nlong_lived: [dev]\n")
    with pytest.raises(FinishWorkError, match="not an ancestor"):
        finish_work(repo_root=repo, slug="feat-x")
    assert wt.exists(), "nothing may be removed when the proof fails"


def test_refuses_worktree_on_declared_long_lived_branch(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "long_lived: [dev]\n")
    wt = repo / ".worktrees" / "devwt"
    subprocess.check_call(
        ["git", "worktree", "add", str(wt), "-b", "dev", "main"], cwd=repo)
    with pytest.raises(FinishWorkError, match="refusing"):
        finish_work(repo_root=repo, worktree_path=str(wt))


def test_malformed_branches_yaml_is_hard_error(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "bogus: 1\n")
    _add_worktree(repo, "feat-x", "feat/x")
    with pytest.raises(FinishWorkError, match="unknown key"):
        finish_work(repo_root=repo, slug="feat-x")
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python -m pytest tests/harness/test_finish_work.py -x -q`
Expected: FAIL on `test_merged_into_declared_target_while_head_on_main` (git `branch -d`/merge-check error or refusal), existing tests still pass up to that point.

- [ ] **Step 3: Rework `finish_work.py`**

In `scripts/harness/finish_work.py`:

3a. Update the module docstring's last sentence to:

```python
"""leash-finish-work: remove a .worktrees/<slug> worktree + its branch.

Stateless (no lockfiles). Counterpart to /leash-start-work. Refuses on a
dirty worktree or an unmerged branch unless --keep-branch. Deletion uses
`git branch -D` ONLY after an explicit `git merge-base --is-ancestor`
proof against the configured merge target (local or remote-tracking) —
never `-d`'s HEAD-relative heuristic, and never without proof. Every
deletion is audited to .harness/finish_audit.log; work is never silently
discarded.
"""
```

3b. Add imports after the existing ones:

```python
import datetime as _dt

from scripts.harness.branches import (
    BranchConfigError,
    load_branch_config,
    prove_merged,
)
```

(`finish_work.py` is always imported as `scripts.harness.finish_work` by tests and run with `python -m`; no sys.path shim needed beyond what exists.)

3c. Delete the now-unused `_branch_is_merged` function entirely.

3d. Add the audit helper below `_worktree_dirty`:

```python
def _audit_delete(repo_root: Path, *, branch: str, sha: str, proven: str) -> None:
    log = repo_root / ".harness" / "finish_audit.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.UTC).isoformat()
    with log.open("a", encoding="utf-8") as f:
        f.write(f"{ts}\tDELETE\tbranch={branch}\tsha={sha}\tproven={proven}\n")
```

3e. Replace the body of `finish_work` from the `branch = _current_branch(wt)` line down with:

```python
    branch = _current_branch(wt)
    try:
        cfg = load_branch_config(repo_root)
    except BranchConfigError as exc:
        raise FinishWorkError(str(exc)) from exc
    if branch in cfg.protected:
        raise FinishWorkError(f"worktree {wt} is on {branch}; refusing")
    if _worktree_dirty(wt):
        raise FinishWorkError(
            f"worktree {wt} has uncommitted changes; commit or stash first"
        )
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
    # Prove everything BEFORE the first destructive step so a failure can
    # never leave "worktree gone, branch orphaned".
    sha = _git(["rev-parse", branch], cwd=repo_root).strip()
    _git(["worktree", "remove", str(wt)], cwd=repo_root)
    if not keep_branch:
        assert proven is not None
        # -D is sanctioned here by the explicit ancestry proof above; -d's
        # HEAD-relative check cannot express "merged into dev while HEAD
        # is on main" and would abort the multi-branch flow mid-way.
        _git(["branch", "-D", branch], cwd=repo_root)
        _audit_delete(repo_root, branch=branch, sha=sha, proven=proven)
    return branch
```

- [ ] **Step 4: Run the full finish_work suite**

Run: `python -m pytest tests/harness/test_finish_work.py -x -q`
Expected: PASS — all pre-existing tests (no-config behavior unchanged: `merge_target` defaults to `main`, `test_removes_merged_clean_worktree`'s trivially-merged branch is an ancestor of main, and `test_refuses_unmerged_branch`'s `match="unmerged"` still matches the new "is unmerged — not an ancestor of" message) plus the four new ones.

- [ ] **Step 5: Add `.harness/finish_audit.log` to this repo's `.gitignore`** (runtime audit file, same class as `.harness/exceptions.log`) — append under the existing `# dev-on-leash` heading:

```
.harness/finish_audit.log
```

- [ ] **Step 6: Commit**

```bash
git add scripts/harness/finish_work.py tests/harness/test_finish_work.py .gitignore
git commit -m "feat(harness): finish_work proves ancestry against merge_target, audited -D"
```

<!-- task-meta
id: T03
touches:
  - scripts/harness/finish_work.py
  - tests/harness/test_finish_work.py
  - .gitignore
depends: [T01]
verify: python -m pytest tests/harness/test_finish_work.py -x -q
acceptance: null
-->

---

### Task 4 — `cycle_done.py`: advisory agrees with enforcement

**Files:**
- Modify: `scripts/harness/cycle_done.py` (function `advise_merged_worktrees`, currently lines 134-168)
- Test: `tests/harness/test_cycle_done_advise.py` (extend)

**Interfaces:**
- Consumes: `load_branch_config`, `BranchConfigError`, `prove_merged` from `scripts.harness.branches` (Task 1).
- Produces: `advise_merged_worktrees(*, repo_root: Path) -> list[str]` — same signature, same reminder string format.

- [ ] **Step 1: Add the failing test**

Append to `tests/harness/test_cycle_done_advise.py` — the file already defines `_init_git_repo(path)` and `_add_worktree(repo, rel_dir, branch)`; reuse them exactly:

```python
def test_advises_branch_merged_into_declared_target_not_head(tmp_path: Path):
    """Advisory must agree with finish_work: merged into dev while HEAD
    is on main still earns a clean-up reminder."""
    repo = tmp_path / "p"
    _init_git_repo(repo)
    subprocess.check_call(["git", "branch", "dev"], cwd=repo)
    wt = _add_worktree(repo, ".worktrees/x", "feat/x")
    (wt / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=wt)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=wt)
    subprocess.check_call(["git", "fetch", ".", "feat/x:dev"], cwd=repo)
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "branches.yaml").write_text(
        "merge_target: dev\nlong_lived: [dev]\n", encoding="utf-8")
    reminders = advise_merged_worktrees(repo_root=repo)
    assert any("feat/x" in r for r in reminders), reminders


def test_advisory_quiet_on_malformed_config(tmp_path: Path):
    repo = tmp_path / "p"
    _init_git_repo(repo)
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "branches.yaml").write_text("bogus: 1\n", encoding="utf-8")
    # advisory never raises — enforcement (finish_work) surfaces the error
    assert advise_merged_worktrees(repo_root=repo) == []
```

- [ ] **Step 2: Run to verify the first new test fails**

Run: `python -m pytest tests/harness/test_cycle_done_advise.py -x -q`
Expected: FAIL on `test_advises_branch_merged_into_declared_target_not_head` (bare `git branch --merged` is HEAD-relative; feat/x is not merged into main).

- [ ] **Step 3: Rework `advise_merged_worktrees`**

In `scripts/harness/cycle_done.py`, add the import near the top (after the `sys.path` insertion block that already exists):

```python
from scripts.harness.branches import BranchConfigError, load_branch_config, prove_merged
```

Replace the merged-set logic inside `advise_merged_worktrees` — delete these two lines:

```python
    merged_raw = _git_out(["branch", "--merged"], repo_root)
    merged = {b.strip().lstrip("*+ ").strip() for b in merged_raw.splitlines()}
```

insert instead:

```python
    try:
        cfg = load_branch_config(repo_root)
    except BranchConfigError:
        # Advisory stays quiet on a bad config; finish_work (the
        # enforcement half) raises the loud error.
        return reminders
```

and replace the membership test

```python
        if branch not in merged:
            continue
```

with

```python
        if prove_merged(repo_root, branch, cfg) is None:
            continue
```

Also update the function docstring's location-filter sentence: the parenthetical about `git branch --merged` listing "merged into itself" no longer applies; replace that parenthetical with "(the primary checkout is excluded by location, and merged-ness is proven per-branch against the configured merge target via `prove_merged`)".

- [ ] **Step 4: Run the advise suite**

Run: `python -m pytest tests/harness/test_cycle_done_advise.py -x -q`
Expected: PASS (existing tests unchanged — with no config, `merge_target` = main and ancestry-of-main matches the old `git branch --merged` result for these fixtures).

- [ ] **Step 5: Commit**

```bash
git add scripts/harness/cycle_done.py tests/harness/test_cycle_done_advise.py
git commit -m "feat(harness): cycle_done advisory shares prove_merged semantics"
```

<!-- task-meta
id: T04
touches:
  - scripts/harness/cycle_done.py
  - tests/harness/test_cycle_done_advise.py
depends: [T01]
verify: python -m pytest tests/harness/test_cycle_done_advise.py -x -q
acceptance: null
-->

---

### Task 5 — Skills: thin prose over the scripts

**Files:**
- Modify: `skills/leash-start-work/SKILL.md`
- Modify: `skills/leash-finish-work/SKILL.md`
- Test: `tests/test_skill_start_work.py` (rewrite affected tests)

**Interfaces:**
- Consumes: CLI shapes from Tasks 2-3: `python -m scripts.harness.start_work <type>/<slug> [--base <branch>]`, `python -m scripts.harness.finish_work <slug> [--keep-branch]`.

- [ ] **Step 1: Update the start-work skill tests first**

In `tests/test_skill_start_work.py`, replace `test_branches_from_main` and `test_creates_worktree_without_moving_session` with:

```python
def test_invokes_mechanical_backend():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "python -m scripts.harness.start_work" in text
    assert "--base" in text


def test_documents_base_resolution():
    text = SKILL_PATH.read_text(encoding="utf-8")
    # precedence: --base → .harness/branches.yaml → main/master
    assert ".harness/branches.yaml" in text
    assert "main" in text  # default without config


def test_creates_worktree_without_moving_session():
    """Sessions rooted inside `.worktrees/<slug>` lose their history when
    the worktree is removed (history is keyed to the session root). The
    skill must run the backend from the main checkout and forbid
    session-relocating mechanisms such as EnterWorktree."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "Do **not** use session-relocating mechanisms (`EnterWorktree`" in text
    assert "session stays" in text.lower() or "stays rooted" in text.lower()
```

Keep every other existing test unchanged.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_skill_start_work.py -x -q`
Expected: FAIL — the skill text does not yet mention `scripts.harness.start_work`.

- [ ] **Step 3: Rewrite `skills/leash-start-work/SKILL.md` "How" section**

Replace steps 1-5 of the `## How` section with:

````markdown
1. **Pick the branch name.** Choose `type` ∈ `feat | fix | refactor | docs |
   chore` and a short kebab-case `slug`. The branch is `<type>/<slug>`; the
   worktree directory is `.worktrees/<slug>` (no type prefix on the dir).
   Never target `main`/`master` or any branch declared `long_lived` in
   `.harness/branches.yaml` — branch discipline is mandatory and never
   overridden here (the backend refuses these mechanically).

2. **Run the mechanical backend** from the main checkout:

   ```
   python -m scripts.harness.start_work <type>/<slug> [--base <branch>]
   ```

   Base resolution precedence: `--base` argument → `base:` in
   `.harness/branches.yaml` → detected `main`/`master`. A `--base` must be
   `main`/`master` or declared in the config's `long_lived` list. The
   script fetches the base's remote when one exists and, if the local base
   is behind, warns and branches from the remote-tracking ref with
   `--no-track` (the feature branch gets no upstream). It refuses a
   diverged base, a protected slug, and a missing base ref. Offline work
   never blocks — fetch failures warn and fall back to local refs. Do not
   hand-roll `git worktree add`; the script is the guardrail.

3. **Stay home.** Do **not** use session-relocating mechanisms (`EnterWorktree`,
   opening the worktree folder as a new workspace, launching a new session
   inside `.worktrees/<slug>`): they re-root the session in the worktree, and
   its history is lost when the worktree is removed. The
   `session_root_guard` SessionStart hook warns if a session is ever
   rooted there.

4. **Heed the warnings.** The script warns when `.worktrees/` is not in the
   project `.gitignore` (bootstrap declined or never run) — point at
   `bootstrap-dev-leash` / adding `.worktrees/` under the `# dev-on-leash`
   heading.

5. **Report.** Relay the script's output — worktree path and the base it
   actually started from — and remind that every `Edit`, `Write`, and file
   `Read` for this change targets paths under `.worktrees/<slug>`, while the
   session itself stays rooted in the main checkout.
````

Update the frontmatter `description` to mention the configurable base:
`Picks a <type>/<slug> branch off the configured base branch (.harness/branches.yaml, default main), creates .worktrees/<slug> via scripts.harness.start_work while the session stays rooted in the main checkout, and keeps you on the disciplined path without the stash-dance.`

- [ ] **Step 4: Update `skills/leash-finish-work/SKILL.md`**

In the `## How` section, replace step 1 with:

```markdown
1. Make sure the worktree is committed and, unless you pass `--keep-branch`,
   that its branch is merged into the project's `merge_target`
   (`.harness/branches.yaml`; default `main`/`master`). The script proves
   merged-ness itself with `git merge-base --is-ancestor` against the local
   target **or** its remote-tracking ref, so a stale local target does not
   block cleanup.
```

In step 3's bullet list, replace the last bullet with:

```markdown
   - refuses if the branch is not proven merged into the merge target
     (merge it, or pass `--keep-branch`)
   - proves ancestry **before** removing anything, then runs
     `git worktree remove` and `git branch -D` — `-D` is sanctioned only by
     the explicit proof, and every deletion is audited to
     `.harness/finish_audit.log`
```

Replace the `## Constraints` section body with:

```markdown
- Never delete without proof. `git branch -D` runs only after the script's
  own `merge-base --is-ancestor` proof; `git worktree remove --force` is out
  of scope. If the script refuses, fix the underlying issue.
- Squash- and rebase-merges produce new SHAs and are not provable — use
  `--keep-branch` and delete the branch manually once you are sure.
```

- [ ] **Step 5: Run the skills suite**

Run: `python -m pytest tests/test_skill_start_work.py -x -q`
Expected: PASS. (`tests/test_docs.py` only asserts README strings, not skill wording — it is untouched here and belongs to Task 7.)

- [ ] **Step 6: Commit**

```bash
git add skills/leash-start-work/SKILL.md skills/leash-finish-work/SKILL.md tests/test_skill_start_work.py
git commit -m "docs(skills): start/finish-work skills wrap the mechanical backends"
```

<!-- task-meta
id: T05
touches:
  - skills/leash-start-work/SKILL.md
  - skills/leash-finish-work/SKILL.md
  - tests/test_skill_start_work.py
depends: [T02, T03]
verify: python -m pytest tests/test_skill_start_work.py -x -q
acceptance: null
-->

---

### Task 6 — Templates `{{BASE_BRANCH}}` + bootstrap interview

**Files:**
- Modify: `templates/AGENTS.md.tmpl`, `templates/CLAUDE.md.tmpl`
- Modify: `skills/bootstrap-dev-leash/SKILL.md`
- Test: `tests/test_templates.py`, `tests/test_skill_bootstrap.py` (extend)

**Interfaces:**
- Produces: new placeholder `{{BASE_BRANCH}}` in both templates (bootstrap renders it, default `main`); bootstrap interview item 13; bootstrap Step 3d writes `.harness/branches.yaml` (hand-write pattern, like Step 3b's `.harness/gates`).

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_templates.py`:

```python
def test_templates_use_base_branch_placeholder():
    # NB: this file imports `pathlib` and defines ROOT — no bare Path here.
    agents = (ROOT / "templates" / "AGENTS.md.tmpl").read_text(encoding="utf-8")
    claude = (ROOT / "templates" / "CLAUDE.md.tmpl").read_text(encoding="utf-8")
    assert "{{BASE_BRANCH}}" in agents
    assert "{{BASE_BRANCH}}" in claude
    # the raw hardcoded worktree command must be gone — the backend script
    # is the single path
    assert "git worktree add .worktrees/<slug> -b <type>/<slug> main" not in agents
    assert "python -m scripts.harness.start_work" in agents
```

Append to `tests/test_skill_bootstrap.py`:

```python
def test_bootstrap_documents_branches_config():
    text = Path("skills/bootstrap-dev-leash/SKILL.md").read_text(encoding="utf-8")
    assert ".harness/branches.yaml" in text
    assert "{{BASE_BRANCH}}" in text
    assert "long_lived" in text
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_templates.py tests/test_skill_bootstrap.py -x -q`
Expected: FAIL on both new tests.

- [ ] **Step 3: Edit `templates/AGENTS.md.tmpl`**

- Line 11: `created from \`main\` (or \`master\`)` → `created from \`{{BASE_BRANCH}}\``. Keep the rest of the sentence (never commit directly to `main`/`master`) intact.
- Line 17: `1. \`git checkout main && git pull\` — start from the latest state.` → `1. \`git checkout {{BASE_BRANCH}} && git pull\` — start from the latest state.`
- Line 147: replace the fenced command

  ```
  git worktree add .worktrees/<slug> -b <type>/<slug> main   # type ∈ feat|fix|refactor|docs|chore
  ```

  with

  ```
  python -m scripts.harness.start_work <type>/<slug>   # type ∈ feat|fix|refactor|docs|chore; add --base <branch> to override {{BASE_BRANCH}}
  ```

- Line 151: `branched from \`main\`` → `branched from \`{{BASE_BRANCH}}\``.
- Line 161: `(from \`main\`)` → `(from \`{{BASE_BRANCH}}\`)`.
- Leave line 71 (CI on push to `main`/`master`) untouched — it describes CI, not branching.

- [ ] **Step 4: Edit `templates/CLAUDE.md.tmpl`**

- Line 35: `branch merged to main` → `branch merged to the project's merge target (\`.harness/branches.yaml\`, default \`{{BASE_BRANCH}}\`)`.
- Line 43: `\`<type>/<slug>\` branch off \`main\`` → `\`<type>/<slug>\` branch off \`{{BASE_BRANCH}}\``.
- Line 53: `from \`main\`)` → `from \`{{BASE_BRANCH}}\`)`.

- [ ] **Step 5: Edit `skills/bootstrap-dev-leash/SKILL.md`**

- Interview table: add row `| 13 | Long-lived branches besides main? (dev/qa/homol/prod) | AskUserQuestion (yes / no) + free-text follow-up | {{BASE_BRANCH}} + .harness/branches.yaml (Step 3d) |`.
- Notes on specific items — add:

```markdown
- **Long-lived branches (item 13):** if no, `{{BASE_BRANCH}}` renders as
  `main` (or `master` — match the repo's default branch) and no
  `branches.yaml` is written. If yes, follow up in free text for: the list
  of long-lived branches, the default base for new work (e.g. `prod` when
  production trails dev), and the merge target where work branches land
  (e.g. `dev`). `{{BASE_BRANCH}}` renders as the chosen base. This never
  weakens branch discipline — the long-lived branches become *protected*
  (no direct work on them), exactly like main/master.
```

- Placeholders per template: add `{{BASE_BRANCH}}` to both the `CLAUDE.md.tmpl` and `AGENTS.md.tmpl` substitute lists.
- After Step 3c, add:

````markdown
## Step 3d — Write the branches config (only if item 13 = yes)

Write `.harness/branches.yaml` by hand (same pattern as Step 3b's
`.harness/gates` — no template file):

```yaml
# dev-on-leash: multi-branch config. See README "Multi-branch projects".
base: <default base from the interview>
merge_target: <merge target from the interview>
long_lived: [<the declared branches>]
```

Do NOT overwrite an existing `branches.yaml` — show a diff and confirm,
like the Step 3 discipline files. The init script (Step 4) never touches
this file.
````

- [ ] **Step 6: Run the suites**

Run: `python -m pytest tests/test_templates.py tests/test_skill_bootstrap.py -x -q`
Expected: PASS — including the pre-existing template tests (`test_agents_template_documents_worktree_start_path`, `test_claude_template_mentions_start_work`; if either asserts the old literal `git worktree add ... main` string, update it to the new `python -m scripts.harness.start_work` line in this commit).

- [ ] **Step 7: Commit**

```bash
git add templates/AGENTS.md.tmpl templates/CLAUDE.md.tmpl skills/bootstrap-dev-leash/SKILL.md tests/test_templates.py tests/test_skill_bootstrap.py
git commit -m "feat(templates): {{BASE_BRANCH}} placeholder + bootstrap branches.yaml interview"
```

<!-- task-meta
id: T06
touches:
  - templates/AGENTS.md.tmpl
  - templates/CLAUDE.md.tmpl
  - skills/bootstrap-dev-leash/SKILL.md
  - tests/test_templates.py
  - tests/test_skill_bootstrap.py
depends: [T05]
verify: python -m pytest tests/test_templates.py tests/test_skill_bootstrap.py -x -q
acceptance: null
-->

---

### Task 7 — README + dogfood config + full suite

**Files:**
- Modify: `README.md`
- Create: `.harness/branches.yaml` (this repo — dogfood)
- Test: `tests/test_docs.py` (extend)

- [ ] **Step 1: Add the failing doc test**

Append to `tests/test_docs.py`:

```python
def test_readme_documents_multi_branch_config():
    # NB: follow this file's convention — `pathlib` + ROOT, no bare Path.
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert ".harness/branches.yaml" in text
    assert "merge_target" in text
    assert "--base" in text
```

Run: `python -m pytest tests/test_docs.py -x -q` — Expected: FAIL on the new test.

- [ ] **Step 2: Add the README section**

Add under the section that documents `leash-start-work`/worktrees (keep the README's existing tone and heading level):

````markdown
### Multi-branch projects (`.harness/branches.yaml`)

Projects with several long-lived branches (dev / qa / homol / prod)
declare them once:

```yaml
# .harness/branches.yaml  (optional — absent means classic main/master)
base: prod                          # where new worktrees start
merge_target: dev                   # where work branches land (delete-safety)
long_lived: [dev, qa, homol, prod]  # protected, like main/master
```

- `/leash-start-work` starts worktrees from `base` (override per-invocation
  with `--base <branch>`), fetching first and warning when the local base
  trails its remote.
- `/leash-finish-work` deletes a work branch only after proving it is an
  ancestor of `merge_target` (local or remote-tracking) — squash-merged
  branches are not provable; use `--keep-branch`.
- Every `long_lived` branch is protected exactly like `main`: no direct
  work, no worktree removal while checked out on one.
````

- [ ] **Step 3: Dogfood — declare this repo's config**

Create `.harness/branches.yaml` in this repo:

```yaml
# dev-on-leash itself: single-trunk. Present to dogfood the config path.
base: main
merge_target: main
```

Commit-tracked (it is config, not runtime state — unlike `finish_audit.log`).

- [ ] **Step 4: Full-suite verification**

Run: `python -m pytest -x -q`
Expected: PASS (0 failed).

- [ ] **Step 5: Dogfood the live cycle** (human-run check, still in this task): from the main checkout run `python -m scripts.harness.start_work chore/dogfood-branches` then `python -m scripts.harness.finish_work dogfood-branches` (trivially merged — no commits). Expected: worktree created from `main` and cleanly removed; `.harness/finish_audit.log` gains a `DELETE` line.

- [ ] **Step 6: Commit**

```bash
git add README.md tests/test_docs.py .harness/branches.yaml
git commit -m "docs(readme): multi-branch config + dogfood branches.yaml"
```

<!-- task-meta
id: T07
touches:
  - README.md
  - tests/test_docs.py
  - .harness/branches.yaml
depends: [T06]
verify: python -m pytest -x -q
acceptance: null
-->

---

## Completion

After all tasks: run `python -m scripts.harness.cycle_done --plan docs/plans/configurable-base-branch.md`, then merge `feat/configurable-base-branch` into `main` and clean up with `/leash-finish-work configurable-base-branch`.
