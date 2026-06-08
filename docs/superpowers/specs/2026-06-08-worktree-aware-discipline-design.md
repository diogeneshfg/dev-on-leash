# Worktree-Aware Branch Discipline — Design

**Status:** approved (brainstorm complete), pending implementation plan
**Date:** 2026-06-08
**Project:** dev-on-leash

## Problem

dev-on-leash enforces "every change on a new branch from `main`, never commit
to `main` directly" (`AGENTS.md` → "Branch discipline (mandatory)"). The
discipline is sound, but in a single working directory it pushes the developer
into the stash-dance whenever they want to touch a second feature: a dirty tree
blocks `git checkout`, the IDE reindexes, terminals and the debugger reset. So
the discipline (one branch per change) and the ergonomics of N changes in
flight are in tension.

Today the two halves live in different plugins:

- **dev-on-leash** owns the *rules* — branch naming, never-`main`, TDD, the harness.
- **`superpowers:using-git-worktrees`** owns the *mechanism* — `git worktree add`, one folder per branch.

A team that adopts dev-on-leash for the governance does not get the parallel-WIP
workflow unless they separately know about, and reach for, the worktree skill.

dev-on-leash is *already* worktree-aware: the session-leash `SessionStart` hook
records live PIDs and worktree paths in `.harness/sessions/<pid>.json`, and
`cycle_done.py` already sweeps `session/*` worktrees. But it only ever creates
worktrees **reactively**, to keep two colliding Claude sessions apart. It never
offers a worktree for the ordinary "I want to start a second feature" case.

We want to make worktrees a first-class, **opt-in** part of the branch-discipline
workflow — the discipline shipping *ready* for parallel work, not just aware of it.

## Decisions locked during brainstorm

1. **Two distinct worktree mechanisms, not one.** The existing session-leash
   worktrees stay exactly as they are: reactive, sibling dirs
   (`../<repo>--session-<id>/`), `session/<id>` branches, created mid-session by
   `/leash-session-new`. We add a *separate* proactive path. They are not
   unified.

   *Why:* session-leash is a reactive safety net that fires when a collision is
   already underway. It cannot assume `bootstrap` ever ran, so it deliberately
   uses sibling dirs that live **outside** the repo and are safe-by-construction
   — they can never be accidentally committed even with no `.gitignore` entry.
   That is precisely why session-leash never needed the gitignore patch. The
   proactive path is opt-in and bootstrap-time, so nested `.worktrees/<slug>`
   is fine *because* bootstrap can guarantee the gitignore entry first. Forcing
   session-leash into nested `.worktrees/` would couple the reactive safety net
   to a setup step that may not have run. Unify later only if real use shows the
   two conventions confuse people.

2. **The proactive path delegates the mechanism; it does not reimplement it.**
   dev-on-leash contributes the *convention* (`<type>/<slug>` naming),
   `.gitignore` ownership, and the never-`main` guardrail. The actual
   `git worktree add` is delegated to `EnterWorktree` (native tool) or
   `superpowers:using-git-worktrees` when present, with a documented
   `git worktree add` fallback when neither is available. No second worktree
   engine is built.

