"""Asserts the architecture leash is in place on this repo and that gates
fire on a deliberate violation. Run as part of T11's verify command.
"""
from __future__ import annotations
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _require(path: pathlib.Path, desc: str) -> None:
    if not path.exists():
        print(f"MISSING: {desc} ({path})", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    _require(ROOT / ".harness" / "architecture.yaml", "architecture spec")
    _require(ROOT / "agents" / "architecture-reviewer.md", "reviewer agent")
    gates = (ROOT / ".harness" / "gates").read_text(encoding="utf-8")
    if "# arch-leash:" not in gates:
        print("MISSING: arch-leash gate lines in .harness/gates", file=sys.stderr)
        return 1

    # Pick the first arch-leash check script and exercise it with a
    # deliberate violation in a temp file inside the harness layer.
    checks = list((ROOT / ".harness" / "checks").glob("pattern-*.py"))
    if not checks:
        print("MISSING: at least one pattern check", file=sys.stderr)
        return 1
    script = checks[0]
    # Read the FORBIDDEN list literal from the generated script.
    text = script.read_text(encoding="utf-8")
    import re
    import ast

    m = re.search(r"^FORBIDDEN = (.+)$", text, re.MULTILINE)
    if not m:
        print(f"unable to extract FORBIDDEN from {script}", file=sys.stderr)
        return 1
    forbidden = ast.literal_eval(m.group(1))
    if not forbidden:
        print(f"FORBIDDEN list empty in {script}", file=sys.stderr)
        return 1
    needle = forbidden[0]
    violator = ROOT / "scripts" / "harness" / "_arch_leash_violator.py"
    violator.write_text(f"import {needle}\n", encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, str(script)], cwd=ROOT, capture_output=True
        )
        if result.returncode == 0:
            print(f"FAIL: gate {script.name} accepted a violation", file=sys.stderr)
            return 1
    finally:
        violator.unlink(missing_ok=True)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
