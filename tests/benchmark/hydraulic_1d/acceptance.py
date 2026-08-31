"""Case-specific physical acceptance rules for real MASCARET benchmark runs."""

from __future__ import annotations

from math import isclose, isfinite

from model.hydraulic_1d import HydraulicBenchmarkMetrics, HydraulicResult
from tests.benchmark.hydraulic_1d.cases import HydraulicBenchmarkCase


# Uniform flow starts from the analytic steady state. These tolerances allow
# normal mesh/output rounding while still rejecting material solution drift.
UNIFORM_Q_RELATIVE_TOLERANCE = 0.02
UNIFORM_Q_ABSOLUTE_TOLERANCE_M3S = 0.05
UNIFORM_H_ABSOLUTE_TOLERANCE_M = 0.03
UNIFORM_V_RELATIVE_TOLERANCE = 0.03
UNIFORM_V_ABSOLUTE_TOLERANCE_MS = 0.01

# The n=0.045 case has 3.24 times the friction-slope coefficient of n=0.025.
# Small positive margins distinguish a physical response from numerical noise.
ROUGHNESS_MIN_STAGE_RISE_M = 0.01
ROUGHNESS_MIN_VELOCITY_DROP_MS = 0.002

# A 24 m3/s inflow pulse must remain detectable at the downstream interior
# monitor. One output interval is the minimum resolvable propagation delay.
FLOOD_MIN_PEAK_Q_RISE_M3S = 1.0
FLOOD_MIN_PEAK_H_RISE_M = 0.005
FLOOD_MIN_ARRIVAL_LAG_OUTPUT_STEPS = 1
FLOOD_PEAK_Q_OVERSHOOT_RELATIVE_TOLERANCE = 0.05

# Q and H are imposed boundary laws. These limits allow text/output rounding,
# but reject a law that was omitted, swapped, or interpreted in the wrong unit.
BOUNDARY_Q_RELATIVE_TOLERANCE = 0.005
BOUNDARY_Q_ABSOLUTE_TOLERANCE_M3S = 0.05
BOUNDARY_H_RELATIVE_TOLERANCE = 0.001
BOUNDARY_H_ABSOLUTE_TOLERANCE_M = 0.005

# Storage is reconstructed from authoritative profiles rather than every
# internal MASCARET mesh point, so a 5% normalized residual is the honest gate.
MASS_BALANCE_MAX_RELATIVE_RESIDUAL = 0.05


def _rows_by_section(result: HydraulicResult) -> dict[str, list]:
    """Return chronologically ordered rows for each unified Section."""

    grouped: dict[str, list] = {}
    for row in result.records:
        grouped.setdefault(row.cross_section_id, []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda item: float(item.timestamp))
    return grouped


def _assert_metric_health(metrics: HydraulicBenchmarkMetrics) -> None:
    """Apply the one solver-neutral conservation/runtime gate to every case."""

    assert all(isfinite(value) and value >= 0.0 for value in metrics.to_dict().values())
    assert metrics.runtime > 0.0
    assert metrics.mass_balance_error <= MASS_BALANCE_MAX_RELATIVE_RESIDUAL


def _assert_uniform(case: HydraulicBenchmarkCase, result: HydraulicResult) -> None:
    """Check final Q/H/V at every profile against the analytic steady state."""

    assert case.reference_velocity_m_s is not None
    expected_states = {
        item.cross_section_id: item for item in case.model.initial_condition.by_section
    }
    rows = _rows_by_section(result)
    assert set(rows) == set(expected_states)
    for section_id, expected in expected_states.items():
        final = rows[section_id][-1]
        assert isclose(
            final.discharge_m3s,
            expected.discharge_m3s,
            rel_tol=UNIFORM_Q_RELATIVE_TOLERANCE,
            abs_tol=UNIFORM_Q_ABSOLUTE_TOLERANCE_M3S,
        )
        assert isclose(
            final.water_level_m,
            expected.water_level_m,
            rel_tol=0.0,
            abs_tol=UNIFORM_H_ABSOLUTE_TOLERANCE_M,
        )
        assert isclose(
            final.velocity_m_s,
            case.reference_velocity_m_s,
            rel_tol=UNIFORM_V_RELATIVE_TOLERANCE,
            abs_tol=UNIFORM_V_ABSOLUTE_TOLERANCE_MS,
        )


def _assert_roughness_pair(
    case: HydraulicBenchmarkCase,
    low_result: HydraulicResult,
    high_result: HydraulicResult | None,
) -> None:
    """Require higher Manning n to raise stage and reduce velocity upstream."""

    assert case.comparison_model is not None
    assert high_result is not None
    monitor_id = min(
        case.model.cross_sections,
        key=lambda item: item.chainage_m,
    ).id
    low = _rows_by_section(low_result)[monitor_id][-1]
    high = _rows_by_section(high_result)[monitor_id][-1]
    assert high.water_level_m >= low.water_level_m + ROUGHNESS_MIN_STAGE_RISE_M
    assert high.velocity_m_s <= low.velocity_m_s - ROUGHNESS_MIN_VELOCITY_DROP_MS


