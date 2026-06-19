# Worktree-Mandatory Leash — Design

**Status:** approved (brainstorm complete), pending implementation plan
**Date:** 2026-06-19
**Project:** dev-on-leash
**Supersedes:** [`2026-05-28-session-leash-design.md`](2026-05-28-session-leash-design.md)

## Problem

The session-leash (the 2026-05-28 design) prevents two Claude Code sessions
from clobbering each other's WIP by *detecting* concurrency at `SessionStart`
and pushing the second session into its own worktree. Detection relies on a
per-session lockfile, a PID-based election (lowest live PID wins `primary`),
and a string comparison of `primary_cwd`.

That detection is fragile, especially on Windows:

- **PID election is not order-safe.** `resolve_state` elects `primary` by
  *lowest PID*, assuming PIDs increase with start time. Windows PIDs are not
  monotonic — a session started *later* can receive a *lower* PID. The
  earlier session already resolved to `primary` and never downgrades, so the
  later low-PID session also claims `primary`. Result: **two primaries, both
  writing the same tree.**
- **`primary_cwd` is compared as an exact string.** Windows paths are
  case-insensitive on disk but compared case-sensitively here; `C:\…` vs
  `c:\…` makes two sessions invisible to each other → each elects itself
  `primary` alone.
- **The hook can fail open silently.** If `python -m
  scripts.harness.session_gate` errors in a target project (interpreter not
  on PATH, package layout differs), `PreToolUse` lets the write through.

Observed in the field: a second session was **not** isolated and both wrote
the primary checkout — exactly the failure the feature exists to prevent.

The root cause is the *category* of mechanism: detecting concurrency and
isolating only sometimes. This design removes the need to detect concurrency
at all.

## The pivot

**The main worktree is read-only to write tools. All work happens in a
linked worktree.**

Concurrency stops being *detected* and becomes *impossible by construction*:

- No two sessions share a working tree, because none of them may write the
  main tree.
- Each session works on its own branch in its own worktree; git itself
  refuses to check out one branch in two worktrees.

Mental model: **each session is a developer; the group of sessions is a team
on the same repo; the main tree mirrors the remote.** Nobody edits the
mirror — everyone branches.

## Decisions locked during brainstorm

1. **Always worktree, never detect.** The whole lockfile / election /
   SessionStart-detection machinery is deleted. The gate is stateless and
   git-based.
2. **Hard-block the main tree, with a one-shot audited escape.** The gate
   denies every write whose target resolves into the main worktree. A
   single-use marker authorizes exactly one write to the main tree and is
   consumed on use, logged to `.harness/exceptions.log`.
3. **One creation skill.** `leash-start-work` becomes the single, now
   effectively mandatory, path to begin any change. `leash-session-new` is
   deleted.
4. **Symmetric cleanup skill.** `leash-session-end` is renamed
   `leash-finish-work`, adapted to the `.worktrees/<slug>` + `<type>/<slug>`
   convention, keeping its dirty/unmerged refusal discipline.
5. **`main` mirrors the remote — by convention, not automation.** Because
   the gate forbids editing the main tree, it never drifts via direct
   writes. Keeping it synced with the remote (`git fetch`/`pull`, merging
   branches in) is the developer's normal git flow, documented in
   README/CLAUDE.md. No new sync automation (YAGNI).
