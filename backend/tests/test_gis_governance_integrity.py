"""Verify freeze serialization and governance relational-integrity contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
import os
from uuid import uuid4

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.database.session import SessionLocal
from app.dataset import service as dataset_service
from app.dataset.lifecycle import assert_dataset_version_mutable
from app.dataset.schemas import DatasetVersionUpdate
from app.gis.models import (
    DatasetVersion,
    GISImportBatch,
    GISReview,
    GISValidationIssue,
    GISValidationRun,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    REPOSITORY_ROOT
    / "database/migrations/versions/20260814_0011_qgis_governance.py"
)
requires_postgis = pytest.mark.skipif(
    os.getenv("RUN_POSTGIS_TESTS") != "1",
    reason="requires the migrated GIS-OPT-1 PostGIS database",
)


def _constraint(table: object, name: str, constraint_type: type[object]) -> object:
    """Return one named SQLAlchemy constraint from a mapped table."""

    matches = [
        constraint
        for constraint in table.constraints  # type: ignore[attr-defined]
        if isinstance(constraint, constraint_type) and constraint.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def test_dataset_version_update_uses_locked_mutability_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Version metadata updates must mutate the row reloaded under FOR UPDATE."""

    stale = DatasetVersion(
        id=17,
        version="V-STALE",
        name="stale name",
        creator="pytest",
        status="draft",
        created_time=datetime(2026, 8, 14, tzinfo=UTC),
    )
    locked = DatasetVersion(
        id=17,
        version="V-LOCKED",
        name="locked name",
        creator="pytest",
        status="draft",
        created_time=datetime(2026, 8, 14, tzinfo=UTC),
    )
    session = MagicMock()
    observed: list[tuple[object, int]] = []

    def guard(candidate_session: object, version_id: int) -> DatasetVersion:
        observed.append((candidate_session, version_id))
        return locked

    monkeypatch.setattr(dataset_service, "assert_dataset_version_mutable", guard)

    record = dataset_service.update_dataset_version(
        session,
        stale,
        DatasetVersionUpdate(name="serialized update"),
    )

    assert observed == [(session, 17)]
    assert record.name == "serialized update"
    assert locked.name == "serialized update"
    assert stale.name == "stale name"
    session.flush.assert_called_once_with()


