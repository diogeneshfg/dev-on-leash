"""Baseline dataclass + load/save + JUnit XML ingestion."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Baseline:
    suite: str
    passed: list[str] = field(default_factory=list)
    xfail: list[str] = field(default_factory=list)
    xpass: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def save(b: Baseline, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(b), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load(path: Path) -> Baseline:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Baseline(
        suite=data["suite"],
        passed=sorted(data.get("passed", [])),
        xfail=sorted(data.get("xfail", [])),
        xpass=sorted(data.get("xpass", [])),
        skipped=sorted(data.get("skipped", [])),
    )


def _nodeid(case: ET.Element) -> str:
    """Reconstruct pytest nodeid (file::name) from a JUnit <testcase>."""
    f = case.get("file")
    name = case.get("name", "")
    return f"{f}::{name}" if f else name


def build_from_junit(junit_path: Path, *, suite: str) -> Baseline:
    root = ET.parse(junit_path).getroot()
    passed: list[str] = []
    xfail: list[str] = []
    xpass: list[str] = []
    skipped: list[str] = []
    for case in root.iter("testcase"):
        nid = _nodeid(case)
        if case.find("failure") is not None or case.find("error") is not None:
            continue  # failing tests are NOT baselined
        skip = case.find("skipped")
        if skip is not None:
            msg_type = (skip.get("type") or "").lower()
            if "xfail" in msg_type:
                xfail.append(nid)
            elif "xpass" in msg_type:
                xpass.append(nid)
            else:
                skipped.append(nid)
        else:
            passed.append(nid)
    return Baseline(
        suite=suite,
        passed=sorted(passed),
        xfail=sorted(xfail),
        xpass=sorted(xpass),
        skipped=sorted(skipped),
    )
