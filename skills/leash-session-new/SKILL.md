---
name: leash-session-new
description: Use to escape a session-leash block. Creates a sibling git worktree for this Claude Code session and flips its lockfile to in-worktree so write tools unblock. Invoke as your next action when SessionStart said this session is concurrent.
---

# leash-session-new

## When to use

The `SessionStart` hook reported `SESSION LEASH: concurrent Claude Code
session detected`, and `PreToolUse` is now denying `Edit`, `Write`, and
`MultiEdit`. You MUST invoke this skill before any other tool call.

Do NOT use this when only one Claude Code session is open in this repo —
it will refuse with a clear message.

## How

1. Run the backing script:

   ```bash
   python -m scripts.harness.session_new
   ```

2. The script:
   - reads this session's lockfile at `.harness/sessions/<pid>.json`
   - creates a sibling worktree `../<repo>--session-<id>/` on a new
     `session/<id>` branch from `HEAD`
   - flips the lockfile state to `in-worktree`
3. The script prints the worktree path. From that point on, **use
   absolute paths under that directory** for every `Edit`, `Write`,
   `MultiEdit`, and file `Read`. Your session cwd has not moved; this
   is intentional.
4. The skill is idempotent. Running it twice returns the same worktree.

## Constraints

- The skill does NOT copy uncommitted WIP from the primary checkout.
  The second session starts from `HEAD` and proceeds from there.
- Do not edit the lockfile JSON by hand to "skip" this step. The
  `PreToolUse` gate will keep denying writes.
- When you finish, invoke `/leash-session-end` to remove the worktree
  and clean up.
