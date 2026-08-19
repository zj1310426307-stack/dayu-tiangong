"""HYDRO-DATA-02 gates for factual water-surface GeoJSON output."""

import copy

import pytest

from app.hydraulic.validation_artifacts import (
    ValidationArtifactError,
    build_water_surface_geojson,
)
from model.provenance import snapshot_hash
from tests.hydro_validation.test_model_input_v3 import make_validation_snapshot


def make_surface_snapshot() -> dict:
    """Expand the compact validation snapshot to four ordered real locations."""

    snapshot = make_validation_snapshot()
    snapshot["branches"][0]["length_m"] = 300.0
    snapshot["reaches"][0]["end_chainage_m"] = 300.0
    snapshot["cross_sections"] = []
    snapshot["cross_section_profiles"] = []
    for index, chainage in enumerate((0.0, 100.0, 200.0, 300.0), start=1):
        section_id = 500 + index
        profile_id = 900 + index
        location = (
            None
            if chainage == 200.0
            else {
                "type": "Point",
                "coordinates": [113.0 + chainage / 100_000.0, 23.0],
            }
        )
        snapshot["cross_sections"].append(
            {
                "id": section_id,
                "branch_id": 10,
                "section_code": f"CS-{index:03d}",
                "chainage_m": chainage,
                "orientation_status": "confirmed",
                "active_profile_id": profile_id,
                "location": location,
            }
        )
        snapshot["cross_section_profiles"].append(
            {
                "id": profile_id,
                "cross_section_id": section_id,
                "branch_id": 10,
                "section_code": f"CS-{index:03d}",
                "chainage_m": chainage,
                "topography_id": "SURVEY-2026",
                "profile_hash": f"profile-sha-{section_id}",
                "points": [
                    {"offset_m": 0.0, "elevation_m": 12.0},
                    {"offset_m": 5.0, "elevation_m": 9.0},
                    {"offset_m": 10.0, "elevation_m": 12.0},
                ],
            }
        )
    return snapshot


def make_engine_result(snapshot: dict) -> dict:
    """Return deliberately shuffled section series from one successful task."""

    rows = []
    for section in reversed(snapshot["cross_sections"]):
        index = int(section["id"]) - 500
        rows.append(
            {
                "section_id": section["id"],
                "section_code": section["section_code"],
                "river_id": 110,
                "station": section["chainage_m"],
                "time": [0.0, 60.0],
                "water_level": [10.0, 10.0 + index / 10.0],
                "flow": [90.0, 90.0 + index],
                "velocity": [1.0, 1.0 + index / 100.0],
            }
        )
    return {"schema_version": "dayu.hydraulic-result.v2", "section_series": rows}


def test_water_surface_sorts_sections_records_gap_and_never_builds_risk_polygon() -> None:
    """Only located adjacent sections may become line segments at an exact time."""

    snapshot = make_surface_snapshot()
    before = copy.deepcopy(snapshot)
    task = {
        "id": 7001,
        "status": "success",
        "input_snapshot_hash": snapshot_hash(snapshot),
    }
    output = build_water_surface_geojson(
        snapshot,
        task,
        make_engine_result(snapshot),
        time_seconds=60.0,
    )

    assert snapshot == before
    assert output["type"] == "FeatureCollection"
    assert output["metadata"] == {
        "task_id": 7001,
        "time_seconds": 60.0,
        "dataset_version_id": 31,
        "input_snapshot_hash": snapshot_hash(snapshot),
        "profile_hashes": [
            "profile-sha-501",
            "profile-sha-502",
            "profile-sha-503",
            "profile-sha-504",
        ],
        "coordinate_reference": snapshot["coordinate_reference"],
        "point_count": 3,
        "segment_count": 1,
        "excluded_count": 1,
        "risk_extent_generated": False,
    }
    points = [feature for feature in output["features"] if feature["geometry"]["type"] == "Point"]
    segments = [
        feature
        for feature in output["features"]
        if feature["geometry"]["type"] == "LineString"
    ]
    assert [item["properties"]["chainage_m"] for item in points] == [0.0, 100.0, 300.0]
    assert points[0]["properties"]["water_level"] == pytest.approx(10.1)
    assert points[0]["properties"]["profile_hash"] == "profile-sha-501"
    assert len(segments) == 1
    assert segments[0]["properties"]["start_section_id"] == 501
    assert segments[0]["properties"]["end_section_id"] == 502
    assert output["excluded"] == [
        {
            "task_id": 7001,
            "time_seconds": 60.0,
            "dataset_version_id": 31,
            "profile_hash": "profile-sha-503",
            "branch_id": 10,
            "branch_code": "BR-01",
            "section_id": 503,
            "section_code": "CS-003",
            "chainage_m": 200.0,
            "reason": "missing_or_invalid_point_location",
        }
    ]
    assert all(feature["geometry"]["type"] != "Polygon" for feature in output["features"])


def test_water_surface_rejects_invalid_task_snapshot_and_location() -> None:
    """Task state, frozen hash, and missing spatial facts are hard audit gates."""

    snapshot = make_surface_snapshot()
    results = make_engine_result(snapshot)
    with pytest.raises(ValidationArtifactError, match="successful task"):
        build_water_surface_geojson(
            snapshot,
            {"id": 1, "status": "failed"},
            results,
            time_seconds=60.0,
        )
    with pytest.raises(ValidationArtifactError, match="does not match snapshot"):
        build_water_surface_geojson(
            snapshot,
            {"id": 1, "status": "success", "input_snapshot_hash": "0" * 64},
            results,
            time_seconds=60.0,
        )
    with pytest.raises(ValidationArtifactError, match="no valid Point location"):
        build_water_surface_geojson(
            snapshot,
            {"id": 1, "status": "success"},
            results,
            time_seconds=60.0,
            missing_location="error",
        )


def test_water_surface_accepts_flat_database_rows_without_interpolation() -> None:
    """Persisted scalar rows are filtered to an exact requested time only."""

    snapshot = make_surface_snapshot()
    snapshot["cross_sections"] = snapshot["cross_sections"][:2]
    snapshot["cross_section_profiles"] = snapshot["cross_section_profiles"][:2]
    rows = [
        {
            "section_id": section["id"],
            "river_id": 110,
            "station": section["chainage_m"],
            "time_seconds": time_seconds,
            "water_level": 10.0 + section["id"] / 1000.0,
            "flow": 100.0,
            "velocity": 1.2,
        }
        for time_seconds in (0.0, 60.0)
        for section in reversed(snapshot["cross_sections"])
    ]
    output = build_water_surface_geojson(
        snapshot,
        {"id": 8, "status": "success"},
        rows,
        time_seconds=60.0,
    )
    assert output["metadata"]["point_count"] == 2
    assert output["metadata"]["segment_count"] == 1
    assert {feature["properties"].get("time_seconds") for feature in output["features"]} == {60.0}
