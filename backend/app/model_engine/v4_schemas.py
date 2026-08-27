"""HTTP contracts for native-v4 readiness, preview, and projection evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class V4ReadinessIssue(BaseModel):
    """Describe one actionable, entity-scoped v4 preflight finding."""

    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["error", "warning"]
    entity_type: str
    entity_id: int | str | None = None
    field_path: str
    message: str


class V4ReadinessResponse(BaseModel):
    """Return fail-closed readiness and safe candidate identity summaries."""

    ready: bool
    solver_id: str
    capability_id: str
    runtime_adapter_id: str
    errors: list[V4ReadinessIssue]
    warnings: list[V4ReadinessIssue]
    snapshot_summary: dict[str, Any] = Field(default_factory=dict)
    candidate_hashes: dict[str, str] = Field(default_factory=dict)


class V4PreviewResponse(BaseModel):
    """Expose a bounded v4 summary without returning the complete frozen snapshot."""

    schema_version: str
    solver_id: str
    capability_id: str
    dataset_version_id: int | None
    simulation_case_id: int | None
    branch: dict[str, Any] | None
    section_count: int
    gate: dict[str, Any] | None
    pump: dict[str, Any] | None
    boundary_time_range: dict[str, float | None]
    simulation_duration_seconds: float | None
    hashes: dict[str, str]
    readiness: V4ReadinessResponse
    known_limitations: list[str]


class V4SectionOption(BaseModel):
    """Identify one authoritative hydraulic Section available in a v4 task."""

    hydraulic_cross_section_id: int
    section_code: str
    branch_id: int
    chainage_m: float


class V4SectionResultResponse(V4SectionOption):
    """Return one output-interval Section series without stage-level evidence."""

    task_id: int
    time_seconds: list[float]
    water_level_m: list[float]
    flow_m3s: list[float]
    velocity_m_s: list[float]
    control_volume_m3: list[float]
    available_sections: list[V4SectionOption]


class V4GateResultRecord(BaseModel):
    """Expose one output-interval completed-interface Gate row."""

    model_config = ConfigDict(from_attributes=True)

    time_seconds: float
    canonical_gate_id: int
    opening_m: float
    flow_m3s: float
    upstream_stage_m: float
    downstream_stage_m: float
    head_loss_m: float | None
    reaction_force_per_density: float | None
    regime: str | None


class V4PumpResultRecord(BaseModel):
    """Expose one output-interval external Pump operating point."""

    model_config = ConfigDict(from_attributes=True)

    time_seconds: float
    canonical_pump_id: int
    control_state: str
    running_units: int
    flow_m3s: float
    source_stage_m: float
    outlet_stage_m: float
    pump_head_m: float
    system_head_m: float
    efficiency: float
    input_power_kw: float
    cumulative_energy_kwh: float
    iterations: int
    regime: str | None


class V4ControlEventRecord(BaseModel):
    """Expose one accepted Gate/Pump control event."""

    model_config = ConfigDict(from_attributes=True)

    time_seconds: float
    structure_type: str
    canonical_structure_id: int
    event_type: str
    reason: str | None
    pre_state_json: dict[str, Any] | None
    post_command_json: dict[str, Any] | None


class V4ArtifactManifest(BaseModel):
    """Expose safe root-relative evidence metadata, never a server path."""

    id: int
    artifact_type: str
    storage_key: str
    sha256: str
    size_bytes: int
    record_count: int
    media_type: str
    schema_version: str
    status: str
    metadata: dict[str, Any]
    created_time: datetime
    published_time: datetime | None


class V4ResultSummary(BaseModel):
    """Return result-v3 provenance, quality evidence, and bounded counts."""

    task_id: int
    result_schema_version: Literal["dayu.hydraulic-result.v3"]
    provenance: dict[str, Any]
    section_count: int
    gate_row_count: int
    pump_row_count: int
    event_count: int
    artifacts: list[V4ArtifactManifest]
