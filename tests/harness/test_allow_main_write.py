"""Tests for the one-shot main-write authorization marker."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.harness.allow_main_write import write_marker


def test_write_marker_creates_json(tmp_path: Path):
    harness = tmp_path / ".harness"
    marker = write_marker(harness_dir=harness, reason="quick typo")
    assert marker == harness / "allow-main-write"
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert data["reason"] == "quick typo"
    assert "created_at" in data


def test_write_marker_makes_dir(tmp_path: Path):
    harness = tmp_path / "nope" / ".harness"
    marker = write_marker(harness_dir=harness, reason="r")
    assert marker.exists()
