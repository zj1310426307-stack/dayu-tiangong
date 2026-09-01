"""Deterministic observation alignment and hydraulic performance metrics."""

from __future__ import annotations

from bisect import bisect_left
import math

from app.hydraulic.production.contracts import (
    HydraulicMetrics,
    ProductionSeries,
    TimeAlignmentOptions,
)


def _simulated_values(series: ProductionSeries) -> tuple[list[float], list[float]]:
    """Return finite simulated samples in source order."""

    samples = [sample for sample in series.samples if sample.value is not None]
    return (
        [float(sample.time_seconds) for sample in samples],
        [float(sample.value) for sample in samples],
    )


def _value_at(
    time_seconds: float,
    times: list[float],
    values: list[float],
    options: TimeAlignmentOptions,
) -> float | None:
    """Apply exactly the selected alignment method without shifting observations."""

    position = bisect_left(times, time_seconds)
    if position < len(times) and math.isclose(times[position], time_seconds, abs_tol=1e-9):
        return values[position]
    if options.method == "exact":
        return None
    if options.method == "interpolation":
        if position == 0 or position >= len(times):
            return None
        left_time, right_time = times[position - 1], times[position]
        if right_time <= left_time:
            return None
        fraction = (time_seconds - left_time) / (right_time - left_time)
        return values[position - 1] + fraction * (values[position] - values[position - 1])
    candidates: list[tuple[float, float]] = []
    if position > 0:
        candidates.append((abs(times[position - 1] - time_seconds), values[position - 1]))
    if position < len(times):
        candidates.append((abs(times[position] - time_seconds), values[position]))
    if not candidates:
        return None
    delta, value = min(candidates, key=lambda item: item[0])
    return value if delta <= options.tolerance_seconds else None


def _r_squared(observed: list[float], simulated: list[float]) -> float | None:
    """Return squared Pearson correlation when both series vary."""

    if len(observed) < 2:
        return None
    mean_observed = sum(observed) / len(observed)
    mean_simulated = sum(simulated) / len(simulated)
    covariance = sum(
        (left - mean_observed) * (right - mean_simulated)
        for left, right in zip(observed, simulated)
    )
    observed_variance = sum((value - mean_observed) ** 2 for value in observed)
    simulated_variance = sum((value - mean_simulated) ** 2 for value in simulated)
    if observed_variance <= 0 or simulated_variance <= 0:
        return None
    return (covariance**2) / (observed_variance * simulated_variance)


def align_and_score(
    observed: ProductionSeries,
    simulated: ProductionSeries,
    options: TimeAlignmentOptions,
) -> HydraulicMetrics:
    """Align simulated values to unchanged observation times and compute metrics."""

    if observed.variable != simulated.variable or observed.unit != simulated.unit:
        raise ValueError("observed and simulated series must use the same variable and unit")
    sim_times, sim_values = _simulated_values(simulated)
    if not sim_times:
        raise ValueError("simulated series contains no usable samples")
    usable_observations = [
        sample
        for sample in observed.samples
        if sample.quality_flag == "GOOD" and sample.value is not None
    ]
    observed_values: list[float] = []
    aligned_values: list[float] = []
    aligned_times: list[float] = []
    for sample in usable_observations:
        value = _value_at(float(sample.time_seconds), sim_times, sim_values, options)
        if value is None:
            continue
        observed_values.append(float(sample.value))
        aligned_values.append(value)
        aligned_times.append(float(sample.time_seconds))
    observed_count = len(usable_observations)
    valid_count = len(observed_values)
    coverage = valid_count / observed_count if observed_count else 0.0
    sufficient = (
        valid_count >= options.minimum_valid_samples
        and coverage >= options.minimum_coverage_ratio
    )
    if valid_count == 0:
        return HydraulicMetrics(
            variable=observed.variable,
            unit=observed.unit,
            alignment_method=options.method,
            valid_sample_count=0,
            observed_sample_count=observed_count,
            coverage_ratio=coverage,
            sufficient_samples=False,
        )

    differences = [right - left for left, right in zip(observed_values, aligned_values)]
    mae = sum(abs(value) for value in differences) / valid_count
    rmse = math.sqrt(sum(value**2 for value in differences) / valid_count)
    bias = sum(differences) / valid_count
    mean_observed = sum(observed_values) / valid_count
    nse_denominator = sum((value - mean_observed) ** 2 for value in observed_values)
    nse = (
        1.0 - sum(value**2 for value in differences) / nse_denominator
        if nse_denominator > 0
        else None
    )
    observed_peak_index = max(range(valid_count), key=lambda index: observed_values[index])
    simulated_peak_index = max(range(valid_count), key=lambda index: aligned_values[index])
    observed_peak = observed_values[observed_peak_index]
    simulated_peak = aligned_values[simulated_peak_index]
    peak_error = simulated_peak - observed_peak
    peak_relative = peak_error / abs(observed_peak) if observed_peak != 0 else None
    return HydraulicMetrics(
        variable=observed.variable,
        unit=observed.unit,
        alignment_method=options.method,
        valid_sample_count=valid_count,
        observed_sample_count=observed_count,
        coverage_ratio=coverage,
        sufficient_samples=sufficient,
        mae=mae,
        rmse=rmse,
        bias=bias,
        nse=nse,
        r_squared=_r_squared(observed_values, aligned_values),
        peak_value_error=peak_error,
        peak_relative_error=peak_relative,
        peak_time_error_seconds=(
            aligned_times[simulated_peak_index] - aligned_times[observed_peak_index]
        ),
    )


__all__ = ["align_and_score"]
