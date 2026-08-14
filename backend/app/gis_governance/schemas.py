"""Pydantic contracts for the GIS governance control plane."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


EntityType = Literal["river", "cross_section", "gate", "pump"]
BatchStatus = Literal[
    "created", "staged", "validating", "validation_failed", "validated",
    "in_review", "changes_requested", "rejected", "approved", "promoting",
    "promoted", "published",
]


class GovernanceModel(BaseModel):
    """Forbid undocumented request fields while reading ORM response records."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class BatchCreate(GovernanceModel):
    """Register source provenance before data enters raw or typed staging areas."""

    entity_type: EntityType
    source_filename: str = Field(min_length=1, max_length=255)
    source_format: str = Field(min_length=1, max_length=64)
    source_size: int = Field(ge=0)
    source_hash_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    source_crs: str = Field(min_length=1, max_length=64)
    target_crs: Literal["EPSG:4490"] = "EPSG:4490"
    mapping_version: str = Field(min_length=1, max_length=32)
    operator: str = Field(min_length=1, max_length=64)
    survey_time: datetime | None = None
    parent_version_id: int | None = Field(default=None, gt=0)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None

    @field_validator("source_hash_sha256")
    @classmethod
    def normalize_hash(cls, value: str) -> str:
        """Store SHA-256 consistently in lower case."""

        return value.lower()


class BatchRecord(BatchCreate):
    """Return a batch with immutable identity and current lifecycle state."""

    id: int
    batch_code: str
    status: BatchStatus
    raw_location: str | None = None
    raw_table_name: str | None = None
    parent_content_hash: str | None = None
    staging_content_hash: str | None = None
    promoted_dataset_version_id: int | None = None
    staged_by: str | None = None
    staged_at: datetime | None = None
    review_submitted_by: str | None = None
    review_submitted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class BatchStageRequest(GovernanceModel):
    """Mark a batch ready after raw landing or direct QGIS staging edits."""

    actor: str = Field(min_length=1, max_length=64)
    note: str | None = None
    standardization_completed: bool = False


class ValidationRunRecord(GovernanceModel):
    """Describe one persisted validation generation and its canonical hash."""

    id: int
    batch_id: int
    ruleset_version: str
    status: Literal["running", "passed", "failed"]
    staging_content_hash: str
    started_at: datetime
    finished_at: datetime | None = None
    summary_json: dict[str, Any]


class ValidationIssueRecord(GovernanceModel):
    """Expose one queryable, feature-locatable validation finding."""

    id: int
    validation_run_id: int
    batch_id: int
    entity_type: EntityType
    feature_ref: str | None = None
    rule_code: str
    severity: Literal["error", "warning", "info"]
    message: str
    geometry: dict[str, Any] | None = None
    details_json: dict[str, Any]
    created_at: datetime
    resolved_at: datetime | None = None
    resolution_note: str | None = None


class ReviewSubmitRequest(GovernanceModel):
    """Identify the actor requesting a human review."""

    actor: str = Field(min_length=1, max_length=64)


class ReviewDecisionRequest(GovernanceModel):
    """Append an immutable human decision for the current validation generation."""

    reviewer: str = Field(min_length=1, max_length=64)
    decision: Literal["approve", "reject", "request_changes"]
    comment: str | None = None


class ReviewRecord(GovernanceModel):
    """Return one append-only review event."""

    id: int
    batch_id: int
    validation_run_id: int
    staging_content_hash: str
    reviewer: str
    decision: Literal["approve", "reject", "request_changes"]
    comment: str | None = None
    created_at: datetime


class BatchDiff(GovernanceModel):
    """Summarize code-level additions, updates, deletions, and unchanged rows."""

    batch_id: int
    entity_type: EntityType
    parent_version_id: int | None
    additions: list[str]
    updates: list[str]
    deletions: list[str]
    unchanged: list[str]


class PromoteRequest(GovernanceModel):
    """Name a new immutable authoritative version produced from an approved batch."""

    version: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    creator: str = Field(min_length=1, max_length=64)
    change_summary: str = Field(min_length=1)


class PromotedVersionRecord(GovernanceModel):
    """Return the immutable version identity and stable content hash."""

    id: int
    version: str
    name: str
    description: str | None = None
    creator: str
    status: Literal["approved", "published", "retired"]
    parent_version_id: int | None = None
    source_batch_id: int | None = None
    content_hash: str | None = None
    change_summary: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    published_at: datetime | None = None
    created_time: datetime


class PublishRequest(GovernanceModel):
    """Record the publication actor and service manifest."""

    published_by: str = Field(min_length=1, max_length=64)
    manifest_json: dict[str, Any] = Field(default_factory=dict)


class PublicationRecord(GovernanceModel):
    """Return one idempotent publication audit record."""

    id: int
    dataset_version_id: int
    publication_status: Literal["pending", "published", "failed", "retired"]
    published_by: str
    published_at: datetime | None = None
    previous_publication_id: int | None = None
    manifest_json: dict[str, Any]
    created_at: datetime


class RetireRequest(GovernanceModel):
    """Record who retired a published version and why."""

    retired_by: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1)
