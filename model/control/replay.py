"""Deterministic synthetic replay for frozen Gate/Pump scheduling policies."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from model.control.constraints import validate_target_against_asset
from model.control.policy import (
    CompositeControlPolicy,
    ControlTarget,
    HydraulicObservation,
)
from model.control.rules import ThresholdRule, ThresholdRulePolicy
from model.control.schedule import ManualSchedulePolicy, ScheduledAction


SYNTHETIC_SCHEDULE_EVALUATOR_ID = "dayu.synthetic-static-schedule.v1"
SYNTHETIC_TIE_BREAK_POLICY = (
    "higher_priority_then_rule_then_higher_frozen_rule_id"
)
SYNTHETIC_INITIAL_STATE_BASIS = (
    "ALL_GATES_CLOSED_ALL_PUMPS_STOPPED_MIN_STOP_SATISFIED_"
    "T0_SETPOINTS_APPLY_IMMEDIATELY"
)


@dataclass(frozen=True, slots=True)
class ReplayAsset:
    """Carry one frozen asset identity and its non-hydraulic operating limits."""

    structure_type: str
    structure_id: int
    constraints: dict[str, object]


@dataclass(frozen=True, slots=True)
class ReplayObservationFrame:
    """Carry one explicit synthetic observation frame in increasing time order."""

    time_seconds: float
    values: dict[tuple[str, int], float]


@dataclass(slots=True)
class _ActuatorState:
    """Keep replay-only actuator state without mutating static asset records."""

    gate_opening_m: float = 0.0
    running_units: int = 0
    last_change_time: float = -math.inf
    starts: int = 0
    runtime_seconds: float = 0.0
    stop_seconds: float = math.inf


def _advance_state(state: _ActuatorState, elapsed_seconds: float) -> None:
    """Advance pump duration counters between two explicit observation frames."""

    if state.running_units > 0:
        state.runtime_seconds += elapsed_seconds
        state.stop_seconds = 0.0
    else:
        state.stop_seconds += elapsed_seconds
        state.runtime_seconds = 0.0


def _initial_state(asset: ReplayAsset) -> _ActuatorState:
    """Create the explicit synthetic initial state frozen by evaluator v1."""

    return _ActuatorState(
        gate_opening_m=float(asset.constraints.get("initial_opening_m", 0.0)),
        running_units=int(asset.constraints.get("initial_running_units", 0)),
        stop_seconds=(
            math.inf
            if bool(asset.constraints.get("initial_stop_constraint_satisfied", True))
            else 0.0
        ),
    )


def _gate_value_in_metres(target: ControlTarget, asset: ReplayAsset) -> float:
    """Convert the selected Gate command to the actuator's metre state."""

    if target.command_type == "gate_opening_m":
        return target.target_value
    height = float(asset.constraints["height_m"])
    return target.target_value * height


def _gate_value_from_metres(
    opening_m: float, target: ControlTarget, asset: ReplayAsset
) -> float:
    """Return a resolved Gate value in the request command's original unit."""

    if target.command_type == "gate_opening_m":
        return opening_m
    return opening_m / float(asset.constraints["height_m"])


def _resolve_gate_target(
    target: ControlTarget,
    asset: ReplayAsset,
    state: _ActuatorState,
    *,
    time_seconds: float,
    elapsed_seconds: float,
) -> tuple[float, str, str | None]:
    """Resolve rate/hold limits while retaining requested and resolved values."""

    requested_m = _gate_value_in_metres(target, asset)
    previous_m = state.gate_opening_m
    if math.isclose(requested_m, previous_m, rel_tol=0.0, abs_tol=1.0e-12):
        return target.target_value, "selected", None
    minimum_hold = float(asset.constraints.get("minimum_hold_seconds", 0.0))
    if time_seconds - state.last_change_time < minimum_hold:
        return (
            _gate_value_from_metres(previous_m, target, asset),
            "rejected",
            "minimum_hold_rejected",
        )
    resolved_m = requested_m
    rate_limit = float(asset.constraints.get("opening_rate_limit_m_per_s", 0.0))
    maximum_delta = rate_limit * elapsed_seconds
    if time_seconds > 0 and rate_limit > 0 and abs(requested_m - previous_m) > maximum_delta:
        resolved_m = previous_m + math.copysign(maximum_delta, requested_m - previous_m)
        outcome = "limited"
        reason = "opening_rate_limited"
    else:
        outcome = "selected"
        reason = None
    if not math.isclose(resolved_m, previous_m, rel_tol=0.0, abs_tol=1.0e-12):
        state.gate_opening_m = resolved_m
        state.last_change_time = time_seconds
    return _gate_value_from_metres(resolved_m, target, asset), outcome, reason


