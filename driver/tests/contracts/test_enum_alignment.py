"""Selected Python enums must match the frozen schema enumerations exactly."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

import pytest

from parking_opt.domain.enums import (
    ActionStatus,
    ActionType,
    DepartureInformationSource,
    ExecutorType,
    RecoverabilityPolicy,
    ReservationStatus,
    SolverStatus,
    ValidationStatus,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _values(enum_type: type[StrEnum]) -> set[str]:
    return {member.value for member in enum_type}


def _common_defs() -> dict[str, object]:
    path = REPO_ROOT / "schemas" / "v1" / "common.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))["$defs"]


@pytest.mark.parametrize(
    ("enum_type", "definition_name"),
    [
        (RecoverabilityPolicy, "recoverabilityPolicy"),
        (ExecutorType, "executorType"),
        (ReservationStatus, "reservationStatus"),
        (ActionType, "actionType"),
        (ActionStatus, "actionStatus"),
        (SolverStatus, "solverStatus"),
        (ValidationStatus, "validationStatus"),
    ],
)
def test_enum_matches_common_schema(
    enum_type: type[StrEnum],
    definition_name: str,
) -> None:
    definition = _common_defs()[definition_name]
    assert isinstance(definition, dict)
    assert _values(enum_type) == set(definition["enum"])


def test_departure_information_sources_match_schema() -> None:
    definition = _common_defs()["departureInformation"]
    assert isinstance(definition, dict)
    sources = definition["properties"]["source"]["enum"]
    assert _values(DepartureInformationSource) == set(sources)
