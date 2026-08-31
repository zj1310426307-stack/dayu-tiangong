"""Solver-neutral metrics shared by the MASCARET benchmark suite."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite, sqrt
from time import perf_counter
from typing import Iterable

from model.hydraulic_1d.contracts import (
    BoundaryCondition,
    Hydraulic1DModel,
    HydraulicResult,
    TimeValue,
)


@dataclass(frozen=True, slots=True)
class HydraulicBenchmarkMetrics:
    """Standardize every required accuracy, balance, and runtime measurement."""

    water_level_error: float
    discharge_error: float
    velocity_error: float
    peak_error: float
    peak_time_error: float
    mass_balance_error: float
    runtime: float

    def __post_init__(self) -> None:
        """Reject negative or non-finite values before they enter CI evidence."""

        if any(not isfinite(value) or value < 0.0 for value in asdict(self).values()):
            raise ValueError("benchmark metrics must be finite and non-negative")

    def to_dict(self) -> dict[str, float]:
        """Return the exact metric names consumed by CI artifacts and comparisons."""

        return asdict(self)


def root_mean_square_error(observed: Iterable[float], expected: Iterable[float]) -> float:
    """Calculate an aligned finite RMSE and reject empty or mismatched sequences."""

    actual = tuple(float(value) for value in observed)
    reference = tuple(float(value) for value in expected)
    if not actual or len(actual) != len(reference):
        raise ValueError("benchmark series must be non-empty and aligned")
    return sqrt(sum((left - right) ** 2 for left, right in zip(actual, reference)) / len(actual))


def rectangular_manning_discharge(
    *,
    width_m: float,
    depth_m: float,
    manning_n: float,
    slope: float,
) -> float:
    """Return the theoretical uniform-flow discharge for a rectangular channel."""

    if min(width_m, depth_m, manning_n, slope) <= 0.0:
        raise ValueError("uniform-flow inputs must be positive")
    area = width_m * depth_m
    radius = area / (width_m + 2.0 * depth_m)
    return area * radius ** (2.0 / 3.0) * slope**0.5 / manning_n


def _interpolate(series: tuple[TimeValue, ...], time_seconds: float) -> float:
    """Evaluate a constant or piecewise-linear boundary within frozen coverage."""

    if len(series) == 1:
        return float(series[0].value)
    if time_seconds < series[0].time_seconds or time_seconds > series[-1].time_seconds:
        raise ValueError("benchmark result time lies outside boundary coverage")
    for left, right in zip(series, series[1:]):
        if time_seconds <= right.time_seconds:
            fraction = (time_seconds - left.time_seconds) / (
                right.time_seconds - left.time_seconds
            )
            return float(left.value + fraction * (right.value - left.value))
    return float(series[-1].value)


def _endpoint_boundary(
    model: Hydraulic1DModel,
    location: str,
) -> BoundaryCondition:
    """Return the one validator-approved boundary at a requested endpoint."""

    matches = [item for item in model.boundaries if item.location == location]
    if len(matches) != 1:
        raise ValueError(f"benchmark requires exactly one {location} boundary")
    return matches[0]


def _trapezoidal_integral(times: list[float], values: list[float]) -> float:
    """Integrate an aligned time series using the trapezoidal rule."""

    return sum(
        (right_time - left_time) * (left_value + right_value) / 2.0
        for left_time, right_time, left_value, right_value in zip(
            times,
            times[1:],
            values,
            values[1:],
        )
    )


def evaluate_hydraulic_benchmark(
    model: Hydraulic1DModel,
    result: HydraulicResult,
    *,
    reference_velocity_m_s: float | None = None,
) -> HydraulicBenchmarkMetrics:
    """Calculate required metrics from a real unified engine result.

    Endpoint errors compare the reported Q/H series with the frozen hydraulic
    laws. Peak metrics compare the downstream discharge response with the
    upstream forcing peak, so peak-time error represents propagation delay.
    Mass balance uses the change in trapezoidal Section volume and the
    time-integrated endpoint fluxes; it is normalized to remain comparable.
    """

    if not result.records:
        raise ValueError("benchmark result must contain records")
    if result.simulation_id != model.simulation_id:
        raise ValueError("benchmark result belongs to another simulation")
    sections = sorted(model.cross_sections, key=lambda item: item.chainage_m)
    rows_by_section = {
        section.id: sorted(
            (item for item in result.records if item.cross_section_id == section.id),
            key=lambda item: float(item.timestamp),
        )
        for section in sections
    }
    if any(not rows for rows in rows_by_section.values()):
        raise ValueError("benchmark result is missing an authoritative Section")
    time_axes = [tuple(float(item.timestamp) for item in rows) for rows in rows_by_section.values()]
    if any(axis != time_axes[0] for axis in time_axes[1:]):
        raise ValueError("benchmark result Sections do not share one time axis")
    times = list(time_axes[0])
    upstream_rows = rows_by_section[sections[0].id]
    downstream_rows = rows_by_section[sections[-1].id]
    upstream = _endpoint_boundary(model, "upstream")
    downstream = _endpoint_boundary(model, "downstream")
    expected_q = [_interpolate(upstream.series, value) for value in times]
    expected_h = [_interpolate(downstream.series, value) for value in times]
    observed_q = [item.discharge_m3s for item in upstream_rows]
    observed_h = [item.water_level_m for item in downstream_rows]
    if reference_velocity_m_s is None:
        # Cases without an analytic velocity use this field as an explicit
        # unified-result consistency metric. Their physical velocity response
        # is checked by case-specific paired/temporal acceptance rules.
        expected_velocity = [
            item.discharge_m3s / item.flow_area_m2 for item in result.records
        ]
    else:
        expected_velocity = [reference_velocity_m_s for _ in result.records]
    observed_velocity = [item.velocity_m_s for item in result.records]
    expected_peak = max(float(item.value) for item in upstream.series)
    downstream_q = [item.discharge_m3s for item in downstream_rows]
    observed_peak = max(downstream_q)
    expected_peak_time = float(
        max(upstream.series, key=lambda item: item.value).time_seconds
    )
    observed_peak_time = times[downstream_q.index(observed_peak)]

    volumes: list[float] = []
    for time_index in range(len(times)):
        volume = sum(
            (right.chainage_m - left.chainage_m)
            * (
                rows_by_section[left.id][time_index].flow_area_m2
                + rows_by_section[right.id][time_index].flow_area_m2
            )
            / 2.0
            for left, right in zip(sections, sections[1:])
        )
        volumes.append(volume)
    net_flux = _trapezoidal_integral(
        times,
        [left - right for left, right in zip(observed_q, downstream_q)],
    )
    storage_change = volumes[-1] - volumes[0]
    mass_scale = max(abs(net_flux), abs(volumes[0]), 1.0)
    runtime = result.diagnostics.get("runtime_seconds")
    if isinstance(runtime, bool) or not isinstance(runtime, (int, float)):
        raise ValueError("benchmark result lacks numeric runtime_seconds")
    return HydraulicBenchmarkMetrics(
        water_level_error=root_mean_square_error(observed_h, expected_h),
        discharge_error=root_mean_square_error(observed_q, expected_q),
        velocity_error=root_mean_square_error(observed_velocity, expected_velocity),
        peak_error=abs(observed_peak - expected_peak),
        peak_time_error=abs(observed_peak_time - expected_peak_time),
        mass_balance_error=abs(storage_change - net_flux) / mass_scale,
        runtime=float(runtime),
    )


class BenchmarkTimer:
    """Measure wall time without coupling benchmark calculations to an engine."""

    def __enter__(self) -> "BenchmarkTimer":
        """Start a monotonic benchmark interval."""

        self._started = perf_counter()
        self.elapsed_seconds = 0.0
        return self

    def __exit__(self, *_: object) -> None:
        """Finish the interval even when the measured calculation raises."""

        self.elapsed_seconds = perf_counter() - self._started
