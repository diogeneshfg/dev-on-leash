# Architecture Leash — Design

**Status:** approved (brainstorm complete), pending implementation plan
**Date:** 2026-05-25
**Project:** dev-on-leash

## Problem

The `dev-on-leash` harness today enforces *behavioral* discipline: TDD evidence,
isolation review, per-task `verify` commands, re-checkable ticked checkboxes,
`.harness/gates` at cycle close. None of it knows or enforces anything about
the project's **architecture** — what layers exist, which depend on which, what
shape a use-case or entity is allowed to take, what's forbidden where.

We want to extend the leash to architecture so a user can declare a style
("Clean Architecture + OOP", or a custom one) and the harness will (a)
mechanically gate violations it can prove (dependency direction, forbidden
imports, file-layout) and (b) flag judgment-level violations (OOP idioms, "is
this really a use case?") via a project-local reviewer agent.

## Decisions locked during brainstorm

1. **Layered enforcement.** Mechanical rules become hard gates wired into
   `.harness/gates`. Judgment rules become a new project-local
   `architecture-reviewer` agent. Mechanical rules block CI; the reviewer is
   advisory.
2. **New skill, re-runnable.** A new top-level skill,
   `compose-architecture-leash`, runs after `bootstrap-dev-leash`. It is
   re-runnable to incorporate new architectural aspects as the project matures.
3. **Free-form prose + AI extraction.** The user describes their architecture
   in plain English. A subagent extracts a structured `architecture.yaml`. The
   user confirms before anything is written.
4. **Re-run mode picker.** Each re-run asks the user to pick **add** /
   **revise** / **re-describe**. Each has its own flow (Section 6).
5. **Language coverage v1.** Python and JS/TS get real adapters
   (`import-linter`, `dependency-cruiser`). Other languages get a generic
   grep-based fallback. More adapters are post-v1.
6. **Approach A — peer artifact.** Architecture spec lives at
   `.harness/architecture.yaml`. It is NOT embedded in `task-meta` (rejected
   Approach B). It is NOT advisory-only (rejected Approach C). It composes
   additively with the existing harness.
7. **Dogfood is load-bearing.** Every feature in this design must be applied
   to dev-on-leash itself before merge (see Section 7 and the saved
   `feedback-dogfood` memory).

## Non-goals (v1)

- Cross-layer call-shape rules requiring AST analysis (Java-style "use cases
  must call repositories through interfaces"). Lives in the reviewer agent for
  v1.
- Auto-detection of architecture from existing code. v1 always asks.
- Drift detection in `cycle_done` (assert generated files still match the YAML).
  Easy to add later; not in v1.
- Java/Kotlin/Go/Rust adapters. They get the generic grep fallback.
- A web UI / preview tool.

---

## Section 1 — `architecture.yaml` schema

`.harness/architecture.yaml` is the source of truth: hand-editable,
version-controlled, read by the compiler (for gates) and the reviewer agent
(for judgment).

Top-level keys:

- **`version`** (required, int) — schema version. v1 = `1`.
- **`style`** (free-text) — label like `"Clean Architecture + OOP"`. Shown to
  humans; injected into the reviewer agent's system prompt for context.
- **`layers`** (list) — named buckets with file-path globs. A file's layer is
  determined by glob match.
- **`allowed_dependencies`** (list) — directed allowlist (`from -> to`). Every
  edge **not listed** is forbidden. Compiled to import-linter contracts (Python)
  or dependency-cruiser rules (JS/TS) or a generic grep fallback.
- **`patterns`** (list) — forbidden / required imports or substrings scoped per
  layer. Each compiles to a single grep-based gate script.
- **`review_rules`** (list) — judgment-level rules (OOP idioms, "use cases are
  classes", "Tell-Don't-Ask"). NOT compiled to gates — they live only in the
  reviewer agent's system prompt.

After `version: 1`, every other key is optional. A minimal valid spec can
declare just `layers` + `allowed_dependencies`.

A small validator (`scripts/harness/validate_architecture.py`) checks the file's
schema; `cycle_done.py` calls it before any architecture gate runs so a YAML
typo cannot silently disable enforcement.

### Concrete sketch

```yaml
version: 1
style: "Clean Architecture + OOP"
layers:
  - { name: domain,         paths: [src/myapp/domain/**] }
  - { name: application,    paths: [src/myapp/application/**] }
  - { name: infrastructure, paths: [src/myapp/infrastructure/**] }
allowed_dependencies:
  - { from: application,    to: [domain] }
  - { from: infrastructure, to: [application, domain] }
patterns:
  - id: domain_pure
    layer: domain
    forbidden_imports: [django, sqlalchemy, requests]
    reason: "Domain must be framework-independent."
review_rules:
  - id: use_cases_are_classes
    applies_to: application
    rule: "Each use case is a class exposing a single public `execute` method."
```

Every rule has a stable `id`. The compiler tags every generated gate line with
`# arch-leash:<id>` so removed rules can be cleanly pruned on the next compile.

---

## Section 2 — Skill flow on first run

`compose-architecture-leash` runs inside the target project (same convention as
`bootstrap-dev-leash`). First-run flow:

1. **Precondition check.** Verify `CLAUDE.md` + `AGENTS.md` exist (bootstrap
   was done) and that `.harness/architecture.yaml` does **not** yet exist. If
   it does, the skill switches to re-run mode (Section 6).
2. **Detect language stack.** Read `.claude/settings.json` and/or
   `.harness/gates` to infer Python / JS-TS / mixed / other. This decides which
   adapter the compiler will use. No user question needed — bootstrap already
   captured this.
3. **Prose interview.** Single prompt: "Describe your project's architecture
   and the rules you want enforced. Layers, who depends on what, what's banned
   where, what shape use-cases/entities/etc. should take. Plain English is
   fine."
4. **Subagent extraction.** Dispatch a new subagent type
   `dev-on-leash:architecture-extractor` with:
   - the user's prose,
   - the `architecture.yaml` schema doc,
   - the project's top-level file tree (to ground layer paths in real
     directories).

   Tool grants: `Read`, `Glob`, `Grep` only. Read-only — same minimal set as
   the review agents. The extractor walks the file tree via `Glob` and is not
   permitted to write, execute, or fetch anything.

   It returns a proposed `architecture.yaml` plus a short rationale block per
   rule.
5. **Confirm-and-edit loop.** Show the user the proposed YAML + rationale.
   Three responses: **accept**, **edit** (user names the field to change,
   subagent revises, re-shows), **start over**.
6. **Write and compile.** On accept:
   - Write `.harness/architecture.yaml`.
   - Run the compiler (Section 3) to emit per-language config + grep scripts +
     append to `.harness/gates`.
   - Write `agents/architecture-reviewer.md` with the templated reviewer prompt
     (Section 4).
   - Patch `AGENTS.md` to populate the `OPTIONAL:ARCHITECTURE` block (Section
     5) — same diff-and-confirm rule as bootstrap.
7. **Report.** Concise summary of files created/changed and gates added.

The extraction step is the only model-dependent piece. Everything else is
deterministic.

---

## Section 3 — The compiler

`scripts/harness/compile_architecture.py` reads `.harness/architecture.yaml`
and emits concrete enforcement artifacts. Pure, deterministic, no model calls.
Re-runnable: every time the YAML changes, recompile.

**Inputs:** the YAML, the detected language adapter.

**Outputs (idempotent — overwrites only files it manages, never the YAML
itself):**

1. **Python adapter** (when `pyproject.toml` or `setup.py` is present):
   - Writes `.harness/importlinter.ini` with one `forbidden` contract per
     *implicit* forbidden edge (every layer pair not in
     `allowed_dependencies`). Layer modules come from `layers[].paths`.
   - Appends `python -m importlinter --config .harness/importlinter.ini` to
     `.harness/gates` if not already present.
2. **JS/TS adapter** (when `package.json` is present):
   - Writes `.harness/dependency-cruiser.json` with a `forbidden` rule array
     derived the same way.
   - Appends `npx --no -- depcruise --config .harness/dependency-cruiser.json src`
     to `.harness/gates`.
3. **Generic grep adapter** (always, for `patterns[]` and as a fallback for
   `allowed_dependencies` when no language adapter applies):
   - Writes one tiny script per pattern under `.harness/checks/pattern-<id>.sh`
     (POSIX) and `.harness/checks/pattern-<id>.ps1` (Windows). Each script
     greps the layer's path glob for the forbidden/required strings and exits
     non-zero on violation.
   - Appends each script to `.harness/gates`.
4. **Generated-by header** on every file the compiler writes:

   ```
   # GENERATED by scripts/harness/compile_architecture.py from .harness/architecture.yaml
   # Edit architecture.yaml and recompile; hand edits here will be overwritten.
   ```

   Files without that header are left alone — that's how the compiler knows
   what it owns.
5. **Gate dedup.** `.harness/gates` is append-only by convention; the compiler
   reads it first and only adds missing lines. A removed rule in YAML triggers
   removal of the matching gate line on the next compile (matched by the
   `# arch-leash:<rule-id>` trailing comment).

**When the compiler runs:** at the end of `compose-architecture-leash`, and on
demand via `python scripts/harness/compile_architecture.py`.

**Failure mode:** if a language adapter's tool isn't installed
(`import-linter`, `dependency-cruiser`), the compiler writes the config file
anyway and emits the gate line, but warns the user. The gate then fails loudly
on the next `cycle_done` until the tool is added.

The Python and JS/TS adapters are the riskiest pieces — they translate
"allowed edges" into each tool's contract language. Each gets two small e2e
tests against throwaway fixture projects (matches the existing
`scripts/smoke_e2e.py` pattern).

---

## Section 4 — The `architecture-reviewer` agent

A new agent type, **project-local** (lives at
`agents/architecture-reviewer.md` in the target repo, not the plugin),
templated by the compiler. Pattern matches the existing `isolation-reviewer` /
`plan-reviewer` / `tdd-evidence-checker`.

**Tool grants:** `Read`, `Grep`, `Glob` only. No `Bash`, no `Edit`. Same
minimal read-only set as `isolation-reviewer`.

**System prompt** is templated from `architecture.yaml` at compile time, not
read live. The agent is deterministic per spec version.

Template body (from `templates/architecture-reviewer.md.tmpl`):

```
You review code changes against this project's declared architecture: {{ style }}.

Layers:
{{ layer-table from layers[] }}

Allowed dependency edges (every other edge is forbidden):
{{ edges from allowed_dependencies[] }}

Judgment rules to enforce:
{{ review_rules[] as numbered list with id, applies_to, rule }}

For each changed file in the diff:
1. Identify which layer it belongs to (by path glob). If it doesn't match any layer, say so.
2. Flag any import or call that crosses a forbidden edge.
3. Flag any violation of the judgment rules for that layer.
4. Cite file:line for every finding.

Do not propose fixes. Do not edit code. Output PASS, or a list of findings keyed by rule id.
```

**When it runs — two integration points, neither blocking by default:**

1. **Opt-in `recheck` step:** a flag in `architecture.yaml`
   (`run_reviewer_on_recheck: true`) makes `recheck_plan.py` dispatch the agent
   on changed files. Off by default in v1; slow and model-dependent.
2. **Manual review:** the user dispatches the agent on a branch before opening
   a PR. Same posture as `requesting-code-review`. This is the recommended
   primary path.

The reviewer is **advisory**. Hard-blocking enforcement is the mechanical
gates from Section 3. This matches the "layered" choice: mechanical rules have
teeth, judgment rules have a microphone.

The compiler regenerates `agents/architecture-reviewer.md` on every recompile.
User edits are warned about.

---

## Section 5 — `AGENTS.md` integration

A new `OPTIONAL:ARCHITECTURE` block in `templates/AGENTS.md.tmpl`, placed after
the existing `DOMAIN_RULES` / `UI_RULES` blocks:

```
<!-- OPTIONAL:ARCHITECTURE -->
## Architecture

This project follows **{{ARCHITECTURE_STYLE}}**. The structured spec is in
[`.harness/architecture.yaml`](.harness/architecture.yaml) — that file is the
source of truth. The summary below is regenerated from it; do not hand-edit.

**Layers**

{{ARCHITECTURE_LAYER_TABLE}}

**Allowed dependencies**

{{ARCHITECTURE_EDGE_LIST}}

**Mechanical gates**

The following gates enforce dependency direction and forbidden patterns. They
run as part of `cycle_done` and on every push (see `templates/ci-snippet.md`):

{{ARCHITECTURE_GATE_LIST}}

**Reviewer agent**

The `architecture-reviewer` agent enforces judgment-level rules from
`review_rules[]`. Run it before opening a PR.

**Changing the architecture**

Re-run the `compose-architecture-leash` skill (modes: add / revise /
re-describe). Hand-editing this section will be overwritten on the next
compile.
<!-- /OPTIONAL:ARCHITECTURE -->
```

**Marker contract — intentionally different from DOMAIN/UI blocks.** Unlike
`DOMAIN_RULES` and `UI_RULES`, the architecture block keeps its
`<!-- OPTIONAL:ARCHITECTURE -->` markers **in the rendered AGENTS.md**. That's
because the architecture block is *regenerated* by the compiler on every YAML
change; the markers are the load-bearing anchor that lets the compiler find
its territory without fuzzy heading-matching. Domain/UI blocks are
hand-maintained after bootstrap, so their markers are noise after rendering.
The inconsistency is intentional and worth a one-line comment in the template.

**Bootstrap interaction:** `bootstrap-dev-leash` is **unchanged**. It renders
the `OPTIONAL:ARCHITECTURE` block as a stub:

> Architecture leash not yet configured — run `compose-architecture-leash` to
> set it up.

Once compose runs, that stub is replaced by the real content. This keeps
bootstrap focused (the user's earlier choice) and leaves a visible breadcrumb
in `AGENTS.md` that the architecture leash exists and is reachable.

---

## Section 6 — Re-run flow

When `.harness/architecture.yaml` already exists, the skill prompts the mode
picker:

> What do you want to do?
> - **add** — describe a new architectural aspect to layer on top
> - **revise** — change one or more existing rules
> - **re-describe** — re-extract the whole spec from a fresh description

### Mode: add

1. Prompt: *"What aspect do you want to add? Describe just the addition."*
2. Subagent extracts a **delta** only: new entries for `layers`,
   `allowed_dependencies`, `patterns`, or `review_rules`. The extractor's
   system prompt forbids modifying or removing existing entries. To make this
   stricter than a soft constraint, the subagent returns *only the new entries
   as a YAML fragment* — the skill performs the merge so the existing YAML is
   never touched by a model.
3. Show the user a YAML diff (new entries highlighted) plus rationale per
   added rule.
4. Confirm-and-edit loop (same shape as first-run Section 2 step 5).
5. On accept: merge additions into `architecture.yaml`, recompile, re-render
   the AGENTS.md block. Report what changed.

### Mode: revise

1. Show the current `architecture.yaml` as a numbered list of rules, each with
   its stable `id`.
2. Prompt: *"Which rule(s) by id, and what should change?"*
3. Subagent rewrites just those entries; everything else preserved
   byte-for-byte.
4. Confirm-and-edit loop, then write / compile / re-render.

### Mode: re-describe

1. Same prose interview as first-run.
2. Subagent re-extracts a full spec.
3. Show a **side-by-side diff** between old and new YAML, organized by rule
   `id` — added, removed, modified — with rationale per change.
4. Confirm-and-edit loop. The user can accept all, accept selectively (by id),
   or start over.
5. On accept: the new YAML replaces the old. Old YAML is saved to
   `.harness/architecture.yaml.bak-<timestamp>` (one most-recent backup only;
   git is the real history). Recompile, re-render.

**Invariants across all three modes:**

- Compiler only re-runs if the YAML actually changed (no spurious rewrites).
- Every gate line and generated config traces back to a YAML rule id via the
  `# arch-leash:<id>` comment. Orphaned gate lines from removed rules are
  pruned on compile.
- `architecture-reviewer.md` is fully regenerated each compile — no merging.
- `OPTIONAL:ARCHITECTURE` block in `AGENTS.md` is fully regenerated between
  its markers.
- Same diff-and-confirm rule as bootstrap applies whenever the skill is about
  to overwrite a file the user might have hand-edited.

---

## Section 7 — Testing, dogfood, and file inventory

### Tests that ship with the feature

Three layers, all CI-executable, no Claude Code required:

1. **Unit — compiler determinism.** Given a fixed `architecture.yaml` input,
   `compile_architecture.py` produces byte-identical outputs across runs.
   Covers all three adapters (Python, JS/TS, generic) with small fixtures in
   `tests/fixtures/architecture/`.
2. **Unit — gate behavior.** For each generated gate kind, a known-bad fixture
   project violates it and the gate exits non-zero; a known-good fixture
   passes. One test per rule kind: forbidden-edge (Python), forbidden-edge
   (JS/TS), forbidden-import grep, layer-path glob mismatch.
3. **E2E — extends `scripts/smoke_e2e.py`.** Builds a throwaway project, runs
   the existing harness loop, drops in a synthetic `architecture.yaml`, runs
   the compiler, runs `cycle_done`, asserts the new gates fire when the
   throwaway has a deliberate violation and pass when it doesn't. ~10s total
   target.

The reviewer agent is NOT unit-tested for output quality (model-dependent,
brittle). It gets a smoke test only: given a fixture spec and a fixture diff,
the agent runs, completes without tool errors, and produces output matching a
structural schema (PASS or a list of findings with `rule_id` + `file:line`).
Output quality is validated through dogfood, not assertions.

### Dogfood task (load-bearing)

A dedicated task at the end of the implementation plan, harness-verifiable:

- **Declare dev-on-leash's own architecture** by running
  `compose-architecture-leash` on this repo. Real prose interview, real
  extraction, real confirm step. Commit `.harness/architecture.yaml`,
  `.harness/checks/`, `.harness/importlinter.ini`,
  `agents/architecture-reviewer.md`, and updated `AGENTS.md`.
- **Verify gates fire on a known-bad scenario.** Craft a deliberate violation
  on a throwaway branch (e.g., `import requests` inside `scripts/harness/`).
  `cycle_done` must reject it.
- **Exercise re-run modes.** Use `add` to layer one new rule, use `revise` to
  change one rule. Both produce a clean diff and survive recompile.
- **Run the reviewer agent on a real PR.** Dispatch the architecture-reviewer
  against the most recent merged branch (`harness-hardening`) and capture its
  findings. If the agent produces nonsense on real dev-on-leash code, the
  prompt template needs work before merge.

The `verify` command on the dogfood task is a script that asserts the
expected files exist and the deliberate-violation gate exits non-zero. The
task is machine-checked, not self-attested.

### File inventory

**Plugin (this repo) — new or modified:**

- `skills/compose-architecture-leash/SKILL.md` — new
- `scripts/harness/compile_architecture.py` — new
- `scripts/harness/validate_architecture.py` — new
- `agents/architecture-extractor.md` — new (the extraction subagent)
- `templates/architecture.yaml.tmpl` — new (minimal starter)
- `templates/architecture-reviewer.md.tmpl` — new (templated reviewer prompt)
- `templates/AGENTS.md.tmpl` — modified (add `OPTIONAL:ARCHITECTURE` block)
- `tests/fixtures/architecture/` — new fixtures
- `tests/test_compile_architecture.py` — new
- `scripts/smoke_e2e.py` — modified (e2e step)

**Target projects after the skill runs:**

- `.harness/architecture.yaml` — source of truth, hand-editable
- `.harness/checks/pattern-*.sh|ps1` — generated grep gates
- `.harness/importlinter.ini` (Python) or `.harness/dependency-cruiser.json`
  (JS/TS) — generated configs
- `.harness/gates` — appended with `# arch-leash:<id>` trailing comments
- `agents/architecture-reviewer.md` — generated, project-local
- `AGENTS.md` — `OPTIONAL:ARCHITECTURE` block populated

---

## Open questions for the implementation plan

These were raised during brainstorm and intentionally left for plan-time:

- **Extraction agent type.** Is `architecture-extractor` a registered agent
  type in the plugin's `agents/` directory, or an inline `Agent` call with a
  system prompt? Registered is more discoverable and reusable; inline is less
  to wire up. Lean: registered, to match `isolation-reviewer` etc.
- **`add` mode strictness.** The design (Section 6) commits to "subagent
  returns only the YAML fragment, skill performs the merge." If during
  implementation that turns out awkward, fall back to "subagent returns full
  YAML, post-validator asserts existing entries are byte-identical." Either is
  acceptable; the stricter path is preferred.
- **Reviewer tool grants.** Confirmed `Read`/`Grep`/`Glob`. If the agent needs
  `git diff` output and it's not feasible to feed it via stdin, revisit.
