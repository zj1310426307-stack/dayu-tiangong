"""Normalize SHP ZIP and DXF features through the existing bounded GDAL runtime."""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from typing import Any

from app.data_converter import gdal_service, importer
from app.hydraulic.importers.common import file_identity, safe_code
from app.hydraulic.schemas import (
    HydraulicBranchInput,
    HydraulicChainageInput,
    HydraulicCrossSectionInput,
    HydraulicExchangePayload,
    HydraulicSectionPointInput,
)


def _properties(feature: dict[str, Any]) -> dict[str, object]:
    """Return case-insensitive vector attributes for mapping conventions."""

    return {
        str(key).strip().lower(): value
        for key, value in (feature.get("properties") or {}).items()
        if value not in (None, "")
    }


def _property(properties: dict[str, object], *keys: str, default: object = None) -> object:
    """Read the first available source attribute from a controlled alias list."""

    for key in keys:
        if key.lower() in properties:
            return properties[key.lower()]
    return default


def _line_coordinates(geometry: dict[str, Any]) -> list[list[list[float]]]:
    """Normalize LineString and MultiLineString into independent coordinate sequences."""

    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "LineString":
        return [coordinates]
    if kind == "MultiLineString":
        return coordinates
    return []


def _chainage_points(
    coordinates: list[list[float]], start: float, end: float | None
) -> list[HydraulicChainageInput]:
    """Generate monotonic chainage from metre-based projected coordinates."""

    cumulative = [0.0]
    for left, right in zip(coordinates, coordinates[1:]):
        cumulative.append(
            cumulative[-1]
            + ((float(right[0]) - float(left[0])) ** 2 + (float(right[1]) - float(left[1])) ** 2) ** 0.5
        )
    measured = cumulative[-1]
    target_end = end if end is not None else start + measured
    if target_end <= start:
        raise ValueError("vector branch end_chainage must be greater than start_chainage")
    scale = (target_end - start) / measured if measured > 0 else 0
    return [
        HydraulicChainageInput(
            chainage=start + distance * scale,
            x=float(position[0]),
            y=float(position[1]),
        )
        for distance, position in zip(cumulative, coordinates)
    ]


