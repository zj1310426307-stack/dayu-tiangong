"""HTTP contracts for native-v4 readiness, preview, and projection evidence."""

from __future__ import annotations

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

