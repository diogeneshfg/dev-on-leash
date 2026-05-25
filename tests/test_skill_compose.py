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


def test_rerun_modes_present():
    _, body = _frontmatter(SKILL)
    for needle in (
        "Re-run mode picker",
        "Mode: add",
        "Mode: revise",
        "Mode: re-describe",
        "MODE: ADD",  # delta marker the extractor recognizes
        "architecture.yaml.bak-",
    ):
        assert needle in body, f"re-run section missing: {needle}"


def test_add_mode_uses_delta_strict_merge():
    _, body = _frontmatter(SKILL)
    # The spec commits to strict merge: extractor returns only the fragment,
    # the SKILL performs the merge. Make sure that wording survives.
    assert "fragment" in body.lower()
    assert "skill performs the merge" in body.lower()


def test_add_mode_specifies_fragment_top_level_keys():
    """Per T02 code-review carry-over: the fragment contract must be explicit."""
    _, body = _frontmatter(SKILL)
    # Must explicitly say which top-level keys are allowed and that empties are omitted.
    assert "top-level keys" in body.lower()
    assert "omit" in body.lower()