def parse_vector(
    filename: str, content: bytes, source_srid: int, source_kind: str
) -> HydraulicExchangePayload:
    """Normalize vector features without deriving distance from angular coordinates."""

    if source_srid in {4326, 4490}:
        raise ValueError(
            "vector branch import requires an approved projected source CRS; "
            "geographic coordinates cannot be used to derive chainage"
        )

    job_id, _, source = importer.stage_upload(filename, content, "vector")
    job_root = importer.STORAGE_ROOT / job_id
    target = job_root / "hydraulic.geojson"
    try:
        gdal_service.vector_to_geojson(
            source, target, source_srid, source_srid=source_srid, rfc7946=False
        )
        collection = json.loads(target.read_text(encoding="utf-8"))
    finally:
        root = importer.STORAGE_ROOT.resolve()
        resolved = job_root.resolve()
        if resolved.is_relative_to(root):
            shutil.rmtree(resolved, ignore_errors=True)

    default_code, default_name = file_identity(filename, source_kind.upper())
    branches: list[HydraulicBranchInput] = []
    section_rows: dict[str, list[tuple[dict[str, object], list[float]]]] = defaultdict(list)
    section_axes: dict[str, list[list[float]]] = {}
    explicit_network_codes: set[str] = set()
    explicit_network_names: set[str] = set()
    for feature_index, feature in enumerate(collection.get("features", []), start=1):
        geometry = feature.get("geometry") or {}
        properties = _properties(feature)
        raw_network_code = _property(properties, "network_code")
        raw_network_name = _property(properties, "network_name")
        if raw_network_code is not None:
            explicit_network_codes.add(str(raw_network_code))
        if raw_network_name is not None:
            explicit_network_names.add(str(raw_network_name))
        feature_role = str(_property(properties, "feature_role", default="")).strip().lower()
        line_parts = _line_coordinates(geometry)
        if feature_role == "cross_section_axis":
            section_code = _property(properties, "section_code", "section_id", "xs_code")
            if section_code is None or len(line_parts) != 1 or len(line_parts[0]) < 2:
                raise ValueError(
                    "cross_section_axis requires one LineString and an explicit section_code"
                )
            key = str(section_code)
            if key in section_axes:
                raise ValueError(f"cross section {key} has more than one mapped axis")
            section_axes[key] = line_parts[0]
            continue
        if feature_role not in {"", "branch", "cross_section_point"}:
            raise ValueError(f"unsupported explicit feature_role: {feature_role}")
        for part_index, coordinates in enumerate(
            line_parts if feature_role != "cross_section_point" else [], start=1
        ):
            if len(coordinates) < 2:
                continue
            base_code = str(
                _property(properties, "branch_code", "code", "id", "layer", default=f"BRANCH-{feature_index:03d}")
            )
            code = safe_code(
                f"{base_code}-{part_index}" if len(_line_coordinates(geometry)) > 1 else base_code,
                f"BRANCH-{feature_index:03d}-{part_index:02d}",
            )
            start = float(_property(properties, "start_chainage", "start_sta", default=0) or 0)
            raw_end = _property(properties, "end_chainage", "end_sta")
            branches.append(
                HydraulicBranchInput(
                    code=code,
                    river_name=str(_property(properties, "river_name", "river", default=code))[:128],
                    branch_name=str(_property(properties, "branch_name", "name", "layer", default=code))[:128],
                    flow_direction=str(_property(properties, "flow_direction", "direction", default="forward")).lower(),
                    source_revision=(
                        str(_property(properties, "source_revision"))[:64]
                        if _property(properties, "source_revision") is not None else None
                    ),
                    points=_chainage_points(
                        coordinates, start, float(raw_end) if raw_end is not None else None
                    ),
                )
            )
        if geometry.get("type") == "Point" and feature_role in {"", "cross_section_point"}:
            section_code = _property(properties, "section_code", "section_id", "xs_code")
            distance = _property(properties, "distance", "offset")
            elevation = _property(properties, "elevation", "z", "level")
            branch_code = _property(properties, "branch_code", "reach_id", "river_code")
            if section_code is not None and distance is not None and elevation is not None and branch_code is not None:
                section_rows[str(section_code)].append((properties, geometry.get("coordinates") or []))

    sections: list[HydraulicCrossSectionInput] = []
    for index, (raw_code, rows) in enumerate(section_rows.items(), start=1):
        ordered = sorted(rows, key=lambda item: float(_property(item[0], "distance", "offset", default=0)))
        first, first_coordinate = ordered[0]
        axis = section_axes.get(raw_code, [])
        raw_location_x = _property(first, "location_x")
        raw_location_y = _property(first, "location_y")
        if (raw_location_x is None) != (raw_location_y is None):
            raise ValueError(f"cross section {raw_code} has incomplete explicit location XY")
        omit_source_xy = bool(_property(first, "omit_source_xy", default=False))
        sections.append(
            HydraulicCrossSectionInput(
                section_code=safe_code(raw_code, f"XS-{index:04d}"),
                section_name=str(_property(first, "section_name", default=raw_code))[:128],
                branch_code=safe_code(
                    str(_property(first, "branch_code", "reach_id", "river_code")),
                    "BRANCH-UNKNOWN",
                ),
                chainage=float(_property(first, "chainage", "station", default=0) or 0),
                topography_id=str(_property(first, "topography_id", "topo_id", default="DEFAULT"))[:64],
                survey_date=_property(first, "survey_date"),
                survey_method=str(_property(first, "survey_method"))[:64]
                if _property(first, "survey_method") is not None else None,
                default_manning_n=float(_property(first, "default_manning_n", default=0.03)),
                location_x=(
                    float(raw_location_x) if raw_location_x is not None else
                    float(first_coordinate[0]) if len(first_coordinate) >= 2 else None
                ),
                location_y=(
                    float(raw_location_y) if raw_location_y is not None else
                    float(first_coordinate[1]) if len(first_coordinate) >= 2 else None
                ),
                axis_points=[(float(value[0]), float(value[1])) for value in axis],
                points=[
                    HydraulicSectionPointInput(
                        sequence=point_index,
                        distance=float(_property(properties, "distance", "offset")),
                        elevation=float(_property(properties, "elevation", "z", "level")),
                        point_code=(
                            str(_property(properties, "point_code"))[:64]
                            if _property(properties, "point_code") is not None else None
                        ),
                        x=(
                            None if bool(_property(properties, "omit_source_xy", default=omit_source_xy))
                            else float(coordinate[0]) if len(coordinate) >= 2 else None
                        ),
                        y=(
                            None if bool(_property(properties, "omit_source_xy", default=omit_source_xy))
                            else float(coordinate[1]) if len(coordinate) >= 2 else None
                        ),
                        z=(
                            None if bool(_property(properties, "omit_source_xy", default=omit_source_xy))
                            else float(coordinate[2]) if len(coordinate) >= 3 else None
                        ),
                    )
                    for point_index, (properties, coordinate) in enumerate(ordered)
                ],
            )
        )
    if len(explicit_network_codes) > 1 or len(explicit_network_names) > 1:
        raise ValueError("vector features contain inconsistent explicit network identity")
    network_code = (
        safe_code(next(iter(explicit_network_codes)), default_code)
        if explicit_network_codes else default_code
    )
    network_name = (
        next(iter(explicit_network_names))[:128]
        if explicit_network_names else default_name
    )
    return HydraulicExchangePayload(
        network_code=network_code,
        network_name=network_name,
        source_srid=source_srid,
        source_kind=source_kind,
        branches=branches,
        sections=sections,
    )
