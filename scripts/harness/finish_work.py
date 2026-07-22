"""leash-finish-work: remove a .worktrees/<slug> worktree + its branch.

Stateless (no lockfiles). Counterpart to /leash-start-work. Refuses on a
dirty worktree or an unmerged branch unless --keep-branch. Deletion uses
`git branch -D` ONLY after an explicit `git merge-base --is-ancestor`
proof against the configured merge target (local or remote-tracking) —
never `-d`'s HEAD-relative heuristic, and never without proof. Every
deletion is audited to .harness/finish_audit.log; work is never silently
discarded.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import subprocess
import sys
from pathlib import Path

from scripts.harness.branches import (
    BranchConfigError,
    load_branch_config,
    prove_merged,
)


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


def _audit_delete(repo_root: Path, *, branch: str, sha: str, proven: str) -> None:
    log = repo_root / ".harness" / "finish_audit.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.UTC).isoformat()
    with log.open("a", encoding="utf-8") as f:
        f.write(f"{ts}\tDELETE\tbranch={branch}\tsha={sha}\tproven={proven}\n")


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
