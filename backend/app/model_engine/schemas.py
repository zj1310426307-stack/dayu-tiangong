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
    calculation_mode: Literal["steady", "unsteady"] = "unsteady"
    overbank_treatment: Literal["profile", "vertical_extension"] = "profile"
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
    task_kind: Literal["standard_1d", "controlled_hydraulic_preview"] = "standard_1d"
    evidence_class: str | None = None
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


class SimulationResultOverviewSection(BaseModel):
    """Expose one final-state Cross Section sample for scheme-level review."""

    section_id: int
    section_code: str
    branch_id: int
    chainage_m: FiniteFloat = Field(ge=0)
    time_seconds: FiniteFloat = Field(ge=0)
    water_level_m: FiniteFloat
    bed_elevation_m: FiniteFloat | None = None
    depth_m: FiniteFloat | None = Field(default=None, ge=0)
    flow_m3s: FiniteFloat
    velocity_m_s: FiniteFloat
    flow_area_m2: FiniteFloat | None = Field(default=None, ge=0)
    top_width_m: FiniteFloat | None = Field(default=None, ge=0)
    froude_number: FiniteFloat | None = Field(default=None, ge=0)


class SimulationResultOverviewStructure(BaseModel):
    """Expose one Gate/Pump state at the common final hydraulic time."""

    structure_type: Literal["gate", "pump"]
    structure_id: int = Field(gt=0)
    time_seconds: FiniteFloat = Field(ge=0)
    requested_value: FiniteFloat | None = None
    resolved_value: FiniteFloat | None = None
    applied_value: FiniteFloat | None = None
    flow_m3s: FiniteFloat
    upstream_water_level_m: FiniteFloat | None = None
    downstream_water_level_m: FiniteFloat | None = None
    head_difference_m: FiniteFloat | None = None
    native_applied_capacity_m3s: FiniteFloat | None = None
    actual_discharge_m3s: FiniteFloat | None = None
    pump_head_m: FiniteFloat | None = None
    pump_reduction_factor: FiniteFloat | None = Field(default=None, ge=0, le=1)
    pump_actual_stage: int | None = Field(default=None, ge=0)
    regime: str | None = None


class SimulationResultOverviewResponse(BaseModel):
    """Return a successful task as a directly viewable engineering scheme result."""

    task_id: int
    case_id: int
    dataset_version_id: int
    status: TaskStatus
    task_kind: Literal["standard_1d", "controlled_hydraulic_preview"] = "standard_1d"
    simulation_id: str
    scenario_id: str
    engine: str
    engine_version: str
    calculation_mode: Literal["steady", "unsteady"] | None = None
    evidence_class: str | None = None
    final_time_seconds: FiniteFloat = Field(ge=0)
    created_time: datetime
    end_time: datetime | None
    section_summary: list[SimulationResultOverviewSection] = Field(
        min_length=1, max_length=5000
    )
    structure_summary: list[SimulationResultOverviewStructure] = Field(
        default_factory=list, max_length=1000
    )
    diagnostics: dict[str, Any] | None


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


class ScenarioResultQualityGate(BaseModel):
    """Expose the numerical checks attached to one published scenario."""

    temporal_converged: bool
    mass_balance_residual: FiniteFloat
    mass_balance_tolerance: FiniteFloat = Field(gt=0)
    final_discharge_span_m3s: FiniteFloat = Field(ge=0)
    final_discharge_span_tolerance_m3s: FiniteFloat = Field(gt=0)
    passed: bool


class ScenarioResultSection(BaseModel):
    """Describe one upstream-to-downstream final-state Section sample."""

    cross_section_id: str = Field(min_length=1, max_length=128)
    chainage_m: FiniteFloat = Field(ge=0)
    bed_min_m: FiniteFloat
    final_water_level_m: FiniteFloat
    final_depth_m: FiniteFloat = Field(ge=0)
    final_discharge_m3s: FiniteFloat
    final_velocity_ms: FiniteFloat
    flow_area_m2: FiniteFloat = Field(gt=0)


class PublishedScenarioResult(BaseModel):
    """Return one accepted numerical scenario without claiming calibration."""

    scenario_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=128)
    q_m3s: FiniteFloat
    downstream_h_m: FiniteFloat
    status: str = Field(min_length=1, max_length=64)
    mesh_spacing_m: FiniteFloat = Field(gt=0)
    time_step_seconds: FiniteFloat = Field(gt=0)
    duration_seconds: FiniteFloat = Field(gt=0)
    upstream_water_level_m: FiniteFloat
    maximum_water_level_m: FiniteFloat
    minimum_depth_m: FiniteFloat = Field(ge=0)
    maximum_velocity_ms: FiniteFloat = Field(ge=0)
    final_discharge_span_m3s: FiniteFloat = Field(ge=0)
    mass_balance_residual: FiniteFloat = Field(ge=0)
    quality_gate: ScenarioResultQualityGate
    section_summary: list[ScenarioResultSection] = Field(min_length=2, max_length=500)


class PublishedScenarioBundle(BaseModel):
    """Represent a locally published, solver-neutral engineering result bundle."""

    bundle_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    title: str = Field(min_length=1, max_length=200)
    river_name: str = Field(min_length=1, max_length=128)
    schema_version: str
    generated_at: datetime
    classification: str
    acceptance: str
    not_claimed: list[str]
    input: dict[str, Any]
    physical_assumptions: dict[str, Any]
    numerical_acceptance: dict[str, Any]
    runtime_provenance: dict[str, Any]
    scenarios: list[PublishedScenarioResult] = Field(min_length=1, max_length=20)
    source_digest: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")


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
