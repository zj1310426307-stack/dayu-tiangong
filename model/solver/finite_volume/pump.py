"""Accepted-state hydraulic Pump control and per-stage external-sink runtime."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Mapping

from model.solver.finite_volume.boundary import BoundarySeries
from model.solver.finite_volume.pump_curve import (
    PUMP_CONTROL_POLICY,
    PumpEfficiencyCurve,
    PumpHeadCurve,
    PumpSystemLoss,
    PumpUnitConfiguration,
    off_pump_evidence,
    solve_pump_operating_point,
)
from model.solver.finite_volume.structures import (
    ControlBracketEvidence,
    StructureControlEvent,
    StructureStageContext,
    StructureStageFlow,
)

_CONTROL_STATE_KEYS = frozenset(
    {"control_state", "running_units", "last_transition_time", "starts"}
)


def _finite(value: float, label: str) -> float:
    """Return one finite controller value while rejecting booleans."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


@dataclass(frozen=True)
class StageHysteresisMinimumRuntime:
    """Freeze a chatter-resistant accepted-state Pump control policy."""

    start_level_m: float
    stop_level_m: float
    minimum_run_seconds: float
    minimum_stop_seconds: float
    maximum_starts: int
    policy_id: str = PUMP_CONTROL_POLICY

    def __post_init__(self) -> None:
        """Reject ambiguous thresholds and invalid dwell/start limits."""

        start = _finite(self.start_level_m, "start_level_m")
        stop = _finite(self.stop_level_m, "stop_level_m")
        minimum_run = _finite(self.minimum_run_seconds, "minimum_run_seconds")
        minimum_stop = _finite(self.minimum_stop_seconds, "minimum_stop_seconds")
        if self.policy_id != PUMP_CONTROL_POLICY:
            raise ValueError("unsupported Pump control policy")
        if start <= stop:
            raise ValueError("Pump start_level_m must be greater than stop_level_m")
        if minimum_run < 0.0 or minimum_stop < 0.0:
            raise ValueError("Pump minimum run/stop times must be non-negative")
        if isinstance(self.maximum_starts, bool) or self.maximum_starts <= 0:
            raise ValueError("Pump maximum_starts must be positive")


