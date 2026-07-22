# Configurable base branch for worktrees — design

Date: 2026-07-22
Status: approved (rev 2 — after 2× Opus antagonist-critic round)

## Problem

`/leash-start-work` hardcodes `main`/`master` as the starting point for every
new worktree, and `/leash-finish-work` checks "is the branch merged?" against
whatever branch the main checkout happens to have checked out. Projects with
several long-lived branches (e.g. `dev`, `qa`, `homol`, `prod`) can't follow
their real flow: work often must start from `prod` (production may be behind
`dev`) and gets merged first into `dev`, then promoted.

## Decisions (validated with the user; rev 2 items re-validated after the critic round)

1. **Base branch source:** per-project config declares a default base;
   `/leash-start-work` accepts an optional `--base <branch>` override. With
   neither, behavior is unchanged (`main`/`master`). Both the config `base`
   and the `--base` override are validated the same way: the branch must be
   `main`/`master` or listed in `long_lived`.
2. **Merged check (rev 2):** the config declares a **single integration
   target** (`merge_target`, e.g. `dev`) — the branch where work PRs land.
   A work branch is safe to remove when it is an ancestor of the local
   `merge_target` **or** of `origin/<merge_target>` (remote-tracking ref).
   The original "merged into any declared branch" rule was refuted by the
   critics: it reaps the branch at the *start* of a promotion pipeline and
   downgrades the durability guarantee. Promotion dev→qa→homol→prod happens
   by merging the long-lived branches into each other, so the feature branch
   is no longer needed once it lands in `merge_target`. Pipelines that
   cherry-pick the feature branch into `prod` keep it with `--keep-branch`.
3. **Freshness:** before branching, fetch the base from the detected remote;
   if the local base is strictly behind its remote-tracking ref, warn and
   branch from the remote-tracking ref with `--no-track` (see rev-2 notes).
   No remote / fetch failure ⇒ warn and use the best local ref available.
4. **Protection:** every branch listed in `long_lived` gets the same
   protection `main`/`master` have today — start-work refuses slugs that
   collide with protected names, finish-work refuses to remove a worktree
   sitting on one.
5. **Config home:** a dedicated, optional `.harness/branches.yaml`.
6. **Mechanical gate, not prose (rev 2):** start-work logic moves into a new
   `scripts/harness/start_work.py` script; the SKILL.md becomes a thin
   wrapper that invokes it, matching `finish_work.py` and the repo's
   gates-over-prose philosophy.
7. **Branch deletion (rev 2):** `finish_work` proves merge-ancestry itself
   (`git merge-base --is-ancestor`) *before touching anything*, then deletes
   with `git branch -D`, logging the proof to `.harness/exceptions.log`-style
   audit (`.harness/finish_audit.log`). The "never silently discard work"
   rule is preserved by the explicit proof, not by `-d`'s HEAD-relative
   heuristic — which the critics showed makes the multi-branch flow
   impossible (`-d` refuses anything not merged into HEAD/upstream, so the
   gate would pass and git would then error after the worktree was already
   removed).

## Config file

```yaml
# .harness/branches.yaml  (optional)
base: prod                          # default base for new worktrees
merge_target: dev                   # where work branches land (delete-safety check)
long_lived: [dev, qa, homol, prod]  # protected branches (main/master always implied)
```

Validation rules:

- All keys optional; unknown top-level keys are a hard error (fail loud).
- Missing file ⇒ current behavior exactly: base = detected `main`/`master`,
  `merge_target` = same, protected = `{main, master}`.
- `base` and `merge_target`, when present, must each be `main`/`master` or
  listed in `long_lived`.
- Branch names must be plausible git refs (no spaces, no leading `-`,
  conservative charset; entries containing `/` are rejected — long-lived
  branches are bare names).
- A malformed file is a hard, clearly-worded error naming the file and the
  offending key — never a silent fallback.

## Components

### `scripts/harness/branches.py` (new)

Single reader for the config, using `yaml.safe_load` like
`validate_architecture.py`. API:

```python
load_branch_config(repo_root: Path) -> BranchConfig
# BranchConfig:
#   base: str            # resolved: config base → detected main/master
#   merge_target: str    # resolved: config merge_target → detected main/master
#   protected: set[str]  # long_lived ∪ {main, master}
```

`protected` and `merge_target` are deliberately **separate concepts**
(protection = where you must not work; merge target = where integration is
durable). Raises `BranchConfigError` on malformed input.

### `scripts/harness/start_work.py` (new)

Mechanical implementation of worktree creation; the SKILL.md instructs the
model to run it, never to hand-roll `git worktree add`. Behavior:

- Args: `<type>/<slug>` (validated: `type ∈ feat|fix|refactor|docs|chore`,
  kebab-case slug) and optional `--base <branch>`.
- Refusals (script exit ≠ 0, clear message):
  - slug equals a protected branch name (avoids `.worktrees/prod` confusion);
  - resulting branch name equals any protected name;
  - `--base`/config base not `main`/`master` and not in `long_lived`;
  - base has no ref at all (no local branch **and** no remote-tracking ref);
  - local base **diverged** from its remote-tracking ref (behind AND ahead):
    refuse with instructions — never silently pick a side.
- Remote detection: use the base branch's configured remote if set, else the
  repo's sole remote, else `origin` if present; if none, skip fetch with a
  warning (offline work never blocks).
- Freshness: `git fetch <remote> <base>`; fetch failure ⇒ warn, proceed with
  the freshest ref already available locally. This resolves the rev-1
  contradiction: *existence* is judged from refs already present (local
  branch or remote-tracking ref), so offline + remote-only base works as
  long as the remote-tracking ref was ever fetched.
