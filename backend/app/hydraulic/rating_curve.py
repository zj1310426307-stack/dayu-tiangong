"""Generate and evaluate downstream stage-discharge rating curves."""

from __future__ import annotations

from math import ceil, isfinite, sqrt
from typing import Sequence

from app.hydraulic.processing import section_hydraulic_metrics


RATING_CURVE_METHOD = "manning-normal-depth-v1"


def _vertical_bank_profile(
    points: Sequence[tuple[float, float]], top_elevation_m: float
) -> list[tuple[float, float]]:
    """Return disposable vertical walls without modifying surveyed profile points."""

    values = [(float(station), float(elevation)) for station, elevation in points]
    if len(values) < 2 or any(
        right[0] <= left[0] for left, right in zip(values, values[1:])
    ):
        raise ValueError("rating curve profile stations must be strictly increasing")
    if top_elevation_m <= min(value[1] for value in values):
        raise ValueError("rating curve top elevation must exceed the profile minimum")
    if values[0][1] < top_elevation_m:
        values.insert(0, (values[0][0], top_elevation_m))
    if values[-1][1] < top_elevation_m:
        values.append((values[-1][0], top_elevation_m))
    return values


def generate_manning_rating_curve(
    *,
    points: Sequence[tuple[float, float]],
    roughness_intervals: Sequence[tuple[float, float, float]],
    friction_slope: float,
    reference_discharge_m3s: float,
    vertical_step_m: float = 0.05,
    safety_factor: float = 1.1,
    maximum_depth_m: float = 50.0,
) -> list[dict[str, float]]:
    """Build a monotone Q-H curve from Section conveyance and Manning slope.

    The profile is extended only by disposable vertical endpoint walls.  The
    generated curve must cover the requested discharge with a small range margin;
    it never extrapolates beyond the configured maximum depth.
    """

    if not isfinite(friction_slope) or friction_slope <= 0:
        raise ValueError("friction_slope must be a finite positive value")
    if not isfinite(reference_discharge_m3s) or reference_discharge_m3s <= 0:
        raise ValueError("reference_discharge_m3s must be a finite positive value")
    if not isfinite(vertical_step_m) or vertical_step_m <= 0:
        raise ValueError("vertical_step_m must be a finite positive value")
    if maximum_depth_m <= vertical_step_m:
        raise ValueError("maximum_depth_m must exceed vertical_step_m")
    source = [(float(station), float(elevation)) for station, elevation in points]
    if not source or any(not isfinite(value) for point in source for value in point):
        raise ValueError("rating curve profile points must be finite")
    intervals = [tuple(map(float, value)) for value in roughness_intervals]
    if not intervals or any(n <= 0 for _, _, n in intervals):
        raise ValueError("rating curve requires positive Manning roughness intervals")

    minimum_stage = min(value[1] for value in source)
    target = reference_discharge_m3s * safety_factor
    step_count = int(ceil(maximum_depth_m / vertical_step_m))
    result: list[dict[str, float]] = [
        {"discharge_m3_s": 0.0, "water_level_m": minimum_stage}
    ]
    previous_discharge = 0.0
    for index in range(1, step_count + 1):
        stage = minimum_stage + index * vertical_step_m
        profile = _vertical_bank_profile(source, stage)
        _, _, _, conveyance = section_hydraulic_metrics(profile, intervals, stage)
        discharge = conveyance * sqrt(friction_slope)
        if discharge > previous_discharge + 1.0e-9:
            result.append(
                {
                    "discharge_m3_s": float(discharge),
                    "water_level_m": float(stage),
                }
            )
            previous_discharge = discharge
        if discharge >= target:
            break
    if result[-1]["discharge_m3_s"] < reference_discharge_m3s:
        raise ValueError(
            "automatic rating curve cannot cover the reference discharge within "
            f"{maximum_depth_m:g} m depth"
        )
    return result


def interpolate_rating_curve(
    curve: Sequence[dict[str, float]], discharge_m3s: float
) -> float:
    """Interpolate one discharge without silently extrapolating the rating curve."""

    if not isfinite(discharge_m3s) or discharge_m3s < 0:
        raise ValueError("rating curve discharge must be a finite non-negative value")
    points = [
        (float(item["discharge_m3_s"]), float(item["water_level_m"]))
        for item in curve
    ]
    if len(points) < 2:
        raise ValueError("rating curve requires at least two points")
    if any(
        right[0] <= left[0] or right[1] < left[1]
        for left, right in zip(points, points[1:])
    ):
        raise ValueError("rating curve Q must increase and H must not decrease")
    if discharge_m3s < points[0][0] or discharge_m3s > points[-1][0]:
        raise ValueError("rating curve discharge lies outside the generated range")
    for left, right in zip(points, points[1:]):
        if discharge_m3s <= right[0]:
            ratio = (discharge_m3s - left[0]) / (right[0] - left[0])
            return left[1] + ratio * (right[1] - left[1])
    return points[-1][1]


__all__ = [
    "RATING_CURVE_METHOD",
    "generate_manning_rating_curve",
    "interpolate_rating_curve",
]
