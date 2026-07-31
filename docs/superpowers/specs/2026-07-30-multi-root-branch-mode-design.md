# Multi-root workspaces + `workflow: branch` mode

**Date:** 2026-07-30
**Status:** approved (design), pending implementation plan
**Revision:** 2 — after antagonist-critic round (opus, fable)

## Problem

Field test: one Claude session driving a VS Code multi-root workspace with
four independent git repos. Branch policy in every repo: four long-lived
environment branches (`prod`, `homol`, `qa`, `dev`); every change branches
off `prod` and merges into `dev` (then promotes onward). All four repos had
`.harness/branches.yaml` with `base: prod` and the four environments in
`long_lived`. The test failed on two fronts:

1. **Wrong repo** — `start_work.py` defaults `repo_root` to
   `CLAUDE_PROJECT_DIR`/cwd, which in a multi-root workspace points at one
   repo (the session root) regardless of which project a demand targets.
   Worktrees were created in the wrong repo, and branches were therefore
   cut from the right-*named* base (`prod`) of the wrong repo — which is
   what produced the cascading merge conflicts into `dev`. ("Wrong base"
   is a consequence of wrong repo, not an independent failure: every
   repo's config declared the same base name.)
2. **Unprotected repos** — `session_gate.py` probes worktrees from the
   session root only; files in the other three repos resolve to "outside
   the repo" and every write is allowed. Agents edited environment
   branches directly.

The users had to abandon worktrees mid-test and fall back to plain
branches by hand.

Note: `--repo-root` already exists on `start_work.py` and
`finish_work.py`. It failed in the field partly because it is
undocumented (the SKILL.md invocation omits it) and partly because it is
unvalidated (any path is accepted). Component A is therefore validation +
mechanical ambiguity refusal + documentation of an existing flag, not a
new capability.

## Root cause

Every harness entry point (start, finish, write gate) resolves "the repo"
from the session's root directory. That assumption is false in a
multi-root workspace. Worktrees amplified the damage (ghost directories in
wrong repos, agents lost between paths) but were not the root cause.

## Decision

Four components, in dependency order. A and C are prerequisites for both
workflow modes; B and D add an opt-in plain-branch mode suited to
"one demand per repo, parallelism across repos" workflows.

Recommended configuration for multi-root, environment-branch projects:
`workflow: branch` in each repo's `branches.yaml`. Plugin-wide default
stays `worktree`.

### Shared mechanism: resolving the repo that owns a path

Used by A's validation and C's gate. For a path `p`:

1. Find the nearest **existing** ancestor directory of `p` (so `Write`
   into a not-yet-created subdirectory still resolves — never treat a
   nonexistent leaf directory as a git failure).
2. `git -C <that dir> rev-parse --git-common-dir` → the repo's common
   git dir. `--show-toplevel` alone is insufficient: inside a linked
   worktree it returns the worktree's own root and cannot distinguish
   main from linked, nor find the main repo.
3. The **main worktree** is the parent of the common git dir; the target
   is in a **linked worktree** when its own toplevel differs from the
   main worktree.
4. `branches.yaml` is always loaded from the **main worktree's**
   `.harness/` — never from a linked worktree's checkout (a gated agent
   can edit its own worktree's copy; the main tree's copy is the one the
   gate itself makes read-only).
5. Path comparisons use normalized, case-insensitive-on-Windows
   resolution (`Path.resolve()` + `os.path.normcase` / `samefile`), not
   naive string equality.

### A — Explicit target-repo resolution (`start_work.py`, `finish_work.py`, `allow_main_write.py`)

- `--repo-root` is validated: the resolved path must be the **main
  worktree toplevel** of a git repo (per the shared mechanism). Refused
  with an actionable message: a subdirectory, the workspace folder, a
  non-repo path, and — explicitly — a linked worktree
  (`.worktrees/<slug>` would otherwise pass a naive `--show-toplevel`
  check and nest worktrees).
- **Ambiguity refusal** (mechanical, covers both multi-root layouts):
  when no explicit `--repo-root` is passed, the script refuses and lists
  candidates if either
  - the default root is not itself a git toplevel but its direct
    children include git repos (session rooted at the workspace
    folder), **or**
  - the default root is a git toplevel but **sibling directories contain
    leash-managed repos** (a `.harness/branches.yaml` in a sibling —
    the field-test layout, where the session root is one of the four
    repos). Passing `--repo-root <default>` explicitly satisfies the
    gate; the refusal message says so. Unrelated sibling repos without
    `.harness/` never trigger it, so single-repo users in a crowded
    `~/projects` folder are unaffected.
