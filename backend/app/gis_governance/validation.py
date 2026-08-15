"""Authoritative PostGIS-backed validation for typed QGIS staging batches."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.gis.models import (
    CrossSection,
    Gate,
    GISImportBatch,
    GISValidationIssue,
    GISValidationRun,
    Pump,
    River,
)
from app.gis_governance.hashing import canonical_sha256
from app.gis_governance.repository import BUSINESS_KEYS, STAGING_MODELS, staging_business_rows


RULESET_VERSION = "gis-opt1.1"


def staging_hash(session: Session, batch: GISImportBatch) -> str:
    """Compute the authoritative hash for the current editable staging generation."""

    return canonical_sha256(staging_business_rows(session, batch))


def _issue(
    run: GISValidationRun,
    batch: GISImportBatch,
    entity: Any,
    code: str,
    message: str,
    *,
    severity: str = "error",
    details: dict[str, Any] | None = None,
) -> GISValidationIssue:
    """Build a persistent issue tied to a stable business feature reference."""

    key = BUSINESS_KEYS[batch.entity_type]
    return GISValidationIssue(
        validation_run_id=run.id,
        batch_id=batch.id,
        entity_type=batch.entity_type,
        feature_ref=str(getattr(entity, key, None) or entity.source_feature_id),
        rule_code=code,
        severity=severity,
        message=message,
        geometry=entity.geometry,
        details_json=details or {},
    )


def _common_issues(
    session: Session, run: GISValidationRun, batch: GISImportBatch, rows: list[Any]
) -> list[GISValidationIssue]:
    """Validate universal geometry, provenance, and target CRS requirements."""

    issues: list[GISValidationIssue] = []
    for row in rows:
        geometry_state = session.execute(
            select(
                func.ST_IsEmpty(row.geometry),
                func.ST_IsValid(row.geometry),
                func.ST_SRID(row.geometry),
                func.GeometryType(row.geometry),
            )
        ).one()
        empty, valid, srid, geometry_type = geometry_state
        expected_type = "LINESTRING" if batch.entity_type == "river" else "POINT"
        if empty:
            issues.append(_issue(run, batch, row, "GEOMETRY_EMPTY", "Geometry is empty."))
        if not valid:
            issues.append(_issue(run, batch, row, "GEOMETRY_INVALID", "Geometry is invalid."))
        if srid != 4490:
            issues.append(
                _issue(
                    run, batch, row, "GEOMETRY_SRID",
                    "Geometry must use EPSG:4490.", details={"actual_srid": srid},
                )
            )
        if str(geometry_type).upper() != expected_type:
            issues.append(
                _issue(
                    run, batch, row, "GEOMETRY_TYPE",
                    f"Geometry must be {expected_type}.",
                    details={"actual_type": geometry_type},
                )
            )
        if row.target_crs != "EPSG:4490":
            issues.append(_issue(run, batch, row, "TARGET_CRS", "Target CRS must be EPSG:4490."))
    return issues


def _entity_issues(
    session: Session, run: GISValidationRun, batch: GISImportBatch, rows: list[Any]
) -> list[GISValidationIssue]:
    """Validate the first four water-management object families using mature PostGIS checks."""

    issues: list[GISValidationIssue] = []
    staging_model = STAGING_MODELS[batch.entity_type]
    parent_id = batch.parent_version_id
    parent_river_codes = set(
        session.scalars(
            select(River.code).where(River.dataset_version_id == parent_id)
        ).all()
    ) if parent_id else set()
    for row in rows:
        if row.operation == "delete":
            if batch.entity_type == "river" and parent_id:
                parent_river_id = session.scalar(
                    select(River.id).where(
                        River.dataset_version_id == parent_id,
                        River.code == row.code,
                    )
                )
                if parent_river_id is not None:
                    dependency_counts = {
                        "cross_sections": session.scalar(
                            select(func.count(CrossSection.id)).where(
                                CrossSection.dataset_version_id == parent_id,
                                CrossSection.river_id == parent_river_id,
                            )
                        ) or 0,
                        "gates": session.scalar(
                            select(func.count(Gate.id)).where(
                                Gate.dataset_version_id == parent_id,
                                Gate.river_id == parent_river_id,
                            )
                        ) or 0,
                        "pumps": session.scalar(
                            select(func.count(Pump.id)).where(
                                Pump.dataset_version_id == parent_id,
                                Pump.river_id == parent_river_id,
                            )
                        ) or 0,
                    }
                    if any(dependency_counts.values()):
                        issues.append(
                            _issue(
                                run,
                                batch,
                                row,
                                "RIVER_DELETE_DEPENDENCIES",
                                "River deletion is blocked while dependent core objects remain.",
                                details=dependency_counts,
                            )
                        )
            continue
        if batch.entity_type == "river":
            if not row.code.strip() or not row.name.strip():
                issues.append(_issue(run, batch, row, "RIVER_REQUIRED_TEXT", "River code and name are required."))
            if row.length <= 0:
                issues.append(_issue(run, batch, row, "RIVER_LENGTH", "River length must be greater than zero."))
            if row.status not in {"active", "inactive", "planned"}:
                issues.append(_issue(run, batch, row, "RIVER_STATUS", "River status is outside the allowed domain."))
            if not session.scalar(select(func.ST_IsSimple(row.geometry))):
                issues.append(_issue(run, batch, row, "RIVER_SIMPLE", "River LineString must be simple."))
            measured = session.scalar(
                select(
                    func.ST_Length(
                        cast(staging_model.geometry, Geography(srid=4490))
                    )
                ).where(staging_model.id == row.id)
            ) or 0
            if measured > 0 and abs(row.length - measured) / measured > 0.5:
                issues.append(
                    _issue(
                        run, batch, row, "RIVER_LENGTH_WARNING",
                        "Declared river length differs materially from geodesic length.",
                        severity="warning",
                        details={"declared": row.length, "measured": measured},
                    )
                )
        elif batch.entity_type == "cross_section":
            if row.river_code not in parent_river_codes:
                issues.append(_issue(run, batch, row, "SECTION_RIVER_REFERENCE", "Referenced river code does not exist in the parent version."))
            if row.station < 0 or row.roughness <= 0:
                issues.append(_issue(run, batch, row, "SECTION_HYDRAULICS", "Station must be non-negative and roughness positive."))
            profile = row.points.get("points", []) if isinstance(row.points, dict) else []
            if len(profile) < 2:
                issues.append(_issue(run, batch, row, "SECTION_PROFILE", "Cross-section profile needs at least two points."))
        elif batch.entity_type == "gate":
            if row.river_code not in parent_river_codes:
                issues.append(_issue(run, batch, row, "GATE_RIVER_REFERENCE", "Referenced river code does not exist in the parent version."))
            if row.width <= 0 or row.height <= 0 or row.max_flow <= 0:
                issues.append(_issue(run, batch, row, "GATE_PARAMETERS", "Gate width, height, and maximum flow must be positive."))
            if row.status not in {"online", "offline", "maintenance", "fault"}:
                issues.append(_issue(run, batch, row, "GATE_STATUS", "Gate status is outside the allowed domain."))
        elif batch.entity_type == "pump":
            if row.river_code not in parent_river_codes:
                issues.append(_issue(run, batch, row, "PUMP_RIVER_REFERENCE", "Referenced river code does not exist in the parent version."))
            if row.design_flow <= 0 or row.head <= 0 or row.power <= 0:
                issues.append(_issue(run, batch, row, "PUMP_PARAMETERS", "Pump flow, head, and power must be positive."))
            curve = row.efficiency_curve.get("points", []) if isinstance(row.efficiency_curve, dict) else []
            if len(curve) < 2:
                issues.append(_issue(run, batch, row, "PUMP_CURVE", "Pump efficiency curve needs at least two points."))
            if row.status not in {"online", "offline", "maintenance", "fault"}:
                issues.append(_issue(run, batch, row, "PUMP_STATUS", "Pump status is outside the allowed domain."))
    return issues


def validate_batch(session: Session, batch: GISImportBatch) -> GISValidationRun:
    """Persist a complete validation generation; only zero errors produces a pass."""

    model = STAGING_MODELS[batch.entity_type]
    rows = list(session.scalars(select(model).where(model.batch_id == batch.id).order_by(model.id)).all())
    content_hash = staging_hash(session, batch)
    run = GISValidationRun(
        batch_id=batch.id,
        ruleset_version=RULESET_VERSION,
        status="running",
        staging_content_hash=content_hash,
        summary_json={},
    )
    session.add(run)
    session.flush()
    issues: list[GISValidationIssue] = []
    if not rows:
        issues.append(
            GISValidationIssue(
                validation_run_id=run.id,
                batch_id=batch.id,
                entity_type=batch.entity_type,
                feature_ref=None,
                rule_code="BATCH_EMPTY",
                severity="error",
                message="Batch contains no typed staging features.",
                geometry=None,
                details_json={},
            )
        )
    else:
        issues.extend(_common_issues(session, run, batch, rows))
        issues.extend(_entity_issues(session, run, batch, rows))
    session.add_all(issues)
    errors = sum(issue.severity == "error" for issue in issues)
    warnings = sum(issue.severity == "warning" for issue in issues)
    run.status = "passed" if errors == 0 else "failed"
    run.finished_at = datetime.now(UTC)
    run.summary_json = {
        "features": len(rows),
        "errors": errors,
        "warnings": warnings,
        "infos": sum(issue.severity == "info" for issue in issues),
        "ruleset": RULESET_VERSION,
    }
    batch.staging_content_hash = content_hash
    session.flush()
    return run


def apply_quality_status(
    session: Session, batch: GISImportBatch, run: GISValidationRun
) -> None:
    """Project the latest validation generation onto the QGIS quality indicator."""

    model = STAGING_MODELS[batch.entity_type]
    business_key = BUSINESS_KEYS[batch.entity_type]
    error_refs = set(
        session.scalars(
            select(GISValidationIssue.feature_ref).where(
                GISValidationIssue.validation_run_id == run.id,
                GISValidationIssue.severity == "error",
                GISValidationIssue.feature_ref.is_not(None),
            )
        ).all()
    )
    rows = session.scalars(
        select(model).where(model.batch_id == batch.id).order_by(model.id)
    ).all()
    for row in rows:
        feature_ref = str(
            getattr(row, business_key, None) or row.source_feature_id
        )
        row.quality_status = "failed" if feature_ref in error_refs else "passed"
