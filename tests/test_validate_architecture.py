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


def test_forbidden_imports_scalar_rejected():
    with pytest.raises(ArchitectureSchemaError, match="forbidden_imports must be a list"):
        parse_architecture(
            """
version: 1
layers: [{name: a, paths: [src/a/**]}]
allowed_dependencies: []
patterns:
  - {id: bad, layer: a, forbidden_imports: requests}
""".strip()
        )


def test_paths_non_string_rejected():
    with pytest.raises(ArchitectureSchemaError, match="non-empty list of strings"):
        parse_architecture(
            """
version: 1
layers:
  - {name: a, paths: ["src/a/**", 42]}
allowed_dependencies: []
""".strip()
        )


def test_layer_name_non_string_rejected():
    with pytest.raises(ArchitectureSchemaError, match="name must be a string"):
        parse_architecture(
            """
version: 1
layers:
  - {name: 42, paths: [src/a/**]}
allowed_dependencies: []
""".strip()
        )


def test_duplicate_layer_name_names_offender():
    with pytest.raises(ArchitectureSchemaError, match="duplicate layer name 'domain'"):
        parse_architecture(
            """
version: 1
layers:
  - {name: domain, paths: [src/d1/**]}
  - {name: domain, paths: [src/d2/**]}
allowed_dependencies: []
""".strip()
        )
