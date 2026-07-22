"""Tests for plugin templates."""
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_architecture_reviewer_template_placeholders():
    path = ROOT / "templates" / "architecture-reviewer.md.tmpl"
    text = path.read_text(encoding="utf-8")
    for placeholder in (
        "{{ARCHITECTURE_STYLE}}",
        "{{ARCHITECTURE_LAYER_TABLE}}",
        "{{ARCHITECTURE_EDGE_LIST}}",
        "{{ARCHITECTURE_REVIEW_RULES}}",
    ):
        assert placeholder in text, f"template missing {placeholder}"
    assert text.startswith("---\n"), "template needs YAML frontmatter"
    assert "tools: [Read, Glob, Grep]" in text, "reviewer must be read-only"


def test_agents_template_has_architecture_block():
    text = (ROOT / "templates" / "AGENTS.md.tmpl").read_text(encoding="utf-8")
    assert "<!-- OPTIONAL:ARCHITECTURE -->" in text
    assert "<!-- /OPTIONAL:ARCHITECTURE -->" in text
    open_idx = text.index("<!-- OPTIONAL:ARCHITECTURE -->")
    close_idx = text.index("<!-- /OPTIONAL:ARCHITECTURE -->")
    body = text[open_idx:close_idx]
    assert "compose-architecture-leash" in body
    assert "## Architecture" in body


def test_settings_template_has_worktree_leash_hook():
    text = (ROOT / "templates" / "settings.json.tmpl").read_text(encoding="utf-8")
    # The old session-leash SessionStart *detector* stays gone; the only
    # SessionStart hook is the stateless session_root_guard warning.
    assert "session_start" not in text
    assert "scripts.harness.session_root_guard" in text
    assert "PreToolUse" in text
    # Hooks must be invoked as modules (-m), not by path. See
    # test_session_hook_commands_in_template_actually_run below.
    assert "scripts.harness.session_gate" in text
    assert "Edit|Write|MultiEdit|NotebookEdit" in text


def test_session_hook_commands_in_template_actually_run(tmp_path):
    """Hook commands in the rendered template must not crash on import.

    Regression for the path-vs-module bug: scripts/harness/session_*.py
    use absolute imports (`from scripts.harness import ...`). Direct
    path invocation puts scripts/harness/ on sys.path[0] instead of the
    repo root, so the import fails with ModuleNotFoundError. Hooks must
    be invoked as `python -m scripts.harness.session_X` so the cwd
    (repo root) is on sys.path.
    """
    text = (ROOT / "templates" / "settings.json.tmpl").read_text(encoding="utf-8")
    commands = re.findall(r'"command":\s*"([^"]+)"', text)
    assert commands, "no hook commands found in template"

    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}

    for cmd in commands:
        argv = cmd.split()
        assert argv[0] == "python", f"unexpected interpreter in hook: {cmd}"
        argv[0] = sys.executable
        proc = subprocess.run(
            argv,
            cwd=ROOT,
            env=env,
            input="{}",
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert "ModuleNotFoundError" not in (proc.stderr or ""), (
            f"hook {cmd!r} crashed on import:\n{proc.stderr}"
        )
        assert proc.returncode == 0, (
            f"hook {cmd!r} returned {proc.returncode}\n"
            f"stderr: {proc.stderr}\nstdout: {proc.stdout}"
        )


def test_claude_md_template_mentions_worktree_leash():
    text = (ROOT / "templates" / "CLAUDE.md.tmpl").read_text(encoding="utf-8")
    assert "worktree leash" in text.lower()
    assert "/leash-start-work" in text


def test_agents_md_template_mentions_concurrent_safety():
    from pathlib import Path
    text = Path("templates/AGENTS.md.tmpl").read_text(encoding="utf-8")
    # The worktree leash makes concurrent sessions safe by construction;
    # the template must still speak to concurrency under the new framing.
    assert "concurrent" in text.lower()
    assert "/leash-start-work" in text


def test_agents_template_documents_worktree_start_path():
    text = (ROOT / "templates" / "AGENTS.md.tmpl").read_text(encoding="utf-8")
    assert ".worktrees/" in text
    assert "leash-start-work" in text
    # The proactive path is distinguished from the reactive session leash.
    assert "<type>/<slug>" in text


def test_claude_template_mentions_start_work():
    text = (ROOT / "templates" / "CLAUDE.md.tmpl").read_text(encoding="utf-8")
    assert "leash-start-work" in text


def test_agents_tmpl_has_antagonist_critics_optional_block():
    text = (ROOT / "templates" / "AGENTS.md.tmpl").read_text(encoding="utf-8")
    assert "<!-- OPTIONAL:ANTAGONIST_CRITICS -->" in text
    assert "<!-- /OPTIONAL:ANTAGONIST_CRITICS -->" in text
    block = text.split("<!-- OPTIONAL:ANTAGONIST_CRITICS -->")[1] \
                .split("<!-- /OPTIONAL:ANTAGONIST_CRITICS -->")[0]
    assert ".harness/critics.json" in block          # single source of truth
    assert "antagonist-critic" in block              # agent to dispatch
    assert "one round" in block.lower()              # per presented version
    assert "{{" not in block                         # no placeholders by design


def test_agents_tmpl_critics_block_is_fully_removable():
    # Spec: "fully removed on opt-out". Rendering is done by the bootstrap
    # skill (an LLM), so what we can pin mechanically is removability: the
    # markers appear exactly once, in order, and excising the marked span
    # leaves a template with no trace of the feature.
    text = (ROOT / "templates" / "AGENTS.md.tmpl").read_text(encoding="utf-8")
    open_m = "<!-- OPTIONAL:ANTAGONIST_CRITICS -->"
    close_m = "<!-- /OPTIONAL:ANTAGONIST_CRITICS -->"
    assert text.count(open_m) == 1 and text.count(close_m) == 1
    start, end = text.index(open_m), text.index(close_m) + len(close_m)
    assert start < end
    removed = text[:start] + text[end:]
    assert "antagonist" not in removed.lower()
    assert "critics.json" not in removed


def test_settings_tmpl_registers_critic_reminder_posttooluse():
    text = (ROOT / "templates" / "settings.json.tmpl").read_text(encoding="utf-8")
    assert "PostToolUse" in text
    assert "scripts.harness.critic_reminder" in text


def test_settings_tmpl_renders_to_valid_json():
    text = (ROOT / "templates" / "settings.json.tmpl").read_text(encoding="utf-8")
    rendered = (
        text.replace("{{TEST_RUNNER_COMMANDS}}", '"Bash(pytest*)"')
            .replace("{{LINT_COMMANDS}}", '"Bash(ruff*)"')
            .replace("{{TYPECHECK_COMMANDS}}", '"Bash(mypy*)"')
            .replace("{{BUILD_COMMANDS}}", '"Bash(make*)"')
    )
    data = json.loads(rendered)
    hooks = data["hooks"]["PostToolUse"]
    assert any(
        "critic_reminder" in h["command"]
        for entry in hooks for h in entry["hooks"]
    )
    matcher = hooks[0]["matcher"]
    for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        assert tool in matcher
