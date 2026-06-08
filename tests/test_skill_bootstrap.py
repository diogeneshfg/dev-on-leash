"""Structural assertions for the bootstrap-dev-leash skill markdown."""
from __future__ import annotations

from pathlib import Path


SKILL_PATH = Path("skills/bootstrap-dev-leash/SKILL.md")


def test_skill_file_exists():
    assert SKILL_PATH.exists()


def test_skill_documents_gitignore_patch_for_sessions():
    text = SKILL_PATH.read_text(encoding="utf-8")
    # The skill must explicitly tell Claude to add `.harness/sessions/`
    # to the target project's .gitignore so lockfiles are not committed.
    assert ".harness/sessions/" in text
    assert ".gitignore" in text


def test_skill_explains_why_sessions_are_ignored():
    text = SKILL_PATH.read_text(encoding="utf-8")
    # A one-line justification keeps the directive understandable when
    # someone reads the skill out of context.
    lower = text.lower()
    assert "lockfile" in lower or "session" in lower


def test_skill_documents_worktrees_optin():
    text = SKILL_PATH.read_text(encoding="utf-8")
    # The skill must offer the opt-in .worktrees/ layout and, when accepted,
    # patch .gitignore under the existing # dev-on-leash heading.
    assert ".worktrees/" in text
    assert "# dev-on-leash" in text


def test_skill_worktrees_optin_is_conditional():
    text = SKILL_PATH.read_text(encoding="utf-8").lower()
    # It is opt-in: the skill must frame it as a yes/no choice, not an
    # unconditional patch.
    assert "opt-in" in text or "if the user answered" in text or "if yes" in text
