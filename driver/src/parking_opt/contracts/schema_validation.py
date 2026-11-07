"""Draft 2020-12 validation for the approved v1 schema catalog."""

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from parking_opt.contracts.errors import ContractValidationError, ValidationIssue


def _json_pointer(parts: list[object]) -> str:
    if not parts:
        return "/"
    escaped = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(escaped)


class SchemaCatalog:
    """Load and validate the single approved `schemas/v1` directory."""

    def __init__(self, schema_dir: Path) -> None:
        self.schema_dir = schema_dir.resolve()
        if not self.schema_dir.is_dir():
            raise FileNotFoundError(f"schema directory does not exist: {self.schema_dir}")

        schemas: dict[str, dict[str, Any]] = {}
        resources: list[tuple[str, Resource[Any]]] = []
        for path in sorted(self.schema_dir.glob("*.schema.json")):
            with path.open("r", encoding="utf-8") as handle:
                schema = json.load(handle)
            if not isinstance(schema, dict):
                raise TypeError(f"schema root must be an object: {path}")
            Draft202012Validator.check_schema(schema)
            schema_id = schema.get("$id")
            if not isinstance(schema_id, str):
                raise ValueError(f"schema is missing a string $id: {path}")
            schemas[path.name] = schema
            resources.append((schema_id, Resource.from_contents(schema)))

        if len(schemas) != 8:
            raise ValueError(f"expected 8 v1 schemas, found {len(schemas)}")
        self._schemas = schemas
        self._registry = Registry().with_resources(resources)

    @property
    def names(self) -> tuple[str, ...]:
        """Return schema filenames in deterministic order."""

        return tuple(sorted(self._schemas))

    def validate(self, schema_name: str, instance: object) -> None:
        """Validate an instance and raise structured issues on failure."""

        try:
            schema = self._schemas[schema_name]
        except KeyError as exc:
            raise KeyError(f"unknown schema: {schema_name}") from exc
        validator = Draft202012Validator(
            schema,
            registry=self._registry,
            format_checker=FormatChecker(),
        )
        errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path))
        if not errors:
            return
        issues = tuple(
            ValidationIssue(
                error_code="SCHEMA_VALIDATION_FAILED",
                json_pointer=_json_pointer(list(error.absolute_path)),
                constraint_id=f"schema:{schema_name}:{error.validator}",
                message=error.message,
                observed_value=error.instance,
            )
            for error in errors
        )
        raise ContractValidationError(issues)
