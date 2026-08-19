"""Minimal single-branch orchestrator for the Dayu Saint-Venant MVP."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal, Mapping, Sequence

from model.solver.finite_volume.boundary import BoundaryPair
from model.solver.finite_volume.diagnostics import NumericalStateError, require_quality
from model.solver.finite_volume.flux import GRAVITY
from model.solver.finite_volume.integrator import StepResult, advance_with_retries
from model.solver.finite_volume.mesh import FiniteVolumeMesh
from model.solver.finite_volume.state import HydraulicState
from model.solver.finite_volume.structures import (
    FixedGate,
    OnOffPump,
    StructureControlEvent,
)

_TIME_TOLERANCE = 1.0e-9
_EQUILIBRIUM_RELATIVE_TOLERANCE = 1.0e-10
_EQUILIBRIUM_ABSOLUTE_TOLERANCE = 1.0e-12


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
    scheme: Literal["hll", "rusanov"] = "hll"
    equilibrium_mode: Literal["standard", "uniform-manning-reference"] = "standard"

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
        if self.equilibrium_mode not in ("standard", "uniform-manning-reference"):
            raise ValueError("unsupported finite-volume equilibrium_mode")


@dataclass(frozen=True)
class SingleBranchDiagnostics:
    """Report dynamic storage, signed boundaries, pump outflow and limitations."""

    initial_storage: float
    final_storage: float
    upstream_boundary_volume: float
    downstream_boundary_volume: float
    pump_outflow_volume: float
    water_balance_residual: float
    relative_water_balance_error: float
    water_balance_status: Literal["pass", "fail"]
    maximum_cfl: float
    minimum_dt: float
    retry_count: int
    step_count: int
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
    pumps: Sequence[OnOffPump],
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
        )
        pump_state[pump.pump_id] = next_state
        if event is not None:
            events.append(event)
    return replace(state, gate_state=gate_state, pump_state=pump_state), tuple(events)


def _equilibrium_close(left: float, right: float) -> bool:
    """Compare two analytic-equilibrium quantities with a strict tolerance."""

    return math.isclose(
        left,
        right,
        rel_tol=_EQUILIBRIUM_RELATIVE_TOLERANCE,
        abs_tol=_EQUILIBRIUM_ABSOLUTE_TOLERANCE,
    )


def _require_constant(values: Sequence[float], label: str) -> float:
    """Return the common value or fail the explicit equilibrium contract."""

    if not values:
        raise ValueError(f"uniform-manning-reference requires non-empty {label}")
    reference = float(values[0])
    if any(not _equilibrium_close(float(value), reference) for value in values[1:]):
        raise ValueError(f"uniform-manning-reference requires constant {label}")
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
    pumps: Sequence[OnOffPump],
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
    bed_slope = _require_constant(slopes, "positive linear bed slope")
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
    if not _equilibrium_close(bed_slope, expected_slope):
        raise ValueError(
            "uniform-manning-reference bed slope does not satisfy Manning equilibrium"
        )

    upstream_flow = _require_constant(
        boundaries.upstream.series.values, "upstream Q boundary"
    )
    downstream_stage = _require_constant(
        boundaries.downstream.series.values, "downstream H boundary"
    )
    if not _equilibrium_close(upstream_flow, discharge):
        raise ValueError(
            "uniform-manning-reference upstream Q does not match initial discharge"
        )
    final_stage = mesh.cells[-1].geometry.stage_from_area(initial_state.area[-1])
    if not _equilibrium_close(downstream_stage, final_stage):
        raise ValueError(
            "uniform-manning-reference downstream H does not match the final cell"
        )
    return initial_state


def solve_single_branch(
    *,
    mesh: FiniteVolumeMesh,
    initial_state: HydraulicState,
    boundaries: BoundaryPair,
    config: SingleBranchConfig,
    gates: Sequence[FixedGate] = (),
    pumps: Sequence[OnOffPump] = (),
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

    current, initial_control_events = _synchronize_structure_controls(
        mesh=mesh,
        state=initial_state,
        gates=gates,
        pumps=pumps,
    )
    initial_storage = storage(mesh, initial_state)
    output_states = [current]
    steps: list[StepResult] = []
    control_events = list(initial_control_events)
    next_output = min(initial_state.time + config.output_interval, config.end_time)
    upstream_volume = 0.0
    downstream_volume = 0.0
    pump_volume = 0.0
    flags: set[str] = {
        "boundary_closure_subcritical_mvp_zero_gradient_companion",
        "friction_semi_implicit_per_ssp_stage_not_full_imex",
    }
    if any(gate.control is not None for gate in gates) or any(
        pump.control is not None for pump in pumps
    ):
        flags.add("structure_control_one_shot_accepted_state_discrete")

    while current.time < config.end_time - _TIME_TOLERANCE:
        if len(steps) >= config.maximum_steps:
            raise NumericalStateError("single-branch run exceeded maximum_steps")
        event_candidates = [config.end_time, next_output]
        breakpoint = boundaries.next_breakpoint_after(current.time)
        if breakpoint is not None:
            event_candidates.append(breakpoint)
        next_event = min(
            item for item in event_candidates if item > current.time + _TIME_TOLERANCE
        )
        requested_dt = min(config.maximum_dt, next_event - current.time)
        step = advance_with_retries(
            mesh=mesh,
            state=current,
            requested_dt=requested_dt,
            dry_depth=config.dry_depth,
            boundaries=boundaries,
            cfl_limit=config.cfl_number,
            minimum_dt=config.minimum_dt,
            maximum_retries=config.maximum_retries,
            gates=gates,
            pumps=pumps,
            scheme=config.scheme,
            equilibrium_reference=equilibrium_reference,
        )
        current, accepted_control_events = _synchronize_structure_controls(
            mesh=mesh,
            state=step.state,
            gates=gates,
            pumps=pumps,
        )
        step = replace(step, state=current)
        steps.append(step)
        control_events.extend(accepted_control_events)
        upstream_volume += step.budget.upstream_volume
        downstream_volume += step.budget.downstream_volume
        pump_volume += step.budget.pump_outflow_volume
        flags.update(step.diagnostic_flags)
        if current.time >= next_output - _TIME_TOLERANCE:
            output_states.append(current)
            next_output = min(next_output + config.output_interval, config.end_time)

    if output_states[-1].time < config.end_time - _TIME_TOLERANCE:
        output_states.append(current)
    final_storage = storage(mesh, current)
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
            water_balance_residual=residual,
            relative_water_balance_error=relative_error,
            water_balance_status="pass",
            maximum_cfl=current.diagnostics.maximum_cfl,
            minimum_dt=minimum_used,
            retry_count=current.diagnostics.retry_count,
            step_count=current.diagnostics.step_count,
            diagnostic_flags=tuple(sorted(flags)),
        ),
    )