def _assert_flood(case: HydraulicBenchmarkCase, result: HydraulicResult) -> None:
    """Check flood amplification and delayed arrival at a downstream interior monitor."""

    sections = sorted(case.model.cross_sections, key=lambda item: item.chainage_m)
    assert len(sections) >= 3
    monitor_rows = _rows_by_section(result)[sections[-2].id]
    baseline = monitor_rows[0]
    peak_q = max(monitor_rows, key=lambda item: item.discharge_m3s)
    peak_h = max(monitor_rows, key=lambda item: item.water_level_m)
    upstream = next(
        item for item in case.model.boundaries if item.location == "upstream"
    )
    input_peak = max(upstream.series, key=lambda item: item.value)
    minimum_arrival_time = (
        input_peak.time_seconds
        + FLOOD_MIN_ARRIVAL_LAG_OUTPUT_STEPS
        * case.model.settings.output_interval_seconds
    )

    assert peak_q.discharge_m3s >= baseline.discharge_m3s + FLOOD_MIN_PEAK_Q_RISE_M3S
    assert peak_h.water_level_m >= baseline.water_level_m + FLOOD_MIN_PEAK_H_RISE_M
    assert float(peak_q.timestamp) >= minimum_arrival_time
    assert float(peak_h.timestamp) >= input_peak.time_seconds
    assert float(peak_q.timestamp) <= case.model.settings.duration_seconds
    assert peak_q.discharge_m3s <= (
        input_peak.value * (1.0 + FLOOD_PEAK_Q_OVERSHOOT_RELATIVE_TOLERANCE)
    )


def _assert_natural_mapping(case: HydraulicBenchmarkCase, result: HydraulicResult) -> None:
    """Check every natural Section identity, chainage, H, and Q in real output."""

    expected = {item.id: item.chainage_m for item in case.model.cross_sections}
    assert {item.cross_section_id for item in result.records} == set(expected)
    for row in result.records:
        assert isclose(
            row.chainage_m,
            expected[row.cross_section_id],
            rel_tol=0.0,
            abs_tol=1e-6,
        )
        assert isfinite(row.water_level_m)
        assert isfinite(row.discharge_m3s)


def _assert_boundary_fidelity(
    case: HydraulicBenchmarkCase,
    metrics: HydraulicBenchmarkMetrics,
) -> None:
    """Bound endpoint-law RMSE using both engineering and relative tolerances."""

    upstream = next(
        item for item in case.model.boundaries if item.location == "upstream"
    )
    downstream = next(
        item for item in case.model.boundaries if item.location == "downstream"
    )
    q_scale = max(abs(item.value) for item in upstream.series)
    h_scale = max(abs(item.value) for item in downstream.series)
    q_limit = max(
        BOUNDARY_Q_ABSOLUTE_TOLERANCE_M3S,
        BOUNDARY_Q_RELATIVE_TOLERANCE * q_scale,
    )
    h_limit = max(
        BOUNDARY_H_ABSOLUTE_TOLERANCE_M,
        BOUNDARY_H_RELATIVE_TOLERANCE * h_scale,
    )
    assert metrics.discharge_error <= q_limit
    assert metrics.water_level_error <= h_limit


def assert_case_acceptance(
    case: HydraulicBenchmarkCase,
    result: HydraulicResult,
    metrics: HydraulicBenchmarkMetrics,
    *,
    comparison_result: HydraulicResult | None = None,
    comparison_metrics: HydraulicBenchmarkMetrics | None = None,
) -> None:
    """Apply the named numerical/physical acceptance rules for one family."""

    _assert_metric_health(metrics)
    if comparison_metrics is not None:
        _assert_metric_health(comparison_metrics)
    if case.benchmark_id == "benchmark-01-uniform-rectangular":
        _assert_uniform(case, result)
    elif case.benchmark_id == "benchmark-02-roughness-sensitivity":
        _assert_roughness_pair(case, result, comparison_result)
    elif case.benchmark_id == "benchmark-03-flood-hydrograph":
        _assert_flood(case, result)
    elif case.benchmark_id == "benchmark-04-natural-sections":
        _assert_natural_mapping(case, result)
    elif case.benchmark_id == "benchmark-05-boundary-series":
        _assert_boundary_fidelity(case, metrics)
    else:  # pragma: no cover - ALL_BENCHMARKS is a closed audited registry.
        raise AssertionError(f"benchmark has no physical acceptance rule: {case.benchmark_id}")
