"""Structural tests for compose-architecture-leash SKILL.md."""
import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "compose-architecture-leash" / "SKILL.md"


def _frontmatter(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end]), text[end + 5 :]


def test_skill_frontmatter():
    fm, _ = _frontmatter(SKILL)
    assert fm["name"] == "compose-architecture-leash"
    assert "architecture" in fm["description"].lower()


def test_first_run_flow_sections():
    _, body = _frontmatter(SKILL)
    for needle in (
        "Precondition",
        "Detect language stack",
        "Prose interview",
        "architecture-extractor",
        "Confirm-and-edit",
        "compile_architecture.py",
        "OPTIONAL:ARCHITECTURE",
        "Report",
    ):
        assert needle in body, f"first-run section missing: {needle}"


def test_skill_refuses_when_bootstrap_missing():
    _, body = _frontmatter(SKILL)
    assert "CLAUDE.md" in body and "AGENTS.md" in body
    assert "bootstrap-dev-leash" in body
