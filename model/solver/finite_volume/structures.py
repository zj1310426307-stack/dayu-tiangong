"""Minimal per-stage Gate and Pump mass-flow contracts for the MVP."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Mapping

from model.solver.finite_volume.flux import GRAVITY


_ONE_SHOT_STAGE_ABOVE = "one-shot-stage-above"


def _finite_stage(value: float, label: str) -> float:
    """Return one finite stage value without accepting booleans as numbers."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


@dataclass(frozen=True)
class OneShotStageThreshold:
    """Pure strict-above trigger sampled only at accepted solver states.

    This value object owns no latch and performs no scheduling.  The branch
    orchestrator supplies an accepted absolute water level and separately
    commits the returned structure state.  Equality does not trigger because
    the public contract says water level must *exceed* the frozen threshold.
    """

    threshold_water_level: float

    def __post_init__(self) -> None:
        """Reject an ambiguous or non-finite absolute water-level threshold."""

        object.__setattr__(
            self,
            "threshold_water_level",
            _finite_stage(self.threshold_water_level, "threshold_water_level"),
        )

    def is_exceeded(self, observed_water_level: float) -> bool:
        """Return a side-effect-free strict comparison for one accepted state."""

        observed = _finite_stage(observed_water_level, "observed_water_level")
        return observed > self.threshold_water_level


@dataclass(frozen=True)
class StructureControlEvent:
    """Record one committed one-shot action at an accepted-state time."""

    time: float
    structure_id: str
    structure_type: Literal["gate", "pump"]
    action: Literal["open", "start"]
    threshold_water_level: float
    observed_water_level: float

    def __post_init__(self) -> None:
        """Keep event evidence finite, causal, and type/action consistent."""

        if not self.structure_id:
            raise ValueError("control event structure_id must not be empty")
        event_time = _finite_stage(self.time, "control event time")
        threshold = _finite_stage(
            self.threshold_water_level, "control event threshold_water_level"
        )
        observed = _finite_stage(
            self.observed_water_level, "control event observed_water_level"
        )
        if event_time < 0.0:
            raise ValueError("control event time must be non-negative")
        if observed <= threshold:
            raise ValueError("control event requires observed water level above threshold")
        if (self.structure_type, self.action) not in {
            ("gate", "open"),
            ("pump", "start"),
        }:
            raise ValueError("control event action does not match structure_type")
        object.__setattr__(self, "time", event_time)
        object.__setattr__(self, "threshold_water_level", threshold)
        object.__setattr__(self, "observed_water_level", observed)


def _accepted_control_state(
    *,
    previous_state: Mapping[str, object] | None,
    control: OneShotStageThreshold,
    observed_water_level: float,
    actual_key: Literal["opening", "enabled"],
    active_value: float | bool,
) -> tuple[dict[str, object], bool]:
    """Purely derive the next one-shot latch and actual device command."""

    expected_keys = {
        "control_mode",
        "triggered",
        "threshold_water_level",
        actual_key,
    }
    was_triggered = False
    if previous_state is not None:
        if not isinstance(previous_state, Mapping):
            raise ValueError("controlled structure state must be a mapping")
        if set(previous_state) != expected_keys:
            raise ValueError("controlled structure state has an unknown shape")
        if previous_state["control_mode"] != _ONE_SHOT_STAGE_ABOVE:
            raise ValueError("controlled structure state has an unknown control_mode")
        previous_threshold = _finite_stage(
            previous_state["threshold_water_level"],
            "controlled structure threshold_water_level",
        )
        if previous_threshold != control.threshold_water_level:
            raise ValueError("controlled structure threshold changed during a run")
        if not isinstance(previous_state["triggered"], bool):
            raise ValueError("controlled structure triggered flag must be boolean")
        was_triggered = previous_state["triggered"]
        previous_actual = previous_state[actual_key]
        if actual_key == "enabled" and not isinstance(previous_actual, bool):
            raise ValueError("controlled Pump enabled command must be boolean")
        if actual_key == "opening":
            _finite_stage(previous_actual, "controlled Gate opening command")
        expected_actual = (
            active_value
            if was_triggered
            else (False if actual_key == "enabled" else 0.0)
        )
        if previous_actual != expected_actual:
            raise ValueError("controlled structure actual command contradicts its latch")

    triggered = was_triggered or control.is_exceeded(observed_water_level)
    actual = (
        active_value if triggered else (False if actual_key == "enabled" else 0.0)
    )
    return (
        {
            "control_mode": _ONE_SHOT_STAGE_ABOVE,
            "triggered": triggered,
            "threshold_water_level": control.threshold_water_level,
            actual_key: actual,
        },
        triggered and not was_triggered,
    )


