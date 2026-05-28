"""Tests for plugin templates."""
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


def test_settings_template_has_session_leash_hooks():
    from pathlib import Path
    text = Path("templates/settings.json.tmpl").read_text(encoding="utf-8")
    assert "SessionStart" in text
    assert "PreToolUse" in text
    # Hooks must be invoked as modules (-m), not by path. See
    # test_session_hook_commands_in_template_actually_run below.
    assert "scripts.harness.session_start" in text
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


def test_claude_md_template_mentions_session_leash():
    from pathlib import Path
    text = Path("templates/CLAUDE.md.tmpl").read_text(encoding="utf-8")
    assert "session leash" in text.lower() or "/leash-session-new" in text


def test_agents_md_template_mentions_concurrent_sessions():
    from pathlib import Path
    text = Path("templates/AGENTS.md.tmpl").read_text(encoding="utf-8")
    assert "concurrent" in text.lower() or "/leash-session-new" in text
