# Configurable base branch for worktrees — design

Date: 2026-07-22
Status: approved

## Problem

`/leash-start-work` hardcodes `main`/`master` as the starting point for every
new worktree, and `/leash-finish-work` checks "is the branch merged?" against
whatever branch the main checkout happens to have checked out. Projects with
several long-lived branches (e.g. `dev`, `qa`, `homol`, `prod`) can't follow
their real flow: work often must start from `prod` (production may be behind
`dev`) and gets merged first into `dev`, then promoted.

## Decisions (validated with the user)

1. **Base branch source:** per-project config declares a default base;
   `/leash-start-work` accepts an optional `--base <branch>` override. With
   neither, behavior is unchanged (`main`/`master`).
2. **Merged check:** `/leash-finish-work` treats the work branch as safe to
   remove if it is merged into **any** declared long-lived branch (plus
   `main`/`master`). This covers the "start from prod, merge into dev" flow.
3. **Freshness:** before branching, `git fetch origin <base>` when a remote
   exists; if the local base is behind `origin/<base>`, warn and branch from
   `origin/<base>` (the local base checkout is never touched). No remote ⇒
   use the local base silently.
4. **Protection:** every declared long-lived branch gets the same protection
   `main`/`master` have today — `/leash-start-work` refuses to create a
   branch with one of those names, `/leash-finish-work` refuses to remove a
   worktree sitting on one.
5. **Config home:** a dedicated, optional `.harness/branches.yaml` (approach
   A), not a section of `architecture.yaml` and not flags-only.

## Config file

```yaml
# .harness/branches.yaml  (optional)
base: prod                          # default base for new worktrees
long_lived: [dev, qa, homol, prod]  # protected branches / valid merge targets
```

Validation rules:

- Both keys optional. Missing file ⇒ current behavior exactly (base =
  detected `main`/`master`; protected/merge targets = `{main, master}`).
- `base`, when present, must be `main`/`master` or listed in `long_lived`.
- Branch names must be plausible git refs (no spaces, no leading `-`, pass a
  conservative charset check).
- A malformed file is a hard, clearly-worded error — never a silent fallback.

## Components

### `scripts/harness/branches.py` (new)

Single reader for the config, mirroring the repo's existing
`yaml.safe_load` pattern (`validate_architecture.py`). API:

```python
load_branch_config(repo_root: Path) -> BranchConfig
# BranchConfig:
#   base: str            # resolved: config base → detected main/master
#   protected: set[str]  # long_lived ∪ {main, master}
#   merge_targets: set[str]  # same set as protected
```

Raises `BranchConfigError` with a human-readable message on malformed input.

### `skills/leash-start-work/SKILL.md`

- New optional argument `--base <branch>`; precedence: argument → config
  `base` → detected `main`/`master`.
- Refuse if the requested base does not exist as a local or remote branch.
- Refuse a `<type>/<slug>` whose resulting branch name collides with any
  protected branch (in addition to today's main/master refusal).
- Freshness step: fetch-and-warn as per decision 3; the worktree command
  becomes `git worktree add .worktrees/<slug> -b <type>/<slug> <start-point>`
  where `<start-point>` is the base or `origin/<base>`.
- The final report names the base the work started from.

### `scripts/harness/finish_work.py`

- Replace the hardcoded `("main", "master")` refusal tuple with
  `BranchConfig.protected`.
- `_branch_is_merged` checks `git branch --merged <target>` for each branch
  in `merge_targets` (skipping targets that don't exist locally); merged into
  any one of them ⇒ safe. Without a config this degrades to main/master —
  equivalent to today for the standard flow, and strictly more correct than
  checking against the current HEAD.

### `skills/leash-finish-work/SKILL.md`

Document the new merged-into-any-declared-branch semantics.

### `skills/bootstrap-dev-leash`

Interview gains one optional question: "does the project have long-lived
branches besides main (dev/qa/homol/prod)? Which is the default base?" — a
yes renders `.harness/branches.yaml`.

### README

User-facing feature ⇒ README section on multi-branch projects and
`.harness/branches.yaml`, per project rule (README update ships in the same
plan, not as a follow-up).

## Error handling

- Malformed `branches.yaml` → hard error naming the file and the offending
  key.
- `--base` naming a nonexistent branch → refusal listing available
  long-lived branches.
- Fetch failure (offline, no such remote branch) → warn and proceed from the
  local base; never block offline work.
- `finish_work` git failures keep the existing `FinishWorkError` path.

## Testing

- Unit tests for `branches.py`: missing file, valid file, malformed YAML,
  unknown top-level keys (rejected — fail loud), `base` not in `long_lived`,
  bad ref names.
- `finish_work` tests: refusal on a worktree sitting on a declared long-lived
  branch; merged-into-`dev`-but-not-`prod` branch is removable when `dev` is
  declared; no-config behavior unchanged (existing tests keep passing).
- Docs tests (`tests/test_docs.py`) updated if they assert on the skill text.
- Dogfood: add a trivial `branches.yaml` (`base: main`) to this repo and run
  a start→finish cycle to verify nothing regresses.

## Out of scope (YAGNI)

- Automatic promotion flows (dev → qa → homol → prod).
- Keeping long-lived branches in sync with each other.
- Changes to `session_gate.py` — the directory-based write gate already
  prevents editing any branch checked out in the main worktree.
