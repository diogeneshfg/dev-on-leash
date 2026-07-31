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
