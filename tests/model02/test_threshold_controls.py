"""Scientific guardrails for accepted-state one-shot Gate and Pump controls."""

from __future__ import annotations

import pytest

import model.solver.finite_volume.integrator as integrator_module
from model.geometry.sections import RectangularSectionGeometry
from model.solver.finite_volume import (
    BoundaryPair,
    BoundarySeries,
    DownstreamStageBoundary,
    FiniteVolumeCell,
    FiniteVolumeMesh,
    FixedGate,
    HydraulicState,
    OneShotStageThreshold,
    OnOffPump,
    SingleBranchConfig,
    StabilityError,
    StructureStageContext,
    UpstreamDischargeBoundary,
    solve_single_branch,
)


def _context(*, upstream_stage: float = 11.0, downstream_stage: float = 10.0):
    """Return one finite structure-stage context for pure device checks."""

    return StructureStageContext(
        time=1.0,
        dt=0.5,
        upstream_stage=upstream_stage,
        downstream_stage=downstream_stage,
        upstream_area=10.0,
        downstream_area=9.0,
        upstream_discharge=1.0,
        downstream_discharge=1.0,
    )


def _control_run(*, end_time: float = 1.0, maximum_dt: float = 0.25):
    """Run a fast rising-head case with one Gate and Pump on the first cell."""

    geometry = RectangularSectionGeometry(width=10.0, bed_elevation=0.0)
    mesh = FiniteVolumeMesh(
        tuple(
            FiniteVolumeCell(
                cell_id=f"cell-{index}",
                dx=100.0,
                section_id=f"section-{index}",
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
            BoundarySeries((0.0, end_time), (1.0, 1.0), "discharge")
        ),
        downstream=DownstreamStageBoundary(
            BoundarySeries((0.0, end_time), (1.0, 1.0), "stage")
        ),
    )
    control = OneShotStageThreshold(1.00001)
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
            output_interval=0.25,
        ),
        gates=(gate,),
        pumps=(pump,),
    )
    return result, gate, pump


def test_strict_threshold_and_gate_latch_are_pure_and_one_shot() -> None:
    """Equality stays closed; the first accepted exceedance opens exactly once."""

    control = OneShotStageThreshold(10.0)
    gate = FixedGate(
        "gate-1",
        face_index=0,
        opening=0.8,
        width=2.0,
        height=1.0,
        control=control,
    )

    closed, event = gate.synchronize_accepted_state(
        time=0.0,
        observed_water_level=10.0,
    )
    assert control.is_exceeded(10.0) is False
    assert closed["triggered"] is False
    assert closed["opening"] == 0.0
    assert event is None
    assert gate.evaluate_stage(_context(), closed).flow == 0.0

    opened, event = gate.synchronize_accepted_state(
        time=2.0,
        observed_water_level=10.0001,
        previous_state=closed,
    )
    assert closed["triggered"] is False
    assert opened["triggered"] is True
    assert opened["opening"] == 0.8
    assert event is not None
    assert (event.time, event.action, event.observed_water_level) == (
        2.0,
        "open",
        10.0001,
    )
    assert gate.evaluate_stage(_context(), opened).flow > 0.0

    still_open, repeated = gate.synchronize_accepted_state(
        time=3.0,
        observed_water_level=9.0,
        previous_state=opened,
    )
    assert still_open["triggered"] is True
    assert repeated is None


def test_pump_latch_keeps_control_state_separate_from_actual_status() -> None:
    """A threshold starts the external sink once and never restarts on later samples."""

    pump = OnOffPump(
        "pump-1",
        cell_index=0,
        design_flow=0.25,
        enabled=False,
        control=OneShotStageThreshold(5.0),
    )

    off, event = pump.synchronize_accepted_state(
        time=0.0,
        observed_water_level=4.9,
    )
    assert off["triggered"] is False
    assert off["enabled"] is False
    assert event is None
    assert pump.evaluate_stage(_context(), off).flow == 0.0

    on, event = pump.synchronize_accepted_state(
        time=1.5,
        observed_water_level=5.1,
        previous_state=off,
    )
    assert on["triggered"] is True
    assert on["enabled"] is True
    assert event is not None
    assert event.action == "start"
    assert pump.evaluate_stage(_context(), on).flow == 0.25

    on_again, repeated = pump.synchronize_accepted_state(
        time=2.0,
        observed_water_level=5.2,
        previous_state=on,
    )
    assert on_again == on
    assert repeated is None


def test_controlled_stage_evaluation_never_triggers_from_rk_stage_head() -> None:
    """A high trial-stage head cannot mutate or activate an uncommitted latch."""

    gate = FixedGate(
        "gate-1",
        face_index=0,
        opening=0.8,
        width=2.0,
        height=1.0,
        control=OneShotStageThreshold(10.0),
    )
    pump = OnOffPump(
        "pump-1",
        cell_index=0,
        design_flow=0.25,
        enabled=False,
        control=OneShotStageThreshold(10.0),
    )
    context = _context(upstream_stage=100.0, downstream_stage=0.0)

    assert gate.evaluate_stage(context).flow == 0.0
    assert pump.evaluate_stage(context).flow == 0.0


