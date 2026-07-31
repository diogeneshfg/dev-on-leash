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
_ALLOWED_KEYS = {"base", "merge_target", "long_lived", "workflow"}
# Bare branch names only: long-lived branches carry no slash and no
# leading '-'; conservative charset keeps shell/git-arg surprises out.
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
WORK_BRANCH_RE = re.compile(r"^(feat|fix|refactor|docs|chore)/([a-z0-9][a-z0-9-]*)$")
_ALLOWED_WORKFLOWS = ("worktree", "branch")


class BranchConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class BranchConfig:
    base: str
    merge_target: str
    protected: frozenset[str]
    workflow: str


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
            workflow="worktree",
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

    workflow_raw = raw.get("workflow")
    if workflow_raw is None:
        workflow_raw = "worktree"
    if workflow_raw not in _ALLOWED_WORKFLOWS:
        raise BranchConfigError(
            f"{path}: `workflow: {workflow_raw!r}` must be one of "
            f"{list(_ALLOWED_WORKFLOWS)}"
        )

    return BranchConfig(
        base=_resolve("base"),
        merge_target=_resolve("merge_target"),
        protected=frozenset(long_lived) | {"main", "master"},
        workflow=workflow_raw,
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