- Start-point selection: local base if up to date; `<remote>/<base>` if the
  local base is behind (or absent). When the start-point is a
  remote-tracking ref, pass `--no-track` so the feature branch gets **no
  upstream** — otherwise git silently sets upstream to `origin/<base>`,
  corrupting `git status`/`git pull`/deletion semantics on the feature
  branch.
- Creates `git worktree add .worktrees/<slug> -b <type>/<slug> <start-point>
  [--no-track]` and prints worktree path + the base actually used.
- Warns if `.worktrees/` is not gitignored (existing behavior, moved from
  prose into the script).

### `scripts/harness/finish_work.py`

- Refusal list `("main", "master")` → `BranchConfig.protected`.
- `_branch_is_merged` → `_prove_merged(repo, branch)`: true iff
  `git merge-base --is-ancestor <branch> <merge_target>` or
  `... <branch> origin/<merge_target>` (whichever refs exist) succeeds.
  Checking the remote-tracking ref fixes the critic-found rot: a chronically
  behind local `dev` no longer blocks cleanup of genuinely merged branches.
- Order: prove ancestry (or `--keep-branch`) **before** removing anything;
  then `git worktree remove`; then `git branch -D <branch>` (a branch
  checked out in a worktree cannot be deleted first). `-D` is used **only**
  after the explicit ancestry proof; each deletion appends an audit line
  (branch, proven target, SHA) to `.harness/finish_audit.log`.
- Known limitation, documented (not "strictly more correct"): squash- and
  rebase-merges produce new SHAs and fail the ancestry proof — use
  `--keep-branch` and delete manually, same as today.

### `scripts/harness/cycle_done.py`

`advise_merged_worktrees` switches from HEAD-relative `git branch --merged`
to the same `_prove_merged` semantics (shared via `branches.py` or a small
shared helper), so the advisory and the enforcement agree on what "merged"
means.

### `skills/leash-start-work/SKILL.md` and `skills/leash-finish-work/SKILL.md`

Thin prose over the scripts: when to use, `python -m
scripts.harness.start_work <type>/<slug> [--base <branch>]`, the
session-stays-home rule, and the new semantics (base precedence, single
merge target, `-D`-after-proof) documented for humans.

### Templates (`templates/AGENTS.md.tmpl`, `templates/CLAUDE.md.tmpl`)

Rev-2 addition (critic-found): both templates hardcode "branch from `main`"
and the literal `git worktree add ... main` command — the prose the agent
actually follows. They gain a `{{BASE_BRANCH}}` placeholder (rendered from
the bootstrap interview, default `main`) and reference
`scripts.harness.start_work` instead of a raw `git worktree add` line, so
config and discipline text can never disagree.

### `skills/bootstrap-dev-leash`

- Interview gains one optional question: "long-lived branches besides main
  (dev/qa/homol/prod)? default base? merge target?".
- A yes writes `.harness/branches.yaml` directly (same hand-write pattern as
  Step 3b's `.harness/gates` — no `.tmpl` needed) and feeds
  `{{BASE_BRANCH}}` into the template rendering. Init scripts must not
  clobber an existing `branches.yaml`.

### README

User-facing feature ⇒ README section on multi-branch projects and
`.harness/branches.yaml`, shipped in the same plan (project rule).

## Error handling

- Malformed `branches.yaml` → hard error naming file + offending key.
- `--base` outside `long_lived ∪ {main, master}` → refusal listing the
  declared branches (symmetric with config validation).
- No ref for the base anywhere → refusal telling the user to fetch first.
- Diverged local base → refusal with reconcile instructions.
- Fetch failure / no remote → warn and proceed from local refs.
- `finish_work` git failures keep the existing `FinishWorkError` path;
  ancestry is proven before any destructive step, so a failure can no longer
  leave "worktree gone, branch orphaned".

## Testing

- `branches.py`: missing file, valid file, malformed YAML, unknown top-level
  keys (fail loud), `base`/`merge_target` not in `long_lived`, bad ref
  names, slash-containing long-lived entries rejected.
- `start_work.py`: happy path from local base; behind base → branches from
  remote-tracking ref with no upstream set; diverged base → refusal;
  protected-slug refusal; `--base` validation; no-remote path.
- `finish_work.py`: refusal on a worktree sitting on a declared long-lived
  branch; branch merged into `dev` (local or only `origin/dev`) removable
  while HEAD is on `main`; unmerged branch still refused; audit line
  written; no-config behavior unchanged (existing tests keep passing).
- `cycle_done.py`: advisory fires for a branch merged into `merge_target`
  while HEAD is elsewhere.
- Docs/template tests updated where they assert on skill or template text.
- Dogfood: add a trivial `branches.yaml` (`base: main`) to this repo and run
  a start→finish cycle to verify nothing regresses.

## Out of scope (YAGNI)

- Automatic promotion flows (dev → qa → homol → prod).
- Keeping long-lived branches in sync with each other.
- Changes to `session_gate.py` — the directory-based write gate already
  prevents editing any branch checked out in the main worktree (this
  out-of-scope claim survived the critic round).
- Squash-merge detection heuristics — `--keep-branch` is the escape hatch.

## Critic round (2× Opus antagonists)

Rev 1 was reviewed by two independent antagonist critics. Their consolidated
verdict (1 blocker, 4+4 majors, minors) drove rev 2: `-D`-after-proof
deletion, single `merge_target` split from `protected`, remote-tracking-ref
ancestry, mechanical `start_work.py`, template parameterization,
`cycle_done` alignment, `--no-track`, diverged-base refusal, symmetric
`--base` validation, remote-name detection, and removal of the "strictly
more correct" overclaim.
