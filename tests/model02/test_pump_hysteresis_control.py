"""D1 Pump hysteresis, minimum-runtime, energy, and stage-purity tests."""

from __future__ import annotations

import pytest

from model.solver.finite_volume import BoundarySeries, StructureStageContext
from model.solver.finite_volume.pump import (
    HydraulicExternalPump,
    StageHysteresisMinimumRuntime,
)
from model.solver.finite_volume.pump_curve import (
    PumpEfficiencyCurve,
    PumpHeadCurve,
    PumpSystemLoss,
    PumpUnitConfiguration,
)


def _pump(
    *,
    minimum_run_seconds: float = 10.0,
    minimum_stop_seconds: float = 5.0,
    maximum_starts: int = 2,
) -> HydraulicExternalPump:
    """Return one D1 Pump whose target stage is explicitly frozen."""

    return HydraulicExternalPump(
        pump_id="pump-d1",
        cell_index=0,
        source_bed_elevation_m=0.0,
        minimum_source_depth_m=0.01,
        head_curve=PumpHeadCurve(
            ((0.0, 8.5), (5.0, 7.8), (10.0, 6.3), (15.0, 3.2))
        ),
        efficiency_curve=PumpEfficiencyCurve(
            ((2.0, 0.65), (8.0, 0.84), (12.0, 0.80))
        ),
        unit_configuration=PumpUnitConfiguration(1, 1, 1, 1),
        system_loss=PumpSystemLoss(0.5, 0.02),
        outlet_stage=BoundarySeries((0.0, 100.0), (14.0, 14.0), "stage"),
        control=StageHysteresisMinimumRuntime(
            start_level_m=10.5,
            stop_level_m=9.5,
            minimum_run_seconds=minimum_run_seconds,
            minimum_stop_seconds=minimum_stop_seconds,
            maximum_starts=maximum_starts,
        ),
        initial_status="off",
    )


def _context(time: float, source_stage_m: float) -> StructureStageContext:
    """Build one pure Pump stage context with an explicit external target."""

    return StructureStageContext(
        time=time,
        dt=1.0,
        upstream_stage=source_stage_m,
        downstream_stage=14.0,
        upstream_area=20.0,
        downstream_area=20.0,
        upstream_discharge=1.0,
        downstream_discharge=1.0,
    )


def test_p4_hysteresis_holds_until_minimum_stop_and_run_are_satisfied() -> None:
    """P4 verifies start, hold, stop, and chatter prevention at accepted states."""

    pump = _pump()
    state, event = pump.synchronize_accepted_state(
        time=0.0,
        observed_water_level=11.0,
    )
    assert state["control_state"] == "off"
    assert event is None

    state, event = pump.synchronize_accepted_state(
        time=5.0,
        observed_water_level=11.0,
        previous_state=state,
    )
    assert state["control_state"] == "on"
    assert event is not None and event.action == "start"

    held, event = pump.synchronize_accepted_state(
        time=14.0,
        observed_water_level=9.0,
        previous_state=state,
    )
    assert held["control_state"] == "on"
    assert event is None

    stopped, event = pump.synchronize_accepted_state(
        time=15.0,
        observed_water_level=9.0,
        previous_state=held,
    )
    assert stopped["control_state"] == "off"
    assert event is not None and event.action == "stop"

    deadband, event = pump.synchronize_accepted_state(
        time=30.0,
        observed_water_level=10.0,
        previous_state=stopped,
    )
    assert deadband == stopped
    assert event is None


def test_p4_maximum_starts_holds_the_station_off() -> None:
    """A start limit prevents another transition without fabricating a command."""

    pump = _pump(
        minimum_run_seconds=0.0,
        minimum_stop_seconds=0.0,
        maximum_starts=1,
    )
    state, first = pump.synchronize_accepted_state(
        time=0.0,
        observed_water_level=11.0,
    )
    state, stop = pump.synchronize_accepted_state(
        time=1.0,
        observed_water_level=9.0,
        previous_state=state,
    )
    held, repeated = pump.synchronize_accepted_state(
        time=2.0,
        observed_water_level=11.0,
        previous_state=state,
    )

    assert first is not None and first.action == "start"
    assert stop is not None and stop.action == "stop"
    assert held["control_state"] == "off"
    assert held["starts"] == 1
    assert repeated is None


def test_stage_evaluation_is_pure_and_recomputes_qh_from_stage_level() -> None:
    """RK evaluations read committed commands and change Q only through hydraulics."""

    pump = _pump(minimum_stop_seconds=0.0)
    on_state, event = pump.synchronize_accepted_state(
        time=0.0,
        observed_water_level=11.0,
    )
    assert event is not None

    lower = pump.evaluate_stage(_context(0.0, 10.0), on_state)
    higher = pump.evaluate_stage(_context(1.0, 11.0), on_state)

    assert higher.flow > lower.flow
    assert on_state["starts"] == 1
    assert lower.state == higher.state == on_state
    assert lower.pump_operating_point is not None
    assert higher.pump_operating_point is not None


def test_p5_stage_evidence_exposes_recomputable_power_and_off_zero() -> None:
    """P5 checks same-point power and the explicit zero-power OFF contract."""

    pump = _pump(minimum_stop_seconds=0.0)
    off = pump.evaluate_stage(_context(0.0, 10.0))
    on_state, _ = pump.synchronize_accepted_state(
        time=0.0,
        observed_water_level=11.0,
    )
    on = pump.evaluate_stage(_context(0.0, 10.0), on_state)

    assert off.flow == 0.0
    assert off.pump_operating_point is not None
    assert off.pump_operating_point.input_power_kw == 0.0
    evidence = on.pump_operating_point
    assert evidence is not None
    independent = (
        1000.0
        * 9.81
        * evidence.total_flow_m3s
        * evidence.pump_head_m
        / evidence.efficiency
        / 1000.0
    )
    assert evidence.input_power_kw == pytest.approx(independent)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"start_level_m": 9.0, "stop_level_m": 9.0}, "greater"),
        ({"minimum_run_seconds": -1.0}, "non-negative"),
        ({"maximum_starts": 0}, "positive"),
    ],
)
def test_hysteresis_preflight_fails_closed(kwargs: dict, message: str) -> None:
    """Invalid threshold/dwell/start inputs never reach a simulation."""

    values = {
        "start_level_m": 10.5,
        "stop_level_m": 9.5,
        "minimum_run_seconds": 0.0,
        "minimum_stop_seconds": 0.0,
        "maximum_starts": 2,
    }
    values.update(kwargs)
    with pytest.raises(ValueError, match=message):
        StageHysteresisMinimumRuntime(**values)


def test_running_pump_rejects_a_dry_source_cell() -> None:
    """A dry Pump source must retry/fail instead of silently reducing Q."""

    pump = _pump(minimum_stop_seconds=0.0)
    on_state, _ = pump.synchronize_accepted_state(
        time=0.0,
        observed_water_level=11.0,
    )
    with pytest.raises(ValueError, match="source cell is dry"):
        pump.evaluate_stage(_context(0.0, 0.001), on_state)
