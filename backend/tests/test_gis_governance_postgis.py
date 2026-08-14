"""PostGIS integration acceptance for the GIS-OPT-1 governance lifecycle."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.common.spatial import geometry_expression
from app.database.session import SessionLocal
from app.gis.models import (
    DatasetVersion,
    GISImportBatch,
    GISPublication,
    GISReview,
    GISValidationIssue,
    GISValidationRun,
    QGISStagingRiver,
    River,
)
from app.gis_governance import service
from app.gis_governance.errors import GovernanceError
from app.gis_governance.hashing import canonical_sha256
from app.gis_governance.schemas import (
    BatchCreate,
    PromoteRequest,
    PublishRequest,
    ReviewDecisionRequest,
)
from app.gis_governance.validation import staging_hash


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGIS_TESTS") != "1",
    reason="requires a PostGIS database migrated through GIS-OPT-1 revision 0011",
)


@pytest.fixture
def db_session() -> Session:
    """Provide an isolated live session and roll back uncommitted test records."""

    with SessionLocal() as session:
        try:
            yield session
        finally:
            session.rollback()


def _token(prefix: str) -> str:
    """Create a short identifier that cannot collide with seeded or parallel test data."""

    return f"{prefix}-{uuid4().hex[:10]}"


def _sha(value: str) -> str:
    """Return a valid lowercase SHA-256 value for source provenance fields."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _line(longitude: float, latitude: float, offset: float = 0.001) -> object:
    """Build a valid, simple EPSG:4490 LineString database expression."""

    return geometry_expression(
        {
            "type": "LineString",
            "coordinates": [
                [longitude, latitude],
                [longitude + offset, latitude + offset],
            ],
        },
        "LineString",
    )


def _create_parent(
    session: Session, token: str, *, include_river: bool = True
) -> tuple[DatasetVersion, River | None]:
    """Create a published parent version owned entirely by the current transaction."""

    parent = DatasetVersion(
        version=f"P-{token}",
        name=f"PostGIS parent {token}",
        description="Integration-test parent",
        creator="pytest",
        status="draft",
    )
    session.add(parent)
    session.flush()
    river = None
    if include_river:
        river = River(
            dataset_version_id=parent.id,
            name=f"Parent river {token}",
            code=f"R-{token}",
            length=150.0,
            level="1",
            status="active",
            description="Immutable parent row",
            geometry=_line(111.0, 22.0),
        )
        session.add(river)
        session.flush()
    parent.content_hash = canonical_sha256(service._core_content_rows(session, parent.id))
    parent.status = "published"
    session.flush()
    return parent, river


def _create_river_batch(
    session: Session, token: str, parent_version_id: int
) -> GISImportBatch:
    """Register one river batch through the public service contract."""

    record = service.create_batch(
        session,
        BatchCreate(
            entity_type="river",
            source_filename=f"{token}.gpkg",
            source_format="GPKG",
            source_size=4096,
            source_hash_sha256=_sha(f"source:{token}"),
            source_crs="EPSG:4490",
            target_crs="EPSG:4490",
            mapping_version="river-v1",
            operator="pytest-editor",
            parent_version_id=parent_version_id,
            metadata_json={"test_token": token},
        ),
    )
    batch = session.get(GISImportBatch, record.id)
    assert batch is not None
    assert batch.parent_content_hash == session.get(
        DatasetVersion, parent_version_id
    ).content_hash
    return batch


def test_batch_rejects_mutable_or_hashless_parent(db_session: Session) -> None:
    """A review generation may only inherit a frozen, hash-bound parent."""

    token = _token("draft-parent")
    draft = DatasetVersion(
        version=f"D-{token}", name="Mutable parent", creator="pytest", status="draft"
    )
    db_session.add(draft)
    db_session.flush()
    with pytest.raises(GovernanceError) as captured:
        service.create_batch(
            db_session,
            BatchCreate(
                entity_type="river",
                source_filename="draft.gpkg",
                source_format="GPKG",
                source_size=1,
                source_hash_sha256=_sha(token),
                source_crs="EPSG:4490",
                mapping_version="river-v1",
                operator="pytest",
                parent_version_id=draft.id,
            ),
        )
    assert captured.value.code == "PARENT_VERSION_NOT_AUTHORITATIVE"


