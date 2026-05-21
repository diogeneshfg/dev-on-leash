#!/bin/sh
# init.sh — Copy the dev-on-leash project-agnostic layer into a target repo.
#
# Usage: sh scripts/init.sh <target-repo-path>
#
# Copies:
#   scripts/harness/       -> <target>/scripts/harness/   (skipped if already exists)
#   templates/task-schema.md  -> <target>/docs/task-schema.md
#   templates/plan-template.md -> <target>/docs/plan-template.md
#   Creates empty            <target>/docs/plans/
#
# Does NOT touch CLAUDE.md or AGENTS.md — those are bootstrap-skill's job.

set -e

# ---------------------------------------------------------------------------
# Resolve plugin root: the directory containing this script's parent.
# $0 may be relative; resolve via pwd + dirname without bashisms.
# ---------------------------------------------------------------------------
_script_dir() {
    _s="$1"
    # If the path has no directory component, it is on $PATH or cwd.
    case "$_s" in
        /*)  printf '%s' "$(dirname "$_s")" ;;
        */*) printf '%s' "$(cd "$(dirname "$_s")" && pwd)" ;;
        *)   printf '%s' "$(pwd)" ;;
    esac
}

SCRIPT_DIR="$(_script_dir "$0")"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Validate argument
# ---------------------------------------------------------------------------
if [ $# -lt 1 ] || [ -z "$1" ]; then
    printf 'ERROR: missing required argument <target-repo-path>\n' >&2
    printf 'Usage: sh %s <target-repo-path>\n' "$0" >&2
    exit 1
fi

TARGET="$1"

if [ ! -d "$TARGET" ]; then
    printf 'ERROR: target path does not exist or is not a directory: %s\n' "$TARGET" >&2
    exit 1
fi

TARGET="$(cd "$TARGET" && pwd)"

# ---------------------------------------------------------------------------
# Source paths
# ---------------------------------------------------------------------------
SRC_HARNESS="$PLUGIN_ROOT/scripts/harness"
SRC_SCHEMA="$PLUGIN_ROOT/templates/task-schema.md"
SRC_PLAN="$PLUGIN_ROOT/templates/plan-template.md"

# ---------------------------------------------------------------------------
# Destination paths
# ---------------------------------------------------------------------------
DST_HARNESS="$TARGET/scripts/harness"
DST_DOCS="$TARGET/docs"
DST_SCHEMA="$DST_DOCS/task-schema.md"
DST_PLAN="$DST_DOCS/plan-template.md"
DST_PLANS_DIR="$DST_DOCS/plans"

COPIED=""
SKIPPED=""
CREATED=""

# ---------------------------------------------------------------------------
# 1. Copy scripts/harness/ — skip (do not clobber) if already present
# ---------------------------------------------------------------------------
if [ -e "$DST_HARNESS" ]; then
    printf 'WARNING: %s already exists — skipping harness copy to avoid clobbering.\n' "$DST_HARNESS"
    SKIPPED="$SKIPPED scripts/harness/"
else
    mkdir -p "$TARGET/scripts"
    cp -r "$SRC_HARNESS" "$TARGET/scripts/"
    printf 'Copied:  scripts/harness/\n'
    COPIED="$COPIED scripts/harness/"
fi

# ---------------------------------------------------------------------------
# 2. Ensure docs/ exists
# ---------------------------------------------------------------------------
if [ ! -d "$DST_DOCS" ]; then
    mkdir -p "$DST_DOCS"
fi

# ---------------------------------------------------------------------------
# 3. Copy task-schema.md
# ---------------------------------------------------------------------------
if [ -e "$DST_SCHEMA" ]; then
    printf 'Skipped: docs/task-schema.md (already exists)\n'
    SKIPPED="$SKIPPED docs/task-schema.md"
else
    cp "$SRC_SCHEMA" "$DST_SCHEMA"
    printf 'Copied:  docs/task-schema.md\n'
    COPIED="$COPIED docs/task-schema.md"
fi

# ---------------------------------------------------------------------------
# 4. Copy plan-template.md
# ---------------------------------------------------------------------------
if [ -e "$DST_PLAN" ]; then
    printf 'Skipped: docs/plan-template.md (already exists)\n'
    SKIPPED="$SKIPPED docs/plan-template.md"
else
    cp "$SRC_PLAN" "$DST_PLAN"
    printf 'Copied:  docs/plan-template.md\n'
    COPIED="$COPIED docs/plan-template.md"
fi

# ---------------------------------------------------------------------------
# 5. Create docs/plans/ directory
# ---------------------------------------------------------------------------
if [ -d "$DST_PLANS_DIR" ]; then
    printf 'Skipped: docs/plans/ (already exists)\n'
    SKIPPED="$SKIPPED docs/plans/"
else
    mkdir -p "$DST_PLANS_DIR"
    printf 'Created: docs/plans/\n'
    CREATED="$CREATED docs/plans/"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf '%s\n' '' '--- dev-on-leash init summary ---'
printf 'Target: %s\n' "$TARGET"
if [ -n "$COPIED" ]; then
    printf 'Copied:%s\n' "$COPIED"
fi
if [ -n "$CREATED" ]; then
    printf 'Created:%s\n' "$CREATED"
fi
if [ -n "$SKIPPED" ]; then
    printf 'Skipped:%s\n' "$SKIPPED"
fi
printf '%s\n' '--- done ---'