3. **`leash-start-work` is voluntary and intent-triggered — not enforced.**
   Unlike `/leash-session-new` (which the `SessionStart` hook *forces*), nothing
   blocks a developer into the proactive path. It is discovered through its skill
   `description` (Claude reaches for it when the user expresses "start new work /
   work on another thing in parallel") and through the docs. No PreToolUse nudge.

   *Why no nudge:* a "you're on `main`" nudge would introduce branch-discipline
   enforcement at the hook layer that does not exist today — branch discipline is
   enforced via docs, `tdd-evidence-checker`, `recheck_plan`, and CI, not a live
   gate. It would also fire false positives on the explicitly-allowed
   doc-edit-on-`main` exception. A nudge can come later as its own focused change
   if the path proves popular but forgotten.

4. **Branch from `main`, not `HEAD`.** `leash-start-work` creates the worktree
   branch from `main`/`master` to honor the mandatory branch-discipline section,
   not from the current `HEAD`.

5. **Worktrees are opt-in at bootstrap.** The `.worktrees/` layout is offered as
   one more opt-in interview item, in the same style as the existing Domain-rules
   and UI-rules concerns. If declined, no `.gitignore` change is made.

6. **Cleanup for proactive worktrees is advisory-only.** `cycle_done.py` already
   *auto-removes* `session/*` worktrees (conservative: merged + clean + dead PID).
   Proactive `<type>/<slug>` worktrees are developer-owned feature branches that
   may have an open PR, so `cycle_done` only **prints a reminder** to
   `git worktree remove` for them. It never auto-removes them and never blocks
   the cycle — consistent with `/leash-session-end`'s "never `--force`" stance.

## Non-goals (v1)

- Unifying session-leash and proactive worktrees onto one layout.
- A PreToolUse nudge toward `leash-start-work`.
- Auto-removing proactive `<type>/<slug>` worktrees.
- Copying uncommitted WIP into the new worktree (same stance as
  `/leash-session-new` — start from `main`).
- A `leash-start-work`-specific "finish" skill. Cleanup is the advisory
  `cycle_done` reminder plus the human running `git worktree remove`.

## Design

### Piece A — Bootstrap (`bootstrap-dev-leash`)

**Interview (Step 2).** Add one opt-in item following the existing
yes/no-concern pattern:

> *"Standardize a `.worktrees/` layout so you can run several branches in
> parallel without the stash-dance?"* (`AskUserQuestion`, yes/no)

**Gitignore patch (Step 3c).** If the user answered **yes**, ensure
`.worktrees/` is present in the target `.gitignore`, added under the *same*
`# dev-on-leash` heading already used for `.harness/exceptions.log` and
`.harness/sessions/`. Idempotent — an exact match anywhere in the file counts
as present; never duplicate. If **no**, make no gitignore change.

**Report (Step 5).** State whether the `.worktrees/` layout was standardized.

### Piece B — New skill: `leash-start-work`

A new skill in the `leash-*` family (`skills/leash-start-work/SKILL.md`).
Voluntary; invoked when the developer wants to begin a change in its own
worktree. Flow:

1. **Collect & validate.** Ask for `type` (`feat | fix | refactor | docs |
   chore`) and a short `slug`. Validate the resulting `<type>/<slug>` against the
   convention. Refuse anything that would land on `main`/`master`.
2. **Branch from `main`.** The target is worktree dir `.worktrees/<slug>` on
   branch `<type>/<slug>`, branched from `main`/`master`.
3. **Delegate the mechanism.** Prefer the `EnterWorktree` tool if available;
   else `superpowers:using-git-worktrees` if installed; else fall back to the
   documented command:

   ```
   git worktree add .worktrees/<slug> -b <type>/<slug> main
   ```

   (`type ∈ feat|fix|refactor|docs|chore`)
4. **Warn if not ignored.** If `.worktrees/` is not in `.gitignore` (bootstrap
   was declined or not run), warn that the worktree dir is not ignored before
   proceeding.
5. **Report.** Print the worktree path and remind that edits now happen under it.

The skill owns convention + guardrails only; it never reimplements `git
worktree`.

### Piece C — `cycle_done.py` advisory cleanup reminder

`cycle_done.py` already has `sweep_session_worktrees` (auto-removes `session/*`
worktrees) and helpers `_worktree_branches` (currently filtered to `session/`),
`_git_out`, and `git branch --merged` parsing. Add a sibling, advisory-only
step that runs after gates pass and after the existing session sweep:

- Enumerate worktrees whose branch does **not** start with `session/` (i.e. the
  proactive `<type>/<slug>` worktrees) and whose branch **is merged** into the
  current branch.
- For each, **print** a reminder to stderr, e.g.
  `reminder: branch <type>/<slug> is merged — run \`git worktree remove
  .worktrees/<slug>\` to clean up`.
- Never remove, never change the exit code. Wrapped in the same defensive
  `try/except` as the existing sweep so a git hiccup cannot fail the cycle.

Implementation note: generalize `_worktree_branches` (or add a sibling) so the
`session/` filter is a parameter rather than hardcoded, keeping the existing
sweep behavior byte-for-byte unchanged.

### Piece D — Templates & docs

- **`AGENTS.md.tmpl` / `CLAUDE.md.tmpl`.** Document the branch+worktree start
  path using the `<type>/<slug>` convention, placed near the existing
  "Concurrent sessions" note so the *proactive* (parallel WIP) and *reactive*
  (concurrency safety) worktree stories are both present and clearly
  distinguished. Keep the fixed branch-discipline prose intact — this *adds* the
  physical-worktree option to "branch first, edit after"; it does not weaken the
  rule.
- **`README.md`.** Add the worktree-aware workflow to the repo's own README
  before merge (per the project convention that user-facing features get a
  README touch in the same change, not as a follow-up).

## Testing & dogfood

- **Bootstrap:** test that the `.gitignore` patch adds `.worktrees/` under the
  `# dev-on-leash` heading when opted in, is idempotent, and makes no change
  when declined.
- **`leash-start-work`:** a skill presence/shape test (mirrors existing
  `tests/test_skill_*`), asserting the `<type>/<slug>` convention, the
  delegation order, the branch-from-`main` rule, and the not-ignored warning are
  all documented.
- **`cycle_done`:** test that a merged non-`session/` worktree produces an
  advisory reminder, is **not** removed, and the exit code is unchanged; and that
  `session/*` auto-sweep behavior is untouched.
- **Dogfood (load-bearing, per the `feedback-dogfood` memory):** exercise the
  proactive path on this repo itself — create a `.worktrees/<slug>` via the
  documented fallback command, confirm `.worktrees/` is gitignored here, and
  confirm `cycle_done` prints the advisory reminder once the branch is merged.
  The plan does not close without this passing.

## Open implementation details (resolve in plan)

- Exact detection of `EnterWorktree` / `superpowers:using-git-worktrees`
  availability from within a skill (tool-presence vs skill-presence check), and
  the precise prose for the fallback path.
- Whether the advisory reminder dedupes against worktrees the session sweep
  already removed in the same run (it should only consider non-`session/`
  branches, so overlap is none — but confirm during implementation).