def _add_staging_river(
    session: Session,
    batch: GISImportBatch,
    *,
    code: str,
    feature_id: str,
    name: str,
    length: float,
    longitude: float = 111.0,
    latitude: float = 22.0,
) -> QGISStagingRiver:
    """Insert a typed staging row exactly as a controlled QGIS edit would."""

    row = QGISStagingRiver(
        batch_id=batch.id,
        source_feature_id=feature_id,
        operation="upsert",
        quality_status="pending",
        source_crs="EPSG:4490",
        target_crs="EPSG:4490",
        source_hash=_sha(f"{batch.batch_code}:{feature_id}"),
        operator="pytest-editor",
        source_payload={"source_feature_id": feature_id},
        name=name,
        code=code,
        length=length,
        level="1",
        status="active",
        description="Typed QGIS staging feature",
        geometry=_line(longitude, latitude),
    )
    session.add(row)
    session.flush()
    return row


def _approve_valid_batch(session: Session, batch: GISImportBatch) -> str:
    """Run the valid path through staging, validation, review submission, and approval."""

    assert service.stage_batch(session, batch.id).status == "staged"
    run = service.run_batch_validation(session, batch.id)
    assert run.status == "passed"
    assert run.summary_json["errors"] == 0
    assert service.submit_review(session, batch.id).status == "in_review"
    review = service.review_batch(
        session,
        batch.id,
        ReviewDecisionRequest(
            reviewer="pytest-reviewer",
            decision="approve",
            comment="Integration-test approval",
        ),
    )
    assert review.decision == "approve"
    assert session.get(GISImportBatch, batch.id).status == "approved"
    return run.staging_content_hash


def _promote_payload(token: str) -> PromoteRequest:
    """Build a unique immutable dataset-version request."""

    return PromoteRequest(
        version=f"V-{token}",
        name=f"Promoted {token}",
        creator="pytest-publisher",
        change_summary=f"GIS governance integration test {token}",
    )


