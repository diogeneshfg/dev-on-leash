# Antagonist critics on spec/plan completion — design

**Date:** 2026-07-22
**Status:** approved; revised after antagonist-critic round (2× Opus, 2026-07-22)

## Problem

Specs and plans are the highest-leverage artifacts in the dev-on-leash flow — an
error there multiplies through every implementation task. Today, before
execution, a plan gets the `plan-reviewer` agent's **schema audit** (task-meta
structure, verify commands) plus the session agent's self-review and the user.
Nothing performs an adversarial **content** critique — false premises, missing
scope, ignored alternatives — and the session agent is structurally biased
toward its own design. Extending `plan-reviewer` was considered and rejected:
schema auditing is mechanical and always-on; adversarial critique is
judgment-heavy, opt-in, runs on different (superior) models, and applies to
specs as well as plans.

## Feature

An **opt-in** capability configured during bootstrap: at the end of every spec
creation and every plan creation, **before** presenting the document to the user
for review, the session agent dispatches antagonist critic subagents in
parallel — one per model configured at bootstrap (recommended two, e.g. Opus
and Fable). Each critic's sole job is to refute the document. The session agent
resolves what it can, and presents the user with the refined document plus a
summary: criticism → what was fixed / why it was not.

**Honest framing:** the hook layer guarantees the *reminder* is injected after
every spec/plan write; it does not and cannot guarantee the critics run. The
trigger ("document complete", "one round per presented version") is model
judgment bound by the AGENTS.md protocol. This is deliberately advisory —
resolve-then-justify, not a gate — and is therefore weaker than the worktree
gate or `cycle_done`. Accepted trade-off; the hard-gate variant was rejected as
disproportionate (see Out of scope).

## Decisions (from interview + critic round)

- **Mechanism:** hook-injected reminder + prose protocol.
- **Models:** chosen by the user at bootstrap from a hand-maintained list of
  top-tier models (`opus`, `fable`), default both, minimum one — an empty
  selection is treated as opting out. The list lives in the bootstrap skill
  with a maintenance note to extend it when new top-tier models ship. No
  automatic tier ordering or session-model comparison is attempted (there is
  no reliable way to know the session model at bootstrap). Caveat, stated in
  the rendered prose: if the session runs on the same model as a critic, the
  independence benefit shrinks to fresh-context adversarial framing.
- **Single source of truth:** `.harness/critics.json`. On/off and model list
  live there only. The AGENTS.md block and the hook both defer to it — no
  `{{CRITIC_MODELS}}` placeholder, so hand-edits to the config never drift
  from the prose.
- **Effect:** resolve-then-justify. The session agent fixes every criticism it
  can and justifies the rest to the user. Not a hard gate.
- **Trigger:** once per presented version — when the document is complete and
  before user review. Substantial post-critique edits re-trigger; the
  resolution edits themselves do not. The hook re-fires on resolution edits
  too (it is stateless); its reminder text therefore includes "if the critics
  already ran for the version being presented, do not re-dispatch".

## Components

### 1. Bootstrap interview item 13 (`skills/bootstrap-dev-leash/SKILL.md`)

`AskUserQuestion` yes/no: "Enable antagonist critics on specs and plans?"
If yes, a second `AskUserQuestion` (multiSelect) listing the top-tier models
(`opus`, `fable`), defaulting to both selected. Zero models selected = treated
as "no". Feeds:

- keep or drop `OPTIONAL:ANTAGONIST_CRITICS` in `AGENTS.md.tmpl`
- write or skip `.harness/critics.json`

Nothing else is conditional: the hook registration ships unconditionally in
`settings.json.tmpl` (see component 6) and is inert without the config file.

### 2. `.harness/critics.json` (target project)

Written by bootstrap when the user opts in:

```json
{"models": ["opus", "fable"]}
```

Absence of the file = feature off. `models` must be a non-empty list of
strings. Hand-editable, like `.harness/gates`. Committed to the repo (it is
project configuration, not runtime state — verified compatible with the
bootstrap `.gitignore` guidance, which ignores only `exceptions.log`,
`allow-main-write`, and `.worktrees/`).

