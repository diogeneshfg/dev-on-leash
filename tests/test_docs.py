"""README and plugin manifest describe the tool honestly."""
import json
import pathlib

import pytest

pytestmark = pytest.mark.unit

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_readme_has_trust_model_section():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Trust model" in readme


def test_readme_drops_overclaiming_language():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "proven internal harness" not in readme


def test_plugin_description_is_honest():
    desc = json.loads(
        (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )["description"]
    assert "re-verifiable" in desc
    assert "guardrails" not in desc.lower(), f"description still contains 'guardrails': {desc}"


def test_followups_records_touches_integrity():
    text = (ROOT / "docs" / "follow-ups.md").read_text(encoding="utf-8")
    assert "touches-integrity" in text
