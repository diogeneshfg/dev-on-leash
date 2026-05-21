#!/usr/bin/env bash
# Pre-push entry point: thin wrapper around check_regression.py.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python "$REPO_ROOT/scripts/harness/check_regression.py" "$@"
