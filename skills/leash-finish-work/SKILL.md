---
name: leash-finish-work
description: Use to clean up a .worktrees/<slug> worktree created by /leash-start-work. Refuses on a dirty worktree or an unmerged branch unless --keep-branch. Removes the worktree and deletes the branch (unless kept).
---

# leash-finish-work

## When to use

You finished a change started with `/leash-start-work` and the branch is
merged (or has an open PR you want to keep). This removes the worktree
directory and, by default, the merged branch. Counterpart to
`/leash-start-work`.

## How

1. Make sure the worktree is committed and, unless you pass `--keep-branch`,
   that its branch is merged into `main`/`master`.

2. Run (from the main checkout), naming the slug:

   ```bash
   python -m scripts.harness.finish_work <slug>
   ```

   or point at an explicit path:

   ```bash
   python -m scripts.harness.finish_work --path .worktrees/<slug>
   ```

3. The script:
   - refuses to touch the main worktree
   - refuses if the worktree has uncommitted changes (commit or stash first)
   - refuses if the branch is unmerged (merge it, or pass `--keep-branch`)
   - runs `git worktree remove`, then `git branch -d <type>/<slug>` (only
     `-d`, never `-D`) unless `--keep-branch`

## Flags

- `--keep-branch` — remove the worktree directory but keep the branch
  (useful when a PR is still open).

## Constraints

- Never `--force`. If the script refuses, fix the underlying issue;
  `git worktree remove --force` / `git branch -D` would silently discard
  work and are out of scope.
