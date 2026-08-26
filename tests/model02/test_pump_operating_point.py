"""D1 pure Pump-curve and operating-point benchmarks."""

from __future__ import annotations

import math

import pytest

from model.solver.finite_volume.capabilities import require_solver_capability
from model.solver.finite_volume.pump_curve import (
    PumpEfficiencyCurve,
    PumpHeadCurve,
    PumpSystemLoss,
    PumpUnitConfiguration,
    solve_pump_operating_point,
)


def _head_curve() -> PumpHeadCurve:
    """Return a four-point Q-H curve with hand-checkable linear segments."""

    return PumpHeadCurve(((0.0, 8.5), (5.0, 7.8), (10.0, 6.3), (15.0, 3.2)))


def _efficiency_curve() -> PumpEfficiencyCurve:
    """Return a Q-efficiency curve whose domain intersects the Q-H domain."""

    return PumpEfficiencyCurve(((2.0, 0.65), (8.0, 0.84), (12.0, 0.80)))


def _units(count: int = 1) -> PumpUnitConfiguration:
    """Return an identical parallel-unit configuration for a running station."""

    return PumpUnitConfiguration(
        total_units=count,
        running_units=count,
        minimum_running_units=1,
        maximum_running_units=count,
    )


def test_d1_capability_manifest_names_every_new_pump_policy() -> None:
    """The new route is registered instead of extending implicit conditionals."""

    capability = require_solver_capability("v4-lite-7")

    assert capability.manifest.pump_coupling_policy == (
        "qh-operating-point-external-sink-v1"
    )
    assert capability.manifest.pump_curve_policy == "piecewise-linear-qh-v1"
    assert capability.manifest.pump_efficiency_policy == (
        "piecewise-linear-q-efficiency-v1"
    )
    assert capability.manifest.pump_control_policy == (
        "stage-hysteresis-min-runtime-v1"
    )


def test_p1_piecewise_linear_curves_are_deterministic_and_bounded() -> None:
    """P1 verifies exact linear interpolation and fail-closed extrapolation."""

    assert _head_curve().head_at(7.5) == pytest.approx(7.05)
    assert _efficiency_curve().efficiency_at(5.0) == pytest.approx(0.745)
    assert _head_curve().segment_at(15.0) == 2

    with pytest.raises(ValueError, match="outside"):
        _head_curve().head_at(15.0001)
    with pytest.raises(ValueError, match="outside"):
        _efficiency_curve().efficiency_at(1.9999)


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: PumpHeadCurve(((0.0, 8.0),)), "at least two"),
        (
            lambda: PumpHeadCurve(((0.0, 8.0), (0.0, 7.0))),
            "strictly increasing",
        ),
        (lambda: PumpHeadCurve(((0.0, 8.0), (1.0, -1.0))), "non-negative"),
        (
            lambda: PumpEfficiencyCurve(((0.0, 0.8), (1.0, 1.01))),
            "0 < efficiency <= 1",
        ),
    ],
)
def test_curve_preflight_fails_closed(factory, message: str) -> None:
    """Malformed Q-H/Q-efficiency data cannot be sorted, clamped, or guessed."""

    with pytest.raises(ValueError, match=message):
        factory()