def test_revision_0012_creates_governance_schemas_tables_views_and_indexes(
    db_session: Session,
) -> None:
    """Inspect physical PostGIS catalog objects rather than trusting ORM metadata."""

    assert db_session.scalar(text("SELECT version_num FROM alembic_version")) == "20260814_0012"

    schemas = set(
        db_session.scalars(
            text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name IN ('staging_qgis', 'publish')"
            )
        ).all()
    )
    assert schemas == {"staging_qgis", "publish"}

    public_tables = set(
        db_session.scalars(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE' "
                "AND table_name LIKE 'gis_%'"
            )
        ).all()
    )
    assert {
        "gis_import_batch",
        "gis_validation_run",
        "gis_validation_issue",
        "gis_review",
        "gis_publication",
    }.issubset(public_tables)

    staging_tables = set(
        db_session.scalars(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='staging_qgis' AND table_type='BASE TABLE'"
            )
        ).all()
    )
    assert staging_tables == {"river", "cross_section", "gate", "pump"}

    publish_views = dict(
        db_session.execute(
            text(
                "SELECT table_name, is_updatable FROM information_schema.views "
                "WHERE table_schema='publish'"
            )
        ).all()
    )
    assert publish_views == {
        name: "NO"
        for name in {
            "river", "river_segment", "river_node", "cross_section", "gate", "pump",
            "map_annotation", "administrative_area", "road", "place_name", "water_name", "poi",
        }
    }

    lifecycle_columns = set(
        db_session.scalars(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='dataset_version'"
            )
        ).all()
    )
    assert {
        "status",
        "parent_version_id",
        "source_batch_id",
        "content_hash",
        "change_summary",
        "reviewed_by",
        "reviewed_at",
        "approved_by",
        "approved_at",
        "published_at",
        "retired_at",
    }.issubset(lifecycle_columns)

    geometries = set(
        db_session.execute(
            text(
                "SELECT f_table_name, type, srid FROM geometry_columns "
                "WHERE f_table_schema='staging_qgis'"
            )
        ).all()
    )
    assert geometries == {
        ("river", "LINESTRING", 4490),
        ("cross_section", "POINT", 4490),
        ("gate", "POINT", 4490),
        ("pump", "POINT", 4490),
    }

    constraints = set(
        db_session.scalars(
            text(
                "SELECT con.conname FROM pg_constraint con "
                "JOIN pg_class rel ON rel.oid=con.conrelid "
                "JOIN pg_namespace ns ON ns.oid=rel.relnamespace "
                "WHERE (ns.nspname='public' AND rel.relname IN "
                "('dataset_version','gis_import_batch','gis_validation_run',"
                "'gis_validation_issue','gis_review','gis_publication')) "
                "OR ns.nspname='staging_qgis'"
            )
        ).all()
    )
    assert {
        "ck_dataset_version_status",
        "fk_dataset_version_parent_version_id",
        "fk_dataset_version_source_batch_id",
        "uq_dataset_version_source_batch_id",
        "ck_gis_import_batch_status",
        "fk_gis_import_batch_parent_version_id",
        "fk_gis_import_batch_promoted_dataset_version_id",
        "uq_gis_import_batch_code",
        "ck_gis_validation_run_status",
        "uq_gis_validation_run_batch_id_id",
        "fk_gis_validation_issue_batch_run",
        "ck_gis_review_decision",
        "fk_gis_review_batch_run",
        "uq_gis_publication_dataset_version_id",
        "fk_qgis_river_batch_id",
        "uq_qgis_river_source",
        "uq_qgis_river_code",
        "fk_qgis_section_batch_id",
        "uq_qgis_section_section_code",
        "fk_qgis_gate_batch_id",
        "uq_qgis_gate_gate_code",
        "fk_qgis_pump_batch_id",
        "uq_qgis_pump_pump_code",
    }.issubset(constraints)

    indexes = {
        (row.schemaname, row.tablename, row.indexname): row.indexdef.lower()
        for row in db_session.execute(
            text(
                "SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes "
                "WHERE schemaname IN ('public','staging_qgis')"
            )
        )
    }
    assert ("public", "gis_import_batch", "ix_gis_import_batch_status") in indexes
    assert ("public", "gis_validation_issue", "ix_gis_validation_issue_batch_severity") in indexes
    for table_name, index_name in {
        "river": "ix_qgis_river_geometry_gist",
        "cross_section": "ix_qgis_section_geometry_gist",
        "gate": "ix_qgis_gate_geometry_gist",
        "pump": "ix_qgis_pump_geometry_gist",
    }.items():
        definition = indexes[("staging_qgis", table_name, index_name)]
        assert "using gist" in definition

    provenance_triggers = set(
        db_session.scalars(
            text(
                "SELECT trigger_name FROM information_schema.triggers "
                "WHERE event_object_schema='staging_qgis' "
                "AND action_statement LIKE '%apply_batch_provenance%'"
            )
        ).all()
    )
    assert provenance_triggers == {
        "trg_qgis_river_batch_provenance",
        "trg_qgis_cross_section_batch_provenance",
        "trg_qgis_gate_batch_provenance",
        "trg_qgis_pump_batch_provenance",
    }
    edit_guard_triggers = set(
        db_session.scalars(
            text(
                "SELECT trigger_name FROM information_schema.triggers "
                "WHERE event_object_schema='staging_qgis' "
                "AND action_statement LIKE '%guard_batch_edit%'"
            )
        ).all()
    )
    assert edit_guard_triggers == {
        "trg_qgis_river_guard_batch_edit",
        "trg_qgis_cross_section_guard_batch_edit",
        "trg_qgis_gate_guard_batch_edit",
        "trg_qgis_pump_guard_batch_edit",
    }


def test_staging_insert_inherits_read_only_provenance_from_batch(
    db_session: Session,
) -> None:
    """Allow QGIS inserts without exposing source hash and CRS as editable fields."""

    token = _token("provenance")
    parent, _ = _create_parent(db_session, token, include_river=False)
    batch = _create_river_batch(db_session, token, parent.id)
    row_id = db_session.scalar(
        text(
            "INSERT INTO staging_qgis.river "
            "(batch_id,source_feature_id,name,code,length,level,status,geometry) "
            "VALUES (:batch_id,:feature_id,:name,:code,120,'1','active',"
            "ST_GeomFromText('LINESTRING(111 22,111.001 22.001)',4490)) "
            "RETURNING id"
        ),
        {
            "batch_id": batch.id,
            "feature_id": f"{token}-feature",
            "name": f"Provenance river {token}",
            "code": f"R-{token}",
        },
    )
    inherited = db_session.execute(
        text(
            "SELECT source_crs,target_crs,source_hash,operator "
            "FROM staging_qgis.river WHERE id=:row_id"
        ),
        {"row_id": row_id},
    ).one()
    assert inherited.source_crs == batch.source_crs
    assert inherited.target_crs == "EPSG:4490"
    assert inherited.source_hash == batch.source_hash_sha256
    assert inherited.operator == batch.operator


