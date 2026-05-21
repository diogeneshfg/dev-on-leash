import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK = REPO_ROOT / "scripts" / "harness" / "check_freshness.py"


def run_cli(*files: Path, today: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECK), *(str(f) for f in files)],
        capture_output=True,
        text=True,
        env={**os.environ, "HARNESS_TODAY": today},
    )


def write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_fresh_marker_exits_0(tmp_path):
    doc = write(
        tmp_path,
        "doc.md",
        "Status line.\n<!-- freshness: 2026-05-01 ttl: 60d -->\n",
    )
    r = run_cli(doc, today="2026-05-21")
    assert r.returncode == 0, r.stderr


def test_expired_marker_exits_1(tmp_path):
    doc = write(
        tmp_path,
        "doc.md",
        "Status line.\n<!-- freshness: 2026-01-01 ttl: 30d -->\n",
    )
    r = run_cli(doc, today="2026-05-21")
    assert r.returncode == 1
    assert "STALE" in r.stderr and "doc.md:2" in r.stderr


def test_no_markers_exits_0(tmp_path):
    doc = write(tmp_path, "doc.md", "No markers here at all.\n")
    r = run_cli(doc, today="2026-05-21")
    assert r.returncode == 0


def test_missing_file_exits_2(tmp_path):
    r = run_cli(tmp_path / "nope.md", today="2026-05-21")
    assert r.returncode == 2


def test_no_args_exits_2():
    r = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True)
    assert r.returncode == 2


def test_marker_expiring_exactly_today_is_still_fresh(tmp_path):
    # marked 2026-05-01 + ttl 30d => expires 2026-05-31; on that exact day it is fresh
    doc = write(
        tmp_path,
        "doc.md",
        "Status line.\n<!-- freshness: 2026-05-01 ttl: 30d -->\n",
    )
    r = run_cli(doc, today="2026-05-31")
    assert r.returncode == 0, r.stderr
