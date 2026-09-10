"""Regression gates for Marker detection and non-destructive Vertical Extension."""

from __future__ import annotations

import copy

import pytest

from app.hydraulic.marker_processing import (
    SectionPoint,
    build_processed_geometry,
    detect_markers,
    marker_dict,
)
from app.hydraulic.processing import _submerged_interval_metrics
from model.hydraulic_1d import CrossSectionPoint, HydraulicCrossSection, RoughnessZone


def points(elevations: list[float]) -> list[SectionPoint]:
    """Build a stable left-to-right profile without introducing XY semantics."""

    return [SectionPoint(index, float(index * 10), elevation) for index, elevation in enumerate(elevations)]


@pytest.mark.parametrize(
    "elevations",
    [
        [5, 3, 1, 3, 5],  # V section
        [5, 2, 2, 2, 5],  # trapezoidal/flat channel
        [6, 4, 1, 3, 5],  # unequal crests
    ],
)
def test_full_extent_and_mike11_find_ordered_markers(elevations: list[float]) -> None:
    result = detect_markers(points(elevations), "MIKE11_COMPATIBLE")
    assert [marker.type for marker in result.markers] == ["M1", "M2", "M3"]
    assert result.markers[0].sequence < result.markers[1].sequence < result.markers[2].sequence


def test_equal_low_platform_is_deterministic() -> None:
    profile = points([5, 3, 1, 1, 1, 4, 6])
    first = detect_markers(profile, "MIKE11_COMPATIBLE")
    second = detect_markers(profile, "MIKE11_COMPATIBLE")
    assert first == second
    assert first.markers[1].sequence == 3
    assert "MULTIPLE_LOW_POINTS" in first.warnings


def test_wide_crests_and_boundary_candidates_require_review() -> None:
    result = detect_markers(points([8, 8, 4, 1, 5, 9, 9]), "MIKE11_COMPATIBLE")
    assert "MULTIPLE_LEFT_CRESTS" in result.warnings
    assert "MULTIPLE_RIGHT_CRESTS" in result.warnings
    assert result.review_status == "NEEDS_REVIEW"


def test_natural_slope_or_road_spike_is_not_silently_accepted() -> None:
    result = detect_markers(points([12, 4, 3, 1, 3, 4, 11]), "MIKE11_COMPATIBLE")
    assert "CREST_AT_SECTION_BOUNDARY" in result.warnings
    assert result.review_status == "NEEDS_REVIEW"
    assert all(marker.confidence < 0.9 for marker in result.markers)


def test_detection_ignores_global_xy_and_branch_reverse() -> None:
    forward = [SectionPoint(i, i * 10, z, x=1000 - i * 100, y=2000 + i) for i, z in enumerate([5, 2, 1, 3, 6])]
    reverse_xy = [SectionPoint(p.sequence, p.offset, p.elevation, x=-p.x, y=-p.y) for p in forward]
    assert [m.sequence for m in detect_markers(forward, "MIKE11_COMPATIBLE").markers] == [m.sequence for m in detect_markers(reverse_xy, "MIKE11_COMPATIBLE").markers]


def test_insufficient_points_fail_closed() -> None:
    result = detect_markers(points([3, 1]), "MIKE11_COMPATIBLE")
    assert not result.markers
    assert result.warnings == ("INSUFFICIENT_POINTS",)


def test_locked_manual_and_higher_priority_gis_markers_survive_auto() -> None:
    profile = points([7, 5, 2, 1, 3, 6, 8])
    base = marker_dict(detect_markers(profile, "FULL_EXTENT"))
    base["M1"].update({"sequence": 1, "offset": 10.0, "elevation": 5.0, "source": "MANUAL", "locked": True, "review_status": "REVIEWED"})
    base["M3"].update({"sequence": 5, "offset": 50.0, "elevation": 6.0, "source": "GIS_LEVEE", "locked": False})
    result = detect_markers(profile, "MIKE11_COMPATIBLE", base)
    assert result.markers[0].sequence == 1
    assert result.markers[0].source == "MANUAL"
    assert result.markers[2].sequence == 5
    assert result.markers[2].source == "GIS_LEVEE"


def test_invalid_locked_marker_order_is_reported() -> None:
    profile = points([6, 4, 1, 3, 5])
    existing = marker_dict(detect_markers(profile, "FULL_EXTENT"))
    existing["M1"].update({"sequence": 3, "offset": 30.0, "locked": True, "source": "MANUAL"})
    result = detect_markers(profile, "MIKE11_COMPATIBLE", existing)
    assert "INVALID_MARKER_ORDER" in result.warnings


