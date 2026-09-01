"""Public contracts for the solver-neutral Standard 1D task chain."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator

from model.hydraulic_1d import (
    DEFAULT_HYDRAULIC_1D_ENGINE_ID,
    DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
    HYDRAULIC_1D_INPUT_SCHEMA,
)


TaskStatus = Literal[
    "pending", "queued", "running", "cancel_requested", "cancelled", "success", "failed"
]


class RoughnessOverride(BaseModel):
    """Apply one calibration candidate to an explicit Cross Section group."""

    model_config = ConfigDict(extra="forbid")

    group_id: str = Field(min_length=1, max_length=128)
    cross_section_ids: list[int] = Field(min_length=1)
    manning_n: FiniteFloat = Field(gt=0, le=0.3)

    @field_validator("cross_section_ids", mode="before")
    @classmethod
    def reject_boolean_targets(cls, value: object) -> object:
        """Do not allow JSON booleans to coerce into integer database identities."""

        if isinstance(value, list) and any(isinstance(item, bool) for item in value):
            raise ValueError("roughness override cross_section_ids must contain integers")
        return value

    @model_validator(mode="after")
    def validate_targets(self) -> "RoughnessOverride":
        """Reject duplicated targets inside one parameter group."""

        if len(self.cross_section_ids) != len(set(self.cross_section_ids)):
            raise ValueError("roughness override cross_section_ids must be unique")
        if any(value <= 0 for value in self.cross_section_ids):
            raise ValueError("roughness override cross_section_ids must be positive")
        return self


class SimulationTaskCreate(BaseModel):
    """Create an immutable Standard 1D task from one Simulation Case."""

    model_config = ConfigDict(extra="forbid")

    case_id: int = Field(gt=0)
    duration_seconds: FiniteFloat | None = Field(default=None, gt=0)
    time_step_seconds: FiniteFloat | None = Field(default=None, gt=0)
    output_interval_seconds: FiniteFloat | None = Field(default=None, gt=0)
    initial_water_level: FiniteFloat | None = None
    initial_flow: FiniteFloat | None = None
    engine: Literal[DEFAULT_HYDRAULIC_1D_ENGINE_ID] = DEFAULT_HYDRAULIC_1D_ENGINE_ID
    input_schema_version: Literal[HYDRAULIC_1D_INPUT_SCHEMA] = HYDRAULIC_1D_INPUT_SCHEMA
    storage_level: Literal["full"] = "full"
    roughness_overrides: list[RoughnessOverride] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_initial_override_pair(self) -> "SimulationTaskCreate":
        """Forbid a half-specified initial-state override."""

        supplied = (self.initial_water_level is not None, self.initial_flow is not None)
        if supplied[0] != supplied[1]:
            raise ValueError("initial_water_level and initial_flow must be supplied together")
        group_ids = [item.group_id for item in self.roughness_overrides]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("roughness override group_id values must be unique")
        targets = [
            section_id
            for group in self.roughness_overrides
            for section_id in group.cross_section_ids
        ]
        if len(targets) != len(set(targets)):
            raise ValueError("a Cross Section cannot belong to two roughness override groups")
        return self


class SimulationTaskRecord(BaseModel):
    """Expose durable lifecycle, external-engine identity, and diagnostics."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int
    dataset_version_id: int
    status: TaskStatus
    progress: int = Field(ge=0, le=100)
    config: dict[str, Any]
    input_schema_version: str | None
    input_snapshot_hash: str | None
    engine_version: str | None
    engine_commit: str | None
    solver_build_id: str | None
    build_mode: str | None
    build_verified: bool
    solver_id: str | None
    capability_id: str | None
    runtime_adapter_id: str | None
    result_schema_version: str | None
    registry_hash: str | None
    execution_phase: str | None
    snapshot_summary: dict[str, Any] | None = None
    queue_job_id: str | None
    delivery_attempt_count: int
    last_delivery_time: datetime | None
    worker_id: str | None
    queued_time: datetime | None
    heartbeat_time: datetime | None
    cancel_requested: bool
    execution_attempt_count: int
    manual_retry_count: int
    infrastructure_retry_count: int
    retry_reason: str | None
    diagnostics: dict[str, Any] | None
    result_path: str | None
    error_message: str | None
    last_infrastructure_error: str | None
    retry_eligible: bool = False
    retry_block_reason: str | None = None
    created_time: datetime
    start_time: datetime | None
    end_time: datetime | None


class TaskSnapshotResponse(BaseModel):
    """Return the immutable unified input and its build provenance."""

    task_id: int
    input_schema_version: str
    input_snapshot_hash: str
    engine_version: str
    engine_commit: str
    solver_build_id: str | None
    build_mode: str | None
    build_verified: bool
    snapshot: dict[str, Any]


class ResultSectionOption(BaseModel):
    """Identify one Cross Section available within a unified result."""

    section_id: int
    section_code: str
    branch_id: int
    chainage_m: float


class SimulationResultResponse(BaseModel):
    """Return aligned Standard 1D series without exposing MASCARET files."""

    task_id: int
    status: TaskStatus
    simulation_id: str
    scenario_id: str
    engine: str
    engine_version: str
    section_id: int
    section_code: str
    branch_id: int
    chainage_m: float
    time: list[float]
    water_level: list[float]
    depth: list[float | None]
    flow: list[float]
    velocity: list[float]
    flow_area: list[float | None]
    wet_area: list[float | None]
    hydraulic_radius: list[float | None]
    top_width: list[float | None]
    froude_number: list[float | None]
    available_sections: list[ResultSectionOption]
    diagnostics: dict[str, Any] | None


class Hydraulic1DReadinessResponse(BaseModel):
    """Explain Case mapping readiness and external runtime availability."""

    case_id: int
    ready: bool
    engine_id: Literal[DEFAULT_HYDRAULIC_1D_ENGINE_ID] = DEFAULT_HYDRAULIC_1D_ENGINE_ID
    engine_version: Literal[DEFAULT_HYDRAULIC_1D_ENGINE_VERSION] = (
        DEFAULT_HYDRAULIC_1D_ENGINE_VERSION
    )
    runtime_available: bool
    runtime_detail: str
    runtime_identity: dict[str, Any]
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    input_summary: dict[str, Any] | None = None


class Hydraulic1DPreviewResponse(BaseModel):
    """Return a mapping preview without creating a Task or workspace."""

    readiness: Hydraulic1DReadinessResponse
    snapshot_hash: str | None = None
    snapshot: dict[str, Any] | None = None
