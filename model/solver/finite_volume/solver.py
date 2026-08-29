"""Minimal single-branch orchestrator for the Dayu Saint-Venant MVP."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal, Mapping, Sequence

from model.core.callbacks import check_cancellation
from model.solver.finite_volume.boundary import BoundaryPair
from model.solver.finite_volume.diagnostics import NumericalStateError, require_quality
from model.solver.finite_volume.event_locator import detect_bracketed_crossings
from model.solver.finite_volume.flux import GRAVITY
from model.solver.finite_volume.geometry import pressure_moment
from model.solver.finite_volume.geometry_source import (
    MAX_ADJACENT_HYDRAULIC_RELATIVE_CHANGE,
    adjacent_hydraulic_relative_change,
)
from model.solver.finite_volume.friction import estimate_manning_time_step
from model.solver.finite_volume.integrator import StepResult, advance_with_retries
from model.solver.finite_volume.mesh import FiniteVolumeMesh
from model.solver.finite_volume.pump import HydraulicExternalPump
from model.solver.finite_volume.state import HydraulicState
from model.solver.finite_volume.runtime_envelope import (
    CapabilityRuntimeEnvelope,
    RuntimeEnvelopeObservation,
    require_runtime_envelope,
)
from model.solver.finite_volume.structures import (
    BracketedOneShotStageThreshold,
    ControlBracketEvidence,
    FixedGate,
    OneShotStageThreshold,
    OnOffPump,
    StructureControlEvent,
)

_TIME_TOLERANCE = 1.0e-9
_EQUILIBRIUM_RELATIVE_TOLERANCE = 1.0e-10
_EQUILIBRIUM_ABSOLUTE_TOLERANCE = 1.0e-12
_ENERGY_HEAD_ABSOLUTE_TOLERANCE_M = 1.0e-10
_MOVING_REFERENCE_MAXIMUM_FROUDE = 0.8
_MOVING_REFERENCE_DRY_DEPTH_FACTOR = 100.0
_MOVING_REFERENCE_MINIMUM_TRANSIT_FRACTION = 0.02
_MOVING_REFERENCE_MAXIMUM_DEPTH_L1_RELATIVE = 1.0e-4
_MOVING_REFERENCE_MAXIMUM_DISCHARGE_L1_RELATIVE = 1.0e-4
_MOVING_REFERENCE_MAXIMUM_ENERGY_LINF_M = 1.0e-4

NONPRISMATIC_LAKE_SCOPE = "lake-at-rest-v1"
NONPRISMATIC_MOVING_ENERGY_SCOPE = (
    "fully-wet-subcritical-frictionless-energy-reference-v1"
)
NONPRISMATIC_ENGINEERING_SCOPE = (
    "fully-wet-subcritical-manning-slope-engineering-v1"
)


@dataclass(frozen=True)
class SingleBranchConfig:
    """Freeze the MVP time, stability, wet/dry and output controls."""

    end_time: float
    maximum_dt: float
    output_interval: float
    cfl_number: float = 0.7
    dry_depth: float = 1.0e-3
    minimum_dt: float = 1.0e-6
    maximum_retries: int = 8
    maximum_steps: int = 1_000_000
    water_balance_tolerance: float = 0.01
    maximum_friction_number: float | None = None
    friction_predictor_safety_factor: float | None = None
    runtime_envelope: CapabilityRuntimeEnvelope | None = None
    scheme: Literal["hll", "rusanov"] = "hll"
    equilibrium_mode: Literal["standard", "uniform-manning-reference"] = "standard"
    geometry_source_mode: Literal[
        "hydrostatic-reconstruction-v1",
        "hydraulic-function-linear-face-v1",
    ] = "hydrostatic-reconstruction-v1"
    nonprismatic_scope: Literal[
        "lake-at-rest-v1",
        "fully-wet-subcritical-frictionless-energy-reference-v1",
        "fully-wet-subcritical-manning-slope-engineering-v1",
    ] = NONPRISMATIC_LAKE_SCOPE
    structure_event_policy: Literal[
        "accepted-state-discrete-v1",
        "bracketed-conservative-replay-right-end-v1",
    ] = "accepted-state-discrete-v1"
    event_time_tolerance: float = 1.0e-3
    maximum_event_refinements: int = 30
    structure_capability: Literal[
        "legacy-v1",
        "d1-single-branch-gate-pump-v1",
        "d3a-1-single-branch-gate-pump-manning-v1",
        "d3a-2-single-branch-gate-pump-manning-slope-v1",
        "d3a-3-single-branch-gate-pump-engineering-profile-v1",
    ] = "legacy-v1"

    def __post_init__(self) -> None:
        """Reject unsafe controls before any boundary or state evaluation."""

        positive = (self.end_time, self.maximum_dt, self.output_interval, self.minimum_dt)
        if not all(math.isfinite(item) and item > 0.0 for item in positive):
            raise ValueError("end/max/output/min time controls must be finite and positive")
        if not 0.0 < self.cfl_number <= 1.0:
            raise ValueError("cfl_number must lie in (0, 1]")
        if not math.isfinite(self.dry_depth) or self.dry_depth < 0.0:
            raise ValueError("dry_depth must be finite and non-negative")
        if self.maximum_retries < 0 or self.maximum_steps <= 0:
            raise ValueError("retry count must be non-negative and maximum_steps positive")
        if not 0.0 < self.water_balance_tolerance < 1.0:
            raise ValueError("water_balance_tolerance must lie in (0, 1)")
        if self.maximum_friction_number is not None and (
            not math.isfinite(self.maximum_friction_number)
            or self.maximum_friction_number <= 0.0
        ):
            raise ValueError("maximum_friction_number must be finite and positive")
        if self.friction_predictor_safety_factor is not None:
            if self.maximum_friction_number is None:
                raise ValueError(
                    "friction predictor requires maximum_friction_number"
                )
            if (
                not math.isfinite(self.friction_predictor_safety_factor)
                or not 0.0 < self.friction_predictor_safety_factor < 1.0
            ):
                raise ValueError("friction predictor safety factor must lie in (0, 1)")
        if self.equilibrium_mode not in ("standard", "uniform-manning-reference"):
            raise ValueError("unsupported finite-volume equilibrium_mode")
        if self.geometry_source_mode not in (
            "hydrostatic-reconstruction-v1",
            "hydraulic-function-linear-face-v1",
        ):
            raise ValueError("unsupported finite-volume geometry_source_mode")
        if self.nonprismatic_scope not in (
            NONPRISMATIC_LAKE_SCOPE,
            NONPRISMATIC_MOVING_ENERGY_SCOPE,
            NONPRISMATIC_ENGINEERING_SCOPE,
        ):
            raise ValueError("unsupported finite-volume nonprismatic_scope")
        if (
            self.nonprismatic_scope
            in {NONPRISMATIC_MOVING_ENERGY_SCOPE, NONPRISMATIC_ENGINEERING_SCOPE}
            and self.geometry_source_mode != "hydraulic-function-linear-face-v1"
        ):
            raise ValueError(
                "moving non-prismatic scope requires the hydraulic-function face source"
            )
        if self.structure_event_policy not in (
            "accepted-state-discrete-v1",
            "bracketed-conservative-replay-right-end-v1",
        ):
            raise ValueError("unsupported finite-volume structure_event_policy")
        if (
            not math.isfinite(self.event_time_tolerance)
            or self.event_time_tolerance <= 0.0
        ):
            raise ValueError("event_time_tolerance must be finite and positive")
        if (
            isinstance(self.maximum_event_refinements, bool)
            or self.maximum_event_refinements < 0
        ):
            raise ValueError("maximum_event_refinements must be non-negative")
        if self.structure_capability not in {
            "legacy-v1",
            "d1-single-branch-gate-pump-v1",
            "d3a-1-single-branch-gate-pump-manning-v1",
            "d3a-2-single-branch-gate-pump-manning-slope-v1",
            "d3a-3-single-branch-gate-pump-engineering-profile-v1",
        }:
            raise ValueError("unsupported finite-volume structure_capability")
        if self.structure_capability in {
            "d3a-1-single-branch-gate-pump-manning-v1",
            "d3a-2-single-branch-gate-pump-manning-slope-v1",
            "d3a-3-single-branch-gate-pump-engineering-profile-v1",
        } and self.maximum_friction_number != 0.1:
            raise ValueError(
                "D3A Manning capabilities require maximum_friction_number=0.1"
            )
        if self.runtime_envelope is not None:
            if self.structure_capability not in {
                "d3a-1-single-branch-gate-pump-manning-v1",
                "d3a-2-single-branch-gate-pump-manning-slope-v1",
                "d3a-3-single-branch-gate-pump-engineering-profile-v1",
            }:
                raise ValueError("runtime envelope is only enabled for D3A capabilities")
            expected_depth = max(self.dry_depth, 1.0e-9)
            if not math.isclose(
                self.runtime_envelope.minimum_water_depth_m,
                expected_depth,
                rel_tol=0.0,
                abs_tol=1.0e-15,
            ):
                raise ValueError(
                    "runtime envelope wet-depth threshold must match dry_depth"
                )


@dataclass(frozen=True)
class SingleBranchDiagnostics:
    """Report dynamic storage, signed boundaries, pump outflow and limitations."""

    initial_storage: float
    final_storage: float
    upstream_boundary_volume: float
    downstream_boundary_volume: float
    pump_outflow_volume: float
    pump_input_energy_kwh: float
    water_balance_residual: float
    relative_water_balance_error: float
    water_balance_status: Literal["pass", "fail"]
    maximum_cfl: float
    minimum_dt: float
    retry_count: int
    step_count: int
    cfl_reduction_count: int
    positivity_retry_count: int
    event_refinement_count: int
    gate_solver_retry_count: int
    pump_solver_retry_count: int
    maximum_friction_number: float
    friction_retry_count: int
    friction_predictor_reduction_count: int
    predicted_minimum_friction_dt: float | None
    minimum_water_depth_m: float | None
    minimum_discharge_m3s: float | None
    maximum_froude_number: float | None
    runtime_envelope_retry_count: int
    runtime_envelope_status: Literal["pass", "not_applicable"]
    minimum_dt_failure_count: int
    diagnostic_flags: tuple[str, ...]


@dataclass(frozen=True)
class SingleBranchResult:
    """Return output-aligned accepted states, step evidence and diagnostics."""

    states: tuple[HydraulicState, ...]
    steps: tuple[StepResult, ...]
    diagnostics: SingleBranchDiagnostics
    control_events: tuple[StructureControlEvent, ...] = ()


def storage(mesh: FiniteVolumeMesh, state: HydraulicState) -> float:
    """Return dynamic branch storage ``sum(A_i*dx_i)`` in cubic metres."""

    value = sum(area * cell.dx for area, cell in zip(state.area, mesh.cells))
    if not math.isfinite(value) or value < 0.0:
        raise NumericalStateError("branch storage must be finite and non-negative")
    return value


def _previous_structure_state(
    states: Mapping[str, object], structure_id: str
) -> Mapping[str, object] | None:
    """Return one previous accepted device state or reject a corrupt shape."""

    value = states.get(structure_id)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("accepted structure state must be a mapping")
    return value


def _synchronize_structure_controls(
    *,
    mesh: FiniteVolumeMesh,
    state: HydraulicState,
    gates: Sequence[FixedGate],
    pumps: Sequence[OnOffPump | HydraulicExternalPump],
    brackets: Mapping[tuple[str, str], ControlBracketEvidence] | None = None,
) -> tuple[HydraulicState, tuple[StructureControlEvent, ...]]:
    """Purely derive and atomically attach commands for one accepted state.

    Gate control observes the absolute water level in its upstream adjacent
    cell; Pump control observes the absolute water level in its bound cell.
    No RK stage or rejected retry calls this function, so one-shot events are
    committed once at the exact accepted-state time and apply to the next
    attempted interval.
    """

    if len({gate.gate_id for gate in gates}) != len(gates):
        raise ValueError("Gate identities must be unique")
    if len({pump.pump_id for pump in pumps}) != len(pumps):
        raise ValueError("Pump identities must be unique")

    bracket_by_key = {} if brackets is None else dict(brackets)
    gate_state = dict(state.gate_state)
    pump_state = dict(state.pump_state)
    events: list[StructureControlEvent] = []
    for gate in gates:
        if gate.face_index >= len(mesh.cells) - 1:
            raise ValueError(f"gate {gate.gate_id} is not bound to an internal face")
        observed = mesh.cells[gate.face_index].geometry.stage_from_area(
            state.area[gate.face_index]
        )
        next_state, event = gate.synchronize_accepted_state(
            time=state.time,
            observed_water_level=observed,
            previous_state=_previous_structure_state(gate_state, gate.gate_id),
            bracket=bracket_by_key.pop(("gate", gate.gate_id), None),
        )
        gate_state[gate.gate_id] = next_state
        if event is not None:
            events.append(event)
    for pump in pumps:
        if pump.cell_index >= len(mesh.cells):
            raise ValueError(f"pump {pump.pump_id} cell_index is outside the mesh")
        observed = mesh.cells[pump.cell_index].geometry.stage_from_area(
            state.area[pump.cell_index]
        )
        next_state, event = pump.synchronize_accepted_state(
            time=state.time,
            observed_water_level=observed,
            previous_state=_previous_structure_state(pump_state, pump.pump_id),
            bracket=bracket_by_key.pop(("pump", pump.pump_id), None),
        )
        pump_state[pump.pump_id] = next_state
        if event is not None:
            events.append(event)
    if bracket_by_key:
        raise ValueError("control bracket references an unknown or already-triggered device")
    return replace(state, gate_state=gate_state, pump_state=pump_state), tuple(events)


def _equilibrium_close(left: float, right: float) -> bool:
    """Compare two analytic-equilibrium quantities with a strict tolerance."""

    return math.isclose(
        left,
        right,
        rel_tol=_EQUILIBRIUM_RELATIVE_TOLERANCE,
        abs_tol=_EQUILIBRIUM_ABSOLUTE_TOLERANCE,
    )


def _absolute_stage_close(left: float, right: float) -> bool:
    """Compare absolute water levels without datum-scaled relative slack."""

    return math.isclose(
        left,
        right,
        rel_tol=0.0,
        abs_tol=_EQUILIBRIUM_ABSOLUTE_TOLERANCE,
    )


def _c1_reference_close(left: float, right: float) -> bool:
    """Compare a C1 reference scalar with no magnitude-relative slack."""

    tolerance = max(
        _EQUILIBRIUM_ABSOLUTE_TOLERANCE,
        8.0 * math.ulp(abs(left)),
        8.0 * math.ulp(abs(right)),
    )
    return math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance)


def _energy_head_close(left: float, right: float) -> bool:
    """Compare energy heads with fixed tolerance plus datum-scale ULP guard."""

    tolerance = max(
        _ENERGY_HEAD_ABSOLUTE_TOLERANCE_M,
        8.0 * math.ulp(abs(left)),
        8.0 * math.ulp(abs(right)),
    )
    return math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance)


def _cell_length_close(left: float, right: float) -> bool:
    """Compare cell lengths without scale-dependent engineering slack."""

    return _c1_reference_close(left, right)


def _require_constant(values: Sequence[float], label: str) -> float:
    """Return the common value or fail the explicit equilibrium contract."""

    if not values:
        raise ValueError(f"uniform-manning-reference requires non-empty {label}")
    reference = float(values[0])
    if any(not _equilibrium_close(float(value), reference) for value in values[1:]):
        raise ValueError(f"uniform-manning-reference requires constant {label}")
    return reference


def _require_scope_constant(
    values: Sequence[float],
    label: str,
    scope: str,
) -> float:
    """Return one constant value for an explicitly named reference scope."""

    if not values:
        raise ValueError(f"{scope} requires non-empty {label}")
    reference = float(values[0])
    if any(
        not _c1_reference_close(float(value), reference)
        for value in values[1:]
    ):
        raise ValueError(f"{scope} requires constant {label}")
    return reference


def _require_absolute_stage_constant(
    values: Sequence[float],
    label: str,
) -> float:
    """Return one absolute water level or reject datum-dependent near-equality."""

    if not values:
        raise ValueError(f"equilibrium policy requires non-empty {label}")
    reference = float(values[0])
    if any(
        not _absolute_stage_close(float(value), reference)
        for value in values[1:]
    ):
        raise ValueError(f"equilibrium policy requires constant {label}")
    return reference


def _relative_geometry_signature(cell: object) -> tuple[object, ...]:
    """Return a fail-closed signature for the two supported prismatic shapes."""

    geometry = getattr(cell, "geometry")
    geometry_type = getattr(geometry, "geometry_type", None)
    if geometry_type == "rectangular" and hasattr(geometry, "width"):
        return ("rectangular", float(geometry.width))
    if geometry_type == "tabulated" and hasattr(geometry, "points"):
        bed = float(getattr(cell, "bed_elevation"))
        return (
            "tabulated",
            tuple(
                (float(offset), float(elevation) - bed)
                for offset, elevation in geometry.points
            ),
        )
    raise ValueError(
        "uniform-manning-reference requires rectangular or tabulated geometry"
    )


def _same_relative_geometry(
    left: tuple[object, ...], right: tuple[object, ...]
) -> bool:
    """Compare normalized geometry without trusting absolute bed elevation."""

    if left[0] != right[0]:
        return False
    if left[0] == "rectangular":
        return _equilibrium_close(float(left[1]), float(right[1]))
    left_points = left[1]
    right_points = right[1]
    if not isinstance(left_points, tuple) or not isinstance(right_points, tuple):
        return False
    if len(left_points) != len(right_points):
        return False
    return all(
        _equilibrium_close(left_offset, right_offset)
        and _equilibrium_close(left_elevation, right_elevation)
        for (left_offset, left_elevation), (right_offset, right_elevation) in zip(
            left_points, right_points
        )
    )


def _validated_uniform_manning_reference(
    *,
    mesh: FiniteVolumeMesh,
    initial_state: HydraulicState,
    boundaries: BoundaryPair,
    config: SingleBranchConfig,
    gates: Sequence[FixedGate],
    pumps: Sequence[OnOffPump | HydraulicExternalPump],
) -> HydraulicState:
    """Validate and return an analytic uniform-Manning moving equilibrium.

    This explicit opt-in accepts only a subcritical, prismatic, single-slope
    reference with constant A/Q/depth/n and constant matching Q/H boundaries.
    It therefore cannot silently turn an arbitrary initial condition into a
    steady solution.
    """

    if gates or pumps:
        raise ValueError(
            "uniform-manning-reference does not support Gate or Pump structures"
        )
    if len(mesh.cells) < 2:
        raise ValueError("uniform-manning-reference requires at least two cells")

    area = _require_constant(initial_state.area, "initial area")
    discharge = _require_constant(initial_state.discharge, "initial discharge")
    depth = _require_constant(initial_state.water_depth, "initial water depth")
    manning_n = _require_constant(
        tuple(cell.manning_n for cell in mesh.cells), "Manning n"
    )
    if area <= 0.0 or discharge <= 0.0 or depth <= config.dry_depth or manning_n <= 0.0:
        raise ValueError(
            "uniform-manning-reference requires wet positive A/Q/depth/n"
        )

    reference_geometry = _relative_geometry_signature(mesh.cells[0])
    if any(
        not _same_relative_geometry(
            reference_geometry, _relative_geometry_signature(cell)
        )
        for cell in mesh.cells[1:]
    ):
        raise ValueError(
            "uniform-manning-reference requires identical relative prismatic geometry"
        )

    slopes = tuple(
        (left.bed_elevation - right.bed_elevation)
        / (0.5 * (left.dx + right.dx))
        for left, right in zip(mesh.cells, mesh.cells[1:])
    )
    centre_gaps = tuple(
        0.5 * (left.dx + right.dx)
        for left, right in zip(mesh.cells, mesh.cells[1:])
    )
    slope_absolute_tolerance = max(
        _EQUILIBRIUM_ABSOLUTE_TOLERANCE,
        8.0
        * max(math.ulp(abs(cell.bed_elevation)) for cell in mesh.cells)
        / min(centre_gaps),
    )
    bed_slope = slopes[0]
    if any(
        not math.isclose(
            slope,
            bed_slope,
            rel_tol=_EQUILIBRIUM_RELATIVE_TOLERANCE,
            abs_tol=slope_absolute_tolerance,
        )
        for slope in slopes[1:]
    ):
        raise ValueError(
            "uniform-manning-reference requires constant positive linear bed slope"
        )
    if bed_slope <= 0.0:
        raise ValueError(
            "uniform-manning-reference requires a positive downstream bed slope"
        )

    hydraulic_radii: list[float] = []
    for cell, cell_area, cell_depth, cell_discharge in zip(
        mesh.cells,
        initial_state.area,
        initial_state.water_depth,
        initial_state.discharge,
    ):
        stage = cell.geometry.stage_from_area(cell_area)
        if not _equilibrium_close(stage - cell.bed_elevation, cell_depth):
            raise ValueError(
                "uniform-manning-reference depth is inconsistent with section geometry"
            )
        radius = float(cell.geometry.hydraulic_radius(stage))
        top_width = float(cell.geometry.top_width(stage))
        if radius <= 0.0 or top_width <= 0.0:
            raise ValueError(
                "uniform-manning-reference requires positive hydraulic geometry"
            )
        celerity = math.sqrt(GRAVITY * cell_area / top_width)
        if abs(cell_discharge / cell_area) >= celerity:
            raise ValueError(
                "uniform-manning-reference currently requires subcritical flow"
            )
        hydraulic_radii.append(radius)
    radius = _require_constant(hydraulic_radii, "hydraulic radius")
    expected_slope = (
        manning_n
        * manning_n
        * discharge
        * abs(discharge)
        / (area * area * radius ** (4.0 / 3.0))
    )
    if not math.isclose(
        bed_slope,
        expected_slope,
        rel_tol=_EQUILIBRIUM_RELATIVE_TOLERANCE,
        abs_tol=slope_absolute_tolerance,
    ):
        raise ValueError(
            "uniform-manning-reference bed slope does not satisfy Manning equilibrium"
        )

    upstream_flow = _require_constant(
        boundaries.upstream.series.values, "upstream Q boundary"
    )
    downstream_stage = _require_absolute_stage_constant(
        boundaries.downstream.series.values, "downstream H boundary"
    )
    if not _equilibrium_close(upstream_flow, discharge):
        raise ValueError(
            "uniform-manning-reference upstream Q does not match initial discharge"
        )
    final_stage = mesh.cells[-1].geometry.stage_from_area(initial_state.area[-1])
    if not _absolute_stage_close(downstream_stage, final_stage):
        raise ValueError(
            "uniform-manning-reference downstream H does not match the final cell"
        )
    return initial_state


def _validate_nonprismatic_lake_at_rest_scope(
    *,
    mesh: FiniteVolumeMesh,
    initial_state: HydraulicState,
    boundaries: BoundaryPair,
    config: SingleBranchConfig,
    gates: Sequence[FixedGate],
    pumps: Sequence[OnOffPump | HydraulicExternalPump],
) -> None:
    """Limit the first non-prismatic path to its verified static-water scope.

    The hydraulic-function face path is an explicit first-order geometric
    quadrature.  B2 validates exact lake-at-rest preservation and a local
    perturbation response, but not general moving-water, wet/dry, or structure
    coupling.  The public branch orchestrator therefore rejects those broader
    states until a manufactured-solution convergence gate is frozen.
    """

    if gates or pumps:
        raise ValueError(
            "hydraulic-function-linear-face-v1 does not support structures"
        )
    if boundaries.boundary_closure != "subcritical-characteristic-v1":
        raise ValueError(
            "hydraulic-function-linear-face-v1 requires characteristic boundaries"
        )
    if config.equilibrium_mode != "standard":
        raise ValueError(
            "hydraulic-function-linear-face-v1 uses the standard equilibrium mode"
        )
    if any(
        abs(value) > _EQUILIBRIUM_ABSOLUTE_TOLERANCE
        for value in initial_state.discharge
    ):
        raise ValueError(
            "hydraulic-function-linear-face-v1 currently requires zero initial discharge"
        )
    stages = tuple(
        cell.geometry.stage_from_area(area)
        for cell, area in zip(mesh.cells, initial_state.area)
    )
    common_stage = _require_absolute_stage_constant(
        stages,
        "non-prismatic initial stage",
    )
    if any(
        stage - cell.bed_elevation <= config.dry_depth
        for cell, stage in zip(mesh.cells, stages)
    ):
        raise ValueError(
            "hydraulic-function-linear-face-v1 currently requires every cell fully wet"
        )
    upstream_flow = _require_constant(
        boundaries.upstream.series.values,
        "non-prismatic upstream Q boundary",
    )
    if abs(upstream_flow) > _EQUILIBRIUM_ABSOLUTE_TOLERANCE:
        raise ValueError(
            "hydraulic-function-linear-face-v1 currently requires zero upstream Q"
        )
    downstream_stage = _require_absolute_stage_constant(
        boundaries.downstream.series.values,
        "non-prismatic downstream H boundary",
    )
    if not _absolute_stage_close(downstream_stage, common_stage):
        raise ValueError(
            "hydraulic-function-linear-face-v1 downstream H must match initial stage"
        )


def _core_hydraulic_signature(cell: object, stage: float) -> tuple[float, ...]:
    """Evaluate the A/T/P/I1 identity consumed by the moving reference gate."""

    geometry = getattr(cell, "geometry")
    area = float(geometry.area(stage))
    top_width = float(geometry.top_width(stage))
    radius = float(geometry.hydraulic_radius(stage))
    if area <= 0.0 or top_width <= 0.0 or radius <= 0.0:
        raise ValueError(
            f"{NONPRISMATIC_MOVING_ENERGY_SCOPE} requires positive hydraulic geometry"
        )
    perimeter = area / radius
    moment = pressure_moment(geometry, stage)
    return area, top_width, perimeter, moment


def _validate_nonprismatic_moving_energy_scope(
    *,
    mesh: FiniteVolumeMesh,
    initial_state: HydraulicState,
    boundaries: BoundaryPair,
    config: SingleBranchConfig,
    gates: Sequence[FixedGate],
    pumps: Sequence[OnOffPump | HydraulicExternalPump],
) -> None:
    """Validate the frozen fully wet, frictionless Bernoulli reference class."""

    scope = NONPRISMATIC_MOVING_ENERGY_SCOPE
    if gates or pumps:
        raise ValueError(f"{scope} does not support structures")
    if boundaries.boundary_closure != "subcritical-characteristic-v1":
        raise ValueError(f"{scope} requires characteristic boundaries")
    if config.equilibrium_mode != "standard":
        raise ValueError(f"{scope} uses the standard equilibrium mode")
    if len(mesh.cells) < 3:
        raise ValueError(f"{scope} requires at least three cells")

    reference_dx = mesh.cells[0].dx
    if any(
        not _cell_length_close(cell.dx, reference_dx)
        for cell in mesh.cells[1:]
    ):
        raise ValueError(f"{scope} requires one uniform cell-centre grid")
    beds = tuple(cell.bed_elevation for cell in mesh.cells)
    bed_tolerance = max(
        _EQUILIBRIUM_ABSOLUTE_TOLERANCE,
        8.0 * max(math.ulp(abs(bed)) for bed in beds),
    )
    if any(
        not math.isclose(
            bed,
            beds[0],
            rel_tol=0.0,
            abs_tol=bed_tolerance,
        )
        for bed in beds[1:]
    ):
        raise ValueError(f"{scope} requires one flat bed elevation")
    if any(cell.manning_n != 0.0 for cell in mesh.cells):
        raise ValueError(f"{scope} requires Manning n=0 in every cell")

    discharge = _require_scope_constant(
        initial_state.discharge,
        "initial discharge",
        scope,
    )
    if discharge <= 0.0:
        raise ValueError(f"{scope} requires positive downstream discharge")
    minimum_wet_depth = max(
        _MOVING_REFERENCE_DRY_DEPTH_FACTOR * config.dry_depth,
        1.0e-6,
    )
    if any(depth <= minimum_wet_depth for depth in initial_state.water_depth):
        raise ValueError(
            f"{scope} requires depth greater than the frozen wet margin"
        )

    stages: list[float] = []
    celerities: list[float] = []
    energy_heads: list[float] = []
    for cell, area in zip(mesh.cells, initial_state.area):
        stage = cell.geometry.stage_from_area(area)
        top_width = float(cell.geometry.top_width(stage))
        if area <= 0.0 or top_width <= 0.0:
            raise ValueError(f"{scope} requires positive hydraulic geometry")
        celerity = math.sqrt(GRAVITY * area / top_width)
        froude = abs(discharge / area) / celerity
        if not math.isfinite(froude) or froude > _MOVING_REFERENCE_MAXIMUM_FROUDE:
            raise ValueError(f"{scope} requires Froude number <= 0.8")
        stages.append(stage)
        celerities.append(celerity)
        energy_heads.append(
            stage + discharge * discharge / (2.0 * GRAVITY * area * area)
        )
    reference_energy = energy_heads[0]
    if any(
        not _energy_head_close(energy, reference_energy)
        for energy in energy_heads[1:]
    ):
        raise ValueError(f"{scope} requires one constant total energy head")
    comparison_stage = min(stages)
    signatures = tuple(
        _core_hydraulic_signature(cell, comparison_stage)
        for cell in mesh.cells
    )
    if all(
        all(
            _equilibrium_close(left, right)
            for left, right in zip(signatures[0], signature)
        )
        for signature in signatures[1:]
    ):
        raise ValueError(
            f"{scope} requires at least two distinct hydraulic Profile signatures"
        )
    observation_fraction = (
        (config.end_time - initial_state.time)
        * max(celerities)
        / sum(cell.dx for cell in mesh.cells)
    )
    if observation_fraction < _MOVING_REFERENCE_MINIMUM_TRANSIT_FRACTION:
        raise ValueError(
            f"{scope} requires a dimensionless observation fraction >= 0.02"
        )

    upstream_flow = _require_scope_constant(
        boundaries.upstream.series.values,
        "upstream Q boundary",
        scope,
    )
    if not _c1_reference_close(upstream_flow, discharge):
        raise ValueError(f"{scope} upstream Q must match initial discharge")
    downstream_stage = _require_absolute_stage_constant(
        boundaries.downstream.series.values,
        "downstream H boundary",
    )
    if not _absolute_stage_close(downstream_stage, stages[-1]):
        raise ValueError(f"{scope} downstream H must match the final cell")


def _validate_nonprismatic_engineering_scope(
    *,
    mesh: FiniteVolumeMesh,
    initial_state: HydraulicState,
    boundaries: BoundaryPair,
    config: SingleBranchConfig,
    gates: Sequence[FixedGate],
    pumps: Sequence[OnOffPump | HydraulicExternalPump],
) -> None:
    """Guard the D3A-3 gradually varying engineering validation envelope."""

    scope = NONPRISMATIC_ENGINEERING_SCOPE
    if gates or pumps:
        if config.structure_capability != (
            "d3a-3-single-branch-gate-pump-engineering-profile-v1"
        ):
            raise ValueError(f"{scope} structures require the D3A-3 capability")
        if len(gates) != 1 or len(pumps) != 1:
            raise ValueError(f"{scope} requires exactly one Gate and one Pump")
    if boundaries.boundary_closure != "subcritical-characteristic-v1":
        raise ValueError(f"{scope} requires characteristic boundaries")
    if config.equilibrium_mode != "standard":
        raise ValueError(f"{scope} uses the standard equilibrium mode")
    if len(mesh.cells) < 3:
        raise ValueError(f"{scope} requires at least three cells")
    if any(not 0.0 < cell.manning_n <= 0.10 for cell in mesh.cells):
        raise ValueError(f"{scope} requires effective Manning n in (0, 0.10]")

    beds = tuple(cell.bed_elevation for cell in mesh.cells)
    if any(right >= left for left, right in zip(beds, beds[1:])):
        raise ValueError(f"{scope} requires a strictly descending explicit bed")

    local_shapes: list[tuple[tuple[float, float], ...]] = []
    for cell in mesh.cells:
        points = getattr(cell.geometry, "points", None)
        if not isinstance(points, tuple) or len(points) < 3:
            raise ValueError(f"{scope} requires legal tabulated Profile geometry")
        local_shapes.append(
            tuple(
                (
                    round(float(offset), 12),
                    round(float(elevation) - cell.bed_elevation, 12),
                )
                for offset, elevation in points
            )
        )
    if len(set(local_shapes)) < 2:
        raise ValueError(f"{scope} requires non-identical local Profile shapes")
    changes = tuple(
        adjacent_hydraulic_relative_change(left.geometry, right.geometry)
        for left, right in zip(mesh.cells, mesh.cells[1:])
    )
    if any(change > MAX_ADJACENT_HYDRAULIC_RELATIVE_CHANGE for change in changes):
        maximum = max(changes)
        raise ValueError(
            f"{scope} adjacent Profile change {maximum:.6g} exceeds "
            f"{MAX_ADJACENT_HYDRAULIC_RELATIVE_CHANGE:.6g}"
        )

    wet_margin = max(config.dry_depth, 1.0e-9)
    for cell, area, discharge in zip(
        mesh.cells,
        initial_state.area,
        initial_state.discharge,
    ):
        stage = cell.geometry.stage_from_area(area)
        if stage - cell.bed_elevation <= wet_margin:
            raise ValueError(f"{scope} requires every initial cell fully wet")
        if discharge < 0.0:
            raise ValueError(f"{scope} prohibits reverse initial discharge")
        top_width = float(cell.geometry.top_width(stage))
        if area <= 0.0 or top_width <= 0.0:
            raise ValueError(f"{scope} requires positive hydraulic geometry")
        celerity = math.sqrt(GRAVITY * area / top_width)
        froude = abs(discharge / area) / celerity
        if not math.isfinite(froude) or froude > _MOVING_REFERENCE_MAXIMUM_FROUDE:
            raise ValueError(f"{scope} requires initial Froude number <= 0.8")

    if any(value <= 0.0 for value in boundaries.upstream.series.values):
        raise ValueError(f"{scope} requires a strictly positive inflow hydrograph")
    final_stage = mesh.cells[-1].geometry.stage_from_area(initial_state.area[-1])
    downstream_values = boundaries.downstream.series.values
    if any(
        value - mesh.cells[-1].bed_elevation <= wet_margin
        or value > final_stage
        for value in downstream_values
    ):
        raise ValueError(f"{scope} downstream process must stay wet and non-rising")


def _validate_moving_reference_preservation(
    *,
    mesh: FiniteVolumeMesh,
    initial_state: HydraulicState,
    steps: Sequence[StepResult],
) -> None:
    """Reject a reference run whose accepted states drift beyond frozen gates."""

    if not steps:
        raise NumericalStateError("moving reference quality gate requires accepted steps")
    initial_stages = tuple(
        cell.geometry.stage_from_area(area)
        for cell, area in zip(mesh.cells, initial_state.area)
    )
    depth_scale = sum(
        cell.dx * depth for cell, depth in zip(mesh.cells, initial_state.water_depth)
    )
    discharge_scale = sum(
        cell.dx * abs(discharge)
        for cell, discharge in zip(mesh.cells, initial_state.discharge)
    )
    if depth_scale <= 0.0 or discharge_scale <= 0.0:
        raise NumericalStateError("moving reference quality scales must be positive")
    reference_energies = tuple(
        stage + discharge * discharge / (2.0 * GRAVITY * area * area)
        for stage, discharge, area in zip(
            initial_stages,
            initial_state.discharge,
            initial_state.area,
        )
    )
    maximum_depth_l1 = 0.0
    maximum_discharge_l1 = 0.0
    maximum_energy_linf = 0.0
    for step in steps:
        state = step.state
        stages = tuple(
            cell.geometry.stage_from_area(area)
            for cell, area in zip(mesh.cells, state.area)
        )
        maximum_depth_l1 = max(
            maximum_depth_l1,
            sum(
                cell.dx * abs(stage - reference)
                for cell, stage, reference in zip(
                    mesh.cells,
                    stages,
                    initial_stages,
                )
            )
            / depth_scale,
        )
        maximum_discharge_l1 = max(
            maximum_discharge_l1,
            sum(
                cell.dx * abs(discharge - reference)
                for cell, discharge, reference in zip(
                    mesh.cells,
                    state.discharge,
                    initial_state.discharge,
                )
            )
            / discharge_scale,
        )
        maximum_energy_linf = max(
            maximum_energy_linf,
            max(
                abs(
                    stage
                    + discharge * discharge / (2.0 * GRAVITY * area * area)
                    - reference
                )
                for stage, discharge, area, reference in zip(
                    stages,
                    state.discharge,
                    state.area,
                    reference_energies,
                )
            ),
        )
    if maximum_depth_l1 > _MOVING_REFERENCE_MAXIMUM_DEPTH_L1_RELATIVE:
        raise NumericalStateError("moving reference depth L1 quality gate failed")
    if (
        maximum_discharge_l1
        > _MOVING_REFERENCE_MAXIMUM_DISCHARGE_L1_RELATIVE
    ):
        raise NumericalStateError("moving reference discharge L1 quality gate failed")
    if maximum_energy_linf > _MOVING_REFERENCE_MAXIMUM_ENERGY_LINF_M:
        raise NumericalStateError("moving reference energy Linf quality gate failed")


def _validate_structure_event_scope(
    *,
    mesh: FiniteVolumeMesh,
    initial_state: HydraulicState,
    config: SingleBranchConfig,
    gates: Sequence[FixedGate],
    pumps: Sequence[OnOffPump | HydraulicExternalPump],
) -> None:
    """Bind discrete and bracketed controls to distinct, fail-closed policies."""

    controls = tuple(
        structure.control
        for structure in (*gates, *pumps)
        if structure.control is not None
    )
    bracketed = tuple(
        control
        for control in controls
        if isinstance(control, BracketedOneShotStageThreshold)
    )
    discrete = tuple(
        control for control in controls if isinstance(control, OneShotStageThreshold)
    )
    if bracketed:
        if config.structure_event_policy != (
            "bracketed-conservative-replay-right-end-v1"
        ):
            raise ValueError("bracketed controls require the bracketed event policy")
        if discrete:
            raise ValueError("discrete and bracketed controls cannot be mixed")
        if config.event_time_tolerance < config.minimum_dt:
            raise ValueError("event_time_tolerance must not be less than minimum_dt")
        for gate in gates:
            if not isinstance(gate.control, BracketedOneShotStageThreshold):
                continue
            observed = mesh.cells[gate.face_index].geometry.stage_from_area(
                initial_state.area[gate.face_index]
            )
            if observed >= gate.control.threshold_water_level:
                raise ValueError("bracketed Gate initial stage must be below threshold")
        for pump in pumps:
            if not isinstance(pump.control, BracketedOneShotStageThreshold):
                continue
            observed = mesh.cells[pump.cell_index].geometry.stage_from_area(
                initial_state.area[pump.cell_index]
            )
            if observed >= pump.control.threshold_water_level:
                raise ValueError("bracketed Pump initial stage must be below threshold")
        return
    if config.structure_event_policy != "accepted-state-discrete-v1":
        raise ValueError("bracketed event policy requires a bracketed control")


def _validate_completed_gate_scope(
    *,
    mesh: FiniteVolumeMesh,
    initial_state: HydraulicState,
    boundaries: BoundaryPair,
    config: SingleBranchConfig,
    gates: Sequence[FixedGate],
    pumps: Sequence[OnOffPump | HydraulicExternalPump],
) -> None:
    """Keep the completed-interface Gate inside its verified C2b subset."""

    d1_scope = config.structure_capability == "d1-single-branch-gate-pump-v1"
    d3a_1_scope = config.structure_capability == (
        "d3a-1-single-branch-gate-pump-manning-v1"
    )
    d3a_2_scope = config.structure_capability == (
        "d3a-2-single-branch-gate-pump-manning-slope-v1"
    )
    d3a_3_scope = config.structure_capability == (
        "d3a-3-single-branch-gate-pump-engineering-profile-v1"
    )
    gate_pump_scope = d1_scope or d3a_1_scope or d3a_2_scope or d3a_3_scope
    completed = tuple(gate for gate in gates if gate.uses_completed_interface)
    if not completed:
        if gate_pump_scope:
            raise ValueError("Gate/Pump capability requires one completed-interface Gate")
        return
    if len(gates) != 1 or len(completed) != 1:
        raise ValueError("completed-interface scope requires exactly one Gate")
    if gate_pump_scope:
        if len(pumps) != 1 or not isinstance(pumps[0], HydraulicExternalPump):
            raise ValueError(
                "Gate/Pump capability requires exactly one hydraulic external Pump"
            )
    elif pumps:
        raise ValueError("completed-interface scope requires exactly one Gate and no Pump")
    gate = completed[0]
    if gate.control is not None and not isinstance(
        gate.control, BracketedOneShotStageThreshold
    ):
        raise ValueError(
            "completed-interface scope supports only fixed or bracketed Gate control"
        )
    if gate.control is not None and config.structure_event_policy != (
        "bracketed-conservative-replay-right-end-v1"
    ):
        raise ValueError(
            "controlled completed-interface Gate requires bracketed replay"
        )
    if config.equilibrium_mode != "standard":
        raise ValueError("completed-interface scope requires standard equilibrium")
    expected_geometry_source = (
        "hydraulic-function-linear-face-v1"
        if d3a_3_scope
        else "hydrostatic-reconstruction-v1"
    )
    if config.geometry_source_mode != expected_geometry_source:
        raise ValueError(
            f"completed-interface scope requires {expected_geometry_source}"
        )
    if boundaries.boundary_closure != "subcritical-characteristic-v1":
        raise ValueError("completed-interface scope requires characteristic boundaries")
    reference = mesh.cells[0]
    if d3a_2_scope:
        reference_points = getattr(reference.geometry, "points", None)
        if not isinstance(reference_points, tuple):
            raise ValueError("D3A-2 requires tabulated Profile geometry")
        reference_shape = tuple(
            (float(offset), float(elevation) - reference.bed_elevation)
            for offset, elevation in reference_points
        )
        for cell in mesh.cells[1:]:
            points = getattr(cell.geometry, "points", None)
            shape = (
                tuple(
                    (float(offset), float(elevation) - cell.bed_elevation)
                    for offset, elevation in points
                )
                if isinstance(points, tuple)
                else ()
            )
            if len(shape) != len(reference_shape) or any(
                not math.isclose(left_x, right_x, rel_tol=1.0e-10, abs_tol=1.0e-12)
                or not math.isclose(left_z, right_z, rel_tol=1.0e-10, abs_tol=1.0e-12)
                for (left_x, left_z), (right_x, right_z) in zip(
                    reference_shape, shape
                )
            ):
                raise ValueError("D3A-2 requires one identical local Profile shape")
        beds = tuple(cell.bed_elevation for cell in mesh.cells)
        if any(right >= left for left, right in zip(beds, beds[1:])):
            raise ValueError("D3A-2 requires a strictly descending bed")
    elif d3a_3_scope:
        if any(
            not isinstance(getattr(cell.geometry, "points", None), tuple)
            for cell in mesh.cells
        ):
            raise ValueError("D3A-3 requires tabulated Profile geometry")
        beds = tuple(cell.bed_elevation for cell in mesh.cells)
        if any(right >= left for left, right in zip(beds, beds[1:])):
            raise ValueError("D3A-3 requires a strictly descending explicit bed")
        if any(
            adjacent_hydraulic_relative_change(left.geometry, right.geometry)
            > MAX_ADJACENT_HYDRAULIC_RELATIVE_CHANGE
            for left, right in zip(mesh.cells, mesh.cells[1:])
        ):
            raise ValueError("D3A-3 requires gradually varying adjacent Profiles")
    else:
        if any(cell.geometry != reference.geometry for cell in mesh.cells[1:]):
            raise ValueError("completed-interface scope requires one prismatic section")
        if any(
            not math.isclose(
                cell.bed_elevation,
                reference.bed_elevation,
                rel_tol=0.0,
                abs_tol=1.0e-12,
            )
            for cell in mesh.cells[1:]
        ):
            raise ValueError("completed-interface scope requires a flat bed")
    if d3a_1_scope or d3a_2_scope or d3a_3_scope:
        if any(cell.manning_n <= 0.0 for cell in mesh.cells):
            raise ValueError("D3A completed-interface scope requires positive Manning n")
    elif any(cell.manning_n != 0.0 for cell in mesh.cells):
        raise ValueError("completed-interface scope requires zero Manning friction")
    if any(
        cell.geometry.stage_from_area(area) - cell.bed_elevation
        <= max(config.dry_depth, 1.0e-9)
        for cell, area in zip(mesh.cells, initial_state.area)
    ):
        raise ValueError("completed-interface scope requires a fully wet initial state")
    if gate.face_index >= len(mesh.cells) - 1:
        raise ValueError("completed-interface Gate must bind an internal face")
    if gate_pump_scope:
        pump = pumps[0]
        assert isinstance(pump, HydraulicExternalPump)
        if pump.cell_index in {gate.face_index, gate.face_index + 1}:
            raise ValueError("Gate/Pump placements must not overlap")
        if pump.initial_status != "off":
            raise ValueError("hydraulic Pump must start OFF")
        pump.outlet_stage.validate_coverage(initial_state.time, config.end_time)
        source_stage = mesh.cells[pump.cell_index].geometry.stage_from_area(
            initial_state.area[pump.cell_index]
        )
        if (
            source_stage - pump.source_bed_elevation_m
            <= pump.minimum_source_depth_m
        ):
            raise ValueError("hydraulic Pump source cell must start fully wet")
    if gate.control is not None:
        left = mesh.cells[gate.face_index].geometry.stage_from_area(
            initial_state.area[gate.face_index]
        )
        right = mesh.cells[gate.face_index + 1].geometry.stage_from_area(
            initial_state.area[gate.face_index + 1]
        )
        if (d3a_2_scope or d3a_3_scope) and left <= right:
            raise ValueError("D3A sloping-bed Gate requires positive initial head")
        if not (d3a_2_scope or d3a_3_scope) and not math.isclose(
            left, right, rel_tol=0.0, abs_tol=1.0e-12
        ):
            raise ValueError(
                "controlled completed-interface Gate requires an initially level face"
            )
        if any(abs(value) > 1.0e-12 for value in initial_state.discharge):
            raise ValueError(
                "controlled completed-interface Gate requires zero initial discharge"
            )
        upstream_values = boundaries.upstream.series.values
        if gate_pump_scope:
            if any(value <= 0.0 for value in upstream_values):
                raise ValueError(
                    "Gate/Pump capability requires a positive inflow hydrograph"
                )
        else:
            upstream_reference = upstream_values[0]
            if upstream_reference <= 0.0 or any(
                not math.isclose(
                    value,
                    upstream_reference,
                    rel_tol=0.0,
                    abs_tol=max(
                        1.0e-12,
                        8.0 * math.ulp(abs(value)),
                        8.0 * math.ulp(abs(upstream_reference)),
                    ),
                )
                for value in upstream_values[1:]
            ):
                raise ValueError(
                    "controlled completed-interface Gate requires positive constant inflow"
                )
        final_stage = mesh.cells[-1].geometry.stage_from_area(
            initial_state.area[-1]
        )
        if gate_pump_scope:
            if any(
                value > final_stage
                or value - mesh.cells[-1].bed_elevation <= config.dry_depth
                for value in boundaries.downstream.series.values
            ):
                raise ValueError(
                    "Gate/Pump downstream stage process must stay wet and not exceed initial"
                )
        elif any(
            not math.isclose(
                value,
                final_stage,
                rel_tol=0.0,
                abs_tol=1.0e-12,
            )
            for value in boundaries.downstream.series.values
        ):
            raise ValueError(
                "controlled completed-interface Gate downstream stage must match initial"
            )
        if min(left, right) <= float(gate.sill_elevation) + gate.opening:
            raise ValueError(
                "controlled completed-interface Gate target must be initially submerged"
            )


def solve_single_branch(
    *,
    mesh: FiniteVolumeMesh,
    initial_state: HydraulicState,
    boundaries: BoundaryPair,
    config: SingleBranchConfig,
    gates: Sequence[FixedGate] = (),
    pumps: Sequence[OnOffPump | HydraulicExternalPump] = (),
    cancel_check: object | None = None,
    progress_callback: object | None = None,
) -> SingleBranchResult:
    """Run the composable single-river MVP and enforce its numerical gates.

    Every accepted step lands exactly on the next boundary knot, output time or
    simulation end.  Internal Gate transfer is excluded from the external
    water balance; an ON Pump is an explicit external outflow.
    """

    if config.end_time <= initial_state.time + _TIME_TOLERANCE:
        raise ValueError("end_time must be later than the initial-state time")
    if len(initial_state.area) != len(mesh.cells):
        raise ValueError("initial_state cell count must match the mesh")
    boundaries.validate_coverage(initial_state.time, config.end_time)
    require_quality(initial_state, mesh)
    if config.geometry_source_mode == "hydraulic-function-linear-face-v1":
        if config.nonprismatic_scope == NONPRISMATIC_LAKE_SCOPE:
            _validate_nonprismatic_lake_at_rest_scope(
                mesh=mesh,
                initial_state=initial_state,
                boundaries=boundaries,
                config=config,
                gates=gates,
                pumps=pumps,
            )
        elif config.nonprismatic_scope == NONPRISMATIC_MOVING_ENERGY_SCOPE:
            _validate_nonprismatic_moving_energy_scope(
                mesh=mesh,
                initial_state=initial_state,
                boundaries=boundaries,
                config=config,
                gates=gates,
                pumps=pumps,
            )
        else:
            _validate_nonprismatic_engineering_scope(
                mesh=mesh,
                initial_state=initial_state,
                boundaries=boundaries,
                config=config,
                gates=gates,
                pumps=pumps,
            )
    equilibrium_reference = (
        _validated_uniform_manning_reference(
            mesh=mesh,
            initial_state=initial_state,
            boundaries=boundaries,
            config=config,
            gates=gates,
            pumps=pumps,
        )
        if config.equilibrium_mode == "uniform-manning-reference"
        else None
    )
    _validate_structure_event_scope(
        mesh=mesh,
        initial_state=initial_state,
        config=config,
        gates=gates,
        pumps=pumps,
    )
    _validate_completed_gate_scope(
        mesh=mesh,
        initial_state=initial_state,
        boundaries=boundaries,
        config=config,
        gates=gates,
        pumps=pumps,
    )

    current, initial_control_events = _synchronize_structure_controls(
        mesh=mesh,
        state=initial_state,
        gates=gates,
        pumps=pumps,
    )
    envelope_observation: RuntimeEnvelopeObservation | None = None
    if config.runtime_envelope is not None:
        envelope_observation = require_runtime_envelope(
            mesh=mesh,
            state=current,
            envelope=config.runtime_envelope,
            checkpoint="initial accepted state",
        )
    initial_storage = storage(mesh, initial_state)
    output_states = [current]
    steps: list[StepResult] = []
    control_events = list(initial_control_events)
    next_output = min(initial_state.time + config.output_interval, config.end_time)
    upstream_volume = 0.0
    downstream_volume = 0.0
    pump_volume = 0.0
    pump_energy = 0.0
    total_event_refinements = 0
    gate_solver_retries = 0
    pump_solver_retries = 0
    friction_predictor_reductions = 0
    predicted_friction_dts: list[float] = []
    last_event: dict[str, object] | None = None
    boundary_flag = (
        "boundary_closure_subcritical_mvp_zero_gradient_companion"
        if boundaries.boundary_closure == "zero-gradient-companion-v1"
        else "boundary_closure_subcritical-characteristic-v1"
    )
    flags: set[str] = {
        boundary_flag,
        "friction_semi_implicit_per_ssp_stage_not_full_imex",
    }
    if config.maximum_friction_number is not None:
        flags.add("friction_number_retry_gate_v1")
    if config.friction_predictor_safety_factor is not None:
        flags.add("accepted_state_manning_friction_dt_predictor_v1")
    if config.runtime_envelope is not None:
        flags.add(config.runtime_envelope.runtime_envelope_id)
    if config.nonprismatic_scope == NONPRISMATIC_MOVING_ENERGY_SCOPE:
        flags.add(NONPRISMATIC_MOVING_ENERGY_SCOPE)
    if config.nonprismatic_scope == NONPRISMATIC_ENGINEERING_SCOPE:
        flags.add(NONPRISMATIC_ENGINEERING_SCOPE)
        flags.add("adjacent-profile-relative-change-at-most-0.25-v1")
    if any(isinstance(gate.control, OneShotStageThreshold) for gate in gates) or any(
        isinstance(pump.control, OneShotStageThreshold) for pump in pumps
    ):
        flags.add("structure_control_one_shot_accepted_state_discrete")
    if any(
        isinstance(gate.control, BracketedOneShotStageThreshold) for gate in gates
    ) or any(
        isinstance(pump.control, BracketedOneShotStageThreshold) for pump in pumps
    ):
        flags.add("structure_control_one_shot_bracketed_right_end_v1")
    if any(
        gate.uses_completed_interface
        and isinstance(gate.control, BracketedOneShotStageThreshold)
        for gate in gates
    ):
        flags.add("gate_completed_interface_bracketed_control_v1")

    while current.time < config.end_time - _TIME_TOLERANCE:
        check_cancellation(cancel_check, "accepted_step_start")
        if len(steps) >= config.maximum_steps:
            raise NumericalStateError("single-branch run exceeded maximum_steps")
        event_candidates = [config.end_time, next_output]
        breakpoint = boundaries.next_breakpoint_after(current.time)
        if breakpoint is not None:
            event_candidates.append(breakpoint)
        for pump in pumps:
            if isinstance(pump, HydraulicExternalPump):
                pump_breakpoint = pump.outlet_stage.next_breakpoint_after(current.time)
                if pump_breakpoint is not None:
                    event_candidates.append(pump_breakpoint)
        next_event = min(
            item for item in event_candidates if item > current.time + _TIME_TOLERANCE
        )
        requested_dt = min(config.maximum_dt, next_event - current.time)
        if config.friction_predictor_safety_factor is not None:
            predictor = estimate_manning_time_step(
                mesh=mesh,
                area=current.area,
                discharge=current.discharge,
                maximum_friction_number=config.maximum_friction_number,
            )
            if math.isfinite(predictor.time_step):
                predicted_friction_dts.append(predictor.time_step)
                predictor_limit = (
                    config.friction_predictor_safety_factor * predictor.time_step
                )
                if predictor_limit < requested_dt - 1.0e-12:
                    requested_dt = predictor_limit
                    friction_predictor_reductions += 1
        trial_dt = requested_dt
        event_refinement_count = 0
        accepted_brackets: dict[tuple[str, str], ControlBracketEvidence] = {}
        while True:
            step = advance_with_retries(
                mesh=mesh,
                state=current,
                requested_dt=trial_dt,
                dry_depth=config.dry_depth,
                boundaries=boundaries,
                cfl_limit=config.cfl_number,
                minimum_dt=config.minimum_dt,
                maximum_retries=config.maximum_retries,
                gates=gates,
                pumps=pumps,
                scheme=config.scheme,
                equilibrium_reference=equilibrium_reference,
                geometry_source_mode=config.geometry_source_mode,
                maximum_friction_number=config.maximum_friction_number,
                runtime_envelope=config.runtime_envelope,
                cancel_check=cancel_check,
            )
            crossing_candidates = detect_bracketed_crossings(
                mesh=mesh,
                previous=current,
                candidate=step.state,
                gates=gates,
                pumps=pumps,
            )
            if (
                crossing_candidates
                and step.dt > config.event_time_tolerance + 1.0e-12
            ):
                if event_refinement_count >= config.maximum_event_refinements:
                    raise NumericalStateError(
                        "bracketed control exceeded maximum_event_refinements"
                    )
                next_trial_dt = 0.5 * step.dt
                if next_trial_dt < config.minimum_dt:
                    raise NumericalStateError(
                        "bracketed control refinement would cross minimum_dt"
                    )
                event_refinement_count += 1
                check_cancellation(cancel_check, "event_refinement")
                trial_dt = next_trial_dt
                continue
            if crossing_candidates:
                accepted_brackets = {
                    key: candidate.evidence(
                        event_time_tolerance=config.event_time_tolerance,
                        refinement_count=event_refinement_count,
                    )
                    for key, candidate in crossing_candidates.items()
                }
            break
        current, accepted_control_events = _synchronize_structure_controls(
            mesh=mesh,
            state=step.state,
            gates=gates,
            pumps=pumps,
            brackets=accepted_brackets,
        )
        if config.runtime_envelope is not None:
            accepted_observation = require_runtime_envelope(
                mesh=mesh,
                state=current,
                envelope=config.runtime_envelope,
                checkpoint="accepted state",
            )
            step_observation = step.runtime_envelope_observation
            if step_observation is None:
                raise NumericalStateError(
                    "D3A accepted step omitted runtime-envelope evidence"
                )
            envelope_observation = envelope_observation.merged(
                step_observation
            ).merged(accepted_observation)
        step = replace(step, state=current)
        steps.append(step)
        control_events.extend(accepted_control_events)
        total_event_refinements += event_refinement_count
        gate_solver_retries += sum(
            max(flow.completed_interface.iterations - 1, 0)
            for flow in step.budget.gate_stage_flows
            if flow.completed_interface is not None
        )
        pump_solver_retries += sum(
            max(flow.pump_operating_point.iterations - 1, 0)
            for flow in step.budget.pump_stage_flows
            if flow.pump_operating_point is not None
        )
        if accepted_control_events:
            event = accepted_control_events[-1]
            last_event = {
                "time_seconds": event.time,
                "structure_type": event.structure_type,
                "structure_id": event.structure_id,
                "action": event.action,
                "reason": event.reason,
            }
        upstream_volume += step.budget.upstream_volume
        downstream_volume += step.budget.downstream_volume
        pump_volume += step.budget.pump_outflow_volume
        pump_energy += step.budget.pump_input_energy_kwh
        flags.update(step.diagnostic_flags)
        if accepted_brackets:
            flags.add("structure_event_bracketed_conservative_replay_right_end_v1")
        if current.time >= next_output - _TIME_TOLERANCE:
            output_states.append(current)
            next_output = min(next_output + config.output_interval, config.end_time)
        if callable(progress_callback):
            progress_callback(
                current.time,
                step.maximum_cfl,
                {
                    "accepted_step_count": current.diagnostics.step_count,
                    "retry_count": current.diagnostics.retry_count,
                    "cfl_reduction_count": (
                        current.diagnostics.time_step_reduction_count
                    ),
                    "positivity_retry_count": (
                        current.diagnostics.retry_count
                        - sum(item.friction_retry_count for item in steps)
                        - sum(
                            item.runtime_envelope_retry_count for item in steps
                        )
                    ),
                    "event_refinement_count": total_event_refinements,
                    "gate_solver_retry_count": gate_solver_retries,
                    "pump_solver_retry_count": pump_solver_retries,
                    "maximum_friction_number": max(
                        (item.maximum_friction_number for item in steps),
                        default=0.0,
                    ),
                    "friction_retry_count": sum(
                        item.friction_retry_count for item in steps
                    ),
                    "friction_predictor_reduction_count": (
                        friction_predictor_reductions
                    ),
                    "predicted_minimum_friction_dt": (
                        min(predicted_friction_dts)
                        if predicted_friction_dts
                        else None
                    ),
                    "runtime_envelope_retry_count": sum(
                        item.runtime_envelope_retry_count for item in steps
                    ),
                    "runtime_envelope_status": (
                        envelope_observation.status
                        if envelope_observation is not None
                        else "not_applicable"
                    ),
                    "minimum_dt_failure_count": 0,
                    "last_event": last_event,
                },
            )
        check_cancellation(cancel_check, "accepted_step_end")

    if output_states[-1].time < config.end_time - _TIME_TOLERANCE:
        output_states.append(current)
    if config.nonprismatic_scope == NONPRISMATIC_MOVING_ENERGY_SCOPE:
        _validate_moving_reference_preservation(
            mesh=mesh,
            initial_state=initial_state,
            steps=steps,
        )
        flags.add("moving_reference_preservation_quality_v1")
    final_storage = storage(mesh, current)
    if config.runtime_envelope is not None:
        final_observation = require_runtime_envelope(
            mesh=mesh,
            state=current,
            envelope=config.runtime_envelope,
            checkpoint="final result",
        )
        envelope_observation = envelope_observation.merged(final_observation)
    storage_change = final_storage - initial_storage
    expected_change = upstream_volume - downstream_volume - pump_volume
    residual = storage_change - expected_change
    scale = max(
        abs(initial_storage),
        abs(storage_change),
        abs(upstream_volume) + abs(downstream_volume) + abs(pump_volume),
        1.0,
    )
    relative_error = abs(residual) / scale
    require_quality(
        current,
        mesh,
        maximum_cfl=current.diagnostics.maximum_cfl,
        cfl_limit=config.cfl_number,
        relative_water_balance_error=relative_error,
        water_balance_tolerance=config.water_balance_tolerance,
    )
    minimum_used = current.diagnostics.minimum_dt
    if minimum_used is None:
        raise NumericalStateError("completed run has no accepted time-step diagnostic")
    maximum_accepted_friction_number = max(
        (step.maximum_friction_number for step in steps),
        default=0.0,
    )
    friction_retry_count = sum(step.friction_retry_count for step in steps)
    runtime_envelope_retry_count = sum(
        step.runtime_envelope_retry_count for step in steps
    )
    return SingleBranchResult(
        states=tuple(output_states),
        steps=tuple(steps),
        control_events=tuple(control_events),
        diagnostics=SingleBranchDiagnostics(
            initial_storage=initial_storage,
            final_storage=final_storage,
            upstream_boundary_volume=upstream_volume,
            downstream_boundary_volume=downstream_volume,
            pump_outflow_volume=pump_volume,
            pump_input_energy_kwh=pump_energy,
            water_balance_residual=residual,
            relative_water_balance_error=relative_error,
            water_balance_status="pass",
            maximum_cfl=current.diagnostics.maximum_cfl,
            minimum_dt=minimum_used,
            retry_count=current.diagnostics.retry_count,
            step_count=current.diagnostics.step_count,
            cfl_reduction_count=current.diagnostics.time_step_reduction_count,
            positivity_retry_count=(
                current.diagnostics.retry_count
                - friction_retry_count
                - runtime_envelope_retry_count
            ),
            event_refinement_count=total_event_refinements,
            gate_solver_retry_count=gate_solver_retries,
            pump_solver_retry_count=pump_solver_retries,
            maximum_friction_number=maximum_accepted_friction_number,
            friction_retry_count=friction_retry_count,
            friction_predictor_reduction_count=friction_predictor_reductions,
            predicted_minimum_friction_dt=(
                min(predicted_friction_dts) if predicted_friction_dts else None
            ),
            minimum_water_depth_m=(
                envelope_observation.minimum_water_depth_m
                if envelope_observation is not None
                else None
            ),
            minimum_discharge_m3s=(
                envelope_observation.minimum_discharge_m3s
                if envelope_observation is not None
                else None
            ),
            maximum_froude_number=(
                envelope_observation.maximum_froude_number
                if envelope_observation is not None
                else None
            ),
            runtime_envelope_retry_count=runtime_envelope_retry_count,
            runtime_envelope_status=(
                envelope_observation.status
                if envelope_observation is not None
                else "not_applicable"
            ),
            minimum_dt_failure_count=0,
            diagnostic_flags=tuple(sorted(flags)),
        ),
    )
