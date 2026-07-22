---
name: leash-start-work
description: Use to start a new change in its own git worktree — "start a feature", "work on X in parallel", "new branch+worktree". Picks a <type>/<slug> branch off main, creates .worktrees/<slug> while the session stays rooted in the main checkout, and keeps you on the disciplined path without the stash-dance.
---

# leash-start-work

## When to use

You want to begin a new change — a feature, fix, refactor — and keep it
isolated in its own working directory so you can run several branches in
parallel without the stash-dance (dirty tree blocking `git checkout`, IDE
reindexing, debugger resets). This is the *proactive* worktree path: the
physical version of the mandatory "branch first, edit after" rule.

This skill is the **single, mandatory** path to begin a change. The worktree
leash makes the main worktree read-only to write tools, so you cannot edit
in the main checkout — start here, then edit inside `.worktrees/<slug>`.

**The session stays home.** The Claude Code session remains rooted in the
main checkout; only the *files being edited* live under `.worktrees/<slug>`.
Session history is keyed to the session's root directory — a session rooted
inside the worktree loses its history when `/leash-finish-work` removes it.
The write gate resolves targets absolutely, so edits into any linked
worktree are allowed from the main checkout; there is never a reason to
move the session.

## How

1. **Pick the branch name.** Choose `type` ∈ `feat | fix | refactor | docs |
   chore` and a short kebab-case `slug`. The branch is `<type>/<slug>`; the
   worktree directory is `.worktrees/<slug>` (no type prefix on the dir).
   Validate the slug; **refuse** anything that would land on `main`/`master` —
   branch discipline is mandatory and never overridden here.

2. **Branch from `main`.** The new branch starts from `main`/`master` (not the
   current `HEAD`), honoring the branch-discipline section of `AGENTS.md`.

3. **Create the worktree without moving the session.** Run, from the main
   checkout:

   ```
   git worktree add .worktrees/<slug> -b <type>/<slug> main
   ```

   (`type ∈ feat|fix|refactor|docs|chore`)

   Do **not** use session-relocating mechanisms (`EnterWorktree`, opening
   the worktree folder as a new workspace, launching a new session inside
   `.worktrees/<slug>`): they re-root the session in the worktree, and its
   history is lost when the worktree is removed. The
   `session_root_guard` SessionStart hook warns if a session is ever
   rooted there.

4. **Warn if not ignored.** If `.worktrees/` is not in the project `.gitignore`
   (bootstrap was declined or never run), warn that the worktree directory is
   not ignored before proceeding, and point at `bootstrap-dev-leash` /
   adding `.worktrees/` under the `# dev-on-leash` heading.

5. **Report.** Print the worktree path and remind that every `Edit`, `Write`,
   and file `Read` for this change targets paths under `.worktrees/<slug>`,
   while the session itself stays rooted in the main checkout.

## Cleanup

When the branch is merged, run `/leash-finish-work <slug>` (refuses on
dirty/unmerged work).

`cycle_done.py` prints an advisory reminder for merged `<type>/<slug>`
worktrees, but never removes them for you — feature branches may have an open
PR, so the human decides.

## Constraints

- This skill owns the **convention + guardrails**, not a worktree engine. It
  never reimplements `git worktree`.
- It does NOT copy uncommitted WIP into the new worktree (start from `main`,
  never copy WIP).
- It never weakens branch discipline; it makes the disciplined path comfortable
  when several changes are in flight.
