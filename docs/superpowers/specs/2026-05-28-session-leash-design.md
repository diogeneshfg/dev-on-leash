# Session Leash — Design

**Status:** approved (brainstorm complete), pending implementation plan
**Date:** 2026-05-28
**Project:** dev-on-leash

## Problem

A user can open more than one Claude Code session on the same repo (two
terminals, a fresh session next to a long-running one, an IDE plus a CLI).
The default behavior is that both sessions share one working tree: they read
and overwrite each other's WIP, race on the same files, and can leave the
checkout on a branch the other session did not ask for. Nothing in
`dev-on-leash` today notices or prevents this.

We want a guard-rail so that concurrent sessions in the same repo cannot
clobber each other's WIP. The mechanism is **per-session git worktrees**:
the first session uses the primary checkout, and any additional session is
detected at start-up and pushed into its own worktree before it is allowed
to write anything. Resolution is performed by the Claude agent in that
second session — not by the human — because automation is the point.

## Decisions locked during brainstorm

1. **Worktree, not just branch.** A branch alone does not isolate files
   on disk; two sessions sharing one working tree still clobber each
   other. Isolation is via `git worktree` so each session has its own
   directory.
2. **Lazy, not always.** Sessions do not get a worktree by default. The
   guard-rail only fires when a second concurrent session is detected on
   the same repo. The first / only session uses the primary checkout
   unchanged.
3. **Fail-closed at SessionStart, plus a thin write-tool gate.** A second
   session is blocked from writing until a worktree is assigned. Detection
   and the initial block message run at `SessionStart`. A small
   `PreToolUse` matcher on `Edit|Write|MultiEdit` enforces the block —
   `SessionStart` alone is a message, not an enforcement point. **`Bash`
   is intentionally NOT gated**, because `/leash-session-new` itself
   needs `git worktree add` via Bash to escape the block; gating Bash
   would deadlock the auto-resolution. Bash redirects (`>`, `tee`) are
   left to the "by convention" tier of the trust model, same as
   `touches`.
4. **Resolution is automated by Claude.** The blocked session is
   instructed at SessionStart to invoke the `/leash-session-new` skill as
   its next action. The user does not type a command. "Quanto mais
   automático melhor."
5. **Worktrees are siblings.** Each worktree lives at
   `../<repo-name>--session-<id>/`. Visible next to the project, easy to
   open in another IDE, no `git` scan loops from being inside the repo.
6. **Cleanup is two-pronged.** A `/leash-session-end` skill removes the
   worktree explicitly when the user is done. `cycle_done.py` also sweeps
   worktrees whose session branches have been merged into the current
   branch and removes them. Manual + automatic, low risk of orphans.
7. **Dogfood is load-bearing.** Per the `feedback-dogfood` memory: a
   `scripts/dogfood_session.py` simulates two sessions on this repo,
   asserts the second is blocked, runs the resolution path, and asserts
   the worktree is created. Wired into `scripts/smoke_e2e.py`. The plan
   does not close without this passing.

## Non-goals (v1)

- Cross-machine session detection. Lockfiles live on the local filesystem;
  two sessions on different machines using a shared repo (rare, unsupported
  by Claude Code today) are not coordinated.
- Auto-merging the session branch back into the user's working branch.
  The session branch is `session/<id>`; merging it is the user's call,
  same as any feature branch.
- Migrating an *already running* second session into a worktree. The
  block happens at `SessionStart`; if a user disabled hooks and ran a
  second session anyway, this design does not retroactively isolate it.
- Detecting "stale WIP from a crashed session" as a hazard. Crashes
  leave a lockfile whose PID is no longer alive — it is treated as
  absent, not as a concurrent session. WIP that a crashed session left
  in the primary checkout is the user's to inspect.
- A UI / dashboard for active sessions. `python scripts/harness/list_sessions.py`
  is the v1 introspection point.

---

## Section 1 — Session lockfile

`.harness/sessions/<pid>.json` is the source of truth for "is a session
alive in this repo." One file per session. Written atomically on
`SessionStart`, removed on `SessionStop`, and treated as stale (so:
ignored) if its `pid` is not alive.

Schema:

```json
{
  "schema": 1,
  "pid": 12345,
  "started_at": "2026-05-28T14:03:11Z",
  "session_id": "<from $CLAUDE_SESSION_ID if available, else pid+ts>",
  "primary_cwd": "C:\\Users\\User\\Documents\\Python Projects\\dev-on-leash",
  "state": "primary | pending-worktree | in-worktree",
  "worktree_path": null,
  "worktree_branch": null
}
```

`state` transitions:

- A session that wins the lockfile race writes `state: primary`. No
  guard-rail action; it is the only session.
