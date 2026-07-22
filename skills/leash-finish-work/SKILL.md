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
   that its branch is merged into the project's `merge_target`
   (`.harness/branches.yaml`; default `main`/`master`). The script proves
   merged-ness itself with `git merge-base --is-ancestor` against the local
   target **or** its remote-tracking ref, so a stale local target does not
   block cleanup.

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
   - refuses if the branch is not proven merged into the merge target
     (merge it, or pass `--keep-branch`)
   - proves ancestry **before** removing anything, then runs
     `git worktree remove` and `git branch -D` — `-D` is sanctioned only by
     the explicit proof, and every deletion is audited to
     `.harness/finish_audit.log`

## Flags

- `--keep-branch` — remove the worktree directory but keep the branch
  (useful when a PR is still open).

## Constraints

- Never delete without proof. `git branch -D` runs only after the script's
  own `merge-base --is-ancestor` proof; `git worktree remove --force` is out
  of scope. If the script refuses, fix the underlying issue.
- Squash- and rebase-merges produce new SHAs and are not provable — use
  `--keep-branch` and delete the branch manually once you are sure.
