"""Conservative right-end replay gates for MODEL-02-C threshold events."""

from __future__ import annotations

import pytest

import model.solver.finite_volume.integrator as integrator_module
from model.geometry.sections import RectangularSectionGeometry
from model.solver.finite_volume import (
    BoundaryPair,
    BoundarySeries,
    BracketedOneShotStageThreshold,
    DownstreamStageBoundary,
    FiniteVolumeCell,
    FiniteVolumeMesh,
    FixedGate,
    HydraulicState,
    NumericalStateError,
    OnOffPump,
    SingleBranchConfig,
    StabilityError,
    UpstreamDischargeBoundary,
    solve_single_branch,
)


def _bracketed_run(
    *,
    maximum_dt: float = 0.25,
    event_tolerance: float = 0.01,
    threshold: float = 1.00001,
    upstream_flow: float = 1.0,
    maximum_event_refinements: int = 30,
):
    """Run one rising, fully wet case with simultaneous Gate/Pump controls."""

    end_time = 0.5
    geometry = RectangularSectionGeometry(width=10.0, bed_elevation=0.0)
    mesh = FiniteVolumeMesh(
        tuple(
            FiniteVolumeCell(
                cell_id=f"cell-{index}",
                dx=100.0,
                section_id=index + 1,
                bed_elevation=0.0,
                geometry=geometry,
                manning_n=0.0,
            )
            for index in range(3)
        )
    )
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=(10.0, 10.0, 10.0),
        discharge=(0.0, 0.0, 0.0),
        dry_depth=1.0e-3,
    )
    boundaries = BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries(
                (0.0, end_time),
                (upstream_flow, upstream_flow),
                "discharge",
            ),
            boundary_closure="subcritical-characteristic-v1",
        ),
        downstream=DownstreamStageBoundary(
            BoundarySeries((0.0, end_time), (1.0, 1.0), "stage"),
            boundary_closure="subcritical-characteristic-v1",
        ),
    )
    control = BracketedOneShotStageThreshold(threshold)
    gate = FixedGate(
        "gate-1",
        face_index=0,
        opening=0.5,
        width=2.0,
        height=1.0,
        control=control,
    )
    pump = OnOffPump(
        "pump-1",
        cell_index=0,
        design_flow=0.2,
        enabled=False,
        control=control,
    )
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=boundaries,
        config=SingleBranchConfig(
            end_time=end_time,
            maximum_dt=maximum_dt,
            minimum_dt=1.0e-5,
            output_interval=0.25,
            structure_event_policy="bracketed-conservative-replay-right-end-v1",
            event_time_tolerance=event_tolerance,
            maximum_event_refinements=maximum_event_refinements,
        ),
        gates=(gate,),
        pumps=(pump,),
    )
    return result, gate, pump


def test_bracketed_crossing_is_atomic_bounded_and_applies_next_interval() -> None:
    """Both devices latch from one pre-action state without forward filling."""

    result, gate, pump = _bracketed_run()

    assert [(event.structure_type, event.action) for event in result.control_events] == [
        ("gate", "open"),
        ("pump", "start"),
    ]
    assert len({event.time for event in result.control_events}) == 1
    event_time = result.control_events[0].time
    for event in result.control_events:
        assert event.bracket is not None
        assert event.bracket.previous_observed_water_level <= event.threshold_water_level
        assert event.observed_water_level > event.threshold_water_level
        assert event.time - event.bracket.previous_time <= 0.01 + 1.0e-12
        assert event.bracket.monitored_section_id == 1
        assert event.bracket.refinement_count > 0

    event_step = next(step for step in result.steps if step.state.time == event_time)
    assert {flow.state["opening"] for flow in event_step.budget.gate_stage_flows} == {
        0.0
    }
    assert {flow.state["enabled"] for flow in event_step.budget.pump_stage_flows} == {
        False
    }
    later_step = next(step for step in result.steps if step.state.time > event_time)
    assert {flow.state["opening"] for flow in later_step.budget.gate_stage_flows} == {
        gate.opening
    }
    assert {flow.state["enabled"] for flow in later_step.budget.pump_stage_flows} == {
        True
    }
    assert result.diagnostics.relative_water_balance_error < 1.0e-12
    assert "structure_control_one_shot_accepted_state_discrete" not in (
        result.diagnostics.diagnostic_flags
    )
    assert "structure_control_one_shot_bracketed_right_end_v1" in (
        result.diagnostics.diagnostic_flags
    )
    assert "structure_event_bracketed_conservative_replay_right_end_v1" in (
        result.diagnostics.diagnostic_flags
    )
    assert result.states[-1].gate_state[gate.gate_id]["opening"] == gate.opening
    assert result.states[-1].pump_state[pump.pump_id]["enabled"] is True


def test_coarse_and_fine_event_times_converge_within_frozen_tolerance() -> None:
    """Replay bounds the discretization dependence without interpolating state."""

    coarse, _, _ = _bracketed_run(maximum_dt=0.25)
    fine, _, _ = _bracketed_run(maximum_dt=0.05)
    coarse_time = coarse.control_events[0].time
    fine_time = fine.control_events[0].time

    assert abs(coarse_time - fine_time) <= 0.01
    assert coarse_time in {step.state.time for step in coarse.steps}
    assert fine_time in {step.state.time for step in fine.steps}
    assert coarse_time not in {0.25, 0.5}


def test_never_crossing_has_no_event_and_keeps_devices_inactive() -> None:
    """A bounded non-crossing run remains a valid zero-event result."""

    result, gate, pump = _bracketed_run(threshold=1.1, upstream_flow=0.0)

    assert result.control_events == ()
    assert result.states[-1].gate_state[gate.gate_id]["opening"] == 0.0
    assert result.states[-1].pump_state[pump.pump_id]["enabled"] is False
    assert result.diagnostics.pump_outflow_volume == 0.0


@pytest.mark.parametrize("threshold", [1.0, 0.99])
def test_initial_equality_or_exceedance_fails_closed(threshold: float) -> None:
    """The first accepted state cannot be relabelled as a located crossing."""

    with pytest.raises(ValueError, match="initial stage must be below threshold"):
        _bracketed_run(threshold=threshold)


def test_event_refinement_exhaustion_fails_instead_of_accepting_coarse_time() -> None:
    """A crossing that cannot satisfy the tolerance never produces success."""

    with pytest.raises(NumericalStateError, match="maximum_event_refinements"):
        _bracketed_run(maximum_event_refinements=0)


def test_rejected_numerical_trial_does_not_duplicate_or_shift_event(monkeypatch) -> None:
    """A completed numerical retry is distinct from an event-location replay."""

    reference, _, _ = _bracketed_run()
    original_step = integrator_module.ssp_rk2_step
    attempts = 0

    def reject_first_completed_trial(**kwargs):
        nonlocal attempts
        attempts += 1
        trial = original_step(**kwargs)
        if attempts == 1:
            raise StabilityError("synthetic rejection after both SSP stages")
        return trial

    monkeypatch.setattr(integrator_module, "ssp_rk2_step", reject_first_completed_trial)
    retried, _, _ = _bracketed_run()

    # The rejected numerical attempt belonged only to an event-location probe;
    # replay discards both its state and telemetry before accepting the bracket.
    assert retried.diagnostics.retry_count == reference.diagnostics.retry_count == 0
    assert len(retried.control_events) == 2
    assert [event.time for event in retried.control_events] == pytest.approx(
        [reference.control_events[0].time, reference.control_events[1].time]
    )
    assert retried.diagnostics.pump_outflow_volume == pytest.approx(
        reference.diagnostics.pump_outflow_volume
    )
