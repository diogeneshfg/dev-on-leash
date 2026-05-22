---
name: bootstrap-dev-leash
description: Use to set up dev-on-leash in a target project — bootstrap this project, add the harness, install the dev-on-leash discipline. Interviews the user, renders CLAUDE.md / AGENTS.md / .claude/settings.json from templates, and copies the project-agnostic harness layer in.
---

# bootstrap-dev-leash

This skill runs **inside a target project** (not inside the dev-on-leash plugin repo). It is the entry point a user invokes after installing the `dev-on-leash` plugin. It produces the **project-specific layer** (`CLAUDE.md`, `AGENTS.md`, `.claude/settings.json`) by interview, then triggers the copy of the **project-agnostic layer** (harness scripts, plan skeleton, task/plan templates).

## When to use

The user wants to install the dev-on-leash development discipline into their project — phrasings like "set up dev-on-leash", "bootstrap this project", "add the harness". Run once per project. Do NOT use it to edit an already-bootstrapped project's discipline files — those are hand-maintained after the first render.

## Non-negotiable constraints

Read these before doing anything. They bound the entire skill.

1. **The fixed process prose is non-negotiable.** The templates contain fixed prose — branch discipline, TDD (Red → Green → Refactor), the integration-suite gate, the planning trigger, the harness-tooling description. The interview **only fills `{{placeholder}}` values and selects which optional blocks to keep**. It MUST NOT let the user weaken, soften, reword, or remove TDD, branch discipline, or any fixed section. If the user asks to "skip TDD" or "allow direct commits to main", refuse: explain that those rules are the point of dev-on-leash and are not configurable. The interview customizes; it never edits the discipline.

2. **Never overwrite an existing `CLAUDE.md` or `AGENTS.md` without an explicit confirmed diff.** If either file already exists in the target project, do NOT write over it. Show the user a diff between the existing file and the proposed rendered output, explain what would change, and get an explicit "yes, overwrite" before writing. The same applies to `.claude/settings.json` — if it exists, show the diff and confirm. If the user declines, write the rendered file alongside with a `.dev-on-leash-proposed` suffix and tell them to merge manually.

## Step 1 — Locate the plugin templates

The templates ship inside the plugin. Reference them via the `CLAUDE_PLUGIN_ROOT` environment variable, which Claude Code sets to the plugin's absolute install path:

- `${CLAUDE_PLUGIN_ROOT}/templates/CLAUDE.md.tmpl`
- `${CLAUDE_PLUGIN_ROOT}/templates/AGENTS.md.tmpl`
- `${CLAUDE_PLUGIN_ROOT}/templates/settings.json.tmpl`

Never hardcode an absolute install path — it breaks across machines. If `CLAUDE_PLUGIN_ROOT` is unset, stop and tell the user the skill must be run as part of the installed `dev-on-leash` plugin.

## Step 2 — Interview the user

Collect every project-specific value. Use the `AskUserQuestion` tool for questions with **discrete choices**; use plain free-text questions otherwise. Ask in small batches; do not dump everything at once.

Collect:

| # | Item | Mechanism | Feeds |
|---|------|-----------|-------|
| 1 | Project name | free-text | `{{PROJECT_NAME}}` |
| 2 | Language / stack | free-text | `{{STACK_SUMMARY}}`, `{{STACK_DESCRIPTION}}` |
| 3 | Mono-repo or single package | `AskUserQuestion` (mono-repo / single package) | `{{PACKAGE_LAYOUT}}` |
| 4 | Test command(s) | free-text | `{{TEST_COMMANDS}}`, `{{TEST_RUNNER_COMMANDS}}` |
| 5 | Lint command(s) | free-text | `{{LINT_COMMANDS}}` |
| 6 | Typecheck command(s) | free-text | `{{TYPECHECK_COMMANDS}}` |
| 7 | Build command(s) | free-text | `{{BUILD_COMMANDS}}` |
| 8 | Branch flow | `AskUserQuestion` (PR-based / direct-to-main) | informational — see note below |
| 9 | Domain-rules concern? (multi-tenancy, per-user scoping, etc.) | `AskUserQuestion` (yes / no) | keep or drop `OPTIONAL:DOMAIN_RULES` |
| 10 | Design-system / UI concern? | `AskUserQuestion` (yes / no) | keep or drop `OPTIONAL:UI_RULES` |
| 11 | Coverage targets | free-text | `{{COVERAGE_TARGETS}}` |

