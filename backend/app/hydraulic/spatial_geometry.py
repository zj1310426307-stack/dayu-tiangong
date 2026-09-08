"""Deterministic derived cross-section geometry from a directed branch.

The functions in this module operate on projected engineering coordinates.  They
intentionally do not know about SQLAlchemy or source X/Y field names: coordinate
normalisation happens before these functions are called, so the same algorithm
is used for CGCS2000 east/north and north/east imports.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from bisect import bisect_right


Point = tuple[float, float]
Vertex = tuple[float, float, float]  # (branch chainage, projected x, projected y)


@dataclass(frozen=True)
class DerivedSectionGeometry:
    """Projected coordinates needed to persist one derived section."""

    intersection: Point
    tangent: Point
    left_normal: Point
    right_normal: Point
    profile_points: tuple[Point, ...]
    marker_points: dict[str, Point]


def _normalize(vector: Point) -> Point:
    """Return a unit vector and reject a degenerate branch sample."""

    length = math.hypot(vector[0], vector[1])
    if length <= 1.0e-12:
        raise ValueError("branch tangent is degenerate")
    return vector[0] / length, vector[1] / length


def point_at_chainage(vertices: list[Vertex], chainage: float) -> Point:
    """Linearly interpolate a point in the branch's own upstream-to-downstream order.

    Chainage is the authoritative linear-reference axis.  A vertex hit is returned
    exactly, which avoids a small numerical offset at branch vertices.
    """

    if len(vertices) < 2:
        raise ValueError("branch requires at least two vertices")
    ordered = sorted(vertices, key=lambda value: value[0])
    if any(right[0] <= left[0] for left, right in zip(ordered, ordered[1:])):
        raise ValueError("branch chainage must be strictly increasing")
    if chainage < ordered[0][0] - 1.0e-9 or chainage > ordered[-1][0] + 1.0e-9:
        raise ValueError("chainage is outside branch range")
    station = min(max(chainage, ordered[0][0]), ordered[-1][0])
    index = bisect_right([value[0] for value in ordered], station) - 1
    if index >= len(ordered) - 1:
        return ordered[-1][1], ordered[-1][2]
    left, right = ordered[index], ordered[index + 1]
    fraction = (station - left[0]) / (right[0] - left[0])
    return (
        left[1] + fraction * (right[1] - left[1]),
        left[2] + fraction * (right[2] - left[2]),
    )


def local_tangent(vertices: list[Vertex], chainage: float, delta: float) -> Point:
    """Compute a downstream tangent with central, forward, or backward differences."""

    if delta <= 0:
        raise ValueError("tangent sampling delta must be positive")
    ordered = sorted(vertices, key=lambda value: value[0])
    start, end = ordered[0][0], ordered[-1][0]
    before = max(start, chainage - delta)
    after = min(end, chainage + delta)
    if math.isclose(before, after, abs_tol=1.0e-12):
        raise ValueError("branch has no usable tangent window")
    p_before = point_at_chainage(vertices, before)
    p_after = point_at_chainage(vertices, after)
    return _normalize((p_after[0] - p_before[0], p_after[1] - p_before[1]))


def derive_section_geometry(
    vertices: list[Vertex],
    section_chainage: float,
    stations: list[float],
    anchor_station: float,
    marker_stations: dict[str, float] | None = None,
    delta: float = 1.0,
) -> DerivedSectionGeometry:
    """Build a left-to-right cross-section from one branch intersection.

    ``stations`` are raw hydraulic offsets and are never altered.  The right
    normal is used with ``station - anchor_station`` so negative offsets stay on
    the downstream-looking left side and positive offsets on the right side.
    """

    if not stations or any(right <= left for left, right in zip(stations, stations[1:])):
        raise ValueError("section stations must be strictly increasing")
    intersection = point_at_chainage(vertices, section_chainage)
    tangent = local_tangent(vertices, section_chainage, delta)
    left_normal = (-tangent[1], tangent[0])
    right_normal = (tangent[1], -tangent[0])

    def offset_point(station: float) -> Point:
        distance = station - anchor_station
        return (
            intersection[0] + right_normal[0] * distance,
            intersection[1] + right_normal[1] * distance,
        )

    marker_points = {
        name: offset_point(station)
        for name, station in (marker_stations or {}).items()
    }
    return DerivedSectionGeometry(
        intersection=intersection,
        tangent=tangent,
        left_normal=left_normal,
        right_normal=right_normal,
        profile_points=tuple(offset_point(station) for station in stations),
        marker_points=marker_points,
    )
