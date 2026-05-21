#!/usr/bin/env python3
"""Flag stale dated assertions in Markdown docs via explicit freshness markers.

A freshness marker is an HTML comment placed next to a dated claim:

    <!-- freshness: 2026-05-01 ttl: 60d -->

`freshness` is the date the claim was last verified true; `ttl` is how many
days it stays trustworthy. The script flags every marker whose
`freshness + ttl` is in the past. Un-annotated prose is never flagged — this
is a zero-false-positive check by design.

The current date is `date.today()`, overridable via the HARNESS_TODAY env var
(ISO format) so tests are deterministic.

Usage:
    python scripts/harness/check_freshness.py <file.md> [<file.md> ...]

Exit codes:
    0 - every marker is still fresh (or no markers found)
    1 - at least one marker is expired
    2 - usage error (no files given / a file does not exist)
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import sys
from pathlib import Path

MARKER_RE = re.compile(
    r"<!--\s*freshness:\s*(\d{4}-\d{2}-\d{2})\s+ttl:\s*(\d+)d\s*-->"
)


def _today() -> _dt.date:
    override = os.environ.get("HARNESS_TODAY")
    if override:
        return _dt.date.fromisoformat(override)
    return _dt.date.today()


def find_stale(path: Path, today: _dt.date) -> list[tuple[int, _dt.date, int]]:
    """Return (lineno, marker_date, ttl_days) for every expired marker in path."""
    stale: list[tuple[int, _dt.date, int]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for lineno, line in enumerate(lines, start=1):
        for m in MARKER_RE.finditer(line):
            marked = _dt.date.fromisoformat(m.group(1))
            ttl = int(m.group(2))
            if today > marked + _dt.timedelta(days=ttl):
                stale.append((lineno, marked, ttl))
    return stale


def main(argv: list[str]) -> int:
    files = argv[1:]
    if not files:
        print("usage: check_freshness.py <file.md> [<file.md> ...]", file=sys.stderr)
        return 2
    today = _today()
    any_stale = False
    for raw in files:
        path = Path(raw)
        if not path.exists():
            print(f"error: {path} does not exist", file=sys.stderr)
            return 2
        for lineno, marked, ttl in find_stale(path, today):
            age = (today - marked).days
            print(
                f"STALE: {path}:{lineno} — marked {marked}, ttl {ttl}d, now {age}d old",
                file=sys.stderr,
            )
            any_stale = True
    if any_stale:
        return 1
    print(f"OK: freshness markers current in {len(files)} file(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
