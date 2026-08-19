from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest

from app.hydraulic.importers.vector import parse_vector
from app.hydraulic.production_validation import (
    SectionAxis,
    SurveyBranch,
    SurveyProfile,
    build_exchange_payload,
    extract_survey_profiles,
    match_profiles_to_axes,
    payload_geojson,
)
from app.hydraulic.schemas import CoordinateReferenceSpec


def _text(text: str, x: float, y: float) -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {"text": text},
        "geometry": {"type": "Point", "coordinates": [x, y]},
    }


def _coordinate_reference() -> CoordinateReferenceSpec:
    return CoordinateReferenceSpec(
        source_crs="EPSG:4546", engineering_crs="EPSG:4546",
        coordinate_mode="projected", axis_mapping="x_easting_y_northing",
        x_field="X", y_field="Y", z_field="H", horizontal_unit="m",
        vertical_unit="m", vertical_datum="1985国家高程基准",
        central_meridian=111, zone_width=3, zone_prefix_mode="none",
    )


def test_profile_frame_pairs_and_one_to_one_axis_match() -> None:
    frames = [_text("K0+100.00", 1000, 2000)]
    profile = [
        _text("-0+10.0", 950, 2006), _text("12.0", 950, 2025),
        _text("0+0.0", 1000, 2006), _text("10.0", 1000, 2025),
        _text("0+10.0", 1050, 2006), _text("12.5", 1050, 2025),
    ]
    profiles = extract_survey_profiles(frames, profile, [{
        "code": "main-grid",
        "branch_code": "MAIN",
        "label_x_min": 900,
        "expected_count": 1,
    }])
    assert profiles[0].raw_points == ((-10.0, 12.0), (0.0, 10.0), (10.0, 12.5))
    axis = SectionAxis(
        source_ordinal=7, branch_code="MAIN", coordinates=((100, -20), (100, 20)),
        chainage_m=101, location=(100, 0), snap_distance_m=0,
        intersection_angle_deg=90, perpendicular_deviation_deg=0, quality="passed",
    )
    matches, report = match_profiles_to_axes(profiles, [axis])
    assert len(matches) == 1
    assert report[0]["level"] == "passed"
    assert report[0]["chainage_delta_m"] == pytest.approx(1)


def test_role_tagged_geojson_roundtrip_preserves_axis_and_omits_invented_point_xy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    branch = SurveyBranch(
        code="MAIN", name="main", river_name="survey river", source_ordinal=1,
        coordinates=((500000, 2500000), (500200, 2500000)),
        chainage_start_m=0, chainage_end_m=200, annotation_count=3,
        annotation_rmse_m=0, source_order_reversed=False,
    )
    profile = SurveyProfile(
        group_code="main-grid", branch_code="MAIN", source_chainage_m=100,
        drawing_label="K0+100.00", drawing_label_xy=(1000, 2000),
        raw_points=((-10, 12), (0, 10), (10, 12.5)),
    )
    axis = SectionAxis(
        source_ordinal=1, branch_code="MAIN",
        coordinates=((500100, 2499980), (500100, 2500020)),
        chainage_m=100, location=(500100, 2500000), snap_distance_m=0,
        intersection_angle_deg=90, perpendicular_deviation_deg=0, quality="passed",
    )
    payload = build_exchange_payload(
        [branch], [(profile, axis)], _coordinate_reference(),
        network_code="SYNTHETIC-CASE", network_name="synthetic case",
        survey_date="2025-01-01", source_revision="SYNTHETIC-REV-001",
        topography_id="SYNTHETIC-TOPO-001", default_manning_n=0.035,
    )
    collection = payload_geojson(payload)
    storage = tmp_path / "imports"
    job_root = storage / "job-1"
    job_root.mkdir(parents=True)
    source = job_root / "source.geojson"
    source.write_bytes(b"{}")
    monkeypatch.setattr("app.hydraulic.importers.vector.importer.STORAGE_ROOT", storage)
    monkeypatch.setattr(
        "app.hydraulic.importers.vector.importer.stage_upload",
        lambda *_: ("job-1", "source-hash", source),
    )
    monkeypatch.setattr(
        "app.hydraulic.importers.vector.gdal_service.vector_to_geojson",
        lambda _source, target, *_args, **_kwargs: target.write_text(
            json.dumps(collection), encoding="utf-8"
        ),
    )
    parsed = parse_vector("normalized.geojson", b"{}", 4546, "geojson")
    section = parsed.sections[0]
    assert parsed.network_code == "SYNTHETIC-CASE"
    assert parsed.network_name == "synthetic case"
    assert section.survey_date == date(2025, 1, 1)
    assert section.axis_points == [(500100.0, 2499980.0), (500100.0, 2500020.0)]
    assert section.points[0].distance == 0
    assert all(point.x is None and point.y is None for point in section.points)
    assert parsed.branches[0].code == "MAIN"
    assert parsed.branches[0].flow_direction == "unknown"
    assert parsed.branches[0].source_revision == "SYNTHETIC-REV-001"
    roles = [feature["properties"]["feature_role"] for feature in collection["features"]]
    assert roles.count("branch") == 1
    assert roles.count("cross_section_axis") == 1
    assert roles.count("cross_section_point") == 3


def test_profile_axis_matching_fails_closed_on_bad_geometry_or_chainage() -> None:
    profile = SurveyProfile(
        group_code="main-grid", branch_code="MAIN", source_chainage_m=100,
        drawing_label="K0+100.00", drawing_label_xy=(1000, 2000),
        raw_points=((-10, 12), (0, 10), (10, 12.5)),
    )
    bad_axis = SectionAxis(
        source_ordinal=9, branch_code="MAIN", coordinates=((0, 0), (1, 1)),
        chainage_m=100, location=(0, 0), snap_distance_m=50,
        intersection_angle_deg=45, perpendicular_deviation_deg=45, quality="error",
    )
    with pytest.raises(ValueError, match="matched rejected axis"):
        match_profiles_to_axes([profile], [bad_axis])

    remote_axis = SectionAxis(
        source_ordinal=10, branch_code="MAIN", coordinates=((0, 0), (0, 1)),
        chainage_m=200, location=(0, 0), snap_distance_m=0,
        intersection_angle_deg=90, perpendicular_deviation_deg=0, quality="passed",
    )
    with pytest.raises(ValueError, match="chainage differs"):
        match_profiles_to_axes([profile], [remote_axis], maximum_chainage_delta_m=35)
