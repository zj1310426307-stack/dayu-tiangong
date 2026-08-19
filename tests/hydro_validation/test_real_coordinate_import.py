from __future__ import annotations

import pytest

from app.hydraulic.production_validation import (
    control_point_residual_gate,
    normalize_xyz_rows,
    parse_chainage,
    parse_profile_offset,
)
from app.hydraulic.schemas import CoordinateReferenceSpec


def _coordinate_reference() -> CoordinateReferenceSpec:
    return CoordinateReferenceSpec(
        source_crs="EPSG:4546",
        engineering_crs="EPSG:4546",
        coordinate_mode="projected",
        axis_mapping="x_easting_y_northing",
        x_field="X",
        y_field="Y",
        z_field="H",
        horizontal_unit="m",
        vertical_unit="m",
        vertical_datum="1985国家高程基准",
        central_meridian=111,
        zone_width=3,
        zone_prefix_mode="none",
    )


def test_explicit_cgcs2000_xyz_mapping_and_notation() -> None:
    rows = normalize_xyz_rows(
        [{"点号": "P01", "X": 500000.0, "Y": 2500000.0, "H": 12.0}],
        point_field="点号",
        x_field="X",
        y_field="Y",
        z_field="H",
        coordinate_reference=_coordinate_reference(),
    )
    assert rows == [{
        "point_code": "P01",
        "source_x": 500000.0,
        "source_y": 2500000.0,
        "easting": 500000.0,
        "northing": 2500000.0,
        "elevation": 12.0,
    }]
    assert parse_chainage("K1+234.50") == pytest.approx(1234.5)
    assert parse_profile_offset("-0+155.5") == pytest.approx(-155.5)


def test_control_point_gate_cannot_pass_without_independent_evidence() -> None:
    blocked = control_point_residual_gate([], threshold_m=0.5, minimum_count=10)
    assert blocked["status"] == "blocked"
    assert blocked["passed"] is False

    controls = [{
        "point_code": f"CP{index:02d}",
        "computed_x": 500000.0 + index,
        "computed_y": 2500000.0 + index,
        "expected_x": 500000.0 + index + 0.1,
        "expected_y": 2500000.0 + index - 0.1,
    } for index in range(10)]
    passed = control_point_residual_gate(controls, threshold_m=0.5, minimum_count=10)
    assert passed["status"] == "passed"
    assert passed["maximum_residual_m"] == pytest.approx(2 ** 0.5 / 10)


def test_explicit_xyz_mapping_rejects_missing_or_wrong_range() -> None:
    with pytest.raises(ValueError, match="missing explicit fields"):
        normalize_xyz_rows(
            [{"点号": "P01", "X": 500000.0, "Y": 2500000.0}],
            point_field="点号", x_field="X", y_field="Y", z_field="H",
            coordinate_reference=_coordinate_reference(),
        )
    with pytest.raises(ValueError, match="outside the declared projected coordinate range"):
        normalize_xyz_rows(
            [{"点号": "P01", "X": 22.0, "Y": 113.0, "H": 12.28}],
            point_field="点号", x_field="X", y_field="Y", z_field="H",
            coordinate_reference=_coordinate_reference(),
        )