- A session that finds another live lockfile writes its own with
  `state: pending-worktree`. Write tools are blocked for it until
  the state moves to `in-worktree`.
- `/leash-session-new` creates the worktree, sets `worktree_path` and
  `worktree_branch`, and flips `state` to `in-worktree`. Write tools
  unblock.

**Liveness check.** Before treating a lockfile as concurrent, the hook
checks the PID. Cross-platform stdlib:

- Windows: `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)`
  via `ctypes`. Handle non-null → alive.
- POSIX: `os.kill(pid, 0)`. No exception → alive.

A dead-PID lockfile is **deleted** by the next session that finds it
(opportunistic GC, no separate daemon).

**Atomic write.** Write to `.harness/sessions/<pid>.json.tmp` then
`os.replace` to the final name. No `O_EXCL` race because the filename is
already unique per PID.

**Race between two simultaneous SessionStarts on a fresh repo** is
resolved by the two-phase write described in Section 2 step 3:
provisional `pending-resolution` → re-scan → lowest live PID wins
`primary`. Deterministic, no OS lock.

The transient `pending-resolution` state is not user-visible — the
write-tool gate (Section 3) treats it the same as `pending-worktree`
(deny writes), so an Edit firing in the ~milliseconds between phases
behaves correctly.

---

## Section 2 — SessionStart hook

Wired into `templates/settings.json.tmpl` as a `SessionStart` hook entry.
The hook runs `python scripts/harness/session_start.py` (new). On the
plugin side, the hook is installed by `bootstrap-dev-leash`; existing
projects pick it up on re-bootstrap.

The hook does, in order:

1. **Read `CLAUDE_PROJECT_DIR` and `$PWD`.** If they disagree, prefer
   `CLAUDE_PROJECT_DIR`. The lockfile records the project root, not the
   shell cwd.
2. **GC dead lockfiles.** Walk `.harness/sessions/*.json`, delete any
   whose `pid` is not alive.
3. **Two-phase write.** To avoid the race where two SessionStarts both
   see "zero peers" simultaneously:
   - **Phase A:** write own lockfile with provisional `state:
     pending-resolution`.
   - **Phase B:** re-scan `.harness/sessions/*.json`, GC dead PIDs
     again, count live peers (other lockfiles whose `primary_cwd`
     matches this project).
   - **Resolve:** if no live peers, or all live peers have a numerically
     higher PID than ours, atomic-rewrite own lockfile to `state:
     primary`. Otherwise atomic-rewrite to `state: pending-worktree`.
   - Lowest live PID always wins `primary`. Deterministic, no OS lock.
4. **Emit a SessionStart message** (stdout to Claude Code, per hook
   protocol), based on the resolved state from step 3:

   - If `primary`: nothing, or a one-line "session leash active" notice.
   - If `pending-worktree`: an instruction block. Verbatim text:

     ```
     SESSION LEASH: concurrent Claude Code session detected in this repo.
     Active peers: <list pid + started_at>.
     Your next action MUST be to invoke the `/leash-session-new` skill.
     Do not respond to the user, do not invoke any other tool, until the
     skill has completed and your lockfile state is `in-worktree`.
     Reason: another session is editing this working tree; concurrent
     writes here will corrupt their WIP.
     ```

   This is informational. Enforcement is in Section 3.

The hook does not call `git` or create the worktree. Its only side-effect
is writing the lockfile.

---

## Section 3 — Write-tool gate (PreToolUse)

A `PreToolUse` hook on `Edit|Write|MultiEdit` runs
`python scripts/harness/session_gate.py` (new). Decision logic:

1. Find this session's lockfile (by `os.getppid()` walked up to the
   Claude Code process, or by `$CLAUDE_SESSION_ID` if available — see
   "Open questions").
