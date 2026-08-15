"""Database access helpers for typed QGIS staging and governance records."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.gis.models import (
    CrossSection,
    Gate,
    GISImportBatch,
    GISReview,
    GISValidationIssue,
    GISValidationRun,
    Pump,
    QGISStagingCrossSection,
    QGISStagingGate,
    QGISStagingPump,
    QGISStagingRiver,
    River,
)


STAGING_MODELS = {
    "river": QGISStagingRiver,
    "cross_section": QGISStagingCrossSection,
    "gate": QGISStagingGate,
    "pump": QGISStagingPump,
}
CORE_MODELS = {
    "river": River,
    "cross_section": CrossSection,
    "gate": Gate,
    "pump": Pump,
}
BUSINESS_KEYS = {
    "river": "code",
    "cross_section": "section_code",
    "gate": "gate_code",
    "pump": "pump_code",
}


def lock_batch(session: Session, batch_id: int) -> GISImportBatch | None:
    """Serialize lifecycle changes for a single batch."""

    return session.scalar(
        select(GISImportBatch).where(GISImportBatch.id == batch_id).with_for_update()
    )


def staging_rows(session: Session, batch: GISImportBatch) -> list[Any]:
    """Read the batch's typed staging rows in a deterministic order."""

    model = STAGING_MODELS[batch.entity_type]
    key = getattr(model, BUSINESS_KEYS[batch.entity_type])
    return list(
        session.scalars(
            select(model).where(model.batch_id == batch.id).order_by(key, model.id)
        ).all()
    )


def row_geometry_json(session: Session, geometry: Any) -> dict[str, Any] | None:
    """Serialize a nullable PostGIS geometry without relying on database row order."""

    if geometry is None:
        return None
    raw = session.scalar(select(func.ST_AsGeoJSON(geometry, 12)))
    return json.loads(raw) if raw else None


def row_geometry_hash_value(session: Session, geometry: Any) -> str | None:
    """Return exact little-endian EWKB hex for lossless geometry hashing."""

    if geometry is None:
        return None
    return session.scalar(select(func.encode(func.ST_AsEWKB(geometry, "NDR"), "hex")))


def staging_business_rows(session: Session, batch: GISImportBatch) -> list[dict[str, Any]]:
    """Return canonicalizable staging records including normalized geometry."""

    records: list[dict[str, Any]] = []
    for entity in staging_rows(session, batch):
        row = {column.name: getattr(entity, column.name) for column in entity.__table__.columns}
        row["geometry"] = row_geometry_hash_value(session, entity.geometry)
        records.append(row)
    return records


def latest_validation(session: Session, batch_id: int) -> GISValidationRun | None:
    """Read the newest validation generation for one batch."""

    return session.scalar(
        select(GISValidationRun)
        .where(GISValidationRun.batch_id == batch_id)
        .order_by(GISValidationRun.id.desc())
        .limit(1)
    )


def latest_approval(session: Session, batch_id: int) -> GISReview | None:
    """Read the newest approval event without overwriting review history."""

    return session.scalar(
        select(GISReview)
        .where(GISReview.batch_id == batch_id, GISReview.decision == "approve")
        .order_by(GISReview.id.desc())
        .limit(1)
    )


def issues_for_batch(session: Session, batch_id: int) -> list[GISValidationIssue]:
    """Read all issue generations newest-first for audit and map inspection."""

    return list(
        session.scalars(
            select(GISValidationIssue)
            .where(GISValidationIssue.batch_id == batch_id)
            .order_by(GISValidationIssue.validation_run_id.desc(), GISValidationIssue.id)
        ).all()
    )


def core_statement(entity_type: str, dataset_version_id: int) -> Select[Any]:
    """Build a deterministic core query for one supported object family."""

    model = CORE_MODELS[entity_type]
    key = getattr(model, BUSINESS_KEYS[entity_type])
    return select(model).where(model.dataset_version_id == dataset_version_id).order_by(key)
