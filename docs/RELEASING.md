# Releasing dev-on-leash

The repeatable steps to close out a feature and cut a release. Run them from
the **primary checkout** on `main` unless a step says otherwise. Branch
discipline still applies: do the version bump on a `chore/release-<version>`
branch (in its own worktree), never directly on `main`.

## Versioning

[Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

- **MINOR** — a new user-facing feature or skill (e.g. `0.3.0 → 0.4.0`).
- **PATCH** — a bug fix or docs-only change with no new surface.
- **MAJOR** — a breaking change to the harness contract.

The version lives in **two files that must move in lockstep**:

- `pyproject.toml` → `version = "X.Y.Z"`
- `.claude-plugin/plugin.json` → `"version": "X.Y.Z"`

A release where these disagree is a bug.

## The CHANGELOG

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/), with
one local convention: entries are **not** cut into versioned headings. They
accumulate under `## [Unreleased]` as dated, named subsections:

```
## [Unreleased]
### 2026-06-17 — session-new-base-main
- <what changed and why> …
```

`scripts/harness/cycle_done.py` appends a stub when a cycle closes green; you
edit it by hand to add detail. By the time you cut a release the entry is
usually already there from the feature work — confirm it reads well rather
than writing it from scratch.

## Steps

1. **Land the feature first.** The feature branch is already merged to `main`
   and pushed, its tests green, its CHANGELOG entry under `[Unreleased]`. (See
   "Finishing a feature branch" below for that flow.)

2. **Branch for the release.** From the primary checkout on `main`:

   ```
   git worktree add .worktrees/release-<version> -b chore/release-<version> main
   ```

3. **Bump the version in lockstep** (in the worktree):
   - `pyproject.toml` → `version = "<version>"`
   - `.claude-plugin/plugin.json` → `"version": "<version>"`

4. **Confirm the CHANGELOG** `[Unreleased]` section names the feature(s) in
   this release and reads clearly.

5. **Verify green** in the worktree before merging:

   ```
   python -m pytest -q
   ```

6. **Commit** on the release branch:

   ```
   chore(release): <version> — <feature summary>
   ```

7. **Merge, push, clean up** — the same finish flow as a feature (below).

## Finishing a feature branch (merge + cleanup)

The flow used for every branch, feature or release:

1. **Commit** on the `<type>/<slug>` (or `chore/release-<version>`) branch,
   inside its worktree, with a `Co-Authored-By` trailer.

2. **Merge into `main`** from the primary checkout, preserving the merge
   commit so history shows the branch:

   ```
   git merge --no-ff <branch> -m "Merge <branch>: <summary>"
   ```

3. **Push:**

   ```
   git push origin main
   ```

4. **Remove the worktree:**

   ```
   git worktree remove .worktrees/<slug>
   ```

5. **Delete the merged branch** (and any other inactive merged branches):

   ```
   git branch --merged main | grep -v -E '^\*? *main$'   # review first
   git branch -d <branch>
   git worktree prune
   ```

   `git branch -d` (lowercase) refuses to delete an unmerged branch — that
   safety is intentional; never force with `-D` unless you mean to discard
   unmerged work.

6. **Verify on `main`** after the merge:

   ```
   python -m pytest -q
   git status -sb        # clean, in sync with origin/main
   ```