def test_raw_landing_requires_existing_table_typed_rows_and_explicit_handoff(
    db_session: Session,
) -> None:
    """Keep raw GDAL landing separate from accepted, strongly typed staging."""

    token = _token("raw-stage")
    parent, _ = _create_parent(db_session, token, include_river=False)
    batch = _create_river_batch(db_session, token, parent.id)
    raw_table = f"batch_{uuid4().hex[:20]}"
    batch.raw_table_name = raw_table
    batch.raw_location = f"imports.{raw_table}"
    batch.metadata_json = {
        "_governance": {
            "raw_landing": {"status": "completed"},
            "standardization": {"status": "required"},
        }
    }
    db_session.flush()

    with pytest.raises(GovernanceError) as missing:
        service.stage_batch(
            db_session,
            batch.id,
            actor="pytest-standardizer",
            standardization_completed=True,
        )
    assert missing.value.code == "RAW_LANDING_MISSING"

    db_session.execute(text(f'CREATE TABLE imports."{raw_table}" (id integer)'))
    with pytest.raises(GovernanceError) as undeclared:
        service.stage_batch(db_session, batch.id, actor="pytest-standardizer")
    assert undeclared.value.code == "RAW_BATCH_NOT_STANDARDIZED"

    with pytest.raises(GovernanceError) as empty:
        service.stage_batch(
            db_session,
            batch.id,
            actor="pytest-standardizer",
            standardization_completed=True,
        )
    assert empty.value.code == "TYPED_STAGING_EMPTY"

    _add_staging_river(
        db_session,
        batch,
        code=f"R-{token}",
        feature_id=f"{token}-feature",
        name=f"Standardized river {token}",
        length=150.0,
    )
    staged = service.stage_batch(
        db_session,
        batch.id,
        actor="pytest-standardizer",
        standardization_completed=True,
    )
    assert staged.status == "staged"
    standardization = batch.metadata_json["_governance"]["standardization"]
    assert standardization["status"] == "completed"
    assert standardization["actor"] == "pytest-standardizer"
    assert standardization["completed_at"]


def test_approved_batch_rejects_direct_qgis_edits(db_session: Session) -> None:
    """Enforce the review lock in PostGIS, independently of the QGIS form UI."""

    token = _token("edit-lock")
    parent, parent_river = _create_parent(db_session, token)
    assert parent_river is not None
    batch = _create_river_batch(db_session, token, parent.id)
    staged = _add_staging_river(
        db_session,
        batch,
        code=parent_river.code,
        feature_id=f"{token}-feature",
        name=f"Locked river {token}",
        length=150.0,
    )
    _approve_valid_batch(db_session, batch)
    with pytest.raises(DBAPIError, match="cannot be edited"):
        staged.name = f"Disallowed edit {token}"
        db_session.flush()
    db_session.rollback()