- `allow_main_write.py` gains the same validated `--repo-root`; the
  marker and `exceptions.log` live in the **target repo's** main-worktree
  `.harness/`, and the gate reads them from there. (Today the CLI writes
  the marker to the session root unconditionally — without this, the
  escape hatch can never authorize a write in a non-session-root repo.)
- Every run echoes a context line:
  `repo: <path> | config: <.harness/branches.yaml | default> | base: <resolved> | mode: <worktree|branch>`.
- `skills/leash-start-work/SKILL.md` gains a "multi-root workspace"
  section and documents `--repo-root` in the canonical invocation.

### B — `workflow: branch` mode (opt-in, `branches.yaml`)

- New key `workflow: worktree | branch` in `.harness/branches.yaml`.
  Default `worktree`. Unknown value is a hard `BranchConfigError`.
- Branch mode reuses the existing validation pipeline: branch name
  `<type>/<slug>`, base resolution (`--base` → config → detected
  default), freshness fetch, diverged-base refusal, undeclared-base
  refusal, `--no-track` semantics. The protected-slug refusal is kept
  deliberately (a branch named `feat/dev` invites confusion, and a later
  switch to worktree mode would collide) with a mode-appropriate
  message.
- Branch mode replaces only the final step. Instead of
  `git worktree add`, it:
  - refuses when tracked changes exist (staged or unstaged); untracked
    files produce a **warning listing them**, not a refusal (blocking on
    `.env`-style scratch files would make the mode unusable);
  - refuses when HEAD is already on a `<type>/<slug>` work branch
    (one demand at a time per repo);
  - refuses when the branch name already exists;
  - then runs `git checkout -b <type>/<slug> <start_point>`.
- **Documented trade-off — concurrency:** worktree mode prevents
  same-repo write collisions *by construction* (no session may write the
  main tree). Branch mode cannot: two sessions pointed at the same
  branch-mode repo both pass the gate and share one checkout. Branch
  mode is specified for **one session per repo**; the README states this
  and points concurrent-demand workflows at worktree mode. No lock/PID
  machinery is added — that approach was already tried and removed
  (mis-elected primaries on Windows; see `session_gate.py` docstring).

### C — Path-based write gate (`session_gate.py`)

The gate resolves the repo that owns the **target file** via the shared
mechanism above, loads **that repo's** config from its main worktree,
and applies that repo's mode:

- **Linked-worktree targets are allowed in both modes.** Mode governs
  the main tree only. This also defines the mixed state: a
  `workflow: branch` repo that still contains `.worktrees/<slug>`
  entries (pre-flip or hand-made) keeps its in-flight worktree work
  writable.
- **Main-tree targets, worktree mode:** denied (current rule, now
  correct in every repo, including new-file/new-directory targets).
- **Main-tree targets, branch mode:** **allow-list** — allowed only
  when that repo's HEAD is on a `<type>/<slug>` work branch. Every
  other HEAD state is denied: protected branches, non-conforming
  branches (`experiment`, `dependabot/...`), detached HEAD, unborn
  HEAD. Fail-closed by construction; the one-shot marker is the escape
  for legitimate odd states.
- **Deny messages are mode-aware.** The current hardcoded "start your
  change in a worktree" text is wrong in branch mode; branch mode's
  message says which protected/non-work branch HEAD is on and to run
  `/leash-start-work`. `templates/CLAUDE.md.tmpl` and
  `tests/test_docs.py` (which pin the worktree framing) are updated to
  describe both modes.
- **Malformed `branches.yaml` in the gate: deny**, with the config
  error as the reason — a hook must emit a decision and exit 0, and
  fail-open would let one broken YAML file silently disable protection;
  deny surfaces the problem on the first write. (This is the
  hook-context refinement of "malformed config is a hard error".)
- A target outside any git repo: allowed. Git failure after the
  nearest-existing-ancestor step: fail-open with a logged warning
  (genuinely unchanged semantics, now that new-path targets no longer
  reach it).
- Cost note: this adds 1–2 `git rev-parse` calls plus a YAML read per
  gated write, and makes the hook depend on PyYAML (already a harness
  dependency via `branches.py`). Accepted: gated writes are
  human-timescale events.

Scope note: the gate protects Claude's write tools. Manual git commands
run by the human in a terminal are out of scope and remain a residual
risk the design accepts; the context echo in A is an aid, not a
mitigation.

**Deployment constraint (documented, not solved here):** PreToolUse
wiring lives in the session-root project's `.claude/settings.json` and
resolves `scripts.harness.session_gate` relative to the session root. In
a multi-root workspace the session must therefore be rooted in a
leash-bootstrapped repo (any of the four); that repo's harness version
governs all sibling repos, and `/leash-update` keeps versions aligned.
If the session is rooted in an unbootstrapped folder, no gate runs — the
README and SKILL.md state this requirement explicitly.

