"""Structural assertions on scripts/smoke_e2e.py."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_smoke_e2e_includes_architecture_step():
    text = (ROOT / "scripts" / "smoke_e2e.py").read_text(encoding="utf-8")
    assert "compile_architecture" in text
    assert "architecture.yaml" in text
    # Deliberate-violation step that exercises a gate:
    assert "ARCH-LEASH-VIOLATION" in text