### 3. `scripts/harness/critic_reminder.py` (agnostic layer)

A `PostToolUse` hook for `Edit|Write|MultiEdit|NotebookEdit` (same tool set as
the existing worktree gate — `MultiEdit` on a plan must not slip through).
Behavior:

- Read the hook JSON from stdin; extract `tool_input.file_path`.
- **Path matching is component-aware, not substring/glob on the raw string**
  (same rationale as `session_gate.py`): resolve the path with `pathlib`,
  split into components, and match a `.md` file whose components contain the
  consecutive pair `("docs", "plans")` or contain a `specs` directory
  component. Component matching is what makes worktree-nested paths
  (`.worktrees/<slug>/docs/plans/x.md`) and Windows backslash paths work.
  Exclude paths containing `node_modules`, `.venv`, `site-packages`, or a
  `fixtures` component (vendored/test content must not fire the reminder).
- If matched AND `.harness/critics.json` exists and parses with a non-empty
  `models` list: emit `hookSpecificOutput.additionalContext` reminding the
  agent that this file is a spec/plan and that, before presenting it to the
  user for review, it must dispatch one antagonist critic per configured model
  per the AGENTS.md protocol — one round per presented version; if the
  critics already ran for this version, do not re-dispatch.
- The config is discovered by walking the written file's ancestors for
  `.harness/critics.json`, bounded at the first ancestor holding a `.git`
  entry (dir or worktree-file) — equivalent to the repo toplevel without
  invoking git, and immune to a stray `~/.harness` above the repo. Linked
  worktrees resolve to their own checkout, which shares the committed
  config.
- Malformed `critics.json` or empty `models`: treat as off, but emit a
  one-line warning in the context so it gets fixed. Fail-open is accepted: a
  PostToolUse reminder cannot block by design, and the warning is the best
  available signal.
- Always exit 0, including on internal error. The hook informs; it never
  blocks.

### 4. `agents/antagonist-critic.md` (plugin agent)

Read-only tools (Read, Grep, Glob). Fixed adversarial prompt: the critic's job
is to **refute** the document it is pointed at — false premises (checked
against the actual repository, not just internally), missing scope, ambiguity,
ignored risks and alternatives, unjustified complexity, untestable
requirements. It must not praise; if it finds nothing in some area, it must
explicitly state it tried and failed to refute. Output: a numbered list of
objections, each with a severity (blocking / significant / minor) and a
concrete reason citing evidence.

### 5. `OPTIONAL:ANTAGONIST_CRITICS` block (`templates/AGENTS.md.tmpl`)

Prose protocol, no placeholders:

- **Source of truth:** `.harness/critics.json`. If the file is absent or has
  no models, this protocol is disabled — the prose defers to the config, so
  deleting the file fully disables the feature even though this block remains
  rendered.
- **When:** at the end of every spec creation and every plan creation, before
  asking the user to review. One round per presented version; substantial
  edits after a critique round re-trigger it; resolution edits do not.
- **How:** dispatch one `antagonist-critic` subagent per model listed in the
  config, in parallel, via the Agent tool `model` override, pointing each at
  the document path.
- **Failure:** if a critic dispatch fails (model unavailable / not entitled),
  say so in the summary and proceed with the critics that ran. If **all**
  fail, tell the user explicitly that no adversarial review ran — never
  present the document as if it had been critiqued.
- **Resolution:** fix every objection you can in the document; for each one
  you do not fix, record the justification. Present the user the refined
  document plus the criticism → response summary.

### 6. Hook registration (`templates/settings.json.tmpl`)

The `PostToolUse` hook entry for `critic_reminder.py` is added
**unconditionally** to the template — `settings.json.tmpl` has no
optional-block mechanism (HTML-comment markers are illegal in JSON, and the
bootstrap skill explicitly renders it by placeholder substitution only).
Conditionality lives entirely in the config file: without
`.harness/critics.json` the hook is a fast no-op. This also means toggling the
feature later never requires touching `settings.json`.

### 7. Init-script per-file harness copy (`scripts/init.sh`, `scripts/init.ps1`)