def test_river_batch_failure_repair_review_promote_publish_and_history_stability(
    db_session: Session,
) -> None:
    """Exercise the complete river workflow and prove parent content never drifts."""

    token = _token("life")
    parent, parent_river = _create_parent(db_session, token)
    assert parent_river is not None
    parent_snapshot = deepcopy(service._core_content_rows(db_session, parent.id))
    parent_snapshot_hash = canonical_sha256(parent_snapshot)
    parent_content_hash = parent.content_hash
    parent_count = db_session.scalar(
        select(func.count(River.id)).where(River.dataset_version_id == parent.id)
    )

    batch = _create_river_batch(db_session, token, parent.id)
    staged = _add_staging_river(
        db_session,
        batch,
        code=parent_river.code,
        feature_id=f"{token}-feature",
        name=f"Corrected river {token}",
        length=0.0,
    )
    assert service.stage_batch(db_session, batch.id).status == "staged"

    failed = service.run_batch_validation(db_session, batch.id)
    assert failed.status == "failed"
    assert failed.summary_json["errors"] >= 1
    assert db_session.get(GISImportBatch, batch.id).status == "validation_failed"
    failed_rules = set(
        db_session.scalars(
            select(GISValidationIssue.rule_code).where(
                GISValidationIssue.validation_run_id == failed.id
            )
        ).all()
    )
    assert "RIVER_LENGTH" in failed_rules
    assert staged.quality_status == "failed"

    staged.length = 150.0
    db_session.flush()
    passed = service.run_batch_validation(db_session, batch.id)
    assert passed.status == "passed"
    assert passed.summary_json["errors"] == 0
    assert staged.quality_status == "passed"
    assert passed.staging_content_hash != failed.staging_content_hash
    assert db_session.scalar(
        select(func.count(GISValidationRun.id)).where(
            GISValidationRun.batch_id == batch.id
        )
    ) == 2

    submitted = service.submit_review(db_session, batch.id)
    assert submitted.status == "in_review"
    approved = service.review_batch(
        db_session,
        batch.id,
        ReviewDecisionRequest(
            reviewer="pytest-reviewer",
            decision="approve",
            comment="Length corrected and evidence reviewed",
        ),
    )
    assert approved.staging_content_hash == passed.staging_content_hash
    assert db_session.get(GISImportBatch, batch.id).status == "approved"

    diff = service.batch_diff(db_session, batch.id)
    assert diff.additions == []
    assert diff.updates == [parent_river.code]
    assert diff.deletions == []

    payload = _promote_payload(token)
    promoted = service.promote_batch(db_session, batch.id, payload)
    assert promoted.status == "approved"
    assert promoted.parent_version_id == parent.id
    assert promoted.source_batch_id == batch.id
    assert len(promoted.content_hash) == 64
    assert promoted.content_hash != parent_content_hash
    assert db_session.scalar(
        select(func.count(River.id)).where(River.dataset_version_id == promoted.id)
    ) == 1

    second = service.promote_batch(
        db_session,
        batch.id,
        PromoteRequest(
            version=f"SHOULD-NOT-EXIST-{token}",
            name="Ignored idempotent retry",
            creator="retry-client",
            change_summary="An idempotent retry must return the existing version.",
        ),
    )
    assert second.id == promoted.id
    assert second.version == payload.version
    assert db_session.scalar(
        select(func.count(DatasetVersion.id)).where(
            DatasetVersion.source_batch_id == batch.id
        )
    ) == 1

    assert db_session.scalar(
        select(func.count(River.id)).where(River.dataset_version_id == parent.id)
    ) == parent_count
    assert service._core_content_rows(db_session, parent.id) == parent_snapshot
    assert canonical_sha256(service._core_content_rows(db_session, parent.id)) == parent_snapshot_hash
    assert db_session.get(DatasetVersion, parent.id).content_hash == parent_content_hash

    publication = service.publish_version(
        db_session,
        promoted.id,
        PublishRequest(
            published_by="pytest-publisher",
            manifest_json={"views": ["publish.river"], "dataset": payload.version},
        ),
    )
    assert publication.publication_status == "published"
    assert db_session.get(DatasetVersion, promoted.id).status == "published"
    assert db_session.get(GISImportBatch, batch.id).status == "published"
    assert db_session.scalar(
        text("SELECT count(*) FROM publish.river WHERE dataset_version_id=:version_id"),
        {"version_id": promoted.id},
    ) == 1
    assert db_session.scalar(
        select(func.count(GISPublication.id)).where(
            GISPublication.dataset_version_id == promoted.id
        )
    ) == 1


