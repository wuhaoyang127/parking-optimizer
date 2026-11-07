"""Structured validation errors with JSON Pointer and frozen constraint IDs."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One actionable contract validation failure."""

    error_code: str
    json_pointer: str
    constraint_id: str
    message: str
    observed_value: object | None = None


class ContractValidationError(ValueError):
    """Raised when one or more schema or semantic constraints fail."""

    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        if not issues:
            raise ValueError("ContractValidationError requires at least one issue")
        self.issues = issues
        summary = "; ".join(
            f"{issue.constraint_id} at {issue.json_pointer}: {issue.message}" for issue in issues
        )
        super().__init__(summary)