def _stage_control_state(
    *,
    state: Mapping[str, object] | None,
    control: OneShotStageThreshold,
    actual_key: Literal["opening", "enabled"],
    active_value: float | bool,
) -> dict[str, object]:
    """Read a previously committed latch without evaluating a new threshold."""

    # A missing value is the deterministic pre-trigger initial state.  The
    # solver normally synchronizes time zero first; this fallback keeps the
    # low-level stage evaluator pure and safe when called independently.
    observed = control.threshold_water_level
    normalized, _ = _accepted_control_state(
        previous_state=state,
        control=control,
        observed_water_level=observed,
        actual_key=actual_key,
        active_value=active_value,
    )
    return normalized


@dataclass(frozen=True)
class StructureStageContext:
    """Provide the current RK-stage heads and conservative neighbour values."""

    time: float
    dt: float
    upstream_stage: float
    downstream_stage: float
    upstream_area: float
    downstream_area: float
    upstream_discharge: float
    downstream_discharge: float

    def __post_init__(self) -> None:
        """Reject a non-finite stage context before device evaluation."""

        values = (
            self.time,
            self.dt,
            self.upstream_stage,
            self.downstream_stage,
            self.upstream_area,
            self.downstream_area,
            self.upstream_discharge,
            self.downstream_discharge,
        )
        if not all(math.isfinite(item) for item in values):
            raise ValueError("structure stage context must contain only finite values")
        if self.time < 0.0 or self.dt <= 0.0:
            raise ValueError("structure stage time must be non-negative and dt positive")
        if self.upstream_area < 0.0 or self.downstream_area < 0.0:
            raise ValueError("structure neighbour areas must be non-negative")


@dataclass(frozen=True)
class StructureStageFlow:
    """Return a signed volume flow and an auditable simplified closure label."""

    structure_id: str
    structure_type: str
    flow: float
    state: Mapping[str, object] = field(default_factory=dict)
    momentum_closure: str = "mass_only_mvp_not_strongly_coupled"

    def __post_init__(self) -> None:
        """Keep invalid device outputs from entering the conservative update."""

        if not self.structure_id or not self.structure_type:
            raise ValueError("structure identity and type must not be empty")
        if not math.isfinite(self.flow):
            raise ValueError("structure flow must be finite")


@dataclass(frozen=True)
class FixedGate:
    """Bind a fixed or accepted-state one-shot Gate to one internal face.

    Positive flow is from the lower face index cell to the higher one.  The
    formula implements only the task-book ``Cd*A*sqrt(2*g*deltaH)`` mass-flow
    relation; the orchestrator must retain an explicit diagnostic that a full
    momentum/energy closure is not yet implemented.  ``control=None`` retains
    the original fixed-opening behaviour.  A threshold-controlled Gate starts
    closed and uses ``opening`` as its latched target command.
    """

    gate_id: str
    face_index: int
    opening: float
    width: float
    height: float
    discharge_coefficient: float = 0.62
    allow_reverse: bool = False
    control: OneShotStageThreshold | None = None

    def __post_init__(self) -> None:
        """Validate fixed Gate geometry and its internal-face binding."""

        values = (self.opening, self.width, self.height, self.discharge_coefficient)
        if not self.gate_id:
            raise ValueError("gate_id must not be empty")
        if self.face_index < 0:
            raise ValueError("gate face_index must be non-negative")
        if not all(math.isfinite(item) for item in values):
            raise ValueError("gate parameters must be finite")
        if self.opening < 0.0 or self.width <= 0.0 or self.height <= 0.0:
            raise ValueError("gate opening must be non-negative and dimensions positive")
        if self.discharge_coefficient <= 0.0:
            raise ValueError("gate discharge coefficient must be positive")
        if not isinstance(self.allow_reverse, bool):
            raise ValueError("gate allow_reverse must be boolean")
        if self.control is not None and not isinstance(
            self.control, OneShotStageThreshold
        ):
            raise ValueError("gate control must be OneShotStageThreshold or None")
        if self.control is not None and self.opening <= 0.0:
            raise ValueError("threshold-controlled gate target opening must be positive")

    def synchronize_accepted_state(
        self,
        *,
        time: float,
        observed_water_level: float,
        previous_state: Mapping[str, object] | None = None,
    ) -> tuple[Mapping[str, object], StructureControlEvent | None]:
        """Purely derive the Gate latch at one accepted absolute water level."""

        accepted_time = _finite_stage(time, "accepted Gate state time")
        if accepted_time < 0.0:
            raise ValueError("accepted Gate state time must be non-negative")
        observed = _finite_stage(observed_water_level, "observed_water_level")
        if self.control is None:
            return {"opening": self.opening}, None
        state, newly_triggered = _accepted_control_state(
            previous_state=previous_state,
            control=self.control,
            observed_water_level=observed,
            actual_key="opening",
            active_value=self.opening,
        )
        event = (
            StructureControlEvent(
                time=accepted_time,
                structure_id=self.gate_id,
                structure_type="gate",
                action="open",
                threshold_water_level=self.control.threshold_water_level,
                observed_water_level=observed,
            )
            if newly_triggered
            else None
        )
        return state, event

    def evaluate_stage(
        self,
        context: StructureStageContext,
        control_state: Mapping[str, object] | None = None,
    ) -> StructureStageFlow:
        """Evaluate flow using only the command frozen before this RK stage."""

        state = (
            {"opening": self.opening}
            if self.control is None
            else _stage_control_state(
                state=control_state,
                control=self.control,
                actual_key="opening",
                active_value=self.opening,
            )
        )
        actual_opening = state["opening"]
        if isinstance(actual_opening, bool) or not isinstance(
            actual_opening, (int, float)
        ):
            raise ValueError("gate opening state must be numeric")

        head_difference = context.upstream_stage - context.downstream_stage
        direction = 1.0
        if head_difference < 0.0:
            if not self.allow_reverse:
                head_difference = 0.0
            else:
                direction = -1.0
                head_difference = abs(head_difference)
        opening_area = self.width * min(float(actual_opening), self.height)
        flow = (
            direction
            * self.discharge_coefficient
            * opening_area
            * math.sqrt(2.0 * GRAVITY * max(head_difference, 0.0))
        )
        return StructureStageFlow(
            structure_id=self.gate_id,
            structure_type="gate",
            flow=flow,
            state=state,
        )


