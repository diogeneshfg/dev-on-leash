---
name: leash-start-work
description: Use to start a new change in its own git worktree — "start a feature", "work on X in parallel", "new branch+worktree". Picks a <type>/<slug> branch off main, delegates the worktree creation to native/superpowers tooling, and keeps you on the disciplined path without the stash-dance.
---

# leash-start-work

## When to use

You want to begin a new change — a feature, fix, refactor — and keep it
isolated in its own working directory so you can run several branches in
parallel without the stash-dance (dirty tree blocking `git checkout`, IDE
reindexing, debugger resets). This is the *proactive* worktree path: the
physical version of the mandatory "branch first, edit after" rule.

This skill is **voluntary**. Nothing forces it (unlike `/leash-session-new`,
which the session-leash hook forces when two sessions collide). A developer
who does not need parallelism can still just `git checkout -b <type>/<name>`.

Do NOT use this to escape a session-leash block — that is `/leash-session-new`.

## How

1. **Pick the branch name.** Choose `type` ∈ `feat | fix | refactor | docs |
   chore` and a short kebab-case `slug`. The branch is `<type>/<slug>`; the
   worktree directory is `.worktrees/<slug>` (no type prefix on the dir).
   Validate the slug; **refuse** anything that would land on `main`/`master` —
   branch discipline is mandatory and never overridden here.

2. **Branch from `main`.** The new branch starts from `main`/`master` (not the
   current `HEAD`), honoring the branch-discipline section of `AGENTS.md`.

3. **Delegate the mechanism — do not reimplement `git worktree`.** In order:
   - If the native `EnterWorktree` tool is available, use it.
   - Else if the `superpowers:using-git-worktrees` skill is installed, use it.
   - Else fall back to the documented command:

     ```
     git worktree add .worktrees/<slug> -b <type>/<slug> main
     ```

     (`type ∈ feat|fix|refactor|docs|chore`)

4. **Warn if not ignored.** If `.worktrees/` is not in the project `.gitignore`
   (bootstrap was declined or never run), warn that the worktree directory is
   not ignored before proceeding, and point at `bootstrap-dev-leash` /
   adding `.worktrees/` under the `# dev-on-leash` heading.

5. **Report.** Print the worktree path and remind that every `Edit`, `Write`,
   and file `Read` for this change now happens under `.worktrees/<slug>`.

## Cleanup

When the branch is merged, remove the worktree:

```
git worktree remove .worktrees/<slug>
```

`cycle_done.py` prints an advisory reminder for merged `<type>/<slug>`
worktrees, but never removes them for you — feature branches may have an open
PR, so the human decides.

## Constraints

- This skill owns the **convention + guardrails**, not a worktree engine. It
  never reimplements `git worktree`.
- It does NOT copy uncommitted WIP into the new worktree (same stance as
  `/leash-session-new` — start from `main`).
- It never weakens branch discipline; it makes the disciplined path comfortable
  when several changes are in flight.
