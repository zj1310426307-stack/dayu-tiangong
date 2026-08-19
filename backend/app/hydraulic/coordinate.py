"""Authoritative PostGIS coordinate normalization and import evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.hydraulic.schemas import CoordinateReferenceSpec, HydraulicExchangePayload


def canonical_hash(value: object) -> str:
    """Hash canonical JSON for preview/commit and processing cache identity."""

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def preview_config_hash(
    source_hash: str, parser_profile: str, coordinate_reference: CoordinateReferenceSpec
) -> str:
    """Bind one preview to the exact bytes, parser, and coordinate declaration."""

    return canonical_hash({
        "source_hash_sha256": source_hash,
        "parser_profile": parser_profile,
        "coordinate_reference": coordinate_reference.model_dump(mode="json"),
    })


def _samples(payload: HydraulicExchangePayload | None, limit: int = 10) -> list[tuple[float, float]]:
    """Take a bounded deterministic sample of source XY values."""

    values: list[tuple[float, float]] = []
    if payload is None:
        return values
    for branch in payload.branches:
        values.extend((point.x, point.y) for point in branch.points)
        if len(values) >= limit:
            return values[:limit]
    for section in payload.sections:
        if section.location_x is not None and section.location_y is not None:
            values.append((section.location_x, section.location_y))
        values.extend(section.axis_points)
        values.extend(
            (point.x, point.y)
            for point in section.points
            if point.x is not None and point.y is not None
        )
        if len(values) >= limit:
            return values[:limit]
    return values[:limit]


def transformation_evidence(
    session: Session,
    payload: HydraulicExchangePayload | None,
    coordinate_reference: CoordinateReferenceSpec,
) -> dict[str, object]:
    """Record bounded before/after samples and the database transformation runtime."""

    runtime = session.execute(
        text("SELECT postgis_full_version(), postgis_proj_version()")
    ).one()
    before: list[dict[str, float]] = []
    display: list[dict[str, float]] = []
    engineering: list[dict[str, float]] = []
    for raw_x, raw_y in _samples(payload):
        easting, northing = coordinate_reference.normalize_xy(raw_x, raw_y)
        row = session.execute(
            text(
                "SELECT "
                "ST_X(ST_Transform(ST_SetSRID(ST_MakePoint(:x,:y),:source),4490)), "
                "ST_Y(ST_Transform(ST_SetSRID(ST_MakePoint(:x,:y),:source),4490)), "
                "ST_X(ST_Transform(ST_SetSRID(ST_MakePoint(:x,:y),:source),:engineering)), "
                "ST_Y(ST_Transform(ST_SetSRID(ST_MakePoint(:x,:y),:source),:engineering))"
            ),
            {
                "x": easting,
                "y": northing,
                "source": coordinate_reference.source_srid,
                "engineering": coordinate_reference.engineering_srid,
            },
        ).one()
        before.append({"x": raw_x, "y": raw_y, "normalized_x": easting, "normalized_y": northing})
        display.append({"x": float(row[0]), "y": float(row[1])})
        engineering.append({"x": float(row[2]), "y": float(row[3])})
    return {
        "authority": "PostGIS ST_Transform",
        "postgis_full_version": str(runtime[0]),
        "proj_version": str(runtime[1]),
        "pipeline": (
            f"axis:{coordinate_reference.axis_mapping};"
            f"EPSG:{coordinate_reference.source_srid}->EPSG:4490;"
            f"EPSG:{coordinate_reference.source_srid}->EPSG:{coordinate_reference.engineering_srid}"
        ),
        "source_sample": before,
        "display_sample_epsg4490": display,
        "engineering_sample": engineering,
        "sample_count": len(before),
    }


def normalized_coordinates(
    coordinates: Iterable[Iterable[float]], coordinate_reference: CoordinateReferenceSpec
) -> list[list[float]]:
    """Normalize a list of source pairs according to the declared axis mapping."""

    return [list(coordinate_reference.normalize_xy(*list(value)[:2])) for value in coordinates]
