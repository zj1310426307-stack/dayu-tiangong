"""Durable API contracts for Production-04 workflow evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.hydraulic.production.contracts import (
    AcceptanceCriteria,
    CalibrationCandidate,
    CalibrationObjective,
    DatasetWindow,
    ExternalResultPreview,
    HydraulicMetrics,
    HydraulicModelQARequest,
    ParameterSweepRequest,
    ResultProductRequest,
    TimeSeriesImportPreview,
)
from app.model_engine.schemas import SimulationTaskCreate


class ProductionTaskCreateRequest(BaseModel):
    """Create a formal task only after centralized QA passes."""

    model_config = ConfigDict(extra="forbid")

    run_code: str = Field(min_length=1, max_length=64)
    qa_run_code: str = Field(min_length=1, max_length=64)
    actor: str = Field(min_length=1, max_length=128)
    task: SimulationTaskCreate
    qa: HydraulicModelQARequest


class ProductionRunRecord(BaseModel):
    """Expose immutable task linkage and auditable model state."""

    id: int
    run_code: str
    dataset_version_id: int
    case_id: int
    task_id: int | None
    qa_run_code: str
    model_state: str
    input_snapshot_hash: str
    mass_balance_relative_error: float | None
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime


class ObservationCommitRequest(BaseModel):
    """Commit an already previewed observation and its file lineage."""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    preview: TimeSeriesImportPreview
    actor: str = Field(min_length=1, max_length=128)
    mapping_profile_id: int | None = Field(default=None, gt=0)


class ObservationRecord(BaseModel):
    """Return the durable identity of an imported observation series."""

    id: int
    dataset_version_id: int
    series_code: str
    station_id: str
    branch_id: int
    chainage_m: float
    variable: str
    unit: str
    vertical_datum: str
    source_filename: str
    source_sha256: str
    imported_at: datetime


class ExternalResultCommitRequest(BaseModel):
    """Commit a legally exported external result after preview."""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    result_code: str = Field(min_length=1, max_length=128)
    actor: str = Field(min_length=1, max_length=128)
    preview: ExternalResultPreview


class ExternalResultRecord(BaseModel):
    """Return the durable identity of an external-model result."""

    id: int
    dataset_version_id: int
    result_code: str
    external_model_name: str
    external_model_version: str
    scenario: str
    vertical_datum: str
    source_filename: str
    source_sha256: str
    imported_at: datetime


class CalibrationRunCommitRequest(BaseModel):
    """Persist one bounded sweep and its explicit objective."""

    model_config = ConfigDict(extra="forbid")

    run_code: str = Field(min_length=1, max_length=64)
    calibration_run_id: int | None = Field(default=None, gt=0)
    production_run_id: int = Field(gt=0)
    dataset_version_id: int = Field(gt=0)
    case_id: int = Field(gt=0)
    actor: str = Field(min_length=1, max_length=128)
    dataset: DatasetWindow
    sweep: ParameterSweepRequest
    objective: CalibrationObjective
    candidates: list[CalibrationCandidate]


class CalibrationSweepCreateRequest(BaseModel):
    """Create immutable candidate tasks from one bounded roughness sweep."""

    model_config = ConfigDict(extra="forbid")

    run_code: str = Field(min_length=1, max_length=64)
    production_run_id: int = Field(gt=0)
    actor: str = Field(min_length=1, max_length=128)
    dataset: DatasetWindow
    sweep: ParameterSweepRequest
    objective: CalibrationObjective


class CalibrationRunRecord(BaseModel):
    """Return calibration lifecycle state without promoting parameters."""

    id: int
    run_code: str
    production_run_id: int
    dataset_version_id: int
    case_id: int
    status: str
    selected_candidate_id: str | None
    accepted_by: str | None
    accepted_at: datetime | None
    created_at: datetime


class CalibrationSweepRunResponse(BaseModel):
    """Return the persisted run plus candidate task identities ready for enqueue."""

    run: CalibrationRunRecord
    candidates: list[CalibrationCandidate]


class CalibrationPromotionResponse(BaseModel):
    """Return the accepted experiment and the new gated formal rerun identity."""

    calibration: CalibrationRunRecord
    production_run: ProductionRunRecord


class ValidationRunCommitRequest(BaseModel):
    """Persist independent validation evidence and evaluated project criteria."""

    model_config = ConfigDict(extra="forbid")

    validation_code: str = Field(min_length=1, max_length=64)
    production_run_id: int = Field(gt=0)
    dataset_version_id: int = Field(gt=0)
    case_id: int = Field(gt=0)
    calibration_run_id: int | None = Field(default=None, gt=0)
    actor: str = Field(min_length=1, max_length=128)
    calibration_dataset: DatasetWindow
    validation_dataset: DatasetWindow
    criteria: AcceptanceCriteria
    metrics: list[HydraulicMetrics]
    mass_balance_relative_error: float | None = Field(default=None, ge=0)


class ValidationRunRecord(BaseModel):
    """Return formal validation status and immutable evidence identity."""

    id: int
    validation_code: str
    production_run_id: int
    dataset_version_id: int
    case_id: int
    calibration_run_id: int | None
    status: str
    created_at: datetime


class ResultProductCommitRequest(BaseModel):
    """Persist one generated product bundle under a content hash."""

    model_config = ConfigDict(extra="forbid")

    production_run_id: int = Field(gt=0)
    product_code: str = Field(min_length=1, max_length=64)
    actor: str = Field(min_length=1, max_length=128)
    request: ResultProductRequest


class ProductionApprovalRequest(BaseModel):
    """Capture explicit professional approval after independent validation."""

    model_config = ConfigDict(extra="forbid")

    approved_by: str = Field(min_length=1, max_length=128)
    approval_reason: str = Field(min_length=1, max_length=1000)


class ResultProductRecord(BaseModel):
    """Return one persisted reusable result-product identity."""

    id: int
    product_code: str
    production_run_id: int
    schema_version: str
    product_hash: str
    generated_at: datetime


class AuditEventRecord(BaseModel):
    """Expose consequential production actions in append-only order."""

    id: int
    dataset_version_id: int
    action: Literal[
        "IMPORT",
        "RUN_CREATION",
        "QA_OVERRIDE",
        "PARAMETER_PROMOTION",
        "CALIBRATION_ACCEPTANCE",
        "VALIDATION_ACCEPTANCE",
        "PRODUCTION_APPROVAL",
        "EXPORT",
    ]
    actor: str
    entity_type: str
    entity_id: str
    content_hash: str
    details_json: dict[str, Any]
    created_at: datetime


__all__ = [name for name in globals() if name.endswith(("Request", "Record"))]