Today both init scripts skip the entire `scripts/harness/` directory when it
exists, so re-bootstrap could never deliver `critic_reminder.py` to existing
projects. Change both scripts to copy `scripts/harness/` **per file,
add-only**: copy each file that does not exist at the destination; never
overwrite an existing file. This preserves the no-clobber guarantee while
making re-bootstrap deliver new harness files. Add a migration note to the
bootstrap skill (mirroring the existing SessionStart-removal note): re-running
bootstrap installs the critic hook into `settings.json` and offers interview
item 13.

## Data flow

1. Bootstrap: user opts in, picks ≥1 model → `.harness/critics.json` written,
   AGENTS.md block kept, hook present in rendered settings (always).
2. Session writes/edits a spec or plan file (typically inside a
   `.worktrees/<slug>/` checkout, since the worktree gate denies main-tree
   writes) → hook fires → reminder injected.
3. Document complete → agent dispatches one critic per configured model, in
   parallel.
4. Agent merges objections, edits the document to resolve what it can (these
   edits re-fire the stateless hook reminder; the reminder's own text and the
   protocol's one-round rule tell the agent not to re-dispatch), records
   justifications for the rest.
5. Agent presents to the user: refined document + criticism/response summary.

## Scope note: where specs live

`docs/plans/` is created by the init script, so the plan trigger works in
every bootstrapped project. There is no universal spec-directory convention —
the spec trigger matches any `*.md` under a `specs/` component and therefore
fires for projects using a spec workflow (e.g. superpowers' brainstorming,
which writes `docs/superpowers/specs/`). Projects with no spec workflow simply
never exercise that half of the trigger; the plan half still covers them. The
rendered AGENTS.md block states this.

## Error handling

- `critics.json` missing → feature off (hook emits nothing).
- `critics.json` malformed or `models` empty → treated as off + warning in
  context (accepted fail-open; see component 3).
- A critic model unavailable at dispatch → report in the summary, proceed
  with the critics that ran; if none ran, say so explicitly (protocol,
  component 5).
- Hook always exits 0; a crash inside the hook must not block the write.

## Cost

Accepted and bounded by design: the feature is opt-in, runs one round per
presented version (not per edit), and the user controls the model list —
trimming `critics.json` to one model halves the cost. No automatic budget is
imposed.

## Testing (TDD, pytest)

- `critic_reminder.py` unit tests: plan path matches; spec path matches;
  worktree-nested path matches; Windows-style backslash path matches;
  `node_modules`/`fixtures` paths do not; non-spec path does not; config
  absent → no output; config malformed → warning; `models: []` → warning;
  valid case → JSON with additionalContext naming the models; exit 0 in every
  case including internal error (feed garbage stdin).
- Init-script tests: per-file copy adds a missing harness file without
  touching existing ones (both `.sh` and `.ps1` paths, following existing
  init-script test patterns).
- Template render tests: `OPTIONAL:ANTAGONIST_CRITICS` block kept on opt-in /
  fully removed on opt-out; rendered `settings.json.tmpl` output parses as
  valid JSON once placeholders are substituted with representative values
  (this closes the existing gap where the template is only ever treated as
  text).
- Agent-definition test: `antagonist-critic.md` frontmatter passes the
  existing `test_agents.py` conventions.
- Dogfood: this spec itself was reviewed by two Opus antagonist critics; the
  round surfaced 2 blocking and 9+ significant/minor defects that were folded
  into this revision. Repeat on the implementation plan.

## README

Add a section documenting the feature: what it does, how bootstrap enables it,
the `.harness/critics.json` format, and how to disable (delete the file — the
single source of truth). Part of the plan, not a follow-up.

## Out of scope

- Hard gating (pre-commit/CI evidence of critique) — rejected as
  disproportionate; the feature is resolve-then-justify by design, and the
  advisory nature is stated honestly rather than dressed up as mechanical.
- Critiquing implementation diffs (existing review agents cover that).
- Dynamic model-tier discovery or session-model comparison — the top-tier
  model list is maintained by hand in the bootstrap skill.
- Persistent per-version critique state (what "one round per version" would
  need to become mechanical) — honor system accepted.
