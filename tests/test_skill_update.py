"""Structural assertions for the leash-update skill markdown."""
from __future__ import annotations

from pathlib import Path

SKILL_PATH = Path("skills/leash-update/SKILL.md")


def test_skill_exists_with_frontmatter():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\n") and "name: leash-update" in text


def test_skill_invokes_plugin_script_by_path():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "${CLAUDE_PLUGIN_ROOT}/scripts/leash_update.py" in text
    assert "--force" in text
    # --init-manifest is init-script plumbing, not part of the user flow.
    assert "--init-manifest" not in text.split("## Constraints")[0]


def test_skill_documents_refusal_and_untouched_files():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "CLAUDE.md" in text and "AGENTS.md" in text
    assert "refus" in text.lower()
