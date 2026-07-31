---
name: leash-start-work
description: Use to start a new change in its own git worktree — "start a feature", "work on X in parallel", "new branch+worktree". Picks a <type>/<slug> branch off the configured base branch (.harness/branches.yaml, default main), creates .worktrees/<slug> via scripts.harness.start_work while the session stays rooted in the main checkout, and keeps you on the disciplined path without the stash-dance.
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
   Never target `main`/`master` or any branch declared `long_lived` in
   `.harness/branches.yaml` — branch discipline is mandatory and never
   overridden here (the backend refuses these mechanically).

2. **Run the mechanical backend** from the main checkout:

   ```
   python -m scripts.harness.start_work <type>/<slug> [--base <branch>] [--repo-root <path>]
   ```

   Base resolution precedence: `--base` argument → `base:` in
   `.harness/branches.yaml` → detected `main`/`master`. A `--base` must be
   `main`/`master` or declared in the config's `long_lived` list. The
   script fetches the base's remote when one exists and, if the local base
   is behind, warns and branches from the remote-tracking ref with
   `--no-track` (the feature branch gets no upstream). It refuses a
   diverged base, a protected slug, and a missing base ref. Offline work
   never blocks — fetch failures warn and fall back to local refs. Do not
   hand-roll `git worktree add`; the script is the guardrail.

3. **Stay home.** Do **not** use session-relocating mechanisms (`EnterWorktree`,
   opening the worktree folder as a new workspace, launching a new session
   inside `.worktrees/<slug>`): they re-root the session in the worktree, and
   its history is lost when the worktree is removed. The
   `session_root_guard` SessionStart hook warns if a session is ever
   rooted there.

4. **Heed the warnings.** The script warns when `.worktrees/` is not in the
   project `.gitignore` (bootstrap declined or never run) — point at
   `bootstrap-dev-leash` / adding `.worktrees/` under the `# dev-on-leash`
   heading.

5. **Report.** Relay the script's output — worktree path and the base it
   actually started from — and remind that every `Edit`, `Write`, and file
   `Read` for this change targets paths under `.worktrees/<slug>`, while the
   session itself stays rooted in the main checkout.

## Multi-root workspaces

When the VS Code workspace holds several repos, ALWAYS pass
`--repo-root <target repo>` — determine the demand's target repo FIRST
and never trust the session cwd. The backend mechanically refuses to
run without it when it can detect the layout (sibling leash-managed
repos, or a workspace folder with child repos) and lists the
candidates; layouts it cannot detect (folders from unrelated parents)
are exactly why the explicit flag is mandatory practice. The script
echoes `repo: … | config: … | base: … | mode: …` — read it back and
confirm it matches the demand before editing anything.

Deployment note: the write-gate hook runs from the session-root
project's settings, so the session must be rooted in a leash-
**bootstrapped** repo for the gate to protect the workspace's sibling
repos; keep harness versions aligned with `/leash-update`.

## `workflow: branch` mode

A repo whose `.harness/branches.yaml` declares `workflow: branch` gets a
disciplined checkout instead of a worktree: same base resolution and
refusals, then `git checkout -b <type>/<slug>` in place. One demand at a
time per repo (the backend refuses a second). Edits happen in the normal
project paths; the write gate allows them only while HEAD is on the work
branch. Use worktree mode when a repo needs several parallel demands.
Branch mode assumes ONE session per repo — concurrent sessions on the
same branch-mode repo are not protected against each other.

## Cleanup

When the branch is merged, run `/leash-finish-work <slug>` (refuses on
dirty/unmerged work).

`cycle_done.py` prints an advisory reminder for merged `<type>/<slug>`
worktrees, but never removes them for you — feature branches may have an open
PR, so the human decides.

## Constraints

- This skill owns the **convention + guardrails**, not a worktree engine. It
  never reimplements `git worktree`.
- It does NOT copy uncommitted WIP into the new worktree (start from the
  resolved base branch, never copy WIP).
- It never weakens branch discipline; it makes the disciplined path comfortable
  when several changes are in flight.
