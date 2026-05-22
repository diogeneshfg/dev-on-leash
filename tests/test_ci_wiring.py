"""CI and bootstrap are wired to the recheck_plan enforcement."""
import pathlib

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_ci_yaml_is_valid_and_rechecks_plans():
    ci = ROOT / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    assert doc, "ci.yml must be valid, non-empty YAML"
    step_names = [s.get("name", "") for s in doc["jobs"]["ci"]["steps"]]
    assert "Re-verify ticked tasks in plans" in step_names
    assert "recheck_plan.py" in text


def test_ci_snippet_template_exists():
    snippet = ROOT / "templates" / "ci-snippet.md"
    assert snippet.exists()
    assert "recheck_plan.py" in snippet.read_text(encoding="utf-8")


def test_bootstrap_skill_documents_the_hook():
    text = (ROOT / "skills" / "bootstrap-dev-leash" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "pre-commit" in text
    assert "recheck_plan" in text
