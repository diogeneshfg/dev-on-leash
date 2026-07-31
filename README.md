# dev-on-leash

A verify-gated task harness for AI-assisted development, packaged as a
portable **Claude Code plugin**.

`dev-on-leash` turns a Markdown plan into a machine-checked workflow: a
harness task declares a `verify` command, its checkbox is ticked only when
that command passes, and every ticked harness task can be independently
re-verified so a hand-flipped checkbox cannot survive CI or a pre-commit hook.
It ships a
parallel-execution scheduler, a doc-freshness check, an auto-appended
changelog, custom review agents, a bootstrap skill that scaffolds the
whole setup into any project, and an **architecture leash** that turns a
prose architecture description into mechanical gates and a project-local
reviewer agent.

## What's in the box

- **Harness scripts** (`scripts/harness/`) — `validate_plan`, `run_task`,
  `cycle_done`, `plan_schedule` (parallel scheduler), `check_freshness`,
  baseline/regression tooling, `validate_architecture` /
  `compile_architecture` (architecture-leash). CI-executable, no Claude Code
  required.
- **Skills** (`skills/`) — `bootstrap-dev-leash` (interviews a project and
  generates a tailored `CLAUDE.md` + `AGENTS.md`), `execute-plan-task`, and
  `compose-architecture-leash` (declares an architecture and compiles it to
  gates + reviewer agent).
- **Agents** (`agents/`) — `plan-reviewer`, `tdd-evidence-checker`,
  `isolation-reviewer`, `verification-gate`, `architecture-extractor`.
- **Templates** (`templates/`) — `CLAUDE.md` / `AGENTS.md` skeletons,
  `task-schema`, `plan-template`, `settings.json`,
  `architecture-reviewer.md.tmpl`.
- **Init scripts** (`scripts/init.*`) — copy the project-agnostic layer into a
  target repo without an interview.

## Install

```
/plugin marketplace add diogeneshfg/dev-on-leash
/plugin install dev-on-leash@dev-on-leash
/bootstrap-dev-leash          # interview + generate CLAUDE.md / AGENTS.md
```

## How it works

A **plan** is a Markdown file with `## Task N` headings. Augment any task with
a `task-meta` block — `id`, `touches`, `depends`, `verify` — to make it
machine-verified. `task-meta` is an augmentation, not a separate plan format;
tasks without one are human-run and ignored by the harness. The harness then
drives the loop:

1. **`validate_plan.py <plan>`** — checks the task-meta schema, dependency
   graph, and write-collisions; warns about task headings with no `task-meta`.
2. **`plan_schedule.py <plan>`** — shows which tasks can run in parallel.
3. **`run_task.py <plan> <id>`** — runs the task's `verify` command and ticks
   its checkbox **only if it exits 0**. A failing verify leaves the box unticked.
4. **`cycle_done.py --plan <plan>`** — once every task is checked off, runs the
   project's `.harness/gates` commands and appends a `CHANGELOG.md` entry.

The harness is plain Python operating on Markdown — no Claude Code required to
run it, and no dependency on any other plugin.

## Architecture leash

Once a project is bootstrapped, run `/compose-architecture-leash` to put its
architecture under the same machine-checked discipline as the rest of the
harness. The skill interviews the user in prose, dispatches the
`architecture-extractor` subagent to convert that prose into a structured
`.harness/architecture.yaml`, and compiles the YAML into enforcement
artifacts:

- **Mechanical gates** in `.harness/gates`: dependency-direction contracts
  for Python (`import-linter`) and JS/TS (`dependency-cruiser`), plus a
  generic Python check script per forbidden-imports rule.
- **A project-local reviewer agent** at `agents/architecture-reviewer.md`,
  rendered from `templates/architecture-reviewer.md.tmpl` with the
  declared layers, edges, and judgment rules baked in.

Re-runnable in three modes — **add**, **revise**, **re-describe** — so the
spec grows with the project. Every gate line carries `# arch-leash:<id>`
so the compiler can prune cleanly when a rule is removed.

`dev-on-leash` dogfoods this on itself: see `.harness/architecture.yaml`,
the generated `.harness/checks/`, and `scripts/dogfood_architecture.py`
(which plants a deliberate `import requests` in the harness layer and
asserts the gate rejects it).

## Worktree leash

The **main worktree is read-only** to write tools. A `PreToolUse` gate
denies any `Edit`/`Write`/`MultiEdit`/`NotebookEdit` whose target resolves
into the main worktree; all work happens in a linked worktree created by
`/leash-start-work` (`.worktrees/<slug>` on a `<type>/<slug>` branch from
`main`). Clean up with `/leash-finish-work`.

