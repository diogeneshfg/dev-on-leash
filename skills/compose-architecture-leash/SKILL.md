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

## Re-run mode picker

When `.harness/architecture.yaml` already exists, ask the user one
multiple-choice question:

- **add** — describe a new architectural aspect to layer on top.
- **revise** — change one or more existing rules by id.
- **re-describe** — re-extract the whole spec from a fresh description.

### Mode: add

1. Prompt: "What aspect do you want to add? Describe just the addition."
2. Dispatch `dev-on-leash:architecture-extractor` with the message header
   `MODE: ADD` so the extractor returns ONLY the new entries as a YAML
   fragment. The extractor must not restate or rewrite any existing entry.
3. **Fragment contract** (load-bearing): the YAML fragment the extractor
   returns must use the same top-level keys as the full architecture.yaml
   schema (`layers`, `allowed_dependencies`, `patterns`, `review_rules`).
   Any top-level key that has no new entries is OMITTED entirely from the
   fragment — empty lists are NOT permitted. The fragment must NOT include
   `version` or `style`; those carry over from the existing file.
4. The **skill performs the merge** into `architecture.yaml` — the
   subagent never touches the existing file. The merge appends new entries
   under each present top-level key. If the merged file references an
   `allowed_dependencies` edge whose `from` or `to` layer was not added in
   the same fragment AND does not already exist in the file, the skill
   rejects the fragment and asks the user to either (a) add the missing
   layer in this same fragment or (b) declare it in a separate `add` run
   first.
5. Validate the merged YAML with
   `python scripts/harness/validate_architecture.py` (or by importing
   `parse_architecture` from the validator) before writing.
6. Show a YAML diff (the new entries highlighted) plus rationale.
7. Confirm-and-edit loop, then recompile (`python scripts/harness/compile_architecture.py`)
   and re-render the `OPTIONAL:ARCHITECTURE` block in `AGENTS.md` as in
   first-run Step 5.

### Mode: revise

1. Show the current `architecture.yaml` as a numbered list of rules, each
   labeled with its stable `id` (layer name for layers; `id` field for
   everything else).
2. Prompt: "Which rule(s) by id, and what should change?"
3. Dispatch the extractor with just those rules and the user's correction.
   It returns the rewritten entries; everything else in the YAML is
   preserved byte-for-byte by the skill.
4. Re-validate the resulting YAML with the validator.
5. Confirm-and-edit loop, then write / compile / re-render.

### Mode: re-describe

1. Same prose interview as first-run.
2. Dispatch the extractor with the full prose.
3. Re-validate the proposed YAML with the validator.
4. Side-by-side diff between old and new YAML, organized by rule id —
   added, removed, modified — with a rationale per change.
5. Confirm-and-edit loop. The user can accept all, accept selectively by
   id, or start over.
6. On accept: save the old YAML to
   `.harness/architecture.yaml.bak-<UTC ISO timestamp>` (one backup only;
   overwrites any prior `.bak-` for this run — git is the real history).
   Then write the new YAML, recompile, re-render.

## Invariants across all three modes

- The compiler only runs if `architecture.yaml` actually changed.
- Every generated gate line carries `# arch-leash:<id>`. Orphaned lines
  (from removed rules) are pruned on the next compile.
- `agents/architecture-reviewer.md` is FULLY regenerated each compile.
- The `OPTIONAL:ARCHITECTURE` block in `AGENTS.md` is FULLY regenerated
  between its markers.
- Same diff-and-confirm rule as bootstrap applies before overwriting any
  hand-editable file.