6. **Fail-open on uncertainty.** If the gate cannot determine the worktree
   set (git errors, or the directory is not a repo), it allows the write and
   logs a warning — consistent with the prior posture ("don't break
   workflows that don't opt in").
7. **Dogfood stays load-bearing.** A rewritten dogfood script exercises the
   gate on this repo and must pass before the plan closes (per the
   `feedback-dogfood` memory).

## Non-goals (v1)

- Automating `main`'s synchronization with the remote (decision 5).
- Cross-machine coordination (unchanged from the prior design).
- Auto-merging worktree branches back into `main`.
- Policing `Bash` writes. `Bash` is intentionally not gated — `leash-start-work`
  needs `git worktree add` via Bash, and gating it would deadlock the very
  command that escapes the block. A determined session could `> file` into
  the main tree; this stays in the "by convention" tier of the trust model.
- Retroactively isolating a session that disabled the hook.

---

## Section 1 — The write-tool gate (PreToolUse)

A `PreToolUse` hook on `Edit|Write|MultiEdit|NotebookEdit` runs
`python -m scripts.harness.session_gate` (rewritten; the module name is kept
to avoid touching the hook wiring more than necessary — see Open questions
for an optional rename). The decision is **stateless** — no lockfile, no PID,
no `primary_cwd`. It depends only on the write target and `git worktree list`.

Decision logic:

1. **Tool not in the gated set** → allow.
2. **Resolve the target path.** Read `tool_input.file_path` or
   `tool_input.notebook_path`, resolve to an absolute path. If absent or not
   a string → allow (cannot reason about it).
3. **List worktrees.** Run `git -C <dir> worktree list --porcelain` where
   `<dir>` is the target's parent (falling back to `CLAUDE_PROJECT_DIR`).
   Parse the `worktree <path>` lines.
   - If git fails or the path is not in a repo → **allow + log a warning**
     (fail-open, decision 6).
4. **Match the target to the longest worktree-path prefix.**
   - Target under no worktree (outside the repo) → allow.
   - The matched worktree is the **main worktree** (the first `worktree`
     entry in the porcelain output; equivalently the one whose `.git` is a
     directory, not a gitdir pointer):
     - **One-shot escape marker present** (`.harness/allow-main-write`) →
       allow, **delete the marker**, append an audit line to
       `.harness/exceptions.log`.
     - else → **deny** with:
       ```
       SESSION LEASH: the main worktree is read-only. Start your change in a
       worktree with /leash-start-work, then write there. To make a one-off
       write to the main tree, run:
         python -m scripts.harness.allow_main_write "<reason>"
       and retry — it authorizes exactly one main-tree write and is logged.
       ```
   - The matched worktree is a **linked worktree** → allow.

**Why longest-prefix matching is required.** `leash-start-work` places
worktrees at `.worktrees/<slug>` *inside* the repo. A target like
`<repo>/.worktrees/foo/x.py` is under both `<repo>` (main) and
`<repo>/.worktrees/foo` (linked). The longest matching prefix is the linked
worktree → allow. A target like `<repo>/README.md` matches only `<repo>` →
deny. This works identically for sibling worktrees outside the repo.

`Bash`, `Read`, `Grep`, `Glob` are not gated.

---

## Section 2 — One-shot escape (`allow_main_write.py`)

`scripts/harness/allow_main_write.py` (new). Invoked via Bash (not gated)
when the user wants a trivial direct edit to the main tree.

1. Writes `.harness/allow-main-write` — a small JSON marker:
   ```json
   { "schema": 1, "reason": "<from argv>", "created_at": "<iso8601>" }
   ```
2. Prints a one-line confirmation: the next single main-tree write is
   authorized and will be logged.

The **gate** (Section 1) is what *consumes* the marker: on the first
main-tree write while the marker exists, it deletes the marker and appends to
`.harness/exceptions.log`:

```
<iso8601>  main-write  pid=<gate ppid>  target=<path>  reason=<reason>
```

One write per authorization. A second main-tree write with no fresh marker is
denied again. A marker created but never used simply lingers until consumed;
it authorizes only the next main-tree write, nothing retroactive.

---

## Section 3 — `leash-start-work` becomes the single path

`leash-start-work` keeps its mechanics unchanged:

- branch `<type>/<slug>` (`type ∈ feat|fix|refactor|docs|chore`) from
  `main`/`master`;
- worktree at `.worktrees/<slug>`;
- delegates worktree creation to `EnterWorktree` →
  `superpowers:using-git-worktrees` → `git worktree add .worktrees/<slug> -b
  <type>/<slug> main`;
- warns if `.worktrees/` is not gitignored;
- never copies uncommitted WIP;
- refuses anything that would land on `main`/`master`.

What changes is the **framing**, not the steps:

- The description and "When to use" drop the "voluntary" language. Writing in
  the main tree is now blocked by the gate, and this skill is *the* way to
  begin any change.
- The cross-reference to `leash-session-new` is removed (that skill is gone);
  the cleanup pointer now names `leash-finish-work`.

---

## Section 4 — `leash-finish-work` (renamed from `leash-session-end`)

Symmetric counterpart to `leash-start-work`, adapted to the
`.worktrees/<slug>` + `<type>/<slug>` convention:

1. Identify the worktree to finish (the current one, or one named by slug).
   Refuse if it is the main worktree.
2. Refuse if the worktree has uncommitted changes
   (`git -C <wt> status --porcelain` non-empty) — tell the user to commit or
   stash. Never silently discard work.
3. Confirm the branch is merged into `main`/`master` **or** `--keep-branch`
   was passed; otherwise refuse.
4. `git worktree remove <path>`. On success, if `--keep-branch` was not
   passed, `git branch -d <type>/<slug>` (only `-d`, never `-D`).
5. Report what was removed.

`cycle_done.py` keeps its advisory (never-removing) reminder for merged
`<type>/<slug>` worktrees.

---

## Section 5 — Deletions and migration

**Deleted from this repo:**

- `scripts/harness/session_lockfile.py`
- `scripts/harness/session_start.py`
- `scripts/harness/list_sessions.py`
- `skills/leash-session-new/`
- `tests/harness/test_session_lockfile.py` and any election/`session_start`
  tests
- `tests/test_session_new.py`

**Rewritten:**

- `scripts/harness/session_gate.py` → the stateless gate of Section 1 (no
  import of `session_lockfile`).

**Renamed:**

- `skills/leash-session-end/` → `skills/leash-finish-work/`.

**Templates:**

- `templates/settings.json.tmpl`: remove the `SessionStart` hook entry; keep
  the `PreToolUse` entry pointing at the rewritten gate. The
  `Bash(python -m scripts.harness.*)` permission already covers
  `allow_main_write`.

**Migration / re-bootstrap.** Existing dev-on-leash projects (including the
one currently mis-isolating sessions) must have their
`.claude/settings.json`:

- **`SessionStart` hook entry removed** (the detector is gone);
- `PreToolUse` gate kept (it now behaves statelessly).

`.harness/sessions/` is no longer used and may be deleted. The implementation
plan specifies whether `bootstrap-dev-leash` gains a `--update-hooks` mode or
folds this into the existing re-run flow.

---

## Section 6 — Trust model placement

README's "Trust model" section, updated:

- **Enforced.** Writes to the main worktree via `Edit|Write|MultiEdit|
  NotebookEdit` are denied by `PreToolUse` unless a one-shot escape marker is
  present. Bypass requires editing/removing the hook line in
  `.claude/settings.json` — a visible audit event.
- **By convention.** Writes via `Bash` (e.g. `> file`, `tee`) into the main
  tree are not parsed, same posture as `touches`. The one-shot escape is
  itself an audited, deliberate convention.
- **Escape hatch.** `allow_main_write.py` authorizes a single main-tree
  write and logs it to `.harness/exceptions.log` (same audit pattern as
  `cycle_done --force`).

The README's "Session leash" subsection is rewritten as "Worktree leash"
with the read-only-main model.

---

## Section 7 — Testing, dogfood, and file inventory

### Unit tests

`tests/harness/test_session_gate.py` (rewritten) — decision matrix:

1. Target in the main worktree, no marker → **deny**.
2. Target in a linked worktree → **allow**.
3. Target under a nested `.worktrees/<slug>` → **allow** (longest-prefix
   match beats the main-tree prefix).
4. Target outside the repo → **allow**.
5. One-shot marker present + main-tree target → **allow**, marker deleted,
   `exceptions.log` appended.
6. Second main-tree write after consumption → **deny**.
7. `git worktree list` fails / not a repo → **allow** + warning logged
   (fail-open).
8. Non-gated tool (`Bash`, `Read`) → **allow**.

### Dogfood (load-bearing)

`scripts/dogfood_worktree_gate.py` (renamed/rewritten from
`dogfood_session.py`), on this repo:

1. Run the gate with an `Edit` payload targeting a file in the main tree →
   assert **deny** and that the message names `/leash-start-work`.
2. Create a throwaway worktree (sibling temp dir or `.worktrees/<temp>`,
   throwaway branch). Run the gate with an `Edit` targeting a file inside it
   → assert **allow**.
3. Create the one-shot marker; run the gate with a main-tree `Edit` → assert
   **allow**, marker gone, `exceptions.log` grew. Run a second main-tree
   `Edit` → assert **deny** again.
4. Tear down: remove the worktree, delete the branch, delete the marker and
   any temp `exceptions.log` lines. Exit 0 only if every step asserted clean.

Wired into `scripts/smoke_e2e.py` (the session-leash step is replaced, not
added alongside). The harness task running this has
`verify: python scripts/dogfood_worktree_gate.py`; the checkbox does not tick
until it passes.

### File inventory

**Plugin (this repo) — new / modified / deleted:**

- `scripts/harness/session_gate.py` — rewritten (stateless gate)
- `scripts/harness/allow_main_write.py` — new (one-shot escape)
- `scripts/harness/session_lockfile.py` — **deleted**
- `scripts/harness/session_start.py` — **deleted**
- `scripts/harness/list_sessions.py` — **deleted**
- `skills/leash-session-new/` — **deleted**
- `skills/leash-session-end/` → `skills/leash-finish-work/` — renamed +
  adapted
- `skills/leash-start-work/SKILL.md` — modified (framing: single mandatory
  path; cleanup pointer → finish-work)
- `templates/settings.json.tmpl` — modified (drop `SessionStart`; keep gate)
- `templates/CLAUDE.md.tmpl` — modified (replace concurrent-sessions mention
  with read-only-main rule)
- `templates/AGENTS.md.tmpl` — modified (same)
- `README.md` — modified ("Worktree leash" subsection + trust-model update;
  obligatory per `feedback-plan-includes-readme`)
- `CHANGELOG.md` — modified (breaking change: session-leash removed)
- `scripts/dogfood_session.py` → `scripts/dogfood_worktree_gate.py` —
  rewritten
- `scripts/smoke_e2e.py` — modified (replace the session-leash e2e step)
- `tests/harness/test_session_gate.py` — rewritten
- `tests/harness/test_session_lockfile.py` — **deleted**
- `tests/test_session_new.py` — **deleted**
- `bootstrap-dev-leash` skill / bootstrap path — modified (remove
  `SessionStart` on re-bootstrap; migration note)

**Target projects after (re-)bootstrap:**

- `.claude/settings.json` — `SessionStart` entry removed, `PreToolUse` gate
  kept
- `.harness/sessions/` — no longer used (safe to delete)
- `.harness/allow-main-write` — transient one-shot marker (gitignored)
- `.harness/exceptions.log` — audit log (already present for `cycle_done`)

---

## Open questions for the implementation plan

- **Gate module name.** Kept as `session_gate.py` to minimize hook-wiring
  churn, but the feature is no longer about "sessions." The plan may rename
  it to `worktree_gate.py` and update `settings.json.tmpl` + the
  `Bash(python -m scripts.harness.*)` permission in one move. Low-risk
  cosmetic call left to plan time.
- **Identifying the main worktree robustly.** Use the first `worktree` entry
  of `git worktree list --porcelain`, cross-checked against
  `git rev-parse --git-common-dir`. The plan confirms this is stable on
  Windows (the original motivation) with a probe.
- **`git worktree list` performance per write.** One subprocess per gated
  write. Expected negligible, but if it shows up, the plan may cache the
  worktree list briefly. Not optimized prematurely.
- **Re-bootstrap mechanics.** Whether `bootstrap-dev-leash` gains
  `--update-hooks` or folds migration into its existing re-run flow.
- **Optional `list_worktrees.py`.** `list_sessions.py` is deleted; a thin
  `git worktree list` wrapper for introspection is optional and deferred
  unless the plan finds it needed.
