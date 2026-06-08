"""Structural assertions for the leash-start-work skill markdown."""
from __future__ import annotations

from pathlib import Path

SKILL_PATH = Path("skills/leash-start-work/SKILL.md")


def test_skill_file_exists():
    assert SKILL_PATH.exists()


def test_skill_has_frontmatter_name():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: leash-start-work" in text


def test_documents_type_slug_convention():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "<type>/<slug>" in text
    for t in ("feat", "fix", "refactor", "docs", "chore"):
        assert t in text


def test_branches_from_main():
    text = SKILL_PATH.read_text(encoding="utf-8")
    # The worktree branch is created from main/master, not HEAD.
    assert "git worktree add .worktrees/" in text
    assert "main" in text


def test_delegates_to_worktree_tooling():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "EnterWorktree" in text
    assert "using-git-worktrees" in text
    # Documented fallback command when neither is available.
    assert "git worktree add .worktrees/<slug> -b <type>/<slug> main" in text


def test_warns_when_not_ignored():
    text = SKILL_PATH.read_text(encoding="utf-8").lower()
    assert ".gitignore" in text
    assert "warn" in text or "not ignored" in text


def test_refuses_main():
    text = SKILL_PATH.read_text(encoding="utf-8").lower()
    # Never land work on main/master — branch discipline.
    assert "never" in text or "refuse" in text
