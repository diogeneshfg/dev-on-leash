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

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/). During
development, entries accumulate under `## [Unreleased]` as dated, named
subsections:

```
## [Unreleased]
### 2026-06-17 — session-new-base-main
- <what changed and why> …
```

`scripts/harness/cycle_done.py` appends a stub when a cycle closes green; you
edit it by hand to add detail. By the time you cut a release the entry is
usually already there from the feature work — confirm it reads well rather
than writing it from scratch.

**At release time, cut the heading.** Rename `## [Unreleased]` to the version
being shipped and open a fresh empty `[Unreleased]` above it:

```
## [Unreleased]

## [X.Y.Z] — <release-date>
### 2026-06-17 — session-new-base-main
- …
```

This keeps `[Unreleased]` honest — it only ever holds work that has not
shipped — and lets the CHANGELOG answer "what shipped in version X?" without
reaching for `git log`. The dated `### <slug>` subsections are preserved as-is
under the version heading.

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

4. **Cut the CHANGELOG heading.** Confirm `[Unreleased]` names the feature(s)
   in this release and reads clearly, then rename `## [Unreleased]` to
   `## [<version>] — <release-date>` and add a fresh empty `## [Unreleased]`
   above it.

5. **Verify green** in the worktree before merging:

   ```
   python -m pytest -q
   ```

6. **Commit** on the release branch:

   ```
   chore(release): <version> — <feature summary>
   ```

7. **Merge, push, clean up** — the same finish flow as a feature (below).

8. **Tag and publish the release.** The version bump in the files is *not*
   what GitHub's Releases/Tags view reads — that is driven by git tags. After
   the release merge lands on `main`, create an annotated tag on the **release
   merge commit** and push it, then cut the GitHub Release:

   ```
   git tag -a v<version> <release-merge-sha> \
     -m "dev-on-leash v<version> — <feature summary>"
   git push origin v<version>
   gh release create v<version> \
     --title "v<version> — <feature summary>" \
     --notes "<the [<version>] CHANGELOG section>"
   ```

   Tag the **release merge commit**, not whatever `HEAD` happens to be — later
   `[Unreleased]` work must not be folded into the tag. Confirm with
   `gh release list` that the new version shows as `Latest`. Skipping this step
   is why a version can look "shipped" in `pyproject.toml` yet still show the
   previous release as latest on GitHub.

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

   **On Windows** this can fail with `Permission denied` when something still
   holds a handle inside the worktree (a `.pytest_cache`, an editor, an
   indexer). Git often still de-registers the worktree but leaves the physical
   directory behind. If so, finish the cleanup by hand:

   ```
   git worktree prune                      # drop the stale registration
   rm -rf .worktrees/<slug>                # remove the leftover directory
   ```

   `.worktrees/` is gitignored, so a leftover directory is harmless — but
   prune + remove keeps the tree tidy.

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
