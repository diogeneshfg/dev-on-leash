---
name: compose-architecture-leash
description: Use to declare a project's architecture and turn it into enforced guard-rails. Interviews the user in prose, extracts a structured .harness/architecture.yaml via subagent, compiles it into mechanical gates (import-linter for Python, dependency-cruiser for JS/TS, grep fallback elsewhere) and a project-local architecture-reviewer agent. Re-runnable (add / revise / re-describe).
---

# compose-architecture-leash

This skill runs **inside a target project** (not inside the dev-on-leash
plugin repo). The user invokes it after `bootstrap-dev-leash` has been run.
It declares an architecture and turns it into enforced guard-rails.

## When to use

The user wants to add or change architectural enforcement on top of the
existing harness — phrasings like "put the architecture on leash", "set up
clean architecture rules", "add architecture guard-rails", "the
architecture changed, refresh the leash".

## Precondition

Refuse to run if `CLAUDE.md` or `AGENTS.md` is missing from the target —
that means `bootstrap-dev-leash` was not run. Tell the user to run
bootstrap first.

If `.harness/architecture.yaml` already exists, switch to **re-run mode**
(see the re-run section).

## Step 1 — Detect language stack

Read `.claude/settings.json`'s allowlist and `.harness/gates` to infer the
project's stack:

- `pyproject.toml` or `setup.py` present → Python adapter will fire.
- `package.json` present → JS/TS adapter will fire.
- Both: both fire.
- Neither: only the generic grep adapter fires.

No user question. Bootstrap already captured the stack.

## Step 2 — Prose interview

Ask the user a single open question:

> "Describe your project's architecture and the rules you want enforced.
> Layers, who depends on what, what's banned where, what shape
> use-cases/entities/etc. should take. Plain English is fine — be as long
> or as short as you want."

Do NOT offer multiple-choice presets. The declaration model is free-form
prose by design (see spec).

## Step 3 — Subagent extraction

Dispatch the plugin subagent `dev-on-leash:architecture-extractor` with:

- the user's prose,
- a short reminder of the `architecture.yaml` schema (version, style,
  layers, allowed_dependencies, patterns, review_rules),
- the target project's top-level file tree (or instruction to discover it
  via `Glob`).

The subagent returns a proposed YAML body plus a "Rationale" section.

## Step 4 — Confirm-and-edit loop

Show the user the proposed YAML + rationale. Offer three responses:

- **accept** → proceed to Step 5.
- **edit** → ask which field to change, dispatch the extractor again with
  the user's correction and the previous proposal as context, re-show.
- **start over** → re-ask the prose interview.

## Step 5 — Write, compile, re-render AGENTS.md

Once accepted:

1. Write the YAML to `.harness/architecture.yaml`.
2. Run `python scripts/harness/compile_architecture.py` in the target.
   This emits `.harness/checks/pattern-*.py`, `.harness/importlinter.ini`
   (if Python), `.harness/dependency-cruiser.json` (if JS/TS), and appends
   `# arch-leash:<id>`-tagged gate lines to `.harness/gates`.
3. Replace the body of the `OPTIONAL:ARCHITECTURE` block in `AGENTS.md`
   between its markers with a human-readable summary derived from the
   YAML: `{{ARCHITECTURE_STYLE}}`, a Markdown table of layers, a bullet
   list of allowed edges, a bullet list of the new gates, and a pointer to
   `architecture.yaml` as the source of truth. Keep the
   `<!-- OPTIONAL:ARCHITECTURE -->` markers in place — the compiler
   identifies its territory by them.
4. Write the project-local reviewer agent to `agents/architecture-reviewer.md`
   from `templates/architecture-reviewer.md.tmpl`, substituting
   `{{ARCHITECTURE_STYLE}}`, `{{ARCHITECTURE_LAYER_TABLE}}`,
   `{{ARCHITECTURE_EDGE_LIST}}`, `{{ARCHITECTURE_REVIEW_RULES}}`.
5. Apply the same diff-and-confirm rule as bootstrap whenever about to
   overwrite a file that may have been hand-edited.

## Step 6 — Report

Summarize, in three or four lines:

- Files created / modified.
- Number of new gate lines and which adapter(s) fired.
- The single command to recompile after a hand-edit of
  `architecture.yaml`: `python scripts/harness/compile_architecture.py`.

## Re-run mode (placeholder — populated in T09)

If `.harness/architecture.yaml` already exists, prompt the user to pick
**add** / **revise** / **re-describe** and follow the corresponding flow.
The details of each mode are added by T09.