def test_fixed_device_semantics_remain_backward_compatible() -> None:
    """Omitting control retains the original fixed command and state shape."""

    gate = FixedGate("gate-1", 0, 0.5, 2.0, 1.0)
    pump = OnOffPump("pump-1", 0, 0.25, True)

    gate_flow = gate.evaluate_stage(_context())
    pump_flow = pump.evaluate_stage(_context())

    assert gate_flow.flow > 0.0
    assert gate_flow.state == {"opening": 0.5}
    assert pump_flow.flow == 0.25
    assert pump_flow.state == {"enabled": True}


def test_control_state_shape_and_initial_command_fail_closed() -> None:
    """A conflicting persisted command cannot silently override the latch."""

    control = OneShotStageThreshold(10.0)
    gate = FixedGate("gate-1", 0, 0.5, 2.0, 1.0, control=control)

    with pytest.raises(ValueError, match="unknown shape"):
        gate.evaluate_stage(_context(), {"triggered": True})
    with pytest.raises(ValueError, match="must start disabled"):
        OnOffPump("pump-1", 0, 0.25, True, control=control)


def test_case004_005_mvp_behavior_commits_only_at_accepted_step_end() -> None:
    """A rising level opens/starts once; both RK stages use the prior command."""

    result, gate, pump = _control_run()

    assert tuple(
        (event.structure_type, event.action) for event in result.control_events
    ) == (("gate", "open"), ("pump", "start"))
    event_times = {event.time for event in result.control_events}
    assert len(event_times) == 1
    event_time = event_times.pop()
    accepted_times = {step.state.time for step in result.steps}
    assert event_time in accepted_times
    assert event_time == pytest.approx(0.25)

    for step in result.steps:
        gate_commands = {
            flow.state["opening"] for flow in step.budget.gate_stage_flows
        }
        pump_commands = {
            flow.state["enabled"] for flow in step.budget.pump_stage_flows
        }
        assert len(gate_commands) == 1
        assert len(pump_commands) == 1
        if step.state.time <= event_time:
            assert gate_commands == {0.0}
            assert pump_commands == {False}
        else:
            assert gate_commands == {gate.opening}
            assert pump_commands == {True}

    event_state = next(state for state in result.states if state.time == event_time)
    assert event_state.gate_state[gate.gate_id]["opening"] == gate.opening
    assert event_state.pump_state[pump.pump_id]["enabled"] is True
    assert result.diagnostics.pump_outflow_volume == pytest.approx(0.15)
    assert result.diagnostics.relative_water_balance_error < 1.0e-12
    assert 0.0 <= result.diagnostics.maximum_cfl <= 0.7
    assert (
        "structure_control_one_shot_accepted_state_discrete"
        in result.diagnostics.diagnostic_flags
    )


def test_case004_mvp_behavior_gate_threshold_opens_once() -> None:
    """Case004 behavior gate: accepted upstream stage opens the Gate once."""

    result, gate, _ = _control_run()
    events = [
        event for event in result.control_events if event.structure_type == "gate"
    ]

    assert len(events) == 1
    assert events[0].structure_id == gate.gate_id
    assert events[0].observed_water_level > events[0].threshold_water_level
    assert result.states[0].gate_state[gate.gate_id]["opening"] == 0.0
    assert result.states[-1].gate_state[gate.gate_id]["opening"] == gate.opening


def test_case005_mvp_behavior_pump_threshold_starts_once() -> None:
    """Case005 behavior check: accepted local stage starts the Pump once."""

    result, _, pump = _control_run()
    events = [
        event for event in result.control_events if event.structure_type == "pump"
    ]

    assert len(events) == 1
    assert events[0].structure_id == pump.pump_id
    assert events[0].observed_water_level > events[0].threshold_water_level
    assert result.states[0].pump_state[pump.pump_id]["enabled"] is False
    assert result.states[-1].pump_state[pump.pump_id]["enabled"] is True


def test_rejected_completed_trial_cannot_duplicate_control_events(monkeypatch) -> None:
    """A fully evaluated rejected SSP trial leaves no latch or event side effect."""

    original_step = integrator_module.ssp_rk2_step
    rejected_states = []
    attempts = 0

    def reject_first_completed_trial(**kwargs):
        nonlocal attempts
        attempts += 1
        trial = original_step(**kwargs)
        if attempts == 1:
            rejected_states.append(trial.state)
            raise StabilityError("synthetic rejection after both SSP stages")
        return trial

    monkeypatch.setattr(
        integrator_module,
        "ssp_rk2_step",
        reject_first_completed_trial,
    )

    result, gate, pump = _control_run(end_time=0.5)

    assert len(rejected_states) == 1
    assert rejected_states[0].gate_state[gate.gate_id]["triggered"] is False
    assert rejected_states[0].pump_state[pump.pump_id]["triggered"] is False
    assert result.diagnostics.retry_count == 1
    assert len(result.control_events) == 2
    assert {event.time for event in result.control_events} == {0.125}
    assert [event.structure_id for event in result.control_events] == [
        gate.gate_id,
        pump.pump_id,
    ]


def test_control_time_is_accepted_state_discrete_not_interpolated() -> None:
    """Coarse/fine runs report their first accepted exceedance, not a guessed root."""

    coarse, _, _ = _control_run(maximum_dt=0.25)
    fine, _, _ = _control_run(maximum_dt=0.05)
    coarse_time = coarse.control_events[0].time
    fine_time = fine.control_events[0].time

    assert coarse_time == pytest.approx(0.25)
    assert fine_time == pytest.approx(0.05)
    assert coarse_time != fine_time
    assert coarse_time in {step.state.time for step in coarse.steps}
    assert fine_time in {step.state.time for step in fine.steps}