Notes on specific items:

- **Common commands** (`{{COMMON_COMMANDS}}` in `CLAUDE.md.tmpl`): assemble from the test/lint/typecheck/build answers — no separate question needed.
- **Branch flow (item 8):** record the answer for context, but the fixed AGENTS.md branch-discipline section stands as written regardless. "Direct-to-main" does NOT remove the rule that implementation work happens on a branch off `main`; it only describes the team's PR habit. If the user picks direct-to-main, confirm they understand the harness still expects feature branches for any source/test/config change.
- **Domain rules (item 9):** if yes, ask a follow-up free-text question for the actual rule text → `{{DOMAIN_RULES}}`. If no, drop the optional block entirely.
- **UI rules (item 10):** if yes, ask a follow-up free-text question for the actual rule text → `{{UI_RULES}}`. If no, drop the optional block entirely.

## Step 3 — Render the project-specific files

Read each `.tmpl`, substitute placeholders, handle optional blocks, write the result into the target project.

### Placeholders per template (substitute exactly these)

- **`CLAUDE.md.tmpl`** → `CLAUDE.md`: `{{PROJECT_NAME}}`, `{{STACK_SUMMARY}}`, `{{COMMON_COMMANDS}}`.
- **`AGENTS.md.tmpl`** → `AGENTS.md`: `{{PROJECT_NAME}}` (appears multiple times), `{{STACK_DESCRIPTION}}`, `{{TEST_COMMANDS}}`, `{{COVERAGE_TARGETS}}`, `{{PACKAGE_LAYOUT}}`, and `{{DOMAIN_RULES}}` / `{{UI_RULES}}` (only if their optional block is kept).
- **`settings.json.tmpl`** → `.claude/settings.json`: `{{TEST_RUNNER_COMMANDS}}`, `{{LINT_COMMANDS}}`, `{{TYPECHECK_COMMANDS}}`, `{{BUILD_COMMANDS}}`.

Substitute **every** `{{...}}` occurrence — after rendering, no `{{` may remain in any output file. If an interview answer left a placeholder with no value, ask the user rather than emitting an empty token.

### settings.json command lists

`{{TEST_RUNNER_COMMANDS}}`, `{{LINT_COMMANDS}}`, `{{TYPECHECK_COMMANDS}}`, `{{BUILD_COMMANDS}}` each sit on their own line inside a JSON `"allow"` array. Render each as one or more **comma-separated, quoted JSON strings** in `Bash(<command>*)` permission form — e.g. a pytest answer becomes `"Bash(pytest*)", "Bash(python -m pytest*)"`. The final rendered file MUST be valid JSON: no trailing comma before `]`, no empty slots. If the user has no command for a category, remove that placeholder line entirely (and its trailing comma) rather than leaving an empty string.

### Optional blocks

The optional blocks are delimited in `AGENTS.md.tmpl` by HTML-comment markers:

```
<!-- OPTIONAL:DOMAIN_RULES -->
...
<!-- /OPTIONAL:DOMAIN_RULES -->

<!-- OPTIONAL:UI_RULES -->
...
<!-- /OPTIONAL:UI_RULES -->
```

- If the user answered **yes** to a concern: keep the block's body, substitute its placeholder, and **delete the two marker comment lines** so they do not appear in the rendered file.
- If the user answered **no**: delete the **entire block** including both marker lines and everything between them.

