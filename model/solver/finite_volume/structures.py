"""Minimal per-stage Gate and Pump mass-flow contracts for the MVP."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Mapping

from model.solver.finite_volume.flux import GRAVITY
from model.solver.finite_volume.pump_curve import PumpOperatingPointEvidence


_ONE_SHOT_STAGE_ABOVE = "one-shot-stage-above"
_ONE_SHOT_STAGE_ABOVE_BRACKETED = "one-shot-stage-above-bracketed-v1"


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

    @property
    def control_mode(self) -> str:
        """Return the frozen accepted-state discrete policy identity."""

        return _ONE_SHOT_STAGE_ABOVE

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
class BracketedOneShotStageThreshold:
    """Latch after a conservative right-end replay brackets one rising crossing."""

    threshold_water_level: float

    def __post_init__(self) -> None:
        """Reject an ambiguous or non-finite absolute water-level threshold."""

        object.__setattr__(
            self,
            "threshold_water_level",
            _finite_stage(self.threshold_water_level, "threshold_water_level"),
        )

    @property
    def control_mode(self) -> str:
        """Return the versioned conservative event-location policy identity."""

        return _ONE_SHOT_STAGE_ABOVE_BRACKETED

    def is_exceeded(self, observed_water_level: float) -> bool:
        """Return the same strict physical predicate as the discrete policy."""

        observed = _finite_stage(observed_water_level, "observed_water_level")
        return observed > self.threshold_water_level


ControlPolicy = OneShotStageThreshold | BracketedOneShotStageThreshold


@dataclass(frozen=True)
class ControlBracketEvidence:
    """Freeze one conservative accepted-state crossing bracket."""

    previous_time: float
    previous_observed_water_level: float
    bracket_end_time: float
    bracket_end_observed_water_level: float
    event_time_tolerance: float
    refinement_count: int
    monitored_section_id: int
    spatial_support: str = "bound-section-cell-center-v1"
    locator_policy: str = "bracketed-conservative-replay-right-end-v1"

    def __post_init__(self) -> None:
        """Require finite, ordered, bounded and self-identifying evidence."""

        previous_time = _finite_stage(self.previous_time, "bracket previous_time")
        end_time = _finite_stage(self.bracket_end_time, "bracket end_time")
        previous_level = _finite_stage(
            self.previous_observed_water_level,
            "bracket previous_observed_water_level",
        )
        end_level = _finite_stage(
            self.bracket_end_observed_water_level,
            "bracket end_observed_water_level",
        )
        tolerance = _finite_stage(
            self.event_time_tolerance,
            "bracket event_time_tolerance",
        )
        if previous_time < 0.0 or end_time <= previous_time:
            raise ValueError("control bracket times must be strictly increasing")
        if tolerance <= 0.0 or end_time - previous_time > tolerance + 1.0e-12:
            raise ValueError("control bracket width exceeds event_time_tolerance")
        if isinstance(self.refinement_count, bool) or self.refinement_count < 0:
            raise ValueError("control bracket refinement_count must be non-negative")
        if isinstance(self.monitored_section_id, bool) or self.monitored_section_id <= 0:
            raise ValueError("control bracket monitored_section_id must be positive")
        if self.spatial_support != "bound-section-cell-center-v1":
            raise ValueError("unsupported control bracket spatial_support")
        if self.locator_policy != "bracketed-conservative-replay-right-end-v1":
            raise ValueError("unsupported control bracket locator_policy")
        object.__setattr__(self, "previous_time", previous_time)
        object.__setattr__(self, "bracket_end_time", end_time)
        object.__setattr__(self, "previous_observed_water_level", previous_level)
        object.__setattr__(self, "bracket_end_observed_water_level", end_level)
        object.__setattr__(self, "event_time_tolerance", tolerance)


@dataclass(frozen=True)
class StructureControlEvent:
    """Record one committed structure action at an accepted-state time."""

    time: float
    structure_id: str
    structure_type: Literal["gate", "pump"]
    action: Literal["open", "start", "stop"]
    threshold_water_level: float
    observed_water_level: float
    bracket: ControlBracketEvidence | None = None
    reason: str | None = None

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
        if (self.structure_type, self.action) not in {
            ("gate", "open"),
            ("pump", "start"),
            ("pump", "stop"),
        }:
            raise ValueError("control event action does not match structure_type")
        if self.action in {"open", "start"} and observed <= threshold:
            raise ValueError("start/open event requires water level above threshold")
        if self.action == "stop" and observed > threshold:
            raise ValueError("stop event requires water level at or below threshold")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("control event reason must not be blank")
        if self.bracket is not None:
            if self.action == "stop":
                raise ValueError("stop event cannot use rising one-shot bracket evidence")
            if self.bracket.bracket_end_time != event_time:
                raise ValueError("control event time must equal its bracket end time")
            if self.bracket.bracket_end_observed_water_level != observed:
                raise ValueError("control event level must equal its bracket end level")
            if self.bracket.previous_observed_water_level > threshold:
                raise ValueError("control event bracket must start at or below threshold")
            if observed <= threshold:
                raise ValueError("control event bracket must end above threshold")
        object.__setattr__(self, "time", event_time)
        object.__setattr__(self, "threshold_water_level", threshold)
        object.__setattr__(self, "observed_water_level", observed)


def _accepted_control_state(
    *,
    previous_state: Mapping[str, object] | None,
    control: ControlPolicy,
    observed_water_level: float,
    actual_key: Literal["opening", "enabled"],
    active_value: float | bool,
    trigger_allowed: bool = True,
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
        if previous_state["control_mode"] != control.control_mode:
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

    triggered = was_triggered or (
        trigger_allowed and control.is_exceeded(observed_water_level)
    )
    actual = (
        active_value if triggered else (False if actual_key == "enabled" else 0.0)
    )
    return (
        {
            "control_mode": control.control_mode,
            "triggered": triggered,
            "threshold_water_level": control.threshold_water_level,
            actual_key: actual,
        },
        triggered and not was_triggered,
    )


def _stage_control_state(
    *,
    state: Mapping[str, object] | None,
    control: ControlPolicy,
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
    upstream_top_width: float | None = None
    downstream_top_width: float | None = None
    upstream_pressure_moment: float | None = None
    downstream_pressure_moment: float | None = None

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
        optional = (
            self.upstream_top_width,
            self.downstream_top_width,
            self.upstream_pressure_moment,
            self.downstream_pressure_moment,
        )
        if any(value is not None and not math.isfinite(value) for value in optional):
            raise ValueError("optional structure hydraulic properties must be finite")


@dataclass(frozen=True)
class CompletedGateInterfaceEvidence:
    """Expose one converged submerged-orifice energy/momentum closure.

    ``reaction_force_per_density`` uses the signed downstream-minus-upstream
    momentum-flux convention.  Multiplying by fluid density gives force.
    """

    evaluation_time: float
    upstream_stage: float
    downstream_stage: float
    upstream_area: float
    downstream_area: float
    upstream_top_width: float
    downstream_top_width: float
    upstream_pressure_moment: float
    downstream_pressure_moment: float
    actual_opening: float
    head_loss: float
    energy_residual: float
    iterations: int
    momentum_flux_left: float
    momentum_flux_right: float
    reaction_force_per_density: float
    regime: Literal[
        "closed_barrier_completed_interface",
        "submerged_orifice_completed_interface",
    ] = "submerged_orifice_completed_interface"

    def __post_init__(self) -> None:
        """Keep completed-interface evidence finite and self-consistent."""

        values = (
            self.evaluation_time,
            self.upstream_stage,
            self.downstream_stage,
            self.upstream_area,
            self.downstream_area,
            self.upstream_top_width,
            self.downstream_top_width,
            self.upstream_pressure_moment,
            self.downstream_pressure_moment,
            self.actual_opening,
            self.head_loss,
            self.energy_residual,
            self.momentum_flux_left,
            self.momentum_flux_right,
            self.reaction_force_per_density,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("completed Gate evidence must contain finite values")
        if self.evaluation_time < 0.0 or self.head_loss < 0.0:
            raise ValueError("completed Gate time/head loss must be non-negative")
        if self.actual_opening < 0.0:
            raise ValueError("completed Gate actual opening must be non-negative")
        if min(
            self.upstream_area,
            self.downstream_area,
            self.upstream_top_width,
            self.downstream_top_width,
        ) <= 0.0:
            raise ValueError("completed Gate hydraulic areas/widths must be positive")
        if min(
            self.upstream_pressure_moment,
            self.downstream_pressure_moment,
        ) < 0.0:
            raise ValueError("completed Gate pressure moments must be non-negative")
        if isinstance(self.iterations, bool) or self.iterations < 0:
            raise ValueError("completed Gate iterations must be non-negative")
        if self.regime == "closed_barrier_completed_interface":
            if self.actual_opening != 0.0 or self.iterations != 0:
                raise ValueError("closed Gate evidence requires zero opening/iterations")
        elif self.actual_opening <= 0.0 or self.iterations <= 0:
            raise ValueError("open Gate evidence requires positive opening/iterations")
        expected_reaction = self.momentum_flux_right - self.momentum_flux_left
        tolerance = max(1.0e-12, 8.0 * math.ulp(abs(expected_reaction)))
        if not math.isclose(
            self.reaction_force_per_density,
            expected_reaction,
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            raise ValueError("completed Gate reaction contradicts momentum fluxes")


@dataclass(frozen=True)
class StructureStageFlow:
    """Return a signed volume flow and one explicit momentum-closure policy."""

    structure_id: str
    structure_type: str
    flow: float
    state: Mapping[str, object] = field(default_factory=dict)
    momentum_closure: str = "mass_only_mvp_not_strongly_coupled"
    completed_interface: CompletedGateInterfaceEvidence | None = None
    pump_operating_point: PumpOperatingPointEvidence | None = None

    def __post_init__(self) -> None:
        """Keep invalid device outputs from entering the conservative update."""

        if not self.structure_id or not self.structure_type:
            raise ValueError("structure identity and type must not be empty")
        if not math.isfinite(self.flow):
            raise ValueError("structure flow must be finite")
        if self.completed_interface is not None and self.pump_operating_point is not None:
            raise ValueError("one structure flow cannot contain Gate and Pump evidence")
        if self.completed_interface is not None:
            if self.momentum_closure != "submerged_orifice_energy_momentum_v1":
                raise ValueError("completed Gate evidence requires its versioned closure")
            return
        if self.pump_operating_point is not None:
            if self.structure_type != "pump":
                raise ValueError("Pump operating-point evidence requires structure_type pump")
            if self.momentum_closure != "local-advective-external-sink-v1":
                raise ValueError("hydraulic Pump requires its local momentum sink policy")
            if not math.isclose(
                self.flow,
                self.pump_operating_point.total_flow_m3s,
                rel_tol=0.0,
                abs_tol=1.0e-12,
            ):
                raise ValueError("Pump stage flow contradicts its operating-point evidence")
            return
        if self.momentum_closure != "mass_only_mvp_not_strongly_coupled":
            raise ValueError("unknown structure momentum closure")


@dataclass(frozen=True)
class FixedGate:
    """Bind a fixed or accepted-state one-shot Gate to one internal face.

    Positive flow is from the lower face index cell to the higher one.  The
    legacy policy implements only ``Cd*A*sqrt(2*g*deltaH)`` mass flow.  The
    explicit completed-interface policy solves its restricted total-head
    equation and supplies distinct left/right momentum fluxes.  A bracketed
    completed Gate starts as an impermeable wall and uses ``opening`` only
    after its accepted right-end event; other controls retain legacy policy.
    """

    gate_id: str
    face_index: int
    opening: float
    width: float
    height: float
    discharge_coefficient: float = 0.62
    allow_reverse: bool = False
    control: ControlPolicy | None = None
    coupling_policy: Literal[
        "mass-only-orifice-v1",
        "submerged-orifice-energy-momentum-v1",
    ] = "mass-only-orifice-v1"
    sill_elevation: float | None = None
    equation_tolerance: float = 1.0e-10
    maximum_iterations: int = 80

    def __post_init__(self) -> None:
        """Validate fixed Gate geometry and its internal-face binding."""

        values = (
            self.opening,
            self.width,
            self.height,
            self.discharge_coefficient,
            self.equation_tolerance,
        )
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
            self.control,
            (OneShotStageThreshold, BracketedOneShotStageThreshold),
        ):
            raise ValueError("gate control has an unsupported policy")
        if self.control is not None and self.opening <= 0.0:
            raise ValueError("threshold-controlled gate target opening must be positive")
        if self.coupling_policy not in (
            "mass-only-orifice-v1",
            "submerged-orifice-energy-momentum-v1",
        ):
            raise ValueError("unsupported Gate coupling_policy")
        if self.equation_tolerance <= 0.0:
            raise ValueError("Gate equation_tolerance must be positive")
        if isinstance(self.maximum_iterations, bool) or self.maximum_iterations <= 0:
            raise ValueError("Gate maximum_iterations must be positive")
        if self.coupling_policy == "submerged-orifice-energy-momentum-v1":
            if self.control is not None and not isinstance(
                self.control, BracketedOneShotStageThreshold
            ):
                raise ValueError(
                    "completed-interface Gate supports only fixed or bracketed control"
                )
            if self.allow_reverse:
                raise ValueError("completed-interface Gate does not support reverse flow")
            if self.opening <= 0.0:
                raise ValueError("completed-interface Gate opening must be positive")
            if self.sill_elevation is None or not math.isfinite(self.sill_elevation):
                raise ValueError("completed-interface Gate requires a finite sill_elevation")
        elif self.sill_elevation is not None:
            raise ValueError("mass-only Gate must not declare sill_elevation")

    @property
    def uses_completed_interface(self) -> bool:
        """Return whether this Gate replaces both side-specific momentum fluxes."""

        return self.coupling_policy == "submerged-orifice-energy-momentum-v1"

    def _evaluate_completed_interface(
        self,
        *,
        context: StructureStageContext,
        state: Mapping[str, object],
        actual_opening: float,
    ) -> StructureStageFlow:
        """Solve the restricted submerged-orifice energy equation by bisection."""

        required = (
            context.upstream_top_width,
            context.downstream_top_width,
            context.upstream_pressure_moment,
            context.downstream_pressure_moment,
        )
        if any(value is None for value in required):
            raise ValueError("completed-interface Gate requires hydraulic face properties")
        upstream_width = float(context.upstream_top_width)
        downstream_width = float(context.downstream_top_width)
        upstream_moment = float(context.upstream_pressure_moment)
        downstream_moment = float(context.downstream_pressure_moment)
        if min(
            context.upstream_area,
            context.downstream_area,
            upstream_width,
            downstream_width,
        ) <= 0.0:
            raise ValueError("completed-interface Gate requires fully wet neighbours")
        head = context.upstream_stage - context.downstream_stage
        if head <= 0.0:
            raise ValueError("completed-interface Gate requires positive forward head")
        gate_top = float(self.sill_elevation) + actual_opening
        if min(context.upstream_stage, context.downstream_stage) <= gate_top:
            raise ValueError("completed-interface Gate requires a submerged opening")

        opening_area = self.width * actual_opening
        loss_factor = (
            1.0 / (self.discharge_coefficient * opening_area) ** 2
            - 1.0 / context.upstream_area**2
            + 1.0 / context.downstream_area**2
        )
        if not math.isfinite(loss_factor) or loss_factor <= 0.0:
            raise ValueError("completed-interface Gate energy equation has no positive root")

        def residual(flow: float) -> float:
            return head - flow * flow * loss_factor / (2.0 * GRAVITY)

        lower = 0.0
        upper = 1.25 * math.sqrt(2.0 * GRAVITY * head / loss_factor)
        if residual(upper) >= 0.0:
            raise ValueError("completed-interface Gate failed to bracket its root")
        flow = upper
        energy_residual = residual(flow)
        iterations = 0
        for iterations in range(1, self.maximum_iterations + 1):
            flow = 0.5 * (lower + upper)
            energy_residual = residual(flow)
            if abs(energy_residual) <= self.equation_tolerance:
                break
            if energy_residual > 0.0:
                lower = flow
            else:
                upper = flow
        else:
            raise ValueError("completed-interface Gate equation did not converge")

        upstream_celerity = math.sqrt(
            GRAVITY * context.upstream_area / upstream_width
        )
        downstream_celerity = math.sqrt(
            GRAVITY * context.downstream_area / downstream_width
        )
        upstream_froude = flow / context.upstream_area / upstream_celerity
        downstream_froude = flow / context.downstream_area / downstream_celerity
        if max(upstream_froude, downstream_froude) >= 1.0:
            raise ValueError("completed-interface Gate requires subcritical traces")

        head_loss = flow * flow / (
            2.0
            * GRAVITY
            * (self.discharge_coefficient * opening_area) ** 2
        )
        momentum_left = flow * flow / context.upstream_area + GRAVITY * upstream_moment
        momentum_right = (
            flow * flow / context.downstream_area + GRAVITY * downstream_moment
        )
        evidence = CompletedGateInterfaceEvidence(
            evaluation_time=context.time,
            upstream_stage=context.upstream_stage,
            downstream_stage=context.downstream_stage,
            upstream_area=context.upstream_area,
            downstream_area=context.downstream_area,
            upstream_top_width=upstream_width,
            downstream_top_width=downstream_width,
            upstream_pressure_moment=upstream_moment,
            downstream_pressure_moment=downstream_moment,
            actual_opening=actual_opening,
            head_loss=head_loss,
            energy_residual=energy_residual,
            iterations=iterations,
            momentum_flux_left=momentum_left,
            momentum_flux_right=momentum_right,
            reaction_force_per_density=momentum_right - momentum_left,
        )
        return StructureStageFlow(
            structure_id=self.gate_id,
            structure_type="gate",
            flow=flow,
            state=state,
            momentum_closure="submerged_orifice_energy_momentum_v1",
            completed_interface=evidence,
        )

    def _evaluate_closed_completed_interface(
        self,
        *,
        context: StructureStageContext,
        state: Mapping[str, object],
    ) -> StructureStageFlow:
        """Return an impermeable wall with distinct hydrostatic side momentum.

        The closed command has no orifice equation.  Its mass flux is zero,
        while each side receives its own ``g*I1`` momentum flux.  This keeps
        the event-location trial conservative and prevents the future opening
        command from being backfilled into the crossing interval.
        """

        required = (
            context.upstream_top_width,
            context.downstream_top_width,
            context.upstream_pressure_moment,
            context.downstream_pressure_moment,
        )
        if any(value is None for value in required):
            raise ValueError("closed completed Gate requires hydraulic face properties")
        upstream_width = float(context.upstream_top_width)
        downstream_width = float(context.downstream_top_width)
        upstream_moment = float(context.upstream_pressure_moment)
        downstream_moment = float(context.downstream_pressure_moment)
        if min(
            context.upstream_area,
            context.downstream_area,
            upstream_width,
            downstream_width,
        ) <= 0.0:
            raise ValueError("closed completed Gate requires fully wet neighbours")
        head = context.upstream_stage - context.downstream_stage
        if head < -1.0e-12:
            raise ValueError("closed completed Gate does not support reverse head")
        head_loss = max(head, 0.0)
        momentum_left = GRAVITY * upstream_moment
        momentum_right = GRAVITY * downstream_moment
        evidence = CompletedGateInterfaceEvidence(
            evaluation_time=context.time,
            upstream_stage=context.upstream_stage,
            downstream_stage=context.downstream_stage,
            upstream_area=context.upstream_area,
            downstream_area=context.downstream_area,
            upstream_top_width=upstream_width,
            downstream_top_width=downstream_width,
            upstream_pressure_moment=upstream_moment,
            downstream_pressure_moment=downstream_moment,
            actual_opening=0.0,
            head_loss=head_loss,
            energy_residual=0.0,
            iterations=0,
            momentum_flux_left=momentum_left,
            momentum_flux_right=momentum_right,
            reaction_force_per_density=momentum_right - momentum_left,
            regime="closed_barrier_completed_interface",
        )
        return StructureStageFlow(
            structure_id=self.gate_id,
            structure_type="gate",
            flow=0.0,
            state=state,
            momentum_closure="submerged_orifice_energy_momentum_v1",
            completed_interface=evidence,
        )

    def synchronize_accepted_state(
        self,
        *,
        time: float,
        observed_water_level: float,
        previous_state: Mapping[str, object] | None = None,
        bracket: ControlBracketEvidence | None = None,
    ) -> tuple[Mapping[str, object], StructureControlEvent | None]:
        """Purely derive the Gate latch at one accepted absolute water level."""

        accepted_time = _finite_stage(time, "accepted Gate state time")
        if accepted_time < 0.0:
            raise ValueError("accepted Gate state time must be non-negative")
        observed = _finite_stage(observed_water_level, "observed_water_level")
        if self.control is None:
            return {"opening": self.opening}, None
        if bracket is not None and not isinstance(
            self.control, BracketedOneShotStageThreshold
        ):
            raise ValueError("discrete Gate control cannot consume bracket evidence")
        state, newly_triggered = _accepted_control_state(
            previous_state=previous_state,
            control=self.control,
            observed_water_level=observed,
            actual_key="opening",
            active_value=self.opening,
            trigger_allowed=(
                bracket is not None
                if isinstance(self.control, BracketedOneShotStageThreshold)
                else True
            ),
        )
        event = (
            StructureControlEvent(
                time=accepted_time,
                structure_id=self.gate_id,
                structure_type="gate",
                action="open",
                threshold_water_level=self.control.threshold_water_level,
                observed_water_level=observed,
                bracket=bracket,
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

        if self.uses_completed_interface and float(actual_opening) == 0.0:
            return self._evaluate_closed_completed_interface(
                context=context,
                state=state,
            )
        if self.uses_completed_interface:
            return self._evaluate_completed_interface(
                context=context,
                state=state,
                actual_opening=float(actual_opening),
            )

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
    control: ControlPolicy | None = None

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
            self.control,
            (OneShotStageThreshold, BracketedOneShotStageThreshold),
        ):
            raise ValueError("pump control has an unsupported policy")
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
        bracket: ControlBracketEvidence | None = None,
    ) -> tuple[Mapping[str, object], StructureControlEvent | None]:
        """Purely derive the Pump latch at one accepted absolute water level."""

        accepted_time = _finite_stage(time, "accepted Pump state time")
        if accepted_time < 0.0:
            raise ValueError("accepted Pump state time must be non-negative")
        observed = _finite_stage(observed_water_level, "observed_water_level")
        if self.control is None:
            return {"enabled": self.enabled}, None
        if bracket is not None and not isinstance(
            self.control, BracketedOneShotStageThreshold
        ):
            raise ValueError("discrete Pump control cannot consume bracket evidence")
        state, newly_triggered = _accepted_control_state(
            previous_state=previous_state,
            control=self.control,
            observed_water_level=observed,
            actual_key="enabled",
            active_value=True,
            trigger_allowed=(
                bracket is not None
                if isinstance(self.control, BracketedOneShotStageThreshold)
                else True
            ),
        )
        event = (
            StructureControlEvent(
                time=accepted_time,
                structure_id=self.pump_id,
                structure_type="pump",
                action="start",
                threshold_water_level=self.control.threshold_water_level,
                observed_water_level=observed,
                bracket=bracket,
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
