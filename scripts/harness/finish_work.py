"""leash-finish-work: remove a .worktrees/<slug> worktree + its branch.

Stateless (no lockfiles). Counterpart to /leash-start-work. Refuses on a
dirty worktree or an unmerged branch unless --keep-branch. Never uses
`git worktree remove --force` or `git branch -D` — work is never silently
discarded.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


class FinishWorkError(RuntimeError):
    pass


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise FinishWorkError(
            f"git {' '.join(args)} failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    return proc.stdout


def _current_branch(worktree: Path) -> str:
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree).strip()


def _worktree_dirty(worktree: Path) -> bool:
    return bool(_git(["status", "--porcelain"], cwd=worktree).strip())


def _branch_is_merged(repo: Path, branch: str) -> bool:
    out = _git(["branch", "--merged"], cwd=repo)
    # Strip `*` (current) and `+` (checked out in a linked worktree) markers.
    merged = {b.strip().lstrip("*+ ").strip() for b in out.splitlines()}
    return branch in merged


def resolve_worktree(
    *, repo_root: Path, slug: str | None = None, worktree_path: str | None = None
) -> Path:
    if worktree_path:
        return Path(worktree_path).resolve()
    if slug:
        return (repo_root / ".worktrees" / slug).resolve()
    raise FinishWorkError("name the worktree: pass a slug or --path")


def finish_work(
    *,
    repo_root: Path,
    slug: str | None = None,
    worktree_path: str | None = None,
    keep_branch: bool = False,
) -> str:
    wt = resolve_worktree(repo_root=repo_root, slug=slug, worktree_path=worktree_path)
    if wt == repo_root.resolve():
        raise FinishWorkError("refusing to remove the main worktree")
    if not wt.exists():
        raise FinishWorkError(f"worktree not found: {wt}")
    branch = _current_branch(wt)
    if branch in ("main", "master"):
        raise FinishWorkError(f"worktree {wt} is on {branch}; refusing")
    if _worktree_dirty(wt):
        raise FinishWorkError(
            f"worktree {wt} has uncommitted changes; commit or stash first"
        )
    if not keep_branch and not _branch_is_merged(repo_root, branch):
        raise FinishWorkError(
            f"branch {branch} is unmerged; merge it first or pass --keep-branch"
        )
    _git(["worktree", "remove", str(wt)], cwd=repo_root)
    if not keep_branch:
        _git(["branch", "-d", branch], cwd=repo_root)
    return branch


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("slug", nargs="?", default=None,
                   help="slug under .worktrees/ to finish")
    p.add_argument("--path", dest="worktree_path", default=None,
                   help="explicit worktree path (overrides slug)")
    p.add_argument(
        "--repo-root", type=Path,
        default=Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()),
    )
    p.add_argument("--keep-branch", action="store_true")
    args = p.parse_args(argv[1:])
    try:
        branch = finish_work(
            repo_root=args.repo_root.resolve(),
            slug=args.slug,
            worktree_path=args.worktree_path,
            keep_branch=args.keep_branch,
        )
    except FinishWorkError as exc:
        sys.stderr.write(f"leash-finish-work: {exc}\n")
        return 1
    kept = " (branch kept)" if args.keep_branch else ""
    print(f"Finished work on {branch}; worktree removed{kept}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