@dataclass(frozen=True)
class HydraulicExternalPump:
    """Solve one explicit Q-H external sink from immutable accepted commands.

    The device never mutates during an RK stage. ``synchronize_accepted_state``
    alone advances hysteresis state after a conservative step is accepted.
    Each call to ``evaluate_stage`` resolves a fresh operating point from that
    stage's source and external outlet levels.
    """

    pump_id: str
    cell_index: int
    source_bed_elevation_m: float
    minimum_source_depth_m: float
    head_curve: PumpHeadCurve
    efficiency_curve: PumpEfficiencyCurve
    unit_configuration: PumpUnitConfiguration
    system_loss: PumpSystemLoss
    outlet_stage: BoundarySeries
    control: StageHysteresisMinimumRuntime
    initial_status: Literal["on", "off"]
    head_residual_tolerance_m: float = 1.0e-10
    maximum_iterations: int = 100

    def __post_init__(self) -> None:
        """Validate placement, units, outlet coverage type, and root controls."""

        if not self.pump_id:
            raise ValueError("pump_id must not be empty")
        if isinstance(self.cell_index, bool) or self.cell_index < 0:
            raise ValueError("Pump cell_index must be non-negative")
        bed = _finite(self.source_bed_elevation_m, "source_bed_elevation_m")
        minimum_depth = _finite(
            self.minimum_source_depth_m,
            "minimum_source_depth_m",
        )
        tolerance = _finite(
            self.head_residual_tolerance_m,
            "head_residual_tolerance_m",
        )
        if minimum_depth < 0.0:
            raise ValueError("minimum_source_depth_m must be non-negative")
        if tolerance <= 0.0:
            raise ValueError("head_residual_tolerance_m must be positive")
        if isinstance(self.maximum_iterations, bool) or self.maximum_iterations <= 0:
            raise ValueError("Pump maximum_iterations must be positive")
        if self.outlet_stage.variable != "stage":
            raise ValueError("external Pump outlet series must contain stage")
        if self.unit_configuration.running_units <= 0:
            raise ValueError("D1 commanded running_units must be positive")
        object.__setattr__(self, "source_bed_elevation_m", bed)

    def _initial_control_state(self) -> dict[str, object]:
        """Return the simulation-local state without writing the asset model."""

        return {
            "control_state": self.initial_status,
            "running_units": (
                self.unit_configuration.running_units
                if self.initial_status == "on"
                else 0
            ),
            "last_transition_time": 0.0,
            "starts": 0,
        }

    def _validated_control_state(
        self,
        previous_state: Mapping[str, object] | None,
    ) -> dict[str, object]:
        """Normalize exactly one accepted controller state or fail closed."""

        state = (
            self._initial_control_state()
            if previous_state is None
            else dict(previous_state)
        )
        if frozenset(state) != _CONTROL_STATE_KEYS:
            raise ValueError("hydraulic Pump control state has an unknown shape")
        control_state = state["control_state"]
        running_units = state["running_units"]
        last_transition = state["last_transition_time"]
        starts = state["starts"]
        if control_state not in {"on", "off"}:
            raise ValueError("hydraulic Pump control_state must be on/off")
        if isinstance(running_units, bool) or not isinstance(running_units, int):
            raise ValueError("hydraulic Pump running_units must be an integer")
        if isinstance(starts, bool) or not isinstance(starts, int) or starts < 0:
            raise ValueError("hydraulic Pump starts must be a non-negative integer")
        transition = _finite(float(last_transition), "last_transition_time")
        expected = (
            self.unit_configuration.running_units if control_state == "on" else 0
        )
        if running_units != expected:
            raise ValueError("hydraulic Pump command contradicts control_state")
        if starts > self.control.maximum_starts:
            raise ValueError("hydraulic Pump starts exceeds maximum_starts")
        state["last_transition_time"] = transition
        return state

    def synchronize_accepted_state(
        self,
        *,
        time: float,
        observed_water_level: float,
        previous_state: Mapping[str, object] | None = None,
        bracket: ControlBracketEvidence | None = None,
    ) -> tuple[Mapping[str, object], StructureControlEvent | None]:
        """Commit at most one hysteresis transition at an accepted state."""

        if bracket is not None:
            raise ValueError("hysteresis Pump does not consume one-shot bracket evidence")
        accepted_time = _finite(time, "accepted Pump state time")
        observed = _finite(observed_water_level, "observed Pump stage")
        if accepted_time < 0.0:
            raise ValueError("accepted Pump state time must be non-negative")
        previous = self._validated_control_state(previous_state)
        last_transition = float(previous["last_transition_time"])
        if accepted_time < last_transition:
            raise ValueError("accepted Pump state time moved backwards")
        elapsed = accepted_time - last_transition
        status = str(previous["control_state"])
        starts = int(previous["starts"])
        next_state = dict(previous)
        action: str | None = None
        threshold = self.control.start_level_m
        reason: str | None = None
        if (
            status == "off"
            and observed >= self.control.start_level_m
            and elapsed >= self.control.minimum_stop_seconds
            and starts < self.control.maximum_starts
        ):
            next_state.update(
                {
                    "control_state": "on",
                    "running_units": self.unit_configuration.running_units,
                    "last_transition_time": accepted_time,
                    "starts": starts + 1,
                }
            )
            action = "start"
            reason = "stage_at_or_above_start_and_minimum_stop_satisfied"
        elif (
            status == "on"
            and observed <= self.control.stop_level_m
            and elapsed >= self.control.minimum_run_seconds
        ):
            next_state.update(
                {
                    "control_state": "off",
                    "running_units": 0,
                    "last_transition_time": accepted_time,
                }
            )
            action = "stop"
            threshold = self.control.stop_level_m
            reason = "stage_at_or_below_stop_and_minimum_run_satisfied"
        event = (
            StructureControlEvent(
                time=accepted_time,
                structure_id=self.pump_id,
                structure_type="pump",
                action=action,
                threshold_water_level=threshold,
                observed_water_level=observed,
                reason=reason,
            )
            if action is not None
            else None
        )
        return next_state, event

    def outlet_stage_at(self, time: float) -> float:
        """Return the explicit external target stage without extrapolation."""

        return self.outlet_stage.value_at(time)

    def evaluate_stage(
        self,
        context: StructureStageContext,
        control_state: Mapping[str, object] | None = None,
    ) -> StructureStageFlow:
        """Solve one stage operating point from the committed Pump command."""

        state = self._validated_control_state(control_state)
        running_units = int(state["running_units"])
        if running_units > 0 and (
            context.upstream_area <= 0.0
            or context.upstream_stage - self.source_bed_elevation_m
            <= self.minimum_source_depth_m
        ):
            raise ValueError("hydraulic Pump source cell is dry")
        if running_units == 0:
            evidence = off_pump_evidence(
                evaluation_time=context.time,
                dt=context.dt,
                pump_id=self.pump_id,
                source_stage_m=context.upstream_stage,
                outlet_stage_m=context.downstream_stage,
                system_loss=self.system_loss,
            )
        else:
            units = PumpUnitConfiguration(
                total_units=self.unit_configuration.total_units,
                running_units=running_units,
                minimum_running_units=self.unit_configuration.minimum_running_units,
                maximum_running_units=self.unit_configuration.maximum_running_units,
            )
            evidence = solve_pump_operating_point(
                evaluation_time=context.time,
                dt=context.dt,
                pump_id=self.pump_id,
                source_stage_m=context.upstream_stage,
                outlet_stage_m=context.downstream_stage,
                head_curve=self.head_curve,
                efficiency_curve=self.efficiency_curve,
                units=units,
                system_loss=self.system_loss,
                head_residual_tolerance_m=self.head_residual_tolerance_m,
                maximum_iterations=self.maximum_iterations,
            )
        return StructureStageFlow(
            structure_id=self.pump_id,
            structure_type="pump",
            flow=evidence.total_flow_m3s,
            state=state,
            momentum_closure="local-advective-external-sink-v1",
            pump_operating_point=evidence,
        )


__all__ = [
    "HydraulicExternalPump",
    "StageHysteresisMinimumRuntime",
]
