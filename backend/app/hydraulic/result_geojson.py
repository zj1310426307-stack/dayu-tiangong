"""Convert unified hydraulic results to factual GeoJSON without interpolation."""

from __future__ import annotations

from math import isclose
from typing import Any, Literal

from app.common.spatial import validate_geometry
from model.hydraulic_1d.contracts import Hydraulic1DModel, HydraulicResult


class HydraulicResultGeoJSONError(ValueError):
    """Reject cross-model results, unavailable times, or invalid locations."""


def build_water_surface_geojson(
    model: Hydraulic1DModel,
    result: HydraulicResult,
    *,
    time_seconds: float,
    missing_location: Literal["exclude", "error"] = "exclude",
) -> dict[str, Any]:
    """Build points and only truly adjacent Section segments at one exact time."""

    if result.simulation_id != model.simulation_id or result.scenario_id != model.scenario_id:
        raise HydraulicResultGeoJSONError("result identity does not match the unified model")
    if time_seconds < 0.0:
        raise HydraulicResultGeoJSONError("time_seconds must be non-negative")
    selected = {
        item.cross_section_id: item
        for item in result.records
        if not hasattr(item.timestamp, "tzinfo")
        and isclose(float(item.timestamp), time_seconds, rel_tol=0.0, abs_tol=1e-9)
    }
    if not selected:
        raise HydraulicResultGeoJSONError("result has no record at the requested exact time")

    features: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    point_by_section: dict[str, list[float]] = {}
    ordered_by_branch: dict[str, list[Any]] = {}
    for section in model.cross_sections:
        ordered_by_branch.setdefault(section.branch_id, []).append(section)
        record = selected.get(section.id)
        if record is None:
            continue
        location = section.location_geometry
        try:
            if location is None:
                raise ValueError("missing location")
            validate_geometry(location, "Point")
            coordinates = [float(value) for value in location["coordinates"]]
        except (KeyError, TypeError, ValueError) as exc:
            if missing_location == "error":
                raise HydraulicResultGeoJSONError(
                    f"Cross Section {section.id} has no valid Point location"
                ) from exc
            excluded.append(
                {
                    "branch_id": section.branch_id,
                    "cross_section_id": section.id,
                    "chainage_m": section.chainage_m,
                    "reason": "missing_or_invalid_point_location",
                }
            )
            continue
        point_by_section[section.id] = coordinates
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coordinates},
                "properties": {
                    "simulation_id": result.simulation_id,
                    "scenario_id": result.scenario_id,
                    "engine": result.engine,
                    "engine_version": result.engine_version,
                    "branch_id": record.branch_id,
                    "cross_section_id": record.cross_section_id,
                    "section_code": section.code,
                    "chainage_m": record.chainage_m,
                    "time_seconds": time_seconds,
                    "water_level_m": record.water_level_m,
                    "depth_m": record.depth_m,
                    "discharge_m3s": record.discharge_m3s,
                    "velocity_m_s": record.velocity_m_s,
                    "flow_area_m2": record.flow_area_m2,
                },
            }
        )

    for branch_id, sections in ordered_by_branch.items():
        ordered = sorted(sections, key=lambda item: item.chainage_m)
        for left, right in zip(ordered, ordered[1:]):
            if left.id not in selected or right.id not in selected:
                continue
            left_point = point_by_section.get(left.id)
            right_point = point_by_section.get(right.id)
            if left_point is None or right_point is None:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [left_point, right_point],
                    },
                    "properties": {
                        "branch_id": branch_id,
                        "start_cross_section_id": left.id,
                        "end_cross_section_id": right.id,
                        "time_seconds": time_seconds,
                    },
                }
            )

    if not point_by_section:
        raise HydraulicResultGeoJSONError("no result Section has a valid Point location")
    return {
        "type": "FeatureCollection",
        "metadata": {
            "simulation_id": result.simulation_id,
            "scenario_id": result.scenario_id,
            "engine": result.engine,
            "engine_version": result.engine_version,
            "time_seconds": time_seconds,
            "coordinate_reference": model.metadata.get("display_crs", "EPSG:4490"),
            "point_count": len(point_by_section),
            "segment_count": sum(
                item["geometry"]["type"] == "LineString" for item in features
            ),
            "excluded_count": len(excluded),
            "risk_extent_generated": False,
        },
        "features": features,
        "excluded": excluded,
    }


__all__ = ["HydraulicResultGeoJSONError", "build_water_surface_geojson"]