def test_staging_hash_tamper_after_approval_blocks_promotion(db_session: Session) -> None:
    """Reject staging content that is no longer covered by validation and approval."""

    token = _token("tamper")
    parent, parent_river = _create_parent(db_session, token)
    assert parent_river is not None
    batch = _create_river_batch(db_session, token, parent.id)
    staged = _add_staging_river(
        db_session,
        batch,
        code=parent_river.code,
        feature_id=f"{token}-feature",
        name=f"Reviewed river {token}",
        length=150.0,
    )
    approved_hash = _approve_valid_batch(db_session, batch)
    approval = db_session.scalar(
        select(GISReview)
        .where(GISReview.batch_id == batch.id, GISReview.decision == "approve")
        .order_by(GISReview.id.desc())
    )
    assert approval is not None
    assert approval.staging_content_hash == approved_hash

    # Simulate a privileged owner bypassing database DML triggers. Real QGIS roles
    # cannot do this; the service hash remains the independent final defence.
    db_session.execute(text("SET LOCAL session_replication_role = replica"))
    staged.name = f"Tampered after approval {token}"
    db_session.flush()
    db_session.execute(text("SET LOCAL session_replication_role = origin"))
    assert staging_hash(db_session, batch) != approved_hash

    with pytest.raises(GovernanceError) as captured:
        service.promote_batch(db_session, batch.id, _promote_payload(token))

    assert captured.value.code == "STALE_APPROVAL"
    assert captured.value.status_code == 409
    assert db_session.get(GISImportBatch, batch.id).status == "approved"
    assert db_session.scalar(
        select(func.count(DatasetVersion.id)).where(
            DatasetVersion.source_batch_id == batch.id
        )
    ) == 0


def test_atomic_promotion_rolls_back_all_100_valid_rows_on_injected_row_73_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove a mid-batch runtime failure leaves no ghost version or authoritative rows."""

    token = _token("atomic")
    target_payload = _promote_payload(token)
    original_apply = service._apply_staging_row
    with SessionLocal() as session:
        parent, _ = _create_parent(session, token, include_river=False)
        batch = _create_river_batch(session, token, parent.id)
        code_prefix = f"R-{token}-"
        for index in range(1, 101):
            _add_staging_river(
                session,
                batch,
                code=f"{code_prefix}{index:03d}",
                feature_id=f"feature-{index:03d}",
                name=f"Valid river {index:03d}",
                length=150.0,
                longitude=110.0 + index * 0.01,
                latitude=20.0,
            )
        _approve_valid_batch(session, batch)
        batch_id = batch.id
        parent_id = parent.id
        session.commit()

        calls = 0

        def fail_on_row_73(
            active_session: Session,
            active_batch: GISImportBatch,
            target_id: int,
            row: QGISStagingRiver,
        ) -> None:
            """Inject only a runtime fault; every staged business row remains valid."""

            nonlocal calls
            calls += 1
            if calls == 73:
                raise RuntimeError("injected promotion failure on valid row 73")
            original_apply(active_session, active_batch, target_id, row)

        try:
            monkeypatch.setattr(service, "_apply_staging_row", fail_on_row_73)
            with pytest.raises(RuntimeError, match="valid row 73"):
                service.promote_batch(session, batch_id, target_payload)
            assert calls == 73
            session.rollback()
            session.expire_all()

            assert session.get(GISImportBatch, batch_id).status == "approved"
            assert session.scalar(
                select(func.count(DatasetVersion.id)).where(
                    DatasetVersion.source_batch_id == batch_id
                )
            ) == 0
            assert session.scalar(
                select(func.count(DatasetVersion.id)).where(
                    DatasetVersion.version == target_payload.version
                )
            ) == 0
            assert session.scalar(
                select(func.count(River.id)).where(River.code.like(f"{code_prefix}%"))
            ) == 0

            monkeypatch.setattr(service, "_apply_staging_row", original_apply)
            promoted = service.promote_batch(session, batch_id, target_payload)
            assert promoted.status == "approved"
            assert session.scalar(
                select(func.count(River.id)).where(
                    River.dataset_version_id == promoted.id,
                    River.code.like(f"{code_prefix}%"),
                )
            ) == 100
            assert session.scalar(
                select(func.count(DatasetVersion.id)).where(
                    DatasetVersion.source_batch_id == batch_id
                )
            ) == 1
        finally:
            # The successful retry is intentionally uncommitted; remove it first,
            # then delete only the setup records committed by this test.
            session.rollback()
            session.execute(delete(GISImportBatch).where(GISImportBatch.id == batch_id))
            session.execute(delete(DatasetVersion).where(DatasetVersion.id == parent_id))
            session.commit()
