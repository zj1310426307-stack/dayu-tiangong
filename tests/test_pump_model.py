"""HYDRO-MODEL-01 pump-domain acceptance tests."""

import math

import pytest

from model.structure.pump import PumpControlState, PumpModel


def _pump() -> PumpModel:
    """Return one immutable single-unit pump used by quantitative checks."""

    return PumpModel(
        design_flow_per_unit=2.0,
        minimum_running_units=1,
        maximum_running_units=1,
        minimum_run_seconds=0.0,
        minimum_stop_seconds=0.0,
        maximum_starts_per_run=10,
        minimum_operating_head=0.0,
        maximum_operating_head=10.0,
        efficiency_curve=((0.0, 0.70), (1.0, 0.80)),
    )


def test_pump_model_calculates_flow_power_and_energy() -> None:
    """Flow, power and one-hour energy must remain dimensionally consistent."""

    result = _pump().evaluate(
        requested_units=1,
        head=4.0,
        elapsed_seconds=3600.0,
        state=PumpControlState(),
    )

    expected_power = 1000.0 * 9.81 * 2.0 * 4.0 / 0.80 / 1000.0
    assert result.flow == pytest.approx(2.0)
    assert result.power_kw == pytest.approx(expected_power)
    assert result.energy_kwh == pytest.approx(expected_power)
    assert all(math.isfinite(value) for value in (result.flow, result.power_kw, result.energy_kwh))


def test_pump_model_stops_outside_the_operating_head() -> None:
    """A pump outside its approved head range must fail safe to zero flow."""

    result = _pump().evaluate(
        requested_units=1,
        head=12.0,
        elapsed_seconds=60.0,
        state=PumpControlState(),
    )

    assert result.actual_units == 0
    assert result.flow == 0.0
    assert "head_out_of_range" in result.constraint_flags
