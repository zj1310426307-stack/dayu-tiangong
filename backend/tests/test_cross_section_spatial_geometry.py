"""Pure regression tests for branch-derived cross-section spatial geometry."""

from __future__ import annotations

import math

import pytest

from app.hydraulic.spatial_geometry import derive_section_geometry, local_tangent, point_at_chainage


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ((0.0, 0.0), (0.0, 100.0)),  # south -> north
        ((0.0, 100.0), (0.0, 0.0)),  # north -> south
        ((0.0, 0.0), (100.0, 0.0)),  # west -> east
        ((100.0, 0.0), (0.0, 0.0)),  # east -> west
        ((0.0, 0.0), (-100.0, 100.0)),  # northeast -> southwest direction vector
    ],
)
def test_cardinal_and_diagonal_directions_keep_downstream_left_to_right(start, end) -> None:
    """The right normal maps increasing station to the downstream-looking right bank."""

    vertices = [(0.0, *start), (100.0, *end)]
    result = derive_section_geometry(vertices, 50.0, [-10.0, 0.0, 20.0], 0.0)
    left, intersection, right = result.profile_points
    assert intersection == pytest.approx(result.intersection)
    assert math.dist(left, intersection) == pytest.approx(10.0)
    assert math.dist(right, intersection) == pytest.approx(20.0)
    cross = (
        result.tangent[0] * (left[1] - intersection[1])
        - result.tangent[1] * (left[0] - intersection[0])
    )
    assert cross > 0.0, "negative station must be downstream-looking left"


def test_curved_branch_uses_symmetric_local_tangent_not_one_segment() -> None:
    """A bend at a vertex uses a centred chainage window and remains continuous."""

    vertices = [(0.0, 0.0, 0.0), (50.0, 50.0, 0.0), (100.0, 50.0, 50.0)]
    tangent = local_tangent(vertices, 50.0, 10.0)
    assert tangent == pytest.approx((math.sqrt(0.5), math.sqrt(0.5)))


def test_vertex_and_branch_endpoints_use_exact_or_one_sided_differences() -> None:
    """Vertex hits are exact and endpoints still receive a valid tangent."""

    vertices = [(0.0, 0.0, 0.0), (50.0, 50.0, 0.0), (100.0, 50.0, 50.0)]
    assert point_at_chainage(vertices, 50.0) == pytest.approx((50.0, 0.0))
    assert local_tangent(vertices, 0.0, 10.0) == pytest.approx((1.0, 0.0))
    assert local_tangent(vertices, 100.0, 10.0) == pytest.approx((0.0, 1.0))


def test_asymmetric_stations_and_marker2_anchor_are_preserved() -> None:
    """The intersection is exactly station=anchor and Marker 2 need not be midpoint."""

    result = derive_section_geometry(
        [(0.0, 0.0, 0.0), (100.0, 100.0, 0.0)],
        40.0,
        [-8.0, 2.0, 37.0],
        2.0,
        {"marker1": -8.0, "marker2": 2.0, "marker3": 37.0},
    )
    assert result.profile_points[1] == pytest.approx(result.intersection)
    assert result.marker_points["marker2"] == pytest.approx(result.intersection)


def test_midpoint_fallback_is_explicit_and_raw_station_list_is_unchanged() -> None:
    """Fallback callers can record review status without mutating source stations."""

    stations = [-13.0, 0.0, 31.0]
    before = list(stations)
    result = derive_section_geometry(
        [(0.0, 0.0, 0.0), (100.0, 100.0, 0.0)], 20.0, stations, (stations[0] + stations[-1]) / 2
    )
    assert stations == before
    assert result.profile_points[0] != result.profile_points[-1]


def test_reverse_geometry_uses_its_own_downstream_direction() -> None:
    """Reversed branch coordinates produce the reversed tangent, never a fixed axis."""

    forward = local_tangent([(0.0, 0.0, 0.0), (100.0, 100.0, 0.0)], 50.0, 5.0)
    reverse = local_tangent([(0.0, 100.0, 0.0), (100.0, 0.0, 0.0)], 50.0, 5.0)
    assert forward == pytest.approx((1.0, 0.0))
    assert reverse == pytest.approx((-1.0, 0.0))


def test_derived_length_is_exactly_station_range() -> None:
    """No arbitrary line length is introduced by the derivation."""

    result = derive_section_geometry(
        [(0.0, 0.0, 0.0), (100.0, 0.0, 100.0)], 70.0, [-4.5, 0.0, 27.25], 0.0
    )
    assert math.dist(result.profile_points[0], result.profile_points[-1]) == pytest.approx(31.75)