def test_p2_static_operating_point_closes_head_efficiency_and_power() -> None:
    """P2 independently checks a bracketed Q-H/quadratic-system intersection."""

    system = PumpSystemLoss(
        static_loss_m=0.5,
        quadratic_loss_coefficient_s2_m5=0.02,
    )
    evidence = solve_pump_operating_point(
        evaluation_time=10.0,
        dt=2.0,
        pump_id="pump-d1",
        source_stage_m=10.0,
        outlet_stage_m=14.0,
        head_curve=_head_curve(),
        efficiency_curve=_efficiency_curve(),
        units=_units(),
        system_loss=system,
        head_residual_tolerance_m=1.0e-10,
        maximum_iterations=100,
    )

    assert 8.0 < evidence.total_flow_m3s < 10.0
    assert evidence.pump_head_m == pytest.approx(evidence.system_head_m, abs=1.0e-10)
    assert evidence.efficiency == pytest.approx(
        _efficiency_curve().efficiency_at(evidence.per_unit_flow_m3s)
    )
    independent_input_power = (
        1000.0
        * 9.81
        * evidence.total_flow_m3s
        * evidence.pump_head_m
        / evidence.efficiency
        / 1000.0
    )
    assert evidence.input_power_kw == pytest.approx(independent_input_power)
    assert all(
        math.isfinite(value)
        for value in (
            evidence.total_flow_m3s,
            evidence.pump_head_m,
            evidence.efficiency,
            evidence.input_power_kw,
        )
    )


def test_p3_dynamic_source_stage_changes_flow_instead_of_design_flow() -> None:
    """P3 proves that a higher source stage lowers system head and increases Q."""

    common = dict(
        evaluation_time=0.0,
        dt=1.0,
        pump_id="pump-d1",
        outlet_stage_m=14.0,
        head_curve=_head_curve(),
        efficiency_curve=_efficiency_curve(),
        units=_units(),
        system_loss=PumpSystemLoss(0.5, 0.02),
        head_residual_tolerance_m=1.0e-10,
        maximum_iterations=100,
    )

    lower_source = solve_pump_operating_point(source_stage_m=9.5, **common)
    higher_source = solve_pump_operating_point(source_stage_m=10.5, **common)

    assert higher_source.total_flow_m3s > lower_source.total_flow_m3s
    assert higher_source.total_flow_m3s != pytest.approx(10.0)


def test_identical_parallel_units_use_per_unit_curve_flow() -> None:
    """Two identical parallel units evaluate head and efficiency at Q_total/2."""

    evidence = solve_pump_operating_point(
        evaluation_time=0.0,
        dt=1.0,
        pump_id="pump-parallel",
        source_stage_m=10.0,
        outlet_stage_m=14.0,
        head_curve=_head_curve(),
        efficiency_curve=_efficiency_curve(),
        units=_units(2),
        system_loss=PumpSystemLoss(0.5, 0.005),
        head_residual_tolerance_m=1.0e-10,
        maximum_iterations=100,
    )

    assert evidence.per_unit_flow_m3s == pytest.approx(
        evidence.total_flow_m3s / 2.0
    )
    assert evidence.pump_head_m == pytest.approx(
        _head_curve().head_at(evidence.per_unit_flow_m3s)
    )


def test_gp2_no_root_and_efficiency_domain_fail_closed() -> None:
    """GP2 rejects no-root and non-overlapping efficiency domains."""

    with pytest.raises(ValueError, match="no bracketed root"):
        solve_pump_operating_point(
            evaluation_time=0.0,
            dt=1.0,
            pump_id="pump-no-root",
            source_stage_m=0.0,
            outlet_stage_m=20.0,
            head_curve=_head_curve(),
            efficiency_curve=_efficiency_curve(),
            units=_units(),
            system_loss=PumpSystemLoss(0.0, 0.0),
            head_residual_tolerance_m=1.0e-10,
            maximum_iterations=100,
        )

    with pytest.raises(ValueError, match="operating envelope"):
        solve_pump_operating_point(
            evaluation_time=0.0,
            dt=1.0,
            pump_id="pump-no-efficiency",
            source_stage_m=10.0,
            outlet_stage_m=14.0,
            head_curve=PumpHeadCurve(((0.0, 8.0), (1.0, 7.0))),
            efficiency_curve=PumpEfficiencyCurve(((2.0, 0.7), (3.0, 0.8))),
            units=_units(),
            system_loss=PumpSystemLoss(0.0, 0.0),
            head_residual_tolerance_m=1.0e-10,
            maximum_iterations=100,
        )
