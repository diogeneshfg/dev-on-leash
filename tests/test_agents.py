"""Tests for plugin-scoped agent definitions."""
import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _frontmatter(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} missing frontmatter"
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end])


def test_architecture_extractor_definition():
    fm = _frontmatter(ROOT / "agents" / "architecture-extractor.md")
    assert fm["name"] == "architecture-extractor"
    assert set(fm["tools"]) == {"Read", "Glob", "Grep"}
    assert "extract" in fm["description"].lower()