This makes concurrent Claude Code sessions safe **by construction**: each
session works on its own branch in its own worktree, and none of them can
edit the shared main tree — so two sessions can never clobber each other's
WIP. There is no session detection, no lockfiles, and no PID election (the
previous design's election mis-elected two primaries on Windows, where PIDs
are not monotonic).

The gate is stateless: it runs `git worktree list` and matches the target
to the longest-prefix worktree. For a one-off direct edit to the main tree,
authorize a single write with
`python -m scripts.harness.allow_main_write "<reason>"`; the gate consumes
the authorization on the next main-tree write and logs it to
`.harness/exceptions.log`. The main tree is expected to mirror the remote —
you keep it synced with ordinary `git fetch`/`pull`/merge.

**The session stays rooted in the main checkout.** Only the *files being
edited* live under `.worktrees/<slug>` — never start (or relocate) a Claude
Code session inside the worktree. Session history is keyed to the session's
root directory, so a session rooted in `.worktrees/<slug>` loses its history
the moment `/leash-finish-work` removes the worktree. The gate resolves write
targets absolutely, so editing worktree files from a main-checkout session
always works. A `SessionStart` hook (`scripts/harness/session_root_guard.py`)
warns whenever a session is rooted inside a linked worktree.

`dev-on-leash` dogfoods this on itself: see
`scripts/dogfood_worktree_gate.py`, run from `scripts/smoke_e2e.py`, which
asserts the gate denies a main-tree edit, allows an edit inside a worktree,
and honors a one-shot escape exactly once.

## Parallel work with worktrees (opt-in)

Branch discipline is mandatory — every change on a new `<type>/<slug>` branch
off `main`. Worktrees make running several of those branches at once
comfortable, without the stash-dance.

- **Bootstrap** offers to standardize a `.worktrees/` layout and adds
  `.worktrees/` to `.gitignore` under the `# dev-on-leash` heading.
- **`/leash-start-work`** starts a change in its own worktree via the
  mechanical backend, `python -m scripts.harness.start_work <type>/<slug>`,
  run from the main checkout, without moving the session (no `EnterWorktree`
  or other session-relocating mechanisms). The worktree starts from the
  configured base branch (`.harness/branches.yaml`, default main/master; a
  `--base <branch>` override is available) — see "Multi-branch projects"
  below.
- **`cycle_done.py`** prints an advisory reminder to `git worktree remove`
  once a `<type>/<slug>` branch is merged (it never removes feature worktrees
  for you).

The worktree leash makes this the only path to writing — the main tree is read-only, so every change starts here.

### Multi-branch projects (`.harness/branches.yaml`)

Projects with several long-lived branches (dev / qa / homol / prod)
declare them once:

```yaml
# .harness/branches.yaml  (optional — absent means classic main/master)
base: prod                          # where new worktrees start
merge_target: dev                   # where work branches land (delete-safety)
long_lived: [dev, qa, homol, prod]  # protected, like main/master
```

- `/leash-start-work` starts worktrees from `base` (override per-invocation
  with `--base <branch>`), fetching first and warning when the local base
  trails its remote.
- `/leash-finish-work` deletes a work branch only after proving it is an
  ancestor of `merge_target` (local or remote-tracking) — squash-merged
  branches are not provable; use `--keep-branch`.
- Every `long_lived` branch is protected exactly like `main`: no direct
  work, no worktree removal while checked out on one.

### Workflow modes: `worktree` (default) vs `branch`

`.harness/branches.yaml` accepts `workflow: worktree | branch` to select between two modes:

- **worktree** (default): every demand gets `.worktrees/<slug>`; the
  main checkout is read-only. Choose it when one repo carries several
  parallel demands.
- **branch**: `/leash-start-work` does a disciplined `checkout -b` off
  the configured base instead; the write gate allows edits only while
  HEAD is on a `<type>/<slug>` branch. One demand at a time per repo,
  and **one session per repo** — branch mode does not protect two
  concurrent sessions sharing a checkout. `/leash-finish-work` proves
  the merge and lands on `merge_target` (never the base). Tracked
  changes block start/finish; untracked scratch files only warn.

Example:
```yaml
# .harness/branches.yaml
base: main
merge_target: develop
workflow: branch          # single branch per session
```

### Multi-root workspaces (several repos, one session)

