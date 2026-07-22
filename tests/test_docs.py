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


def test_readme_has_worktree_leash_section():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Worktree leash" in text
    assert "/leash-start-work" in text
    assert "/leash-finish-work" in text
    assert "allow_main_write" in text


def test_readme_trust_model_names_worktree_leash():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    lower = text.lower()
    assert "worktree leash" in lower


def test_readme_documents_worktree_workflow():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    text = (root / "README.md").read_text(encoding="utf-8")
    assert "leash-start-work" in text
    assert ".worktrees/" in text


def test_readme_documents_antagonist_critics():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "antagonist" in text.lower()
    assert ".harness/critics.json" in text
