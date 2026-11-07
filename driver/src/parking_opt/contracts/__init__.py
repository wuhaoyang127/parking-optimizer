"""Schema, hashing, and semantic contract validation."""

from parking_opt.contracts.canonical import canonical_json_bytes, canonical_sha256
from parking_opt.contracts.errors import ContractValidationError, ValidationIssue
from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.contracts.semantic_validation import (
    assert_no_forbidden_fields,
    validate_decision_request_semantics,
    validate_layout_semantics,
    validate_scenario_semantics,
    validate_snapshot_semantics,
)
from parking_opt.contracts.snapshot_projection import (
    observed_snapshot_to_mapping,
    project_observed_snapshot,
)

__all__ = [
    "ContractValidationError",
    "SchemaCatalog",
    "ValidationIssue",
    "assert_no_forbidden_fields",
    "canonical_json_bytes",
    "canonical_sha256",
    "observed_snapshot_to_mapping",
    "project_observed_snapshot",
    "validate_decision_request_semantics",
    "validate_layout_semantics",
    "validate_scenario_semantics",
    "validate_snapshot_semantics",
]
