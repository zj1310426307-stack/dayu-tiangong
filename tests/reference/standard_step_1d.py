"""Independent steady, fully wet, forward-subcritical standard-step reference.

This module deliberately uses only the Python standard library.  It does not
import the production finite-volume solver or its geometry implementation.
The piecewise-linear cross-section formulae are repeated here so the D3A
science gates compare two independently assembled hydraulic paths.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol


class ReferenceSectionLike(Protocol):
    """Describe the geometry terms consumed by the independent step solver."""

    chainage_m: float
    bed_elevation_m: float
    manning_n: float
    maximum_stage_m: float

    def hydraulics(self, stage_m: float) -> tuple[float, float, float]: ...


@dataclass(frozen=True, slots=True)
class RectangularReferenceSection:
    """Provide exact rectangular formulae without production imports."""

    chainage_m: float
    bed_elevation_m: float
    manning_n: float
    width_m: float
    maximum_depth_m: float

    def __post_init__(self) -> None:
        values = (
            self.chainage_m,
            self.bed_elevation_m,
            self.manning_n,
            self.width_m,
            self.maximum_depth_m,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("rectangular reference values must be finite")
        if self.manning_n < 0.0 or self.width_m <= 0.0 or self.maximum_depth_m <= 0.0:
            raise ValueError("rectangular reference dimensions are invalid")

    @property
    def maximum_stage_m(self) -> float:
        return self.bed_elevation_m + self.maximum_depth_m

    def hydraulics(self, stage_m: float) -> tuple[float, float, float]:
        depth = stage_m - self.bed_elevation_m
        if not math.isfinite(depth) or not 0.0 < depth <= self.maximum_depth_m:
            raise ValueError("rectangular reference stage is outside its range")
        return (
            self.width_m * depth,
            self.width_m,
            self.width_m + 2.0 * depth,
        )


@dataclass(frozen=True, slots=True)
class ReferenceSection:
    """Define one ordered section with explicit bed, roughness and profile."""

    chainage_m: float
    bed_elevation_m: float
    manning_n: float
    points: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        values = (self.chainage_m, self.bed_elevation_m, self.manning_n)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("reference section values must be finite")
        if self.manning_n < 0.0:
            raise ValueError("reference Manning n must be non-negative")
        if len(self.points) < 3:
            raise ValueError("reference profile requires at least three points")
        if any(
            not math.isfinite(value)
            for point in self.points
            for value in point
        ):
            raise ValueError("reference profile points must be finite")
        if any(right[0] <= left[0] for left, right in zip(self.points, self.points[1:])):
            raise ValueError("reference profile offsets must be strictly increasing")
        if not math.isclose(
            min(point[1] for point in self.points),
            self.bed_elevation_m,
            rel_tol=0.0,
            abs_tol=1.0e-10,
        ):
            raise ValueError("explicit bed must equal the profile minimum")

    @property
    def maximum_stage_m(self) -> float:
        return min(self.points[0][1], self.points[-1][1])

    def hydraulics(self, stage_m: float) -> tuple[float, float, float]:
        """Return independent ``(area, top width, wetted perimeter)``."""

        if not math.isfinite(stage_m):
            raise ValueError("reference stage must be finite")
        if not self.bed_elevation_m < stage_m <= self.maximum_stage_m:
            raise ValueError("reference stage lies outside the fully wet profile range")

        area = 0.0
        width = 0.0
        perimeter = 0.0
        for (x0, z0), (x1, z1) in zip(self.points, self.points[1:]):
            left_x, left_z = x0, z0
            right_x, right_z = x1, z1
            if left_z >= stage_m and right_z >= stage_m:
                continue
            if left_z > stage_m:
                fraction = (left_z - stage_m) / (left_z - right_z)
                left_x = left_x + fraction * (right_x - left_x)
                left_z = stage_m
            if right_z > stage_m:
                fraction = (stage_m - left_z) / (right_z - left_z)
                right_x = left_x + fraction * (right_x - left_x)
                right_z = stage_m
            segment_width = right_x - left_x
            if segment_width < 0.0:
                raise ValueError("reference profile clipping inverted a segment")
            left_depth = stage_m - left_z
            right_depth = stage_m - right_z
            area += 0.5 * (left_depth + right_depth) * segment_width
            width += segment_width
            perimeter += math.hypot(segment_width, right_z - left_z)

        if area <= 0.0 or width <= 0.0 or perimeter <= 0.0:
            raise ValueError("reference stage has invalid wetted geometry")
        return area, width, perimeter


@dataclass(frozen=True, slots=True)
class StandardStepPoint:
    """Expose every hydraulic term used by one standard-step station."""

    chainage_m: float
    bed_elevation_m: float
    water_level_m: float
    discharge_m3_s: float
    area_m2: float
    velocity_m_s: float
    froude_number: float
    friction_slope: float
    energy_grade_m: float


def _point(
    section: ReferenceSectionLike,
    stage_m: float,
    discharge_m3_s: float,
    gravity_m_s2: float,
) -> StandardStepPoint:
    area, top_width, perimeter = section.hydraulics(stage_m)
    radius = area / perimeter
    velocity = discharge_m3_s / area
    froude = abs(discharge_m3_s) * math.sqrt(
        top_width / (gravity_m_s2 * area**3)
    )
    friction_slope = (
        section.manning_n**2
        * discharge_m3_s
        * abs(discharge_m3_s)
        / (area**2 * radius ** (4.0 / 3.0))
    )
    return StandardStepPoint(
        chainage_m=section.chainage_m,
        bed_elevation_m=section.bed_elevation_m,
        water_level_m=stage_m,
        discharge_m3_s=discharge_m3_s,
        area_m2=area,
        velocity_m_s=velocity,
        froude_number=froude,
        friction_slope=friction_slope,
        energy_grade_m=stage_m + velocity * velocity / (2.0 * gravity_m_s2),
    )


def _bisect(
    function: object,
    lower: float,
    upper: float,
    *,
    tolerance: float,
    maximum_iterations: int,
) -> float:
    if not callable(function):
        raise TypeError("reference root function must be callable")
    lower_value = float(function(lower))
    upper_value = float(function(upper))
    if not all(math.isfinite(value) for value in (lower_value, upper_value)):
        raise ValueError("reference root bracket is non-finite")
    if lower_value == 0.0:
        return lower
    if upper_value == 0.0:
        return upper
    if lower_value * upper_value > 0.0:
        raise ValueError("reference root is not bracketed")
    for _ in range(maximum_iterations):
        midpoint = 0.5 * (lower + upper)
        midpoint_value = float(function(midpoint))
        if not math.isfinite(midpoint_value):
            raise ValueError("reference root residual became non-finite")
        if abs(midpoint_value) <= tolerance or upper - lower <= tolerance:
            return midpoint
        if lower_value * midpoint_value <= 0.0:
            upper = midpoint
        else:
            lower = midpoint
            lower_value = midpoint_value
    raise ValueError("reference root did not converge")


def _critical_stage(
    section: ReferenceSectionLike,
    discharge_m3_s: float,
    gravity_m_s2: float,
    *,
    tolerance: float,
    maximum_iterations: int,
) -> float:
    depth_span = section.maximum_stage_m - section.bed_elevation_m
    lower = section.bed_elevation_m + max(1.0e-10, depth_span * 1.0e-10)
    upper = section.maximum_stage_m - max(1.0e-10, depth_span * 1.0e-10)

    def residual(stage_m: float) -> float:
        return _point(section, stage_m, discharge_m3_s, gravity_m_s2).froude_number - 1.0

    return _bisect(
        residual,
        lower,
        upper,
        tolerance=tolerance,
        maximum_iterations=maximum_iterations,
    )


def standard_step_profile(
    sections: tuple[ReferenceSectionLike, ...],
    *,
    discharge_m3_s: float,
    downstream_stage_m: float,
    gravity_m_s2: float = 9.81,
    root_tolerance: float = 1.0e-11,
    maximum_iterations: int = 160,
) -> tuple[StandardStepPoint, ...]:
    """Integrate the energy equation upstream from a downstream stage.

    The friction loss over each interval is the trapezoidal average of the two
    Manning slopes.  Bisection is restricted to the subcritical branch and
    fails closed if the profile table cannot bracket the physical root.
    """

    if len(sections) < 2:
        raise ValueError("standard-step reference requires at least two sections")
    if not math.isfinite(discharge_m3_s) or discharge_m3_s <= 0.0:
        raise ValueError("standard-step reference requires positive forward discharge")
    if not math.isfinite(gravity_m_s2) or gravity_m_s2 <= 0.0:
        raise ValueError("reference gravity must be finite and positive")
    if any(
        right.chainage_m <= left.chainage_m
        for left, right in zip(sections, sections[1:])
    ):
        raise ValueError("reference sections must be ordered downstream")

    downstream = _point(
        sections[-1],
        downstream_stage_m,
        discharge_m3_s,
        gravity_m_s2,
    )
    if not 0.0 < downstream.froude_number < 1.0:
        raise ValueError("downstream reference state must be strictly subcritical")
    reversed_points = [downstream]

    for section in reversed(sections[:-1]):
        downstream_point = reversed_points[-1]
        dx = downstream_point.chainage_m - section.chainage_m
        critical = _critical_stage(
            section,
            discharge_m3_s,
            gravity_m_s2,
            tolerance=root_tolerance,
            maximum_iterations=maximum_iterations,
        )
        span = section.maximum_stage_m - section.bed_elevation_m
        lower = critical + max(root_tolerance, span * 1.0e-9)
        upper = section.maximum_stage_m - max(root_tolerance, span * 1.0e-9)

        def residual(stage_m: float) -> float:
            candidate = _point(
                section,
                stage_m,
                discharge_m3_s,
                gravity_m_s2,
            )
            friction_loss = 0.5 * dx * (
                candidate.friction_slope + downstream_point.friction_slope
            )
            return (
                candidate.energy_grade_m
                - downstream_point.energy_grade_m
                - friction_loss
            )

        stage = _bisect(
            residual,
            lower,
            upper,
            tolerance=root_tolerance,
            maximum_iterations=maximum_iterations,
        )
        point = _point(section, stage, discharge_m3_s, gravity_m_s2)
        if not 0.0 < point.froude_number < 1.0:
            raise ValueError("standard-step root left the subcritical branch")
        if point.energy_grade_m <= downstream_point.energy_grade_m:
            raise ValueError("Manning reference must lose energy downstream")
        reversed_points.append(point)

    return tuple(reversed(reversed_points))


__all__ = [
    "ReferenceSection",
    "ReferenceSectionLike",
    "RectangularReferenceSection",
    "StandardStepPoint",
    "standard_step_profile",
]
