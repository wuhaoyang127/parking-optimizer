"""Additive visible-observation and portable prediction-model contracts."""
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Literal
from pydantic import AwareDatetime, Field, model_validator
from parking_opt.api.models import ContractModel, Identifier


class HistoricalDurationModel(ContractModel):
    contract: Literal["cart-duration-1.0.0"] = "cart-duration-1.0.0"
    source: Literal["synthetic", "observed"]
    trained_before: AwareDatetime
    training_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    sample_count: int = Field(ge=10, le=1000)
    holdout_mae_s: float = Field(ge=0, le=604800)
    entries: tuple[Identifier, ...] = Field(max_length=32)
    use_entry: bool
    max_depth: int = Field(default=4, ge=2, le=8)
    min_samples_leaf: int = Field(default=5, ge=1, le=20)
    threshold_s: float = Field(gt=0, le=604800)
    fallback_s: float = Field(gt=0, le=604800)
    degenerate: bool
    tree: dict[str, Any]

    @model_validator(mode="after")
    def validate_tree(self):
        count = 0
        def visit(node, depth=0):
            nonlocal count
            count += 1
            if count > 511 or depth > 8 or not isinstance(node, dict):
                raise ValueError("MODEL_TREE_LIMIT")
            value = node.get("value")
            if type(value) not in (float, int) or not isfinite(value) or not 0 < value <= 604800:
                raise ValueError("MODEL_LEAF_VALUE")
            if set(node) == {"value"}:
                return
            if set(node) != {"value", "feature", "threshold", "left", "right"}:
                raise ValueError("MODEL_NODE_FIELDS")
            feature, threshold = node["feature"], node["threshold"]
            if (type(feature) is not int or not 0 <= feature < 1 + (len(self.entries) if self.use_entry else 0)
                    or type(threshold) not in (float, int) or not isfinite(threshold)):
                raise ValueError("MODEL_FEATURE_OR_THRESHOLD")
            visit(node["left"], depth + 1)
            visit(node["right"], depth + 1)
        visit(self.tree)
        if len(self.entries) != len(set(self.entries)) or self.trained_before > datetime.now(UTC):
            raise ValueError("MODEL_ENTRIES_OR_TRAINING_TIME")
        return self


class ArrivalObservation(ContractModel):
    event_id: Identifier
    occurred_at: AwareDatetime
    expected_duration_s: float | None = Field(default=None, gt=0, le=604800)
    estimate_source: Literal["user_estimate", "prediction", "unknown"] = "unknown"

    @model_validator(mode="after")
    def visible_estimate(self):
        if (self.expected_duration_s is None) != (self.estimate_source == "unknown"):
            raise ValueError("ARRIVAL_DURATION_SOURCE_REQUIRED")
        return self


class OccupantEstimate(ContractModel):
    space_id: Identifier
    arrival_at: AwareDatetime
    expected_departure_at: AwareDatetime | None = None
    known_at: AwareDatetime
    source: Literal["user_estimate", "prediction", "unknown"] = "unknown"
    entrance_node_id: Identifier | None = None

    @model_validator(mode="after")
    def estimate_source(self):
        if (self.expected_departure_at is None) != (self.source == "unknown"):
            raise ValueError("DEPARTURE_ESTIMATE_SOURCE_REQUIRED")
        if self.expected_departure_at is not None and self.expected_departure_at <= self.arrival_at:
            raise ValueError("DEPARTURE_MUST_FOLLOW_ARRIVAL")
        return self


class VisibleObservations(ContractModel):
    contract: Literal["visible-observations-1.0.0"] = "visible-observations-1.0.0"
    session_id: Identifier
    parking_lot_id: Identifier
    layout_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed_at: AwareDatetime
    source: Literal["synthetic", "observed"]
    arrivals: tuple[ArrivalObservation, ...] = Field(default=(), max_length=256)
    occupants: tuple[OccupantEstimate, ...] = Field(default=(), max_length=512)

    @model_validator(mode="after")
    def visible_at_time(self):
        if self.observed_at > datetime.now(UTC):
            raise ValueError("OBSERVATION_FROM_FUTURE")
        if len({a.event_id for a in self.arrivals}) != len(self.arrivals):
            raise ValueError("DUPLICATE_ARRIVAL_EVENT")
        if len({a.space_id for a in self.occupants}) != len(self.occupants):
            raise ValueError("DUPLICATE_OCCUPANT")
        if any(a.occurred_at > self.observed_at or (self.observed_at-a.occurred_at).total_seconds() > 86400
               for a in self.arrivals):
            raise ValueError("ARRIVAL_OUTSIDE_VISIBLE_WINDOW")
        if any(a.known_at > self.observed_at or a.arrival_at > self.observed_at
               for a in self.occupants):
            raise ValueError("OCCUPANT_INFORMATION_FROM_FUTURE")
        return self