def test_mutability_guard_selects_dataset_version_for_update() -> None:
    """The shared guard must issue a row-locking query, not a race-prone plain read."""

    version = DatasetVersion(id=23, status="draft")
    session = MagicMock()

    def scalar(statement: object) -> DatasetVersion:
        compiled = str(
            statement.compile(  # type: ignore[attr-defined]
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        assert "FOR UPDATE" in compiled
        assert statement.get_execution_options()["populate_existing"] is True  # type: ignore[attr-defined]
        return version

    session.scalar.side_effect = scalar

    assert assert_dataset_version_mutable(session, 23) is version


def test_import_batch_orm_binds_parent_hash_and_promoted_version() -> None:
    """ORM metadata must mirror the parent-pair check and promoted-version FK."""

    parent_pair = _constraint(
        GISImportBatch.__table__,
        "ck_gis_import_batch_parent_hash_pair",
        CheckConstraint,
    )
    assert "parent_version_id IS NULL AND parent_content_hash IS NULL" in str(
        parent_pair.sqltext  # type: ignore[attr-defined]
    )

    promoted_fk = _constraint(
        GISImportBatch.__table__,
        "fk_gis_import_batch_promoted_dataset_version_id",
        ForeignKeyConstraint,
    )
    assert [column.name for column in promoted_fk.columns] == [  # type: ignore[attr-defined]
        "promoted_dataset_version_id"
    ]
    assert [element.target_fullname for element in promoted_fk.elements] == [  # type: ignore[attr-defined]
        "dataset_version.id"
    ]
    assert promoted_fk.ondelete == "RESTRICT"  # type: ignore[attr-defined]


def test_validation_children_are_bound_to_their_run_batch() -> None:
    """An issue or review cannot cite a validation run owned by another batch."""

    run_identity = _constraint(
        GISValidationRun.__table__,
        "uq_gis_validation_run_batch_id_id",
        UniqueConstraint,
    )
    assert [column.name for column in run_identity.columns] == ["batch_id", "id"]  # type: ignore[attr-defined]

    expected = {
        GISValidationIssue.__table__: (
            "fk_gis_validation_issue_batch_run",
            "CASCADE",
        ),
        GISReview.__table__: ("fk_gis_review_batch_run", "RESTRICT"),
    }
    for table, (name, ondelete) in expected.items():
        foreign_key = _constraint(table, name, ForeignKeyConstraint)
        assert [column.name for column in foreign_key.columns] == [  # type: ignore[attr-defined]
            "batch_id",
            "validation_run_id",
        ]
        assert [element.target_fullname for element in foreign_key.elements] == [  # type: ignore[attr-defined]
            "gis_validation_run.batch_id",
            "gis_validation_run.id",
        ]
        assert foreign_key.ondelete == ondelete  # type: ignore[attr-defined]


def test_migration_declares_and_reverses_new_integrity_constraints() -> None:
    """The deployable Alembic head must carry the same named physical contracts."""

    source = MIGRATION.read_text(encoding="utf-8")
    for name in (
        "ck_gis_import_batch_parent_hash_pair",
        "fk_gis_import_batch_promoted_dataset_version_id",
        "uq_gis_validation_run_batch_id_id",
        "fk_gis_validation_issue_batch_run",
        "fk_gis_review_batch_run",
    ):
        assert name in source
    assert source.count("fk_gis_import_batch_promoted_dataset_version_id") == 2


@requires_postgis
def test_migrated_database_exposes_governance_integrity_constraints() -> None:
    """A migrated PostGIS runtime must expose the exact composite and freeze constraints."""

    expected = {
        "ck_gis_import_batch_parent_hash_pair": (
            "gis_import_batch",
            "CHECK",
        ),
        "fk_gis_import_batch_promoted_dataset_version_id": (
            "gis_import_batch",
            "FOREIGN KEY (promoted_dataset_version_id) REFERENCES dataset_version(id) ON DELETE RESTRICT",
        ),
        "uq_gis_validation_run_batch_id_id": (
            "gis_validation_run",
            "UNIQUE (batch_id, id)",
        ),
        "fk_gis_validation_issue_batch_run": (
            "gis_validation_issue",
            "FOREIGN KEY (batch_id, validation_run_id) REFERENCES gis_validation_run(batch_id, id) ON DELETE CASCADE",
        ),
        "fk_gis_review_batch_run": (
            "gis_review",
            "FOREIGN KEY (batch_id, validation_run_id) REFERENCES gis_validation_run(batch_id, id) ON DELETE RESTRICT",
        ),
    }
    with SessionLocal() as session:
        rows = session.execute(
            text(
                """
                SELECT c.conname, t.relname, pg_get_constraintdef(c.oid)
                  FROM pg_constraint AS c
                  JOIN pg_class AS t ON t.oid = c.conrelid
                 WHERE c.conname = ANY(:constraint_names)
                """
            ),
            {"constraint_names": list(expected)},
        ).all()

    actual = {name: (table, definition) for name, table, definition in rows}
    assert set(actual) == set(expected)
    for name, (table, definition_fragment) in expected.items():
        assert actual[name][0] == table
        assert definition_fragment in actual[name][1]


@requires_postgis
def test_database_rejects_cross_batch_validation_children() -> None:
    """A child row cannot pair one batch with another batch's validation run."""

    with SessionLocal() as session:
        batches = [
            GISImportBatch(
                batch_code=str(uuid4()),
                entity_type="river",
                source_filename=f"integrity-{index}.gpkg",
                source_format="GPKG",
                source_size=1,
                source_hash_sha256=("a" if index == 1 else "b") * 64,
                source_crs="EPSG:4490",
                target_crs="EPSG:4490",
                mapping_version="integrity-v1",
                operator="pytest",
                status="created",
                metadata_json={},
            )
            for index in (1, 2)
        ]
        session.add_all(batches)
        session.flush()
        run = GISValidationRun(
            batch_id=batches[0].id,
            ruleset_version="integrity-v1",
            status="passed",
            staging_content_hash="c" * 64,
            summary_json={"errors": 0},
        )
        session.add(run)
        session.flush()

        invalid_children = (
            GISValidationIssue(
                validation_run_id=run.id,
                batch_id=batches[1].id,
                entity_type="river",
                feature_ref="R-CROSS-BATCH",
                rule_code="INTEGRITY_PROBE",
                severity="error",
                message="must be rejected",
                details_json={},
            ),
            GISReview(
                validation_run_id=run.id,
                batch_id=batches[1].id,
                staging_content_hash=run.staging_content_hash,
                reviewer="pytest",
                decision="approve",
                comment="must be rejected",
            ),
        )
        for child in invalid_children:
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(child)
                session.flush()

        session.rollback()
