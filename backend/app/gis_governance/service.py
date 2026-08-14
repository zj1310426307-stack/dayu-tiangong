"""Business workflow for batch registration, review, promotion, and publication."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.gis.models import (
    CrossSection,
    DatasetVersion,
    Gate,
    GISImportBatch,
    GISPublication,
    GISReview,
    GISValidationIssue,
    GISValidationRun,
    Pump,
    River,
)
from app.gis_governance.errors import GovernanceError
from app.gis_governance.hashing import canonical_sha256
from app.gis_governance.repository import (
    BUSINESS_KEYS,
    CORE_MODELS,
    issues_for_batch,
    latest_approval,
    latest_validation,
    lock_batch,
    row_geometry_hash_value,
    row_geometry_json,
    staging_rows,
)
from app.gis_governance.schemas import (
    BatchCreate,
    BatchDiff,
    BatchRecord,
    PromotedVersionRecord,
    PromoteRequest,
    PublicationRecord,
    PublishRequest,
    ReviewDecisionRequest,
    ReviewRecord,
    RetireRequest,
    ValidationIssueRecord,
    ValidationRunRecord,
)
from app.gis_governance.state import require_transition
from app.gis_governance.validation import (
    apply_quality_status,
    staging_hash,
    validate_batch,
)
from app.river.service import generate_topology
from app.validation.service import run_validation as run_core_validation


def _batch_record(batch: GISImportBatch) -> BatchRecord:
    """Map ORM batch state to the stable public contract."""

    return BatchRecord.model_validate(batch)


def _version_record(version: DatasetVersion) -> PromotedVersionRecord:
    """Map a promoted authoritative version to its governance response contract."""

    return PromotedVersionRecord.model_validate(version)


AUTHORITATIVE_PARENT_STATUSES = frozenset({"approved", "published", "retired"})


def _authoritative_parent(
    session: Session, parent_version_id: int | None, *, lock: bool = False
) -> DatasetVersion | None:
    """Require a frozen parent and verify its exact four-family core hash."""

    if parent_version_id is None:
        return None
    statement = select(DatasetVersion).where(DatasetVersion.id == parent_version_id)
    if lock:
        statement = statement.with_for_update(read=True)
    parent = session.scalar(statement.execution_options(populate_existing=True))
    if parent is None:
        raise GovernanceError(
            "PARENT_VERSION_NOT_FOUND", "Parent dataset version does not exist.", status_code=404
        )
    if parent.status not in AUTHORITATIVE_PARENT_STATUSES or not parent.content_hash:
        raise GovernanceError(
            "PARENT_VERSION_NOT_AUTHORITATIVE",
            "Parent dataset version must be approved, published, or retired with a content hash.",
            status_code=409,
            context={"parent_version_id": parent.id, "status": parent.status},
        )
    actual_hash = canonical_sha256(_core_content_rows(session, parent.id))
    if actual_hash != parent.content_hash:
        raise GovernanceError(
            "PARENT_VERSION_HASH_MISMATCH",
            "Parent dataset content no longer matches its frozen hash.",
            status_code=409,
            context={"parent_version_id": parent.id},
        )
    return parent


def _verify_batch_parent(
    session: Session, batch: GISImportBatch, *, lock: bool = False
) -> DatasetVersion | None:
    """Bind every validation/review/promotion generation to the same parent hash."""

    parent = _authoritative_parent(session, batch.parent_version_id, lock=lock)
    actual_hash = parent.content_hash if parent is not None else None
    if batch.parent_content_hash != actual_hash:
        raise GovernanceError(
            "STALE_PARENT_VERSION",
            "The selected parent version differs from the generation registered for this batch.",
            status_code=409,
            context={"parent_version_id": batch.parent_version_id},
        )
    return parent


def _set_status(batch: GISImportBatch, target: str) -> None:
    """Apply one explicitly allowed state transition."""

    require_transition(batch.status, target)
    batch.status = target
    batch.updated_at = datetime.now(UTC)


def create_batch(session: Session, payload: BatchCreate) -> BatchRecord:
    """Register a traceable source batch without implicitly making it authoritative."""

    parent = _authoritative_parent(session, payload.parent_version_id)
    batch = GISImportBatch(
        batch_code=str(uuid4()),
        status="created",
        parent_content_hash=parent.content_hash if parent is not None else None,
        **payload.model_dump(),
    )
    session.add(batch)
    session.flush()
    return _batch_record(batch)


def list_batches(session: Session) -> list[BatchRecord]:
    """Return batches newest-first for operations and audit."""

    return [
        _batch_record(item)
        for item in session.scalars(select(GISImportBatch).order_by(GISImportBatch.id.desc())).all()
    ]


def get_batch(session: Session, batch_id: int) -> BatchRecord:
    """Return one batch or a stable not-found error."""

    batch = session.get(GISImportBatch, batch_id)
    if batch is None:
        raise GovernanceError("BATCH_NOT_FOUND", "GIS import batch does not exist.", status_code=404)
    return _batch_record(batch)


def _ensure_raw_batch_stageable(
    session: Session,
    batch: GISImportBatch,
    *,
    actor: str,
    standardization_completed: bool,
) -> None:
    """Verify raw landing and record an explicit typed-standardization handoff."""

    if batch.raw_table_name is None:
        return
    governance = (batch.metadata_json or {}).get("_governance", {})
    raw_status = (governance.get("raw_landing") or {}).get("status")
    standardization = governance.get("standardization") or {}
    standardization_status = standardization.get("status")
    if raw_status != "completed":
        raise GovernanceError(
            "RAW_LANDING_INCOMPLETE",
            "Raw landing must complete successfully before typed staging can be accepted.",
            status_code=409,
            context={
                "batch_id": batch.id,
                "raw_landing_status": raw_status,
            },
        )
    expected_location = f"imports.{batch.raw_table_name}"
    if batch.raw_location != expected_location:
        raise GovernanceError(
            "RAW_LANDING_LOCATION_MISMATCH",
            "Raw landing metadata does not match its immutable batch table.",
            status_code=409,
            context={"batch_id": batch.id},
        )
    if session.scalar(
        text("SELECT to_regclass(:raw_location)"),
        {"raw_location": expected_location},
    ) is None:
        raise GovernanceError(
            "RAW_LANDING_MISSING",
            "The recorded raw landing table no longer exists.",
            status_code=409,
            context={"batch_id": batch.id, "raw_location": expected_location},
        )
    if standardization_status == "completed":
        return
    if not standardization_completed:
        raise GovernanceError(
            "RAW_BATCH_NOT_STANDARDIZED",
            "Declare typed standardization complete when staging the raw batch.",
            status_code=409,
            context={
                "batch_id": batch.id,
                "standardization_status": standardization_status,
            },
        )
    if not staging_rows(session, batch):
        raise GovernanceError(
            "TYPED_STAGING_EMPTY",
            "Typed staging must contain mapped features before standardization is complete.",
            status_code=409,
            context={"batch_id": batch.id, "entity_type": batch.entity_type},
        )
    batch.metadata_json = {
        **(batch.metadata_json or {}),
        "_governance": {
            **governance,
            "standardization": {
                **standardization,
                "status": "completed",
                "actor": actor,
                "completed_at": datetime.now(UTC).isoformat(),
            },
        },
    }


def stage_batch(
    session: Session,
    batch_id: int,
    note: str | None = None,
    actor: str = "system",
    standardization_completed: bool = False,
) -> BatchRecord:
    """Mark raw landing or QGIS edits as ready for an authoritative validation run."""

    batch = lock_batch(session, batch_id)
    if batch is None:
        raise GovernanceError("BATCH_NOT_FOUND", "GIS import batch does not exist.", status_code=404)
    _ensure_raw_batch_stageable(
        session,
        batch,
        actor=actor,
        standardization_completed=standardization_completed,
    )
    if batch.status == "created":
        _set_status(batch, "staged")
    elif batch.status in {"validation_failed", "changes_requested"}:
        _set_status(batch, "staged")
    elif batch.status != "staged":
        require_transition(batch.status, "staged")
    if note:
        batch.notes = note
    batch.staged_by = actor
    batch.staged_at = datetime.now(UTC)
    session.flush()
    return _batch_record(batch)


def run_batch_validation(session: Session, batch_id: int) -> ValidationRunRecord:
    """Run and persist validation while retaining failed findings for remediation."""

    batch = lock_batch(session, batch_id)
    if batch is None:
        raise GovernanceError("BATCH_NOT_FOUND", "GIS import batch does not exist.", status_code=404)
    if batch.status not in {
        "staged", "validation_failed", "validated", "approved", "changes_requested"
    }:
        require_transition(batch.status, "validating")
    _verify_batch_parent(session, batch)
    _set_status(batch, "validating")
    run = validate_batch(session, batch)
    _set_status(batch, "validated" if run.status == "passed" else "validation_failed")
    # The database edit guard permits quality projection only after the batch has
    # left ``validating``.  Flush that authoritative state before touching rows.
    session.flush([batch])
    apply_quality_status(session, batch, run)
    session.flush()
    return ValidationRunRecord.model_validate(run)


def get_latest_validation(session: Session, batch_id: int) -> ValidationRunRecord:
    """Return the current validation generation rather than a transient error string."""

    run = latest_validation(session, batch_id)
    if run is None:
        raise GovernanceError("VALIDATION_NOT_FOUND", "Batch has no validation run.", status_code=404)
    return ValidationRunRecord.model_validate(run)


def list_issues(session: Session, batch_id: int) -> list[ValidationIssueRecord]:
    """Return queryable issue records with map-ready geometries."""

    records: list[ValidationIssueRecord] = []
    for issue in issues_for_batch(session, batch_id):
        values = {column.name: getattr(issue, column.name) for column in issue.__table__.columns}
        values["geometry"] = row_geometry_json(session, issue.geometry)
        records.append(ValidationIssueRecord(**values))
    return records


def submit_review(
    session: Session, batch_id: int, actor: str = "system"
) -> BatchRecord:
    """Lock the exact validated content generation for human review."""

    batch = lock_batch(session, batch_id)
    if batch is None:
        raise GovernanceError("BATCH_NOT_FOUND", "GIS import batch does not exist.", status_code=404)
    if batch.status != "validated":
        require_transition(batch.status, "in_review")
    _verify_batch_parent(session, batch)
    run = latest_validation(session, batch.id)
    current_hash = staging_hash(session, batch)
    if run is None or run.status != "passed" or run.staging_content_hash != current_hash:
        raise GovernanceError(
            "STALE_VALIDATION",
            "Staging content changed after validation; validate the batch again.",
            status_code=409,
        )
    _set_status(batch, "in_review")
    batch.review_submitted_by = actor
    batch.review_submitted_at = datetime.now(UTC)
    session.flush()
    return _batch_record(batch)


def review_batch(
    session: Session, batch_id: int, payload: ReviewDecisionRequest
) -> ReviewRecord:
    """Append a review decision bound to the current passed validation hash."""

    batch = lock_batch(session, batch_id)
    if batch is None:
        raise GovernanceError("BATCH_NOT_FOUND", "GIS import batch does not exist.", status_code=404)
    if batch.status != "in_review":
        raise GovernanceError(
            "BATCH_NOT_IN_REVIEW", "Batch must be submitted for review first.", status_code=409
        )
    _verify_batch_parent(session, batch)
    run = latest_validation(session, batch.id)
    current_hash = staging_hash(session, batch)
    if run is None or run.status != "passed" or run.staging_content_hash != current_hash:
        raise GovernanceError(
            "STALE_VALIDATION",
            "Staging content changed after validation; validate and submit it again.",
            status_code=409,
        )
    review = GISReview(
        batch_id=batch.id,
        validation_run_id=run.id,
        staging_content_hash=current_hash,
        reviewer=payload.reviewer,
        decision=payload.decision,
        comment=payload.comment,
    )
    session.add(review)
    target_status = {
        "approve": "approved",
        "request_changes": "changes_requested",
        "reject": "rejected",
    }[payload.decision]
    _set_status(batch, target_status)
    session.flush()
    return ReviewRecord.model_validate(review)


def batch_diff(session: Session, batch_id: int) -> BatchDiff:
    """Compare staging natural keys against the selected immutable parent version."""

    batch = session.get(GISImportBatch, batch_id)
    if batch is None:
        raise GovernanceError("BATCH_NOT_FOUND", "GIS import batch does not exist.", status_code=404)
    rows = staging_rows(session, batch)
    key_name = BUSINESS_KEYS[batch.entity_type]
    staged = {str(getattr(row, key_name)): row for row in rows}
    parent: dict[str, Any] = {}
    if batch.parent_version_id:
        model = CORE_MODELS[batch.entity_type]
        parent = {
            str(getattr(row, key_name)): row
            for row in session.scalars(
                select(model).where(model.dataset_version_id == batch.parent_version_id)
            ).all()
        }
    additions = sorted(key for key, row in staged.items() if row.operation != "delete" and key not in parent)
    deletions = sorted(key for key, row in staged.items() if row.operation == "delete" and key in parent)
    updates = sorted(key for key, row in staged.items() if row.operation != "delete" and key in parent)
    unchanged = sorted(set(parent) - set(staged))
    return BatchDiff(
        batch_id=batch.id,
        entity_type=batch.entity_type,
        parent_version_id=batch.parent_version_id,
        additions=additions,
        updates=updates,
        deletions=deletions,
        unchanged=unchanged,
    )


def _clone_parent_core(session: Session, parent_id: int | None, target_id: int) -> None:
    """Copy parent core objects while remapping every version-local foreign key."""

    if parent_id is None:
        return
    session.execute(text("""
        INSERT INTO river (dataset_version_id,name,code,length,level,status,description,geometry)
        SELECT :target,name,code,length,level,status,description,geometry
          FROM river WHERE dataset_version_id=:parent ORDER BY code
    """), {"target": target_id, "parent": parent_id})
    session.execute(text("""
        INSERT INTO cross_section
          (dataset_version_id,river_id,section_code,section_name,station,points,
           roughness,elevation_min,survey_date,geometry)
        SELECT :target,nr.id,cs.section_code,cs.section_name,cs.station,cs.points,
               cs.roughness,cs.elevation_min,cs.survey_date,cs.geometry
          FROM cross_section cs
          JOIN river oldr ON oldr.id=cs.river_id
          JOIN river nr ON nr.dataset_version_id=:target AND nr.code=oldr.code
         WHERE cs.dataset_version_id=:parent ORDER BY cs.section_code
    """), {"target": target_id, "parent": parent_id})
    session.execute(text("""
        INSERT INTO gate
          (dataset_version_id,name,gate_code,river_id,gate_type,opening_direction,
           control_mode,width,height,max_flow,bottom_elevation,station,crest_elevation,
           discharge_coefficient,minimum_opening,maximum_opening,opening_rate_limit,
           minimum_hold_seconds,allow_reverse_flow,status,geometry)
        SELECT :target,g.name,g.gate_code,nr.id,g.gate_type,g.opening_direction,
               g.control_mode,g.width,g.height,g.max_flow,g.bottom_elevation,g.station,
               g.crest_elevation,g.discharge_coefficient,g.minimum_opening,g.maximum_opening,
               g.opening_rate_limit,g.minimum_hold_seconds,g.allow_reverse_flow,g.status,g.geometry
          FROM gate g JOIN river oldr ON oldr.id=g.river_id
          JOIN river nr ON nr.dataset_version_id=:target AND nr.code=oldr.code
         WHERE g.dataset_version_id=:parent ORDER BY g.gate_code
    """), {"target": target_id, "parent": parent_id})
    session.execute(text("""
        INSERT INTO pump
          (dataset_version_id,name,pump_code,river_id,design_flow,head,power,
           efficiency_curve,head_curve,transfer_type,unit_count,minimum_running_units,
           maximum_running_units,minimum_run_seconds,minimum_stop_seconds,
           maximum_starts_per_run,minimum_operating_head,maximum_operating_head,
           reverse_flow_protection,control_mode,status,geometry)
        SELECT :target,p.name,p.pump_code,nr.id,p.design_flow,p.head,p.power,
               p.efficiency_curve,p.head_curve,p.transfer_type,p.unit_count,p.minimum_running_units,
               p.maximum_running_units,p.minimum_run_seconds,p.minimum_stop_seconds,
               p.maximum_starts_per_run,p.minimum_operating_head,p.maximum_operating_head,
               p.reverse_flow_protection,p.control_mode,p.status,p.geometry
          FROM pump p JOIN river oldr ON oldr.id=p.river_id
          JOIN river nr ON nr.dataset_version_id=:target AND nr.code=oldr.code
         WHERE p.dataset_version_id=:parent ORDER BY p.pump_code
    """), {"target": target_id, "parent": parent_id})


def _apply_staging_row(
    session: Session, batch: GISImportBatch, target_id: int, row: Any
) -> None:
    """Apply one validated staging feature; kept small so rollback can be fault-tested."""

    key_name = BUSINESS_KEYS[batch.entity_type]
    code = getattr(row, key_name)
    core_model = CORE_MODELS[batch.entity_type]
    existing = session.scalar(
        select(core_model).where(
            core_model.dataset_version_id == target_id,
            getattr(core_model, key_name) == code,
        )
    )
    if row.operation == "delete":
        if existing is not None:
            session.delete(existing)
        return
    excluded = {
        "id", "batch_id", "source_feature_id", "operation", "quality_status",
        "source_crs", "target_crs", "source_hash", "operator", "survey_time",
        "source_payload", "created_at", "updated_at", "river_code",
    }
    values = {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name not in excluded
    }
    values["dataset_version_id"] = target_id
    if batch.entity_type != "river":
        river_id = session.scalar(
            select(River.id).where(
                River.dataset_version_id == target_id, River.code == row.river_code
            )
        )
        if river_id is None:
            raise GovernanceError(
                "RIVER_REFERENCE_MISSING",
                f"Referenced river {row.river_code!r} is absent from the target version.",
            )
        values["river_id"] = river_id
    if existing is None:
        session.add(core_model(**values))
    else:
        for name, value in values.items():
            if name not in {"dataset_version_id"}:
                setattr(existing, name, value)


def _core_content_rows(session: Session, version_id: int) -> list[dict[str, Any]]:
    """Serialize four authoritative object families without database-generated IDs."""

    records: list[dict[str, Any]] = []
    for entity_type, model in CORE_MODELS.items():
        key = getattr(model, BUSINESS_KEYS[entity_type])
        rows = session.scalars(
            select(model).where(model.dataset_version_id == version_id).order_by(key)
        ).all()
        for row in rows:
            values = {
                column.name: getattr(row, column.name)
                for column in row.__table__.columns
                if column.name not in {
                    "id", "dataset_version_id", "created_time", "river_id",
                    "river_segment_id", "upstream_node_id", "downstream_node_id",
                    "intake_node_id", "outlet_node_id",
                }
            }
            if entity_type != "river":
                values["river_code"] = session.scalar(select(River.code).where(River.id == row.river_id))
            values["geometry"] = row_geometry_hash_value(session, row.geometry)
            values["entity_type"] = entity_type
            records.append(values)
    return records


def promote_batch(
    session: Session, batch_id: int, payload: PromoteRequest
) -> PromotedVersionRecord:
    """Atomically create exactly one immutable version from the approved staging hash."""

    batch = lock_batch(session, batch_id)
    if batch is None:
        raise GovernanceError("BATCH_NOT_FOUND", "GIS import batch does not exist.", status_code=404)
    existing = session.scalar(
        select(DatasetVersion).where(DatasetVersion.source_batch_id == batch.id)
    )
    if existing is not None:
        return _version_record(existing)
    if batch.status != "approved":
        raise GovernanceError("BATCH_NOT_APPROVED", "Only an approved batch may be promoted.", status_code=409)
    _verify_batch_parent(session, batch, lock=True)
    run = latest_validation(session, batch.id)
    approval = latest_approval(session, batch.id)
    current_hash = staging_hash(session, batch)
    if (
        run is None
        or run.status != "passed"
        or approval is None
        or approval.validation_run_id != run.id
        or run.staging_content_hash != current_hash
        or approval.staging_content_hash != current_hash
    ):
        raise GovernanceError(
            "STALE_APPROVAL",
            "Current staging content is not covered by the latest passed validation and approval.",
            status_code=409,
        )
    error_count = session.scalar(
        select(func.count(GISValidationIssue.id)).where(
            GISValidationIssue.validation_run_id == run.id,
            GISValidationIssue.severity == "error",
        )
    ) or 0
    if error_count:
        raise GovernanceError("VALIDATION_ERRORS", "Validation errors block promotion.", status_code=409)
    _set_status(batch, "promoting")
    version = DatasetVersion(
        version=payload.version,
        name=payload.name,
        description=payload.change_summary,
        creator=payload.creator,
        status="draft",
        parent_version_id=batch.parent_version_id,
        source_batch_id=batch.id,
        change_summary=payload.change_summary,
        reviewed_by=approval.reviewer,
        reviewed_at=approval.created_at,
        approved_by=approval.reviewer,
        approved_at=datetime.now(UTC),
    )
    session.add(version)
    session.flush()
    _clone_parent_core(session, batch.parent_version_id, version.id)
    for row in staging_rows(session, batch):
        _apply_staging_row(session, batch, version.id, row)
        session.flush()
    # Topology generation is valid only while the new version is still a draft and
    # participates in this same transaction; no historical version is touched.
    generate_topology(session, version.id, 0.00001)
    core_report = run_core_validation(session, version.id)
    blocking_core_rules = [
        item.code
        for item in core_report.items
        if item.severity == "error"
        and (
            item.category in {"spatial", "topology", "structure"}
            or item.code == "HYDRAULIC_STATION_RANGE"
        )
    ]
    if blocking_core_rules:
        raise GovernanceError(
            "PROMOTED_CORE_INVALID",
            "Promoted core failed the authoritative spatial/topology consistency check.",
            status_code=409,
            context={"rules": blocking_core_rules},
        )
    version.content_hash = canonical_sha256(_core_content_rows(session, version.id))
    version.status = "approved"
    batch.promoted_dataset_version_id = version.id
    _set_status(batch, "promoted")
    session.flush()
    return _version_record(version)


def list_publications(session: Session) -> list[PublicationRecord]:
    """Return publication audit records newest-first."""

    return [
        PublicationRecord.model_validate(item)
        for item in session.scalars(
            select(GISPublication).order_by(GISPublication.id.desc())
        ).all()
    ]


def publish_version(
    session: Session, version_id: int, payload: PublishRequest
) -> PublicationRecord:
    """Idempotently activate publish views and write the service manifest."""

    version = session.scalar(
        select(DatasetVersion).where(DatasetVersion.id == version_id).with_for_update()
    )
    if version is None:
        raise GovernanceError("VERSION_NOT_FOUND", "Dataset version does not exist.", status_code=404)
    existing = session.scalar(
        select(GISPublication).where(GISPublication.dataset_version_id == version.id)
    )
    if existing is not None and existing.publication_status == "published":
        return PublicationRecord.model_validate(existing)
    if version.status == "published" and existing is None:
        # Compatibility path for an upgraded pre-governance version.  It does
        # not manufacture a batch/hash; it only makes the already-published
        # state visible in the new append-only publication audit.
        now = version.published_at or datetime.now(UTC)
        publication = GISPublication(
            dataset_version_id=version.id,
            publication_status="published",
            published_by=payload.published_by,
            published_at=now,
            manifest_json=payload.manifest_json | {"legacy_backfill": True},
        )
        session.add(publication)
        session.flush()
        return PublicationRecord.model_validate(publication)
    if version.status != "approved":
        raise GovernanceError("VERSION_NOT_APPROVED", "Only an approved version may be published.", status_code=409)
    previous = session.scalar(
        select(GISPublication)
        .where(GISPublication.publication_status == "published")
        .order_by(GISPublication.published_at.desc())
        .limit(1)
    )
    now = datetime.now(UTC)
    publication = existing or GISPublication(dataset_version_id=version.id)
    publication.publication_status = "published"
    publication.published_by = payload.published_by
    publication.published_at = now
    publication.previous_publication_id = previous.id if previous else None
    publication.manifest_json = payload.manifest_json
    session.add(publication)
    version.status = "published"
    version.published_at = now
    batch = session.get(GISImportBatch, version.source_batch_id) if version.source_batch_id else None
    if batch is not None and batch.status == "promoted":
        _set_status(batch, "published")
    session.flush()
    return PublicationRecord.model_validate(publication)


def retire_version(
    session: Session, version_id: int, payload: RetireRequest
) -> PromotedVersionRecord:
    """Retire a published version without deleting its data or frozen consumers."""

    version = session.scalar(
        select(DatasetVersion).where(DatasetVersion.id == version_id).with_for_update()
    )
    if version is None:
        raise GovernanceError("VERSION_NOT_FOUND", "Dataset version does not exist.", status_code=404)
    if version.status == "retired":
        return _version_record(version)
    if version.status != "published":
        raise GovernanceError(
            "VERSION_NOT_PUBLISHED", "Only a published version may be retired.", status_code=409
        )
    now = datetime.now(UTC)
    version.status = "retired"
    version.retired_at = now
    version.change_summary = f"{version.change_summary or ''}\nRetired by {payload.retired_by}: {payload.reason}".strip()
    publication = session.scalar(
        select(GISPublication).where(GISPublication.dataset_version_id == version.id)
    )
    if publication is not None:
        publication.publication_status = "retired"
    session.flush()
    return _version_record(version)
