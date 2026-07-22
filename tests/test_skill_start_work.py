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


def test_creates_worktree_without_moving_session():
    """Sessions rooted inside `.worktrees/<slug>` lose their history when
    the worktree is removed (history is keyed to the session root). The
    skill must use plain `git worktree add` and forbid session-relocating
    mechanisms such as EnterWorktree."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "git worktree add .worktrees/<slug> -b <type>/<slug> main" in text
    assert "Do **not** use session-relocating mechanisms (`EnterWorktree`" in text
    assert "session stays" in text.lower() or "stays rooted" in text.lower()


def test_warns_when_not_ignored():
    text = SKILL_PATH.read_text(encoding="utf-8").lower()
    assert ".gitignore" in text
    assert "warn" in text or "not ignored" in text


def test_refuses_main():
    text = SKILL_PATH.read_text(encoding="utf-8").lower()
    # Never land work on main/master — branch discipline.
    assert "never" in text or "refuse" in text
