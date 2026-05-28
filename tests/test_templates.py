"""Tests for plugin templates."""
import pathlib

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
    assert "scripts/harness/session_start.py" in text
    assert "scripts/harness/session_gate.py" in text
    assert "Edit|Write|MultiEdit" in text


def test_claude_md_template_mentions_session_leash():
    from pathlib import Path
    text = Path("templates/CLAUDE.md.tmpl").read_text(encoding="utf-8")
    assert "session leash" in text.lower() or "/leash-session-new" in text


def test_agents_md_template_mentions_concurrent_sessions():
    from pathlib import Path
    text = Path("templates/AGENTS.md.tmpl").read_text(encoding="utf-8")
    assert "concurrent" in text.lower() or "/leash-session-new" in text