def _resolve_pump_target(
    target: ControlTarget,
    asset: ReplayAsset,
    state: _ActuatorState,
    *,
    time_seconds: float,
) -> tuple[float, str, str | None]:
    """Resolve static start/stop constraints without claiming hydraulic flow."""

    if target.command_type == "pump_target_flow":
        return (
            target.target_value,
            "selected",
            "target_only_no_switching_or_hydraulic_semantics",
        )
    requested_units = (
        int(target.target_value)
        if target.command_type == "pump_unit_count"
        else (
            max(1, int(asset.constraints.get("minimum_running_units", 1)))
            if target.target_value > 0
            else 0
        )
    )
    starting = state.running_units == 0 and requested_units > 0
    stopping = state.running_units > 0 and requested_units == 0
    minimum_run = float(asset.constraints.get("minimum_run_seconds", 0.0))
    minimum_stop = float(asset.constraints.get("minimum_stop_seconds", 0.0))
    maximum_starts = int(asset.constraints.get("maximum_starts_per_replay", 0))
    reason: str | None = None
    if starting and state.stop_seconds < minimum_stop:
        reason = "minimum_stop_rejected"
    elif starting and state.starts >= maximum_starts:
        reason = "maximum_starts_rejected"
    elif stopping and state.runtime_seconds < minimum_run:
        reason = "minimum_run_rejected"
    if reason is not None:
        resolved_units = state.running_units
        resolved = float(resolved_units if target.command_type == "pump_unit_count" else resolved_units > 0)
        return resolved, "rejected", reason
    if requested_units != state.running_units:
        if starting:
            state.starts += 1
        state.running_units = requested_units
        state.last_change_time = time_seconds
        state.runtime_seconds = 0.0 if requested_units == 0 else state.runtime_seconds
        state.stop_seconds = 0.0 if requested_units > 0 else state.stop_seconds
    return target.target_value, "selected", None


def _target_record(
    target: ControlTarget,
    asset: ReplayAsset,
    state: _ActuatorState,
    *,
    time_seconds: float,
    elapsed_seconds: float,
) -> dict[str, object]:
    """Validate and resolve one selected target into an auditable replay record."""

    valid, reason = validate_target_against_asset(target, asset.constraints)
    if not valid:
        return {
            "structure_type": target.structure_type,
            "structure_id": target.structure_id,
            "command_type": target.command_type,
            "requested_value": target.target_value,
            "resolved_value": None,
            "priority": target.priority,
            "source_type": target.source_type,
            "source_id": target.source_id,
            "outcome": "rejected",
            "reason": reason,
        }
    if target.structure_type == "gate":
        resolved, outcome, reason = _resolve_gate_target(
            target,
            asset,
            state,
            time_seconds=time_seconds,
            elapsed_seconds=elapsed_seconds,
        )
    else:
        resolved, outcome, reason = _resolve_pump_target(
            target,
            asset,
            state,
            time_seconds=time_seconds,
        )
    return {
        "structure_type": target.structure_type,
        "structure_id": target.structure_id,
        "command_type": target.command_type,
        "requested_value": target.target_value,
        "resolved_value": resolved,
        "priority": target.priority,
        "source_type": target.source_type,
        "source_id": target.source_id,
        "outcome": outcome,
        "reason": reason,
    }


def replay_schedule(
    *,
    actions: tuple[ScheduledAction, ...],
    rules: tuple[ThresholdRule, ...],
    assets: tuple[ReplayAsset, ...],
    observations: tuple[ReplayObservationFrame, ...],
) -> dict[str, Any]:
    """Replay a frozen policy against explicit synthetic observations only."""

    if not observations or observations[0].time_seconds != 0:
        raise ValueError("synthetic observation replay must start at 0 seconds")
    if any(
        right.time_seconds <= left.time_seconds
        for left, right in zip(observations, observations[1:])
    ):
        raise ValueError("synthetic observation times must be strictly increasing")
    asset_map = {(item.structure_type, item.structure_id): item for item in assets}
    states = {key: _initial_state(asset) for key, asset in asset_map.items()}
    manual_policy = ManualSchedulePolicy(actions)
    rule_policy = ThresholdRulePolicy(rules)
    composite = CompositeControlPolicy((manual_policy, rule_policy))
    steps: list[dict[str, object]] = []
    previous_time = 0.0
    for frame in observations:
        elapsed = frame.time_seconds - previous_time
        for state in states.values():
            _advance_state(state, elapsed)
        observation = HydraulicObservation(
            elapsed_time=frame.time_seconds,
            values={(kind, object_id): value for (kind, object_id), value in frame.values.items()},
        )
        conflicts_before = composite.conflict_count
        try:
            targets = composite.targets_at(frame.time_seconds, observation)
        except KeyError as exc:
            raise ValueError(f"synthetic observation is incomplete: {exc}") from exc
        records: list[dict[str, object]] = []
        for target in targets:
            key = (target.structure_type, target.structure_id)
            asset = asset_map.get(key)
            if asset is None:
                raise ValueError(
                    f"frozen replay asset is missing: {target.structure_type}:{target.structure_id}"
                )
            records.append(
                _target_record(
                    target,
                    asset,
                    states[key],
                    time_seconds=frame.time_seconds,
                    elapsed_seconds=elapsed,
                )
            )
        steps.append(
            {
                "time_seconds": frame.time_seconds,
                "targets": records,
                "conflict_evaluations": composite.conflict_count - conflicts_before,
                "rule_events": rule_policy.consume_audit_events(),
            }
        )
        previous_time = frame.time_seconds
    return {
        "steps": steps,
        "conflict_evaluations": composite.conflict_count,
        "rule_trigger_count": rule_policy.trigger_count,
        "rule_recovery_count": rule_policy.recovery_count,
        "evaluator_id": SYNTHETIC_SCHEDULE_EVALUATOR_ID,
        "tie_break_policy": SYNTHETIC_TIE_BREAK_POLICY,
        "initial_state_basis": SYNTHETIC_INITIAL_STATE_BASIS,
    }