@dataclass(frozen=True)
class OnOffPump:
    """Bind a fixed or accepted-state one-shot external Pump sink to one cell."""

    pump_id: str
    cell_index: int
    design_flow: float
    enabled: bool
    control: OneShotStageThreshold | None = None

    def __post_init__(self) -> None:
        """Validate the fixed pump binding without inventing a Q-H curve."""

        if not self.pump_id:
            raise ValueError("pump_id must not be empty")
        if self.cell_index < 0:
            raise ValueError("pump cell_index must be non-negative")
        if not math.isfinite(self.design_flow) or self.design_flow < 0.0:
            raise ValueError("pump design_flow must be finite and non-negative")
        if not isinstance(self.enabled, bool):
            raise ValueError("pump enabled state must be boolean")
        if self.control is not None and not isinstance(
            self.control, OneShotStageThreshold
        ):
            raise ValueError("pump control must be OneShotStageThreshold or None")
        if self.control is not None and self.enabled:
            raise ValueError("threshold-controlled pump must start disabled")
        if self.control is not None and self.design_flow <= 0.0:
            raise ValueError("threshold-controlled pump design_flow must be positive")

    def synchronize_accepted_state(
        self,
        *,
        time: float,
        observed_water_level: float,
        previous_state: Mapping[str, object] | None = None,
    ) -> tuple[Mapping[str, object], StructureControlEvent | None]:
        """Purely derive the Pump latch at one accepted absolute water level."""

        accepted_time = _finite_stage(time, "accepted Pump state time")
        if accepted_time < 0.0:
            raise ValueError("accepted Pump state time must be non-negative")
        observed = _finite_stage(observed_water_level, "observed_water_level")
        if self.control is None:
            return {"enabled": self.enabled}, None
        state, newly_triggered = _accepted_control_state(
            previous_state=previous_state,
            control=self.control,
            observed_water_level=observed,
            actual_key="enabled",
            active_value=True,
        )
        event = (
            StructureControlEvent(
                time=accepted_time,
                structure_id=self.pump_id,
                structure_type="pump",
                action="start",
                threshold_water_level=self.control.threshold_water_level,
                observed_water_level=observed,
            )
            if newly_triggered
            else None
        )
        return state, event

    def evaluate_stage(
        self,
        context: StructureStageContext,
        control_state: Mapping[str, object] | None = None,
    ) -> StructureStageFlow:
        """Return flow from the already committed command, without side effects."""

        del context
        state = (
            {"enabled": self.enabled}
            if self.control is None
            else _stage_control_state(
                state=control_state,
                control=self.control,
                actual_key="enabled",
                active_value=True,
            )
        )
        actual_enabled = state["enabled"]
        if not isinstance(actual_enabled, bool):
            raise ValueError("pump enabled state must be boolean")
        return StructureStageFlow(
            structure_id=self.pump_id,
            structure_type="pump",
            flow=self.design_flow if actual_enabled else 0.0,
            state=state,
        )