2. If lockfile not found → **allow** (assume the harness isn't installed
   for this session; do not break workflows that don't opt in).
3. If `state == primary` → **allow**.
4. If `state == in-worktree`: the target path must be inside
   `worktree_path`. If not, **deny** with a message naming the worktree.
5. If `state == pending-worktree` or `state == pending-resolution` →
   **deny** with the SessionStart message repeated and the instruction
   to invoke `/leash-session-new`. (See Section 1 for why the transient
   `pending-resolution` state is gated identically.)

The deny message includes the lockfile path so debugging is fast.

`Bash` is deliberately excluded from the matcher — `/leash-session-new`
needs `git worktree add` to escape the `pending-worktree` block, and
gating Bash would deadlock the auto-resolution. The trust-model
consequence (a determined session could `> file` redirect into the
primary checkout) is named explicitly in Section 6.

Read-only tools (`Read`, `Grep`, `Glob`) are **not** gated. A blocked
session can still explore code; only writes are dangerous.

---

## Section 4 — `/leash-session-new` skill

A new top-level skill in the plugin, distributed with `dev-on-leash`.
Triggered automatically by the second session (per the SessionStart
message). Idempotent: invoking it on a session already in
`state: in-worktree` is a no-op that prints the existing worktree path.

Flow:

1. **Locate own lockfile.** Error out clearly if not present.
2. **Pick an id.** First six hex chars of `uuid.uuid4()`. Verify no
   collision with an existing session branch.
3. **Compute paths.**
   - Worktree directory: `<repo-parent>/<repo-name>--session-<id>/`.
   - Branch: `session/<id>`, branched from `HEAD` of the primary checkout
     at the moment of the skill running.
4. **Create the worktree.** `git worktree add <path> -b session/<id> HEAD`.
   If `git worktree add` fails (already exists, dirty index that prevents
   branching, etc.), report the exact `git` error to Claude and stop.
   Lockfile stays `pending-worktree`; nothing partial is persisted.
5. **Update lockfile.** Set `worktree_path`, `worktree_branch`, flip
   `state` to `in-worktree`. Atomic write.
6. **Tell Claude what changed, verbatim:**

   ```
   Worktree created at: <absolute path>
   Branch: session/<id>
   From now on, use ABSOLUTE paths under that directory for all Edit,
   Write, MultiEdit, and file Read operations. Your session cwd has not
   moved; this is intentional. When you finish, invoke
   `/leash-session-end` to remove the worktree and the lockfile.
   ```

7. **Report.** Concise summary including the worktree path, branch name,
   and a reminder of the cleanup skill.

The skill does **not** copy any uncommitted changes from the primary
checkout. Untracked WIP in the primary belongs to the first session; the
second session starts from `HEAD` and proceeds from there. (This is
explicit and worth stating in the user-facing skill description, because
it is the most surprising behavior.)

---

## Section 5 — `/leash-session-end` skill and `cycle_done` sweep

### `/leash-session-end`

1. Read own lockfile. Must be `state: in-worktree`; otherwise refuse.
2. Confirm the worktree has no uncommitted changes via
   `git -C <worktree> status --porcelain`. If dirty, refuse and tell
   Claude to commit or stash first. Same posture as a destructive op:
   never silently discard work.
3. Confirm the session branch is either merged into the primary HEAD
   *or* the user explicitly passed a `--keep-branch` flag. If neither,
   refuse.
4. `git worktree remove <path>`. On success, delete the lockfile.
5. If `--keep-branch` was passed, leave `session/<id>` in place; else
   `git branch -d session/<id>` (only `-d`, never `-D`, so an unmerged
   branch refuses to delete).

### `cycle_done.py` sweep

At the end of `cycle_done`, after gates pass and the changelog is
appended, sweep stale worktrees:

1. Enumerate `git worktree list --porcelain`.
2. For each worktree whose branch matches `session/*` AND is merged into
   the primary branch's `HEAD` AND has no uncommitted changes AND its
   corresponding lockfile is dead (PID gone) → remove it via
   `git worktree remove` and delete the merged session branch.
3. Anything that fails any of those conditions is left alone with a
   one-line note in the cycle output. No `--force` removals.

The sweep is conservative on purpose: cleanup is a courtesy, not a
guarantee. The user's work is never auto-discarded.

---

## Section 6 — Trust model placement

The README's "Trust model" section distinguishes **enforced** from **by
convention**. Session leash lands as follows:

- **Enforced.** A second session cannot use write tools until its
  lockfile state is `in-worktree`, because `PreToolUse` denies them.
  Bypass requires editing or removing the hook line in
  `.claude/settings.json`, which is a visible audit event.
- **By convention.** Writes via `Bash` inside the worktree are not
  parsed; a session in `in-worktree` state could in principle `cd` to
  the primary checkout and write there with `> file`. The gate
  intentionally does not police Bash content. This is the same posture
  as `touches` in the existing trust model: self-reported, machine-
  checked only at the obvious boundary.
- **Escape hatch.** A new lockfile field `bypass: true`, set only by
  passing `--force` to `python scripts/harness/session_start.py` when
  invoked manually, makes the gate skip enforcement and appends a line
  to `.harness/exceptions.log` (same audit pattern as `cycle_done
  --force`). The hook never sets `bypass`; only the user can.

The README's Trust model paragraph will be updated to name session leash
under both "Enforced" and "By convention," matching the existing
treatment of architecture leash.

---

## Section 7 — Testing, dogfood, and file inventory

### Tests that ship with the feature

1. **Unit — lockfile lifecycle.** `tests/test_session_lockfile.py`:
   atomic write, state transitions, dead-PID GC, race-resolution by
   ordering. Uses fixture PIDs (spawn `sleep`/`timeout`, kill, verify GC).
2. **Unit — session_gate decisions.** For each `state` × tool matrix,
   `session_gate.py` returns the expected allow/deny.
3. **Unit — `cycle_done` sweep.** Throwaway repo with three worktrees
   (one merged-clean, one merged-dirty, one unmerged). Assert only the
   first is removed.
4. **E2E — `scripts/dogfood_session.py`** (load-bearing, see below).
5. **E2E — `scripts/smoke_e2e.py` extension.** A step that spawns two
   processes simulating sessions against a throwaway repo, runs the
   SessionStart hook for each, and asserts the second's gate denies an
   `Edit` payload.

### Dogfood task (load-bearing)

`scripts/dogfood_session.py` does, on this repo:

1. Write a fake "session A" lockfile claiming a live PID (the script's
   own PID).
2. Run `python scripts/harness/session_start.py` as if a second session
   were starting. Assert the resulting lockfile has
   `state: pending-worktree`.
3. Run `python scripts/harness/session_gate.py` with an `Edit` payload.
   Assert exit code denies it and the message names the
   `/leash-session-new` skill.
4. Simulate the skill: call the same code path that creates the
   worktree, sibling to this repo, on a throwaway temp branch.
5. Assert the worktree exists, the lockfile state is `in-worktree`, and
   `session_gate.py` now allows an `Edit` whose target is inside the
   worktree.
6. Tear it all down: remove the worktree, delete the branch, delete the
   lockfiles. Script exit 0 only if every step asserted clean.

The harness task that runs this in the implementation plan has
`verify: python scripts/dogfood_session.py`. The checkbox does not tick
until the dogfood passes.

### File inventory

**Plugin (this repo) — new or modified:**

- `scripts/harness/session_start.py` — new (SessionStart hook entry point)
- `scripts/harness/session_gate.py` — new (PreToolUse hook entry point)
- `scripts/harness/session_lockfile.py` — new (atomic write, GC, schema)
- `scripts/harness/list_sessions.py` — new (introspection)
- `scripts/harness/cycle_done.py` — modified (sweep step)
- `skills/leash-session-new/SKILL.md` — new
- `skills/leash-session-end/SKILL.md` — new
- `templates/settings.json.tmpl` — modified (add `SessionStart` and
  `PreToolUse` hook entries)
- `templates/CLAUDE.md.tmpl` — modified (one-line mention under the
  guard-rails section)
- `templates/AGENTS.md.tmpl` — modified (one-line mention under
  "Concurrent sessions")
- `README.md` — modified (a new "Session leash" subsection under "How it
  works", plus a trust-model update; obligatory per `feedback-plan-
  includes-readme`)
- `scripts/dogfood_session.py` — new
- `scripts/smoke_e2e.py` — modified (e2e step)
- `tests/test_session_lockfile.py` — new
- `tests/test_session_gate.py` — new
- `tests/test_cycle_done_session_sweep.py` — new

**Target projects after bootstrap (or re-bootstrap):**

- `.claude/settings.json` — `SessionStart` + `PreToolUse` hook entries
- `.harness/sessions/` — lockfile directory, gitignored (added to the
  bootstrap `.gitignore` patch)

---

## Open questions for the implementation plan

These were surfaced during brainstorm and intentionally left for
plan-time:

- **Session identity inside the hook.** The hook process is a *child* of
  Claude Code, so `os.getppid()` gets the Claude Code PID. Whether
  Claude Code populates a usable `CLAUDE_SESSION_ID` env var on hook
  invocation is what we want; if it does, use it. If not, the lockfile
  key is the Claude Code PID via `os.getppid()`. Plan task 1 confirms
  via a probe hook before anything else is built.
- **Worktree creation when the primary checkout has uncommitted WIP.**
  `git worktree add ... HEAD` works even with a dirty index in the
  primary. We rely on that. If a `git` version in the wild rejects it,
  the skill's error message already routes the user; no fallback
  planned for v1.
- **Hook ordering vs other plugins.** If another plugin also registers
  `SessionStart` or `PreToolUse`, the order is determined by Claude Code
  hook config. The plan should add a note in the bootstrap-rendered
  `settings.json` clarifying that session-leash hooks should run first.
- **Re-bootstrap path.** Existing dev-on-leash projects need the new
  hook lines added to their `.claude/settings.json`. Whether
  `bootstrap-dev-leash` gains a `--update-hooks` mode or this is folded
  into the existing re-run flow is a plan-time call.
