from __future__ import annotations

import pytest

from app.hydraulic.production_validation import extract_survey_branches, locate_section_axes


def _line(coordinates: list[list[float]]) -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {"cadgeom_type": "CADLWPolyline"},
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }


def _text(text: str, x: float, y: float) -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {"cadgeom_type": "CADText", "text": text},
        "geometry": {"type": "Point", "coordinates": [x, y]},
    }


def test_explicit_cad_selection_direction_and_axis_quality() -> None:
    features = [
        _line([[0, 0], [100, 0], [200, 0]]),
        _line([[0, 1000], [9999, 1000]]),
        _text("K0+0.00", 0, 2),
        _text("K0+100.00", 100, 2),
        _text("K0+200.00", 200, 2),
    ]
    branches, reports = extract_survey_branches(features, [{
        "source_ordinal": 1,
        "code": "MAIN",
        "name": "main",
        "river_name": "survey river",
        "expected_end_chainage_m": 200,
    }], annotation_snap_m=5)
    assert len(branches) == 1
    assert reports[0]["confidence"] == "high"
    assert reports[0]["human_flow_direction_confirmation"] == "pending"

    axes = locate_section_axes([
        _line([[50, -20], [50, 20]]),
        _line([[150, -20], [160, 20]]),
    ], branches, perpendicular_tolerance_deg=20)
    assert [value.chainage_m for value in axes] == pytest.approx([50, 155])
    assert axes[0].snap_distance_m == 0
    assert axes[0].perpendicular_deviation_deg == pytest.approx(0)


def test_branch_source_order_is_reversed_when_chainage_requires_it() -> None:
    features = [
        _line([[200, 0], [100, 0], [0, 0]]),
        _text("K0+0.00", 0, 1),
        _text("K0+100.00", 100, 1),
        _text("K0+200.00", 200, 1),
    ]
    branches, _ = extract_survey_branches(features, [{
        "source_ordinal": 1,
        "code": "MAIN",
        "expected_end_chainage_m": 200,
    }], annotation_snap_m=2)
    assert branches[0].source_order_reversed is True
    assert branches[0].coordinates[0] == (0.0, 0.0)
