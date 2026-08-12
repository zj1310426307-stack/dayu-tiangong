"""Typed HTTP contracts for optimization configuration, progress and results."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ObjectiveWeights(BaseModel):
    """Configure the three Phase 5 objective weights."""

    model_config = ConfigDict(extra="forbid")
    flood_risk: float = Field(default=0.5, ge=0)
    energy_cost: float = Field(default=0.3, ge=0)
    operation_cost: float = Field(default=0.2, ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> "ObjectiveWeights":
        """Reject a score that has no active objective."""

        if self.flood_risk + self.energy_cost + self.operation_cost <= 0:
            raise ValueError("at least one objective weight must be positive")
        return self


class ObjectiveNormalization(BaseModel):
    """Version the physical scales used to make objective terms comparable."""

    model_config = ConfigDict(extra="forbid")
    maximum_water_level: float = Field(default=400, gt=0)
    warning_duration: float = Field(default=3600, gt=0)
    guarantee_duration: float = Field(default=3600, gt=0)
    pump_energy_kwh: float = Field(default=1000, gt=0)
    pump_runtime_seconds: float = Field(default=3600, gt=0)
    pump_start_count: float = Field(default=10, gt=0)
    gate_action_count: float = Field(default=20, gt=0)
    gate_cumulative_opening_change: float = Field(default=10, gt=0)
    pump_stop_count: float = Field(default=10, gt=0)


class ObjectiveConfig(BaseModel):
    """Freeze score version, thresholds, weights and normalization constants."""

    model_config = ConfigDict(extra="forbid")
    version: Literal["dayu.objectives.v1"] = "dayu.objectives.v1"
    weights: ObjectiveWeights = Field(default_factory=ObjectiveWeights)
    normalization: ObjectiveNormalization = Field(default_factory=ObjectiveNormalization)
    warning_level: float | None = None
    guarantee_level: float | None = None


class HydraulicLimits(BaseModel):
    """Configure post-simulation hydraulic and pump hard limits."""

    model_config = ConfigDict(extra="forbid")
    maximum_water_level: float | None = None
    maximum_flow: float | None = Field(default=None, ge=0)
    maximum_pump_power_kw: float | None = Field(default=None, ge=0)


class ConstraintConfig(BaseModel):
    """Configure plan and outcome feasibility checks."""

    model_config = ConfigDict(extra="forbid")
    maximum_actions_per_asset: int = Field(default=8, ge=1, le=40)
    maximum_pump_starts: int = Field(default=8, ge=1, le=100)
    invalid_penalty: float = Field(default=1_000_000, gt=0)
    hydraulic_limits: HydraulicLimits = Field(default_factory=HydraulicLimits)


class AlgorithmConfig(BaseModel):
    """Configure seeded PSO and its Phase 4 simulation resolution."""

    model_config = ConfigDict(extra="forbid")
    particle_count: int = Field(default=4, ge=2, le=40)
    max_iterations: int = Field(default=3, ge=1, le=25)
    inertia: float = Field(default=0.65, ge=0, le=1.5)
    cognitive: float = Field(default=1.4, ge=0, le=4)
    social: float = Field(default=1.4, ge=0, le=4)
    tolerance: float = Field(default=1e-4, ge=0)
    patience: int = Field(default=4, ge=1, le=25)
    seed: int = 42
    duration_seconds: float = Field(default=600, gt=0, le=86400)
    time_step_seconds: float = Field(default=10, gt=0)
    output_interval_seconds: float = Field(default=60, gt=0)
    constraints: ConstraintConfig = Field(default_factory=ConstraintConfig)


class OptimizationTaskCreate(BaseModel):
    """Create a pending optimization against one versioned simulation case."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    algorithm: Literal["pso"] = "pso"
    dataset_version_id: int = Field(gt=0)
    simulation_case_id: int = Field(gt=0)
    objective_config: ObjectiveConfig = Field(default_factory=ObjectiveConfig)
    algorithm_config: AlgorithmConfig = Field(default_factory=AlgorithmConfig)


class OptimizationTaskRecord(BaseModel):
    """Expose optimization lifecycle, frozen provenance and progress."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    algorithm: str
    status: Literal["pending", "running", "success", "failed", "cancelled"]
    dataset_version_id: int
    simulation_case_id: int
    objective_config: dict[str, Any]
    algorithm_config: dict[str, Any]
    input_snapshot_hash: str
    algorithm_version: str
    progress: int
    current_generation: int
    best_score: float | None
    queue_job_id: str | None
    worker_id: str | None
    cancel_requested: bool
    converged: bool
    error_message: str | None
    created_time: datetime
    start_time: datetime | None
    end_time: datetime | None
    candidate_count: int = 0
    pareto_count: int = 0
    recommended_candidate_id: int | None = None


class OptimizationCandidateRecord(BaseModel):
    """Expose one candidate and its linked hydraulic evidence."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    task_id: int
    generation: int
    candidate_index: int
    dispatch_plan: dict[str, Any]
    score: float | None
    objective_values: dict[str, Any] | None
    metrics: dict[str, Any] | None
    valid: bool
    constraint_reasons: list[str]
    simulation_task_id: int | None
    created_time: datetime


class ParetoCandidateRecord(OptimizationCandidateRecord):
    """Add Pareto and recommendation metadata to a candidate."""

    pareto_level: int
    rank: int
    recommendation_status: str
    explanation: dict[str, Any]


class RecommendationResponse(BaseModel):
    """Return the recommended candidate for human review only."""

    task_id: int
    candidate: ParetoCandidateRecord | None
    execution_authorized: Literal[False] = False
    notice: str = "仅供人工复核；不会向真实设备发送任何命令。"


class OptimizationExplanation(BaseModel):
    """Provide deterministic, auditable recommendation wording without AI."""

    task_id: int
    candidate_id: int | None
    explanation_type: Literal["deterministic_template"] = "deterministic_template"
    summary: str
    factors: list[str]
    limitations: list[str]
