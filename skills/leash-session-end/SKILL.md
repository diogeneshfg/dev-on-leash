---
name: leash-session-end
description: Use to cleanly close a session-leash worktree. Refuses on dirty index or unmerged branch unless --keep-branch is passed. Removes the worktree, deletes the session branch (unless kept), and clears the lockfile.
---

# leash-session-end

## When to use

You finished the work that prompted `/leash-session-new` and you want
the temporary worktree gone. Run this skill before closing the Claude
Code session.

## How

1. If your session branch's work belongs on a long-lived branch, commit
   and merge it first (the skill refuses to delete unmerged branches by
   default).

2. Run:

   ```bash
   python -m scripts.harness.session_end
   ```

3. The script:
   - reads this session's lockfile
   - refuses if the worktree has uncommitted changes (commit or stash first)
   - refuses if the session branch is unmerged (merge it, or pass
     `--keep-branch`)
   - runs `git worktree remove`, deletes the session branch (when not
     kept), and removes the lockfile

## Flags

- `--keep-branch` — keep the session branch around (useful if you want
  to PR it later). The worktree directory is still removed.

## Constraints

- Never `--force` removal. If the script refuses, fix the underlying
  issue. `git worktree remove --force` would silently discard
  uncommitted work — out of scope.
