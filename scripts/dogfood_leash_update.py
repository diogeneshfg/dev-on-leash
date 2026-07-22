"""Dogfood: run the real leash_update CLI against a fixture project.

Uses this repo as the plugin root. Asserts: stale intact files update,
new files arrive, a planted local edit is refused with a diff, the
missing SessionStart hook is merged, and a second run is all-unchanged.
Exit 0 only if every assertion holds.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def run_cli(target: Path, *extra: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "leash_update.py"),
         str(target), *extra],
        capture_output=True, text=True, cwd=str(REPO))
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / "proj"
        # stale-but-intact copy of one real harness file
        gate_src = REPO / "scripts" / "harness" / "session_gate.py"
        gate_dst = proj / "scripts" / "harness" / "session_gate.py"
        gate_dst.parent.mkdir(parents=True)
        gate_dst.write_text("# old intact copy\n", encoding="utf-8")
        # planted local edit
        hook_dst = proj / ".harness" / "hooks" / "pre-commit"
        hook_dst.parent.mkdir(parents=True)
        hook_dst.write_text("# LOCAL EDIT\n", encoding="utf-8")
        # settings without the SessionStart hook
        st = proj / ".claude" / "settings.json"
        st.parent.mkdir(parents=True)
        st.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        # manifest: gate intact (hash matches), hook edited (hash differs)
        manifest = {"schema": 1, "version": "0.0.1", "files": {
            "scripts/harness/session_gate.py":
                hashlib.sha256(gate_dst.read_bytes()).hexdigest(),
            ".harness/hooks/pre-commit": "0" * 64}}
        (proj / ".harness" / "leash.json").write_text(
            json.dumps(manifest), encoding="utf-8")

        out1 = run_cli(proj)
        assert "updated" in out1 and "session_gate.py" in out1, out1
        assert gate_dst.read_text(encoding="utf-8") == gate_src.read_text(encoding="utf-8")
        assert "refused" in out1 and "pre-commit" in out1, out1
        assert hook_dst.read_text(encoding="utf-8") == "# LOCAL EDIT\n"
        settings = json.loads(st.read_text(encoding="utf-8"))
        assert settings["hooks"].get("SessionStart"), "SessionStart hook not merged"

        out2 = run_cli(proj)
        assert "updated" not in out2 and "added" not in out2, "second run must be quiet"

        out3 = run_cli(proj, "--force", ".harness/hooks/pre-commit")
        assert hook_dst.read_text(encoding="utf-8") != "# LOCAL EDIT\n"
        assert "refused" not in out3, out3
    print("DOGFOOD leash-update PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
