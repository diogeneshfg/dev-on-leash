"""update_check tests: silent off leashed repos, warns on stale manifest."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.update_check import check


def _plugin(tmp_path: Path, version: str = "0.6.0") -> Path:
    root = tmp_path / "plugin"
    meta = root / ".claude-plugin" / "plugin.json"
    meta.parent.mkdir(parents=True)
    meta.write_text(json.dumps({"version": version}), encoding="utf-8")
    return root


def _leashed(tmp_path: Path, manifest_version: str | None) -> Path:
    proj = tmp_path / "proj"
    (proj / ".harness").mkdir(parents=True)
    if manifest_version is not None:
        (proj / ".harness" / "leash.json").write_text(
            json.dumps({"schema": 1, "version": manifest_version, "files": {}}),
            encoding="utf-8")
    return proj


def test_silent_on_non_leashed_cwd(tmp_path: Path):
    plugin = _plugin(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    assert check(cwd=plain, plugin_root=plugin) is None


def test_silent_on_plugin_repo_itself(tmp_path: Path):
    plugin = _plugin(tmp_path)
    (plugin / ".harness").mkdir()
    assert check(cwd=plugin, plugin_root=plugin) is None


def test_silent_when_versions_match(tmp_path: Path):
    plugin = _plugin(tmp_path, "0.6.0")
    proj = _leashed(tmp_path, "0.6.0")
    assert check(cwd=proj, plugin_root=plugin) is None


def test_warns_on_version_mismatch(tmp_path: Path):
    plugin = _plugin(tmp_path, "0.6.0")
    proj = _leashed(tmp_path, "0.5.0")
    msg = check(cwd=proj, plugin_root=plugin)
    assert msg and "0.5.0" in msg and "0.6.0" in msg and "/leash-update" in msg


def test_warns_on_missing_manifest(tmp_path: Path):
    plugin = _plugin(tmp_path, "0.6.0")
    proj = _leashed(tmp_path, None)
    msg = check(cwd=proj, plugin_root=plugin)
    assert msg and "/leash-update" in msg


def test_hooks_json_wires_update_check():
    data = json.loads(Path("hooks/hooks.json").read_text(encoding="utf-8"))
    commands = [h["command"]
                for entry in data["hooks"]["SessionStart"]
                for h in entry["hooks"]]
    assert any("update_check.py" in c and "${CLAUDE_PLUGIN_ROOT}" in c
               for c in commands)
