"""HTTP contracts for Phase 3 hydraulic tasks and time-series results."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from model.solver.registry import (
    D1_CAPABILITY_ID,
    D1_SOLVER_ID,
    D3A_1_CAPABILITY_ID,
    D3A_2_CAPABILITY_ID,
    D3A_3_CAPABILITY_ID,
)


TaskStatus = Literal[
    "pending", "queued", "running", "cancel_requested", "cancelled", "success", "failed"
]


class SimulationTaskCreate(BaseModel):
    """Create a pending task from a versioned Phase 2 simulation case."""

    model_config = ConfigDict(extra="forbid")

    case_id: int = Field(gt=0)
    duration_seconds: FiniteFloat | None = Field(default=None, gt=0)
    time_step_seconds: FiniteFloat | None = Field(default=None, gt=0)
    output_interval_seconds: FiniteFloat | None = Field(default=None, gt=0)
    cfl_number: FiniteFloat | None = Field(default=None, gt=0, le=1)
    initial_water_level: FiniteFloat | None = None
    initial_flow: FiniteFloat | None = None
    minimum_depth: FiniteFloat | None = Field(default=None, gt=0)
    input_schema_version: Literal[
        "dayu.model-input.v1",
        "dayu.model-input.v2",
        "dayu.model-input.v3",
        "dayu.model-input.v4",
    ] = (
        "dayu.model-input.v1"
    )
    solver_id: str | None = Field(default=None, min_length=1, max_length=96)
    capability_id: Literal[
        D1_CAPABILITY_ID,
        D3A_1_CAPABILITY_ID,
        D3A_2_CAPABILITY_ID,
        D3A_3_CAPABILITY_ID,
    ] | None = None
    dispatch_plan_id: int | None = Field(default=None, gt=0)
    execution_mode: Literal["validation", "shadow"] = "validation"
    allow_fallback_boundary: bool = False
    section_geometry: Literal["rectangular", "tabulated"] = "rectangular"
    storage_level: Literal["summary", "key_sections", "full"] = "full"

    @model_validator(mode="after")
    def validate_solver_boundary(self) -> "SimulationTaskCreate":
        """Forbid v4 physical overrides and require its frozen solver/control identities."""

        physical_overrides = {
            "duration_seconds",
            "time_step_seconds",
            "output_interval_seconds",
            "cfl_number",
            "initial_water_level",
            "initial_flow",
            "minimum_depth",
            "allow_fallback_boundary",
            "section_geometry",
        }
        if self.input_schema_version == "dayu.model-input.v4":
            supplied = sorted(physical_overrides.intersection(self.model_fields_set))
            if supplied:
                raise ValueError(
                    "native v4 forbids runtime physical overrides: " + ", ".join(supplied)
                )
            if self.solver_id is not None and self.solver_id != D1_SOLVER_ID:
                raise ValueError(
                    f"native v4 solver assertion must equal {D1_SOLVER_ID}"
                )
            if self.capability_id is None:
                raise ValueError("native v4 requires an explicit capability_id")
            if self.dispatch_plan_id is None:
                raise ValueError("native v4 requires one frozen dispatch_plan_id")
            if self.storage_level != "full":
                raise ValueError("native v4 supports storage_level=full only")
        elif self.dispatch_plan_id is not None or self.capability_id is not None:
            raise ValueError(
                "dispatch_plan_id/capability_id on the generic task endpoint are reserved for v4"
            )
        return self


class SimulationTaskRecord(BaseModel):
    """Expose the durable lifecycle and diagnostics of one hydraulic execution."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int
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
    execution_mode: str | None
    execution_phase: str | None
    runtime_projection_hash: str | None
    mesh_hash: str | None
    solver_policy_hash: str | None
    validation_policy_hash: str | None
    registry_hash: str | None
    artifact_status: str | None
    comparison_group_id: int | None
    group_role: str | None
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
    numerical_retry_count: int
    retry_count: int = Field(
        deprecated=True,
        description=(
            "Deprecated legacy aggregate retry counter; use infrastructure_retry_count "
            "and numerical_retry_count for RC1 retry semantics."
        ),
    )
    accepted_step_count: int
    cfl_reduction_count: int
    positivity_retry_count: int
    event_refinement_count: int
    gate_solver_retry_count: int
    pump_solver_retry_count: int
    minimum_dt_failure_count: int
    retry_reason: str | None
    current_simulation_time: float | None
    current_cfl: float | None
    diagnostics: dict[str, Any] | None
    last_event: dict[str, Any] | None
    result_path: str | None
    error_message: str | None
    last_infrastructure_error: str | None
    retry_eligible: bool = False
    retry_block_reason: str | None = None
    created_time: datetime
    start_time: datetime | None
    end_time: datetime | None


class TaskSnapshotResponse(BaseModel):
    """返回冻结输入、哈希和引擎来源，供受限下载与审计。"""

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
    """Identify one section available within a task result."""

    section_id: int | None
    section_code: str
    river_id: int | None
    station: float


class SimulationResultResponse(BaseModel):
    """Return aligned time series for one selected section."""

    task_id: int
    status: TaskStatus
    section_id: int | None
    section_code: str
    river_id: int | None
    station: float
    time: list[float]
    water_level: list[float]
    flow: list[float]
    velocity: list[float]
    available_sections: list[ResultSectionOption]
    diagnostics: dict[str, Any] | None
