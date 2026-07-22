# Antagonist critics on spec/plan completion — design

**Date:** 2026-07-22
**Status:** approved (pending antagonist-critic review)

## Problem

Specs and plans are the highest-leverage artifacts in the dev-on-leash flow — an
error there multiplies through every implementation task. Today the only review
before execution is the session agent's own self-review plus the user. The
session agent is structurally biased toward its own design.

## Feature

An **opt-in** capability configured during bootstrap: at the end of every spec
creation and every plan creation, **before** presenting the document to the user
for review, the session agent dispatches **two antagonist critic subagents in
parallel**, each running on a superior model chosen by the user at bootstrap
(e.g. Opus and Fable). Each critic's sole job is to refute the document. The
session agent resolves what it can, and presents the user with the refined
document plus a summary table: criticism → what was fixed / why it was not.

## Decisions (from interview)

- **Mechanism:** mechanical hook reminder + prose protocol (hook + prosa).
- **Models:** chosen by the user at bootstrap from a fixed list of superior
  models (`opus`, `fable`); default is both. Rule: only models of a tier equal
  to or above the session model qualify. The list lives in the bootstrap skill
  with a maintenance note to extend it when new tiers ship.
- **Effect:** resolve-then-justify. The session agent fixes every criticism it
  can and justifies the rest to the user. Not a hard gate.
- **Trigger:** once per presented version — when the document is complete and
  before user review. Substantial post-critique edits re-trigger; the
  resolution edits themselves do not (protocol: one round per presented
  version).

## Components

### 1. Bootstrap interview item 13 (`skills/bootstrap-dev-leash/SKILL.md`)

`AskUserQuestion` yes/no: "Enable antagonist critics on specs and plans?"
If yes, a second `AskUserQuestion` (multiSelect) listing the superior models
(`opus`, `fable`), defaulting to both selected. Feeds:

- keep or drop `OPTIONAL:ANTAGONIST_CRITICS` in `AGENTS.md.tmpl`
- keep or drop the PostToolUse hook block in `settings.json.tmpl`
- write or skip `.harness/critics.json`
- `{{CRITIC_MODELS}}` placeholder value

### 2. `.harness/critics.json` (target project)

Written by bootstrap when the user opts in:

```json
{"models": ["opus", "fable"]}
```

Absence of the file = feature off. Hand-editable, like `.harness/gates`.
Committed to the repo (it is project configuration, not runtime state — do NOT
add it to the `.gitignore` runtime patterns).

### 3. `scripts/harness/critic_reminder.py` (agnostic layer)

A `PostToolUse` hook for `Write|Edit`, copied by the init script like the rest
of `scripts/harness/`. Behavior:

- Read the hook JSON from stdin; extract `tool_input.file_path`.
- Match against spec/plan paths: `docs/plans/*.md` and any `*.md` under a
  `specs/` directory (covers `docs/superpowers/specs/`).
- If matched AND `.harness/critics.json` exists and parses: emit
  `hookSpecificOutput.additionalContext` reminding the agent that this file is
  a spec/plan and that, before presenting it to the user for review, it must
  dispatch the antagonist critics (naming the configured models) per the
  AGENTS.md protocol — one round per presented version.
- Malformed `critics.json`: treat as off, but emit a one-line warning in the
  context so it gets fixed.
- Always exit 0. The hook informs; it never blocks.

### 4. `agents/antagonist-critic.md` (plugin agent)

Read-only tools (Read, Grep, Glob). Fixed adversarial prompt: the critic's job
is to **refute** the document it is pointed at — false premises, missing scope,
ambiguity, ignored risks and alternatives, unjustified complexity, untestable
requirements. It must not praise; if it finds nothing, it must explicitly state
it tried and failed to refute. Output: a numbered list of objections, each with
a severity (blocking / significant / minor) and a concrete reason.

### 5. `OPTIONAL:ANTAGONIST_CRITICS` block (`templates/AGENTS.md.tmpl`)

Prose protocol with `{{CRITIC_MODELS}}` placeholder:

- **When:** at the end of every spec creation and every plan creation, before
  asking the user to review. One round per presented version; substantial
  edits after a critique round re-trigger it.
- **How:** dispatch two `antagonist-critic` subagents in parallel, one per
  configured model (via the Agent tool `model` override), pointing each at the
  document path.
- **Resolution:** fix every objection you can in the document; for each one
  you do not fix, record the justification. Present the user the refined
  document plus the criticism → response summary.

### 6. Hook registration block (`templates/settings.json.tmpl`)

An optional block (same marker convention as AGENTS.md optional blocks, adapted
to JSON via bootstrap-side handling) registering
`critic_reminder.py` as a `PostToolUse` hook matching `Write|Edit`. Kept or
removed by bootstrap per the item-13 answer.

## Data flow

1. Bootstrap: user opts in, picks models → `.harness/critics.json` written,
   AGENTS.md block kept and rendered, settings hook registered.
2. Session writes/edits a spec or plan file → hook fires → reminder injected.
3. Document complete → agent dispatches the two critics in parallel.
4. Agent merges objections, edits the document to resolve what it can (these
   edits re-fire the hook reminder, but the protocol's one-round-per-version
   rule means no re-critique), records justifications for the rest.
5. Agent presents to the user: refined document + criticism/response table.

## Error handling

- `critics.json` missing → feature silently off (hook emits nothing).
- `critics.json` malformed → treated as off + warning in context.
- A critic model unavailable at dispatch → report it in the summary and
  proceed with the critic(s) that ran.
- Hook always exits 0; a crash inside the hook must not block the Write/Edit.

## Testing (TDD, pytest)

- `critic_reminder.py` unit tests: plan path matches, spec path matches,
  non-spec path does not, config absent → no output, config malformed →
  warning, valid case → JSON with additionalContext naming the models,
  exit 0 in every case including internal error.
- Bootstrap render tests (following existing template-render test patterns):
  optional block kept + `{{CRITIC_MODELS}}` substituted; block fully removed
  on opt-out; settings hook block kept/removed.
- Dogfood: enable on dev-on-leash itself and verify the critics catch a real
  issue in a real spec/plan before merge.

## README

Add a section documenting the feature: what it does, how bootstrap enables it,
the `.harness/critics.json` format, and how to disable (delete the file /
remove the hook). Part of the plan, not a follow-up.

## Out of scope

- Hard gating (pre-commit/CI evidence of critique) — rejected as
  disproportionate; the feature is resolve-then-justify by design.
- Critiquing implementation diffs (existing review agents cover that).
- Dynamic model-tier discovery — the superior-model list is maintained by hand
  in the bootstrap skill.
