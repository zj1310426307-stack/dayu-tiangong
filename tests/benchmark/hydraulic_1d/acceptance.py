"""Case-specific physical acceptance rules for real MASCARET benchmark runs."""

from __future__ import annotations

from json import loads
from math import isclose, isfinite
from pathlib import Path

from model.hydraulic_1d import HydraulicBenchmarkMetrics, HydraulicResult
from tests.benchmark.hydraulic_1d.cases import HydraulicBenchmarkCase


ACCEPTANCE_MANIFEST = loads(
    (Path(__file__).with_name("acceptance-manifest.json")).read_text(encoding="utf-8")
)


def _tolerance(case_id: str, metric: str) -> float:
    """Read every reviewed tolerance from the one versioned manifest."""

    return float(ACCEPTANCE_MANIFEST[case_id][metric]["tolerance"])


def _rows_by_section(result: HydraulicResult) -> dict[str, list]:
    """Return chronologically ordered rows for each unified Section."""

    grouped: dict[str, list] = {}
    for row in result.records:
        grouped.setdefault(row.cross_section_id, []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda item: float(item.timestamp))
    return grouped


def _assert_metric_health(
    metrics: HydraulicBenchmarkMetrics,
) -> None:
    """Validate metric health and enforce the global continuity ceiling."""

    assert all(isfinite(value) and value >= 0.0 for value in metrics.to_dict().values())
    assert metrics.runtime > 0.0
    assert metrics.mass_balance_error <= _tolerance(
        "global",
        "mass_balance_max_relative_residual",
    )


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
            rel_tol=_tolerance(case.benchmark_id, "discharge_relative"),
            abs_tol=_tolerance(case.benchmark_id, "discharge_absolute_m3s"),
        )
        assert isclose(
            final.water_level_m,
            expected.water_level_m,
            rel_tol=_tolerance(case.benchmark_id, "water_level_relative"),
            abs_tol=_tolerance(case.benchmark_id, "water_level_absolute_m"),
        )
        assert isclose(
            final.velocity_m_s,
            case.reference_velocity_m_s,
            rel_tol=_tolerance(case.benchmark_id, "velocity_relative"),
            abs_tol=_tolerance(case.benchmark_id, "velocity_absolute_ms"),
        )


def _assert_roughness_pair(
    case: HydraulicBenchmarkCase,
    low_result: HydraulicResult,
    comparison_results: tuple[HydraulicResult, ...],
) -> None:
    """Require n1<n2<n3 to raise stage and reduce velocity monotonically."""

    assert len(case.comparison_models) == 2
    assert len(comparison_results) == 2
    monitor_id = min(
        case.model.cross_sections,
        key=lambda item: item.chainage_m,
    ).id
    states = [
        _rows_by_section(item)[monitor_id][-1]
        for item in (low_result, *comparison_results)
    ]
    stage_margin = _tolerance(case.benchmark_id, "minimum_stage_rise_m")
    velocity_margin = _tolerance(case.benchmark_id, "minimum_velocity_drop_ms")
    for lower, higher in zip(states, states[1:]):
        assert higher.water_level_m >= lower.water_level_m + stage_margin
        assert higher.velocity_m_s <= lower.velocity_m_s - velocity_margin


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
        + _tolerance(case.benchmark_id, "minimum_arrival_lag_output_steps")
        * case.model.settings.output_interval_seconds
    )

    assert peak_q.discharge_m3s >= baseline.discharge_m3s + _tolerance(
        case.benchmark_id,
        "minimum_peak_q_rise_m3s",
    )
    assert peak_h.water_level_m >= baseline.water_level_m + _tolerance(
        case.benchmark_id,
        "minimum_peak_h_rise_m",
    )
    assert float(peak_q.timestamp) >= minimum_arrival_time
    assert float(peak_h.timestamp) >= input_peak.time_seconds
    assert float(peak_q.timestamp) <= case.model.settings.duration_seconds
    assert peak_q.discharge_m3s <= (
        input_peak.value
        * (1.0 + _tolerance(case.benchmark_id, "peak_q_overshoot_relative"))
    )


def _assert_natural_mapping(
    case: HydraulicBenchmarkCase, result: HydraulicResult
) -> None:
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
        _tolerance(case.benchmark_id, "discharge_absolute_m3s"),
        _tolerance(case.benchmark_id, "discharge_relative") * q_scale,
    )
    h_limit = max(
        _tolerance(case.benchmark_id, "water_level_absolute_m"),
        _tolerance(case.benchmark_id, "water_level_relative") * h_scale,
    )
    assert metrics.discharge_error <= q_limit
    assert metrics.water_level_error <= h_limit


def assert_case_acceptance(
    case: HydraulicBenchmarkCase,
    result: HydraulicResult,
    metrics: HydraulicBenchmarkMetrics,
    *,
    comparison_results: tuple[HydraulicResult, ...] = (),
    comparison_metrics: tuple[HydraulicBenchmarkMetrics, ...] = (),
) -> None:
    """Apply the named numerical/physical acceptance rules for one family."""

    _assert_metric_health(metrics)
    for item in comparison_metrics:
        _assert_metric_health(item)
    if case.benchmark_id == "benchmark-01-uniform-rectangular":
        _assert_uniform(case, result)
    elif case.benchmark_id == "benchmark-02-roughness-sensitivity":
        _assert_roughness_pair(case, result, comparison_results)
    elif case.benchmark_id == "benchmark-03-flood-hydrograph":
        _assert_flood(case, result)
    elif case.benchmark_id == "benchmark-04-natural-sections":
        _assert_natural_mapping(case, result)
    elif case.benchmark_id == "benchmark-05-boundary-series":
        _assert_boundary_fidelity(case, metrics)
    else:  # pragma: no cover - ALL_BENCHMARKS is a closed audited registry.
        raise AssertionError(
            f"benchmark has no physical acceptance rule: {case.benchmark_id}"
        )