### D — Mode-aware `finish_work`

- Branch-mode CLI: `finish_work <type>/<slug>` names the **branch**
  (today's positional slug names a worktree directory; in branch mode
  the argument is the full `<type>/<slug>` name). With no argument, the
  current HEAD is used when it matches `<type>/<slug>`; otherwise
  refuse.
- Same merge proof as today (`prove_merged` against `merge_target`,
  local and remote-tracking refs); refuses a dirty tree or an
  unproven-merged branch; `--keep-branch` remains the escape for
  squash/rebase merges.
- On success: checks out the **`merge_target`** branch (`dev` in the
  field-test flow) and deletes the work branch. Rationale (user
  decision): the checkout must never land on `prod`; `merge_target` is
  where the work just landed, and it is still a protected branch, so the
  gate denying writes remains the intended idle state between demands.
  The next `start_work` cuts from `base` regardless of where HEAD sits,
  so ending on `merge_target` costs nothing.
- Both modes go through A's `--repo-root` validation.

## Out of scope (explicitly considered and deferred)

- **Workspace manifest** (`workspace.yaml` mapping names → paths):
  A's ambiguity refusal + candidate listing covers the need; layerable
  later without rework.
- **Gating manual terminal git usage** — accepted residual risk.
- **Cross-session locking for branch mode** — deliberately not
  reintroduced (see B's trade-off note).
- **`cycle_done.py` branch-mode advisory** — today it only advises about
  merged `.worktrees/*`; a branch-mode variant (advise merged local
  `<type>/<slug>` branches) is a follow-up, not required for safety.
- **`session_root_guard`** — worktree-specific by nature; it is a no-op
  in branch mode and stays as-is.
- **`check_freshness.py` multi-root awareness** — advisory only;
  follow-up.
- Any change to the promotion flow between environment branches
  (`dev → qa → homol → prod`).

## Error handling

CLI refusals exit non-zero with an actionable message. Offline work never
blocks: fetch failures warn and fall back to local refs. Malformed config
is a hard error in CLIs; in the gate it is a **deny with the error as
reason** (see C). Git failures in the gate fail open with a logged
warning, after the nearest-existing-ancestor resolution step.

## Testing

- Unit: `workflow` key parsing (valid values, default, hard error on
  junk).
- Shared resolver: nearest-existing-ancestor for new paths; linked
  worktree vs main worktree discrimination via `--git-common-dir`;
  Windows-style case-insensitive path comparison.
- `start_work` branch mode over temporary git repos: tracked-dirty
  refusal, untracked-only warning (not refusal), already-on-work-branch
  refusal, existing-branch refusal, correct base checkout, `--no-track`.
- `finish_work` branch mode: branch-name CLI, HEAD-default resolution,
  merge-proof pass/fail, dirty refusal, `--keep-branch`, ends on
  `merge_target` (never `prod`/`base`).
- Repo-root validation: subdirectory, workspace dir, non-repo, **linked
  worktree** — all refused; main toplevel accepted.
- Ambiguity refusal: (a) parent-dir workspace layout, (b) session root
  is one of several leash-managed siblings — both refuse without
  `--repo-root` and list candidates; sibling repos *without* `.harness/`
  do not trigger.
- `allow_main_write` in a non-session-root repo: marker lands in and is
  consumed from the target repo's `.harness/`.
- **Multi-repo gate fixture** (regression test for the field failure):
  two sibling repos, one per mode, session rooted elsewhere. Assert:
  main-tree write denied in the worktree-mode repo (including a write
  that creates a new subdirectory); branch-mode repo denies writes on
  `dev`, on a non-conforming branch, and on detached HEAD; allows on a
  `<type>/<slug>` branch; linked-worktree writes allowed in both modes;
  malformed `branches.yaml` denies with the config error.

## Delivery

- Rollout order matters: adding `workflow:` to `branches.yaml` before
  the harness scripts are updated is a hard `BranchConfigError` from
  every entry point (unknown-key policy). `/leash-update` must deliver
  the new harness first; the README migration note states the order and
  `skills/leash-update/SKILL.md` is checked for anything version-gated.
- Dogfood: this repo keeps worktree mode (exercises A + C here). Branch
  mode: sandbox multi-repo fixture before merge, **then validated in the
  user's real four-repo workspace before the release is tagged** — the
  synthetic fixture alone is the same coverage class that missed the
  original field failure.
- README documents both modes, when to choose each, the one-session-per-
  repo constraint of branch mode, and the multi-root deployment
  constraint — as a plan task, before merge.
