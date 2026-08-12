"""HTTP contracts for Phase 3 hydraulic tasks and time-series results."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


TaskStatus = Literal[
    "pending", "queued", "running", "cancel_requested", "cancelled", "success", "failed"
]


class SimulationTaskCreate(BaseModel):
    """Create a pending task from a versioned Phase 2 simulation case."""

    model_config = ConfigDict(extra="forbid")

    case_id: int = Field(gt=0)
    duration_seconds: float | None = Field(default=None, gt=0)
    time_step_seconds: float | None = Field(default=None, gt=0)
    output_interval_seconds: float | None = Field(default=None, gt=0)
    cfl_number: float | None = Field(default=None, gt=0, le=1)
    initial_water_level: float | None = None
    initial_flow: float | None = None
    minimum_depth: float | None = Field(default=None, gt=0)
    input_schema_version: Literal["dayu.model-input.v1", "dayu.model-input.v2"] = (
        "dayu.model-input.v1"
    )
    allow_fallback_boundary: bool = False
    section_geometry: Literal["rectangular", "tabulated"] = "rectangular"
    storage_level: Literal["summary", "key_sections", "full"] = "full"


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
    snapshot_summary: dict[str, Any] | None = None
    queue_job_id: str | None
    worker_id: str | None
    queued_time: datetime | None
    heartbeat_time: datetime | None
    cancel_requested: bool
    retry_count: int
    retry_reason: str | None
    current_simulation_time: float | None
    current_cfl: float | None
    diagnostics: dict[str, Any] | None
    result_path: str | None
    error_message: str | None
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
