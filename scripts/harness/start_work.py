"""leash-start-work backend: create `.worktrees/<slug>` or branch from the right base.

Mechanical gate for the leash-start-work skill (gates-over-prose): it
validates the `<type>/<slug>` name, resolves the base branch
(`--base` → `.harness/branches.yaml` → detected main/master), does a
fetch-and-warn freshness pass, and creates the worktree (worktree mode)
or checks out a branch (branch mode) without moving the session in branch
mode. Refusals exit non-zero with a clear message; offline work never
blocks (fetch failures warn and fall back to local refs).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.harness.branches import (
    BranchConfigError,
    WORK_BRANCH_RE,
    load_branch_config,
    ref_exists,
)
from scripts.harness.repo_resolve import (
    RepoResolveError,
    echo_context,
    resolve_cli_repo_root,
)


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


def start_work(
    *,
    repo_root: Path,
    branch: str,
    base_override: str | None = None,
    warn=_default_warn,
) -> Path:
    """Start a new work branch.

    Returns the created worktree path (worktree mode) or the repo root (branch mode).
    """
    m = WORK_BRANCH_RE.match(branch)
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
        if cfg.workflow == "branch":
            detail = f"branch {branch!r} shadows protected branch {slug!r}"
        else:
            detail = (f"would create .worktrees/{slug}, colliding with "
                      f"protected branch {slug!r}")
        raise StartWorkError(f"slug {slug!r}: {detail}; pick another slug")
    base = base_override or cfg.base
    # protected == long_lived ∪ {main, master}: exactly the allowed bases.
    if base not in cfg.protected:
        raise StartWorkError(
            f"base {base!r} is not a declared branch; allowed: "
            f"{sorted(cfg.protected)} (declare it in .harness/branches.yaml)"
        )
    print(echo_context(repo_root, cfg, base))
    remote = detect_remote(repo_root, base)
    if remote:
        fetched = _run(["fetch", remote, base], repo_root, check=False)
        if fetched.returncode != 0:
            warn(f"git fetch {remote} {base} failed; using local refs")
    else:
        warn("no remote detected; skipping freshness fetch")
    start_point, no_track = resolve_start_point(repo_root, base, remote, warn)
    if cfg.workflow == "branch":
        return _start_branch_mode(
            repo_root=repo_root, branch=branch,
            start_point=start_point, no_track=no_track, warn=warn,
        )
    # worktree-mode tail:
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
        default=None,
    )
    args = p.parse_args(argv[1:])
    try:
        start_work(
            repo_root=resolve_cli_repo_root(args.repo_root),
            branch=args.branch,
            base_override=args.base_override,
        )
    except (StartWorkError, RepoResolveError) as exc:
        sys.stderr.write(f"leash-start-work: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
