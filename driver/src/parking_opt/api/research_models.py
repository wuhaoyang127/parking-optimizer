"""Independent additive research-release 1.0.0 contracts; no executable uploads."""
from typing import Literal
from pydantic import Field, StrictBool, StrictFloat, StrictInt, model_validator
from parking_opt.api.models import ContractModel, Identifier
from parking_opt.api.research_inputs import HistoricalDurationModel


class ResearchRelease(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    release_id: Identifier
    algorithm_id: Literal["fcfs", "nearest", "random", "greedy", "departure_greedy",
        "duration_greedy", "risk_scoring", "peak_offpeak_fusion", "rho_rolling", "ml_duration_tree"]
    algorithm_version: Literal["stage-d-bridge-1", "stage-d-bridge-2"] = "stage-d-bridge-2"
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    params: dict[str, StrictBool | StrictInt | StrictFloat | str] = Field(default_factory=dict, max_length=16)
    seed: int = Field(default=0, ge=0, le=4294967295)
    model: HistoricalDurationModel | None = None
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def model_binding(self):
        if (self.algorithm_id == "ml_duration_tree") != (self.model is not None):
            raise ValueError("ML_MODEL_REQUIRED_ONLY_FOR_ML_STRATEGY")
        if self.model and self.params.get("use_entry", self.model.use_entry) != self.model.use_entry:
            raise ValueError("ML_FEATURE_CONTRACT_MISMATCH")
        if self.model and any(self.params.get(key, getattr(self.model, key)) != getattr(self.model, key)
                              for key in ("max_depth", "min_samples_leaf")):
            raise ValueError("ML_TRAINING_PARAMETER_MISMATCH")
        return self


class DriverActivation(ContractModel):
    release_id: Identifier | None = None
    expected_active_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class TrialStartRequest(ContractModel):
    release_id: Identifier
    ratio: float = Field(default=1 / 3, gt=0, le=1)
    research_score: float = Field(ge=0, le=100)


class TrialDecision(ContractModel):
    release_id: Identifier
    decision: Literal["promote", "discard"]


class TrialRatioUpdate(ContractModel):
    ratio: float = Field(gt=0, le=1)