`CLAUDE.md.tmpl` and `settings.json.tmpl` have no optional blocks.

### Writing — apply the no-overwrite constraint

For each of `CLAUDE.md`, `AGENTS.md`, `.claude/settings.json`:

- If the file does not exist: write it.
- If it exists: show a diff of existing vs. rendered, explain the change, get explicit confirmation before overwriting. If declined, write to `<name>.dev-on-leash-proposed` and report it.

Create the `.claude/` directory if it does not exist.

## Step 3b — Write the cycle gates

`scripts/harness/cycle_done.py` closes a cycle only when every command in `.harness/gates` exits 0. Build that file from the interview's verification answers (Step 2, items 4–7):

- Create `.harness/` in the target project if it does not exist.
- Write `.harness/gates` with one shell command per line — the project's test, lint, typecheck, and build commands. Skip any category the project does not have. Lines starting with `#` are comments.

Example:

```
# Commands run by cycle_done.py to close a cycle. All must exit 0.
python -m pytest
ruff check .
```

If the project has no verification commands at all, still write `.harness/gates` with just the comment header — `cycle_done` then closes on checkbox state alone, and the user has an obvious place to add gates later.

## Step 4 — Copy the project-agnostic layer

Invoke the plugin's init script to drop the agnostic layer into the target project. The script **requires** the target repo path as its first argument — omitting it causes the script to exit 1 with an error. Since the skill runs from the target project root, pass `.` as the target path. Use the script matching the OS:

- POSIX: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/init.sh" .`
- Windows: `pwsh "${CLAUDE_PLUGIN_ROOT}/scripts/init.ps1" .`

This copies `scripts/harness/`, `docs/task-schema.md`, `docs/plan-template.md`, and an empty `docs/plans/` directory into the target project. Run it from the target project root. If the init script is not yet present in the installed plugin version, report that the agnostic layer could not be copied and tell the user to update the plugin — do not hand-copy files.

## Step 4b — Offer the pre-commit hook (opt-in)

The init script copies an opt-in pre-commit hook to
`.harness/hooks/pre-commit`. It runs `scripts/harness/recheck_plan.py` on any
staged plan file and blocks the commit if a ticked task fails to re-verify —
the local half of the enforcement model.

Ask the user (one `AskUserQuestion`, yes/no) whether to activate it now:

- **Yes:** run `git config core.hooksPath .harness/hooks` in the target repo.
  Tell the user the bypass is `git commit --no-verify`, and that
  `core.hooksPath` redirects *all* git hooks to `.harness/hooks/`.
- **No:** leave the hook file in place, unactivated. Tell the user they can
  activate it later with the same `git config` command.

For CI enforcement, point the user at `${CLAUDE_PLUGIN_ROOT}/templates/ci-snippet.md`
— a copy-pasteable step that re-verifies ticked tasks on every push.

## Step 5 — Report

Tell the user concisely:

- Which files were created or updated (`CLAUDE.md`, `AGENTS.md`, `.claude/settings.json`), and which (if any) were written as `.dev-on-leash-proposed` pending manual merge.
- Which optional blocks were kept or dropped (Domain rules, UI rules).
- That the agnostic layer was copied: `scripts/harness/`, `docs/task-schema.md`, `docs/plan-template.md`, and an empty `docs/plans/` directory.
- That `.harness/gates` was written from the verification commands — editing it tunes what `cycle_done` checks before closing a cycle.
- Whether the pre-commit hook was activated (`git config core.hooksPath`), and
  that the CI snippet in `templates/ci-snippet.md` enforces the same check on push.
- **Next step:** write a plan into `docs/plans/` (by hand from `docs/plan-template.md`, or with `superpowers:writing-plans` if those skills are installed), then execute it task-by-task with the `execute-plan-task` skill. Augment each task you want machine-verified with a `task-meta` block — see `docs/task-schema.md`.
