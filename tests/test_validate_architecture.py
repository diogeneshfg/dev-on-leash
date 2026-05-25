"""Schema-validator tests for architecture.yaml."""
import pytest
from scripts.harness.validate_architecture import (
    ArchitectureSchemaError,
    parse_architecture,
)


def test_minimal_spec_parses():
    data = parse_architecture(
        """
version: 1
layers:
  - {name: domain, paths: [src/myapp/domain/**]}
allowed_dependencies: []
""".strip()
    )
    assert data.version == 1
    assert data.layers[0].name == "domain"
    assert data.allowed_dependencies == ()
    assert data.patterns == ()
    assert data.review_rules == ()


def test_missing_version_rejected():
    with pytest.raises(ArchitectureSchemaError, match="version"):
        parse_architecture("layers: []\nallowed_dependencies: []")


def test_unknown_layer_in_edge_rejected():
    with pytest.raises(ArchitectureSchemaError, match="unknown layer"):
        parse_architecture(
            """
version: 1
layers: [{name: domain, paths: [src/**]}]
allowed_dependencies: [{from: domain, to: [ghost]}]
""".strip()
        )


def test_duplicate_rule_id_rejected():
    with pytest.raises(ArchitectureSchemaError, match="duplicate id"):
        parse_architecture(
            """
version: 1
layers: [{name: a, paths: [src/a/**]}, {name: b, paths: [src/b/**]}]
allowed_dependencies: []
patterns:
  - {id: dup, layer: a, forbidden_imports: [x]}
  - {id: dup, layer: b, forbidden_imports: [y]}
""".strip()
        )