All harness CLIs take `--repo-root`. In a multi-root workspace, ALWAYS
pass it — the CLIs mechanically refuse to guess when they can detect
the layout (sibling leash-managed repos, or a workspace folder with
child repos) and list the candidates; layouts spanning unrelated
parent folders are not detectable, which is why the explicit flag is
the rule, not the fallback. The write gate judges every edit by the
repo that owns the target file, so sibling leash-managed repos are
protected too; repos without `.harness/` are never touched.
Requirement: the session must be rooted in a leash-bootstrapped repo
(its hook wiring serves the whole workspace); keep harnesses aligned
with `/leash-update`.

**Migration note:** update the harness (`/leash-update`) BEFORE adding
`workflow:` to `.harness/branches.yaml` — older harness scripts hard-fail
on unknown keys.

## Antagonist critics on specs and plans (opt-in)

Bootstrap can enable an adversarial review step: at the end of every spec
and every plan creation — before the document reaches you for review —
the session agent dispatches one `antagonist-critic` subagent per model
listed in `.harness/critics.json` (e.g. Opus and Fable), each prompted
solely to refute the document. The agent fixes what it can and presents
you the refined document plus a criticism → response summary.

- **Configure:** answer yes to the bootstrap interview's antagonist-critics
  question and pick the critic models, or hand-write
  `.harness/critics.json`: `{"models": ["opus", "fable"]}`.
- **Disable:** delete `.harness/critics.json` — it is the single source of
  truth; the `critic_reminder` hook and the AGENTS.md protocol both defer
  to it.
- **Honest scope:** the hook mechanically injects a reminder after every
  spec/plan write; running the critics is protocol (one round per
  presented version), not a hard gate. If every critic dispatch fails, the
  agent must tell you no adversarial review ran.

## Updating a bootstrapped project

Skills and agents update with the plugin automatically; the *copied*
layer (`scripts/harness/`, `docs/task-schema.md`, `docs/plan-template.md`,
the pre-commit hook) does not. A plugin-level `SessionStart` hook
(`scripts/update_check.py`) compares the project's `.harness/leash.json`
stamp (version + file-hash manifest, written by init) against the
installed plugin version and warns when the project is stale — including
projects bootstrapped before the stamp existed.

Run `/leash-update` to apply: intact copies are overwritten, new files
are added, and missing hook entries are merged (additively) into
`.claude/settings.json`. Files you edited locally are **refused** with a
diff — override one at a time with `--force <relpath>`. `CLAUDE.md` and
`AGENTS.md` are never touched; the report points at the CHANGELOG
entries between your version and the plugin's for anything worth porting
by hand. Review `git diff` and commit the result.

## Trust model

Be precise about what the harness enforces and what it only assists:

- **Enforced.** A harness task's checkbox is ticked only by `run_task.py`
  after its `verify` command exits 0. `recheck_plan.py` re-runs the `verify`
  of every ticked harness task — run it in CI (see
  [templates/ci-snippet.md](templates/ci-snippet.md)) and/or as the opt-in
  pre-commit hook, and a checkbox flipped by hand without the work done is
  rejected. A task heading with no `task-meta` block is human-run and not
  machine-checked. **Worktree leash:** the PreToolUse gate denies writes
  whose target is in the main worktree; bypass requires editing/removing the
  hook line in `.claude/settings.json` (a visible audit event).
- **By convention only.** `touches` is self-reported: the harness does not yet
  check that a task modified *only* its declared files, so the parallel-safety
  of `plan_schedule.py` depends on `touches` being accurate. Verifying it
  without false positives needs its own design — tracked as a follow-up.
  **Worktree leash:** `Bash` is outside the gate matcher (so
  `/leash-start-work` can run `git worktree add` and the one-shot escape can
  be authorized); a determined session could `> file` into the main tree. The
  one-shot escape is itself an audited, deliberate convention.
- **Escape hatch.** `cycle_done.py --force -m <reason>` closes a cycle past
  failing gates and appends an audit line to `.harness/exceptions.log`. It
  bypasses `cycle_done`'s own gate check only — it does not disable
  `recheck_plan` running in CI or the pre-commit hook. **Worktree leash:**
  `python -m scripts.harness.allow_main_write "<reason>"` authorizes a single
  main-tree write and logs it to `.harness/exceptions.log` (same pattern as
  `cycle_done --force`).

## Validate the harness

```
python scripts/smoke_e2e.py
```

Builds a throwaway repo and drives the whole loop end to end in ~5s. Runs in CI
on every push.

## Releasing

Cutting a release — lockstep version bump (`pyproject.toml` +
`.claude-plugin/plugin.json`), the CHANGELOG convention, and the merge +
cleanup flow — is documented in [docs/RELEASING.md](docs/RELEASING.md).
