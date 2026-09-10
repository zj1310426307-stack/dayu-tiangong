"""Verify derived downstream rating-curve generation and frozen mapping."""

from types import SimpleNamespace

import pytest

from app.hydraulic.rating_curve import (
    generate_manning_rating_curve,
    interpolate_rating_curve,
)
from app.model_engine.hydraulic_1d_service import _boundary
from model.hydraulic_1d.errors import Hydraulic1DValidationError
from model.provenance import snapshot_hash


def test_manning_rating_curve_is_monotone_and_covers_reference_flow() -> None:
    """A rectangular terminal Section produces an invertible Q-H relation."""

    curve = generate_manning_rating_curve(
        points=[(0.0, 0.0), (10.0, 0.0)],
        roughness_intervals=[(0.0, 10.0, 0.03)],
        friction_slope=0.001,
        reference_discharge_m3s=20.0,
        vertical_step_m=0.1,
        maximum_depth_m=10.0,
    )

    assert curve[0] == {"discharge_m3_s": 0.0, "water_level_m": 0.0}
    assert curve[-1]["discharge_m3_s"] >= 20.0
    assert all(
        right["discharge_m3_s"] > left["discharge_m3_s"]
        and right["water_level_m"] > left["water_level_m"]
        for left, right in zip(curve, curve[1:])
    )
    stage = interpolate_rating_curve(curve, 20.0)
    assert 0.0 < stage <= curve[-1]["water_level_m"]


def test_rating_curve_never_extrapolates() -> None:
    """A discharge outside the governed curve range fails closed."""

    curve = [
        {"discharge_m3_s": 0.0, "water_level_m": 1.0},
        {"discharge_m3_s": 10.0, "water_level_m": 2.0},
    ]

    with pytest.raises(ValueError, match="outside"):
        interpolate_rating_curve(curve, 10.1)


def test_model_mapping_resolves_rating_curve_from_case_discharge() -> None:
    """The frozen downstream H series follows the selected upstream Q series."""

    branch = SimpleNamespace(
        id=20,
        upstream_node_id=10,
        downstream_node_id=11,
        start_chainage=0.0,
        end_chainage=1000.0,
    )
    source = SimpleNamespace(
        id=1,
        boundary_type="upstream_discharge",
        hydraulic_node_id=10,
        branch_id=None,
        chainage_m=None,
        values={
            "mode": "series",
            "series": [
                {"time_seconds": 0.0, "flow_m3_s": 5.0},
                {"time_seconds": 60.0, "flow_m3_s": 10.0},
            ],
        },
    )
    downstream = SimpleNamespace(
        id=2,
        boundary_type="downstream_water_level",
        hydraulic_node_id=11,
        branch_id=None,
        chainage_m=None,
        values={
            "mode": "rating_curve",
            "source_discharge_boundary_id": 1,
            "source_discharge_values_hash": snapshot_hash(source.values),
            "curve": [
                {"discharge_m3_s": 0.0, "water_level_m": 20.0},
                {"discharge_m3_s": 10.0, "water_level_m": 22.0},
            ],
        },
    )

    mapped = _boundary(
        downstream,
        [branch],
        boundary_rows=[source, downstream],
    )

    assert [(item.time_seconds, item.value) for item in mapped.series] == [
        (0.0, 21.0),
        (60.0, 22.0),
    ]


def test_model_mapping_rejects_a_stale_rating_curve_source() -> None:
    """Changing the upstream Q boundary forces Q-H regeneration before approval."""

    branch = SimpleNamespace(
        id=20,
        upstream_node_id=10,
        downstream_node_id=11,
        start_chainage=0.0,
        end_chainage=1000.0,
    )
    source = SimpleNamespace(
        id=1,
        boundary_type="upstream_discharge",
        hydraulic_node_id=10,
        branch_id=None,
        chainage_m=None,
        values={"mode": "constant", "value": 8.0},
    )
    downstream = SimpleNamespace(
        id=2,
        boundary_type="downstream_water_level",
        hydraulic_node_id=11,
        branch_id=None,
        chainage_m=None,
        values={
            "mode": "rating_curve",
            "source_discharge_boundary_id": 1,
            "source_discharge_values_hash": "0" * 64,
            "curve": [
                {"discharge_m3_s": 0.0, "water_level_m": 20.0},
                {"discharge_m3_s": 10.0, "water_level_m": 22.0},
            ],
        },
    )

    with pytest.raises(Hydraulic1DValidationError, match="DAYU_RATING_CURVE_SOURCE_STALE"):
        _boundary(downstream, [branch], boundary_rows=[source, downstream])
