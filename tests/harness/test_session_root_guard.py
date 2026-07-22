"""Session-root guard tests.

A Claude Code session stores its history keyed to the directory it is
rooted in. A session rooted inside a linked worktree gets its history
keyed to `.worktrees/<slug>` — a disposable path — and loses it when
`/leash-finish-work` removes the worktree. The guard warns at
SessionStart when that is about to happen.
"""
from __future__ import annotations

from pathlib import Path

from scripts.harness.session_root_guard import classify, parse_payload


def test_cwd_in_linked_worktree_warns(tmp_path: Path):
    main_wt = tmp_path / "repo"
    linked = main_wt / ".worktrees" / "feat-x"
    linked.mkdir(parents=True)
    msg = classify(cwd=linked / "src", worktrees=[main_wt, linked])
    assert msg is not None
    assert str(main_wt) in msg
    assert "session" in msg.lower()


def test_cwd_at_linked_worktree_root_warns(tmp_path: Path):
    main_wt = tmp_path / "repo"
    linked = main_wt / ".worktrees" / "feat-x"
    linked.mkdir(parents=True)
    assert classify(cwd=linked, worktrees=[main_wt, linked]) is not None


def test_cwd_in_main_worktree_is_silent(tmp_path: Path):
    main_wt = tmp_path / "repo"
    linked = main_wt / ".worktrees" / "feat-x"
    linked.mkdir(parents=True)
    assert classify(cwd=main_wt / "src", worktrees=[main_wt, linked]) is None


def test_cwd_outside_repo_is_silent(tmp_path: Path):
    main_wt = tmp_path / "repo"
    main_wt.mkdir()
    assert classify(cwd=tmp_path / "elsewhere", worktrees=[main_wt]) is None


def test_no_worktree_info_is_silent(tmp_path: Path):
    assert classify(cwd=tmp_path, worktrees=None) is None
    assert classify(cwd=tmp_path, worktrees=[]) is None


def test_parse_payload_tolerates_bom_and_garbage():
    assert parse_payload('﻿{"cwd": "C:\\\\x"}') == {"cwd": "C:\\x"}
    assert parse_payload('{"cwd": "/x"}') == {"cwd": "/x"}
    assert parse_payload("") == {}
    assert parse_payload("not json") == {}
    assert parse_payload("[1]") == {}


def test_sibling_name_prefix_is_not_inside(tmp_path: Path):
    """`feat-xEVIL` merely starts with `feat-x`; component-aware matching
    must not classify it as inside the linked worktree."""
    main_wt = tmp_path / "repo"
    linked = main_wt / ".worktrees" / "feat-x"
    evil = main_wt / ".worktrees" / "feat-xEVIL"
    linked.mkdir(parents=True)
    evil.mkdir(parents=True)
    # evil is inside *main* (not the linked wt) → main is fine → silent.
    assert classify(cwd=evil, worktrees=[main_wt, linked]) is None