def test_implausible_active_widths_require_review() -> None:
    narrow = [
        SectionPoint(0, 0.0, 5), SectionPoint(1, 10.0, 2),
        SectionPoint(2, 20.0, 1), SectionPoint(3, 30.0, 5),
        SectionPoint(4, 1000.0, 4),
    ]
    result = detect_markers(narrow, "MIKE11_COMPATIBLE")
    assert "VERY_NARROW_ACTIVE_SECTION" in result.warnings
    wide = [SectionPoint(0, 0.0, 5), SectionPoint(1, 3000.0, 1), SectionPoint(2, 6000.0, 5)]
    result = detect_markers(wide, "FULL_EXTENT")
    assert "VERY_WIDE_ACTIVE_SECTION" in result.warnings
    assert result.review_status == "NEEDS_REVIEW"


def test_marker_extent_preserves_outside_raw_points() -> None:
    raw = points([8, 6, 4, 1, 5, 7, 9])
    before = copy.deepcopy(raw)
    markers = marker_dict(detect_markers(raw, "MIKE11_COMPATIBLE"))
    processed, _ = build_processed_geometry(raw, markers, "MARKER_EXTENT", "REAL_GEOMETRY", None)
    assert raw == before
    assert len(processed) <= len(raw)


def test_vertical_extension_adds_only_virtual_walls_and_preserves_raw() -> None:
    raw = points([8, 5, 1, 4, 7])
    before = copy.deepcopy(raw)
    markers = marker_dict(detect_markers(raw, "FULL_EXTENT"))
    processed, warnings = build_processed_geometry(raw, markers, "MARKER_EXTENT", "VERTICAL_EXTENSION", 10.0, 9.5, 1.0)
    assert raw == before
    assert processed[0].virtual and processed[-1].virtual
    assert processed[0].offset == markers["M1"]["offset"]
    assert processed[-1].offset == markers["M3"]["offset"]
    assert "EXTENSION_BELOW_DESIGN_LEVEL_PLUS_FREEBOARD" in warnings


def test_vertical_extension_rejects_top_below_crest() -> None:
    raw = points([8, 5, 1, 4, 7])
    markers = marker_dict(detect_markers(raw, "FULL_EXTENT"))
    with pytest.raises(ValueError, match="must exceed"):
        build_processed_geometry(raw, markers, "MARKER_EXTENT", "VERTICAL_EXTENSION", 7.5)


def test_manual_force_can_explicitly_replace_locked_markers() -> None:
    profile = points([9, 5, 2, 1, 4, 7, 8])
    existing = marker_dict(detect_markers(profile, "FULL_EXTENT"))
    existing["M1"].update({"sequence": 1, "offset": 10.0, "locked": True, "source": "MANUAL"})
    forced = detect_markers(profile, "MIKE11_COMPATIBLE", existing, force=True)
    assert forced.markers[0].source == "AUTO_MIKE11_COMPATIBLE"


def test_unequal_crests_keep_geometric_stage_metrics_with_vertical_walls() -> None:
    geometry = [(0.0, 9.0), (0.0, 6.0), (10.0, 1.0), (20.0, 5.0), (20.0, 9.0)]
    values = [
        _submerged_interval_metrics(geometry, stage, 0.0, 20.0)
        for stage in (4.0, 5.0, 5.5, 6.0, 8.0)
    ]
    assert all(right[0] > left[0] for left, right in zip(values, values[1:]))
    assert all(right[1] >= left[1] for left, right in zip(values, values[1:]))
    assert all(value[2] > 0 for value in values)


def test_solver_neutral_contract_accepts_boundary_vertical_walls() -> None:
    section = HydraulicCrossSection(
        id="xs-1", branch_id="branch-1", code="XS-1", chainage_m=100,
        vertical_datum="1985-national-height",
        points=(
            CrossSectionPoint(station_m=10, elevation_m=10),
            CrossSectionPoint(station_m=10, elevation_m=6),
            CrossSectionPoint(station_m=20, elevation_m=2),
            CrossSectionPoint(station_m=30, elevation_m=5),
            CrossSectionPoint(station_m=30, elevation_m=10),
        ),
        manning_n=0.029,
        roughness_zones=(RoughnessZone(start_station_m=10, end_station_m=30, manning_n=0.029),),
    )
    assert section.points[0].station_m == section.points[1].station_m


def test_solver_neutral_contract_rejects_interior_duplicate_station() -> None:
    with pytest.raises(ValueError, match="boundary wall"):
        HydraulicCrossSection(
            id="xs-2", branch_id="branch-1", code="XS-2", chainage_m=100,
            vertical_datum="1985-national-height",
            points=(
                CrossSectionPoint(station_m=0, elevation_m=6),
                CrossSectionPoint(station_m=10, elevation_m=2),
                CrossSectionPoint(station_m=10, elevation_m=5),
                CrossSectionPoint(station_m=20, elevation_m=6),
            ),
            manning_n=0.029,
        )
