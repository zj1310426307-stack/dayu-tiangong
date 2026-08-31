"""Unit-check benchmark gates without representing fixtures as engine evidence."""

from __future__ import annotations

import pytest

from model.hydraulic_1d import (
    HydraulicBenchmarkMetrics,
    HydraulicResult,
    HydraulicResultRecord,
)
from tests.benchmark.hydraulic_1d.acceptance import assert_case_acceptance
from tests.benchmark.hydraulic_1d.cases import benchmark_01_uniform_rectangular


def _metrics(**changes: float) -> HydraulicBenchmarkMetrics:
    """Build finite metrics solely to exercise the acceptance decision."""

    values = {
        "water_level_error": 0.0,
        "discharge_error": 0.0,
        "velocity_error": 0.0,
        "peak_error": 0.0,
        "peak_time_error": 0.0,
        "mass_balance_error": 0.0,
        "runtime": 1.0,
    }
    values.update(changes)
    return HydraulicBenchmarkMetrics(**values)


def _uniform_result(*, discharge_factor: float = 1.0) -> HydraulicResult:
    """Build an analytic final state, not a substitute MASCARET calculation."""

    case = benchmark_01_uniform_rectangular()
    assert case.reference_velocity_m_s is not None
    sections = {item.id: item for item in case.model.cross_sections}
    records = tuple(
        HydraulicResultRecord(
            simulation_id=case.model.simulation_id,
            scenario_id=case.model.scenario_id,
            engine="acceptance-unit-fixture",
            engine_version="test-only",
            branch_id=sections[state.cross_section_id].branch_id,
            chainage_m=sections[state.cross_section_id].chainage_m,
            cross_section_id=state.cross_section_id,
            timestamp=case.model.settings.duration_seconds,
            water_level_m=state.water_level_m,
            depth_m=2.0,
            discharge_m3s=state.discharge_m3s * discharge_factor,
            velocity_m_s=case.reference_velocity_m_s,
            flow_area_m2=20.0,
        )
        for state in case.model.initial_condition.by_section
    )
    return HydraulicResult(
        simulation_id=case.model.simulation_id,
        scenario_id=case.model.scenario_id,
        engine="acceptance-unit-fixture",
        engine_version="test-only",
        records=records,
    )


def test_uniform_acceptance_rejects_a_large_but_finite_q_error() -> None:
    """Prove that finite output alone cannot pass the real-runtime gate."""

    case = benchmark_01_uniform_rectangular()
    assert_case_acceptance(case, _uniform_result(), _metrics())

    with pytest.raises(AssertionError):
        assert_case_acceptance(
            case,
            _uniform_result(discharge_factor=1.5),
            _metrics(discharge_error=1.0),
        )


def test_mass_balance_gate_rejects_a_large_but_finite_residual() -> None:
    """Keep the common conservation metric numerically discriminating."""

    case = benchmark_01_uniform_rectangular()
    with pytest.raises(AssertionError):
        assert_case_acceptance(
            case,
            _uniform_result(),
            _metrics(mass_balance_error=0.5),
        )
