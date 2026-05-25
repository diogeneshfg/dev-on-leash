"""Schema validator for .harness/architecture.yaml.

Pure Python, no external deps beyond pyyaml. Parses YAML and returns
typed dataclasses; raises ArchitectureSchemaError on any violation. The
compiler depends on this module and never re-validates fields itself.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import yaml


class ArchitectureSchemaError(ValueError):
    pass


@dataclass(frozen=True)
class Layer:
    name: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class Edge:
    src: str
    dst: tuple[str, ...]


@dataclass(frozen=True)
class Pattern:
    id: str
    layer: str
    forbidden_imports: tuple[str, ...] = ()
    required_imports: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class ReviewRule:
    id: str
    applies_to: str
    rule: str


@dataclass(frozen=True)
class Architecture:
    version: int
    style: str
    layers: tuple[Layer, ...]
    allowed_dependencies: tuple[Edge, ...]
    patterns: tuple[Pattern, ...]
    review_rules: tuple[ReviewRule, ...]


def _require(d: dict, key: str, ctx: str) -> Any:
    if key not in d:
        raise ArchitectureSchemaError(f"{ctx}: missing required key {key!r}")
    return d[key]


def parse_architecture(text: str) -> Architecture:
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ArchitectureSchemaError("top-level must be a mapping")
    version = _require(raw, "version", "root")
    if version != 1:
        raise ArchitectureSchemaError(f"unsupported version: {version!r}")
    style = raw.get("style", "")
    layers_raw = raw.get("layers", [])
    if not isinstance(layers_raw, list):
        raise ArchitectureSchemaError("layers must be a list")
    layers: list[Layer] = []
    for i, l in enumerate(layers_raw):
        name = _require(l, "name", f"layers[{i}]")
        paths = _require(l, "paths", f"layers[{i}]")
        if not isinstance(paths, list) or not paths:
            raise ArchitectureSchemaError(f"layers[{i}].paths must be non-empty list")
        layers.append(Layer(name=name, paths=tuple(paths)))
    layer_names = {l.name for l in layers}
    if len(layer_names) != len(layers):
        raise ArchitectureSchemaError("duplicate layer name")
    edges: list[Edge] = []
    for i, e in enumerate(raw.get("allowed_dependencies", []) or []):
        src = _require(e, "from", f"allowed_dependencies[{i}]")
        dst = _require(e, "to", f"allowed_dependencies[{i}]")
        if isinstance(dst, str):
            dst = [dst]
        for n in (src, *dst):
            if n not in layer_names:
                raise ArchitectureSchemaError(f"unknown layer {n!r} in edge")
        edges.append(Edge(src=src, dst=tuple(dst)))
    seen_ids: set[str] = set()
    patterns: list[Pattern] = []
    for i, p in enumerate(raw.get("patterns", []) or []):
        pid = _require(p, "id", f"patterns[{i}]")
        if pid in seen_ids:
            raise ArchitectureSchemaError(f"duplicate id {pid!r}")
        seen_ids.add(pid)
        layer = _require(p, "layer", f"patterns[{i}]")
        if layer not in layer_names:
            raise ArchitectureSchemaError(f"patterns[{i}]: unknown layer {layer!r}")
        patterns.append(
            Pattern(
                id=pid,
                layer=layer,
                forbidden_imports=tuple(p.get("forbidden_imports", []) or []),
                required_imports=tuple(p.get("required_imports", []) or []),
                reason=p.get("reason", "") or "",
            )
        )
    rules: list[ReviewRule] = []
    for i, r in enumerate(raw.get("review_rules", []) or []):
        rid = _require(r, "id", f"review_rules[{i}]")
        if rid in seen_ids:
            raise ArchitectureSchemaError(f"duplicate id {rid!r}")
        seen_ids.add(rid)
        applies = _require(r, "applies_to", f"review_rules[{i}]")
        if applies not in layer_names:
            raise ArchitectureSchemaError(
                f"review_rules[{i}]: unknown layer {applies!r}"
            )
        rules.append(
            ReviewRule(id=rid, applies_to=applies, rule=_require(r, "rule", f"review_rules[{i}]"))
        )
    return Architecture(
        version=version,
        style=style,
        layers=tuple(layers),
        allowed_dependencies=tuple(edges),
        patterns=tuple(patterns),
        review_rules=tuple(rules),
    )
