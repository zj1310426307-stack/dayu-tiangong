"""CFL control, forward-Euler stages and SSP-RK2 composition."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

from model.solver.finite_volume.boundary import BoundaryPair
from model.solver.finite_volume.diagnostics import NumericalStateError, StabilityError
from model.solver.finite_volume.flux import (
    ConservedVector,
    maximum_signal_speed,
    physical_flux,
)
from model.solver.finite_volume.friction import (
    ManningCellStageEvidence,
    apply_manning_friction,
    apply_manning_friction_with_evidence,
)
from model.solver.finite_volume.geometry_source import (
    geometry_pressure_source,
    hydraulic_path_interface_flux,
    mesh_face_geometries,
)
from model.solver.finite_volume.mesh import FiniteVolumeMesh
from model.solver.finite_volume.pump import HydraulicExternalPump
from model.solver.finite_volume.reconstruction import InterfaceFlux, hydrostatic_interface_flux
from model.solver.finite_volume.state import HydraulicState
from model.solver.finite_volume.structures import (
    FixedGate,
    OnOffPump,
    StructureStageContext,
    StructureStageFlow,
)

_EPSILON = 1.0e-12


def _committed_structure_state(
    states: Mapping[str, object], structure_id: str
) -> Mapping[str, object] | None:
    """Return one immutable accepted command without interpreting trial heads."""

    value = states.get(structure_id)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("committed structure state must be a mapping")
    return value


@dataclass(frozen=True)
class CflEstimate:
    """Describe the limiting cell and stable global time-step estimate."""

    time_step: float
    maximum_signal_speed: float
    limiting_cell: int | None


@dataclass(frozen=True)
class StageBudget:
    """Expose instantaneous external and internal mass-flow accounting."""

    upstream_flux: float
    downstream_flux: float
    pump_outflow: float
    gate_flows: tuple[StructureStageFlow, ...]
    pump_flows: tuple[StructureStageFlow, ...]


@dataclass(frozen=True)
class EulerStageResult:
    """Return one Euler state, mass budget, and directly applied source evidence.

    Residual-equilibrium correction subtracts a second raw operator, so no
    single-cell Manning tuple can truthfully describe its net corrected state.
    That opt-in path therefore returns an empty tuple instead of relabelling
    the uncorrected operator evidence as an accepted source update.
    """

    state: HydraulicState
    budget: StageBudget
    friction_evidence: tuple[ManningCellStageEvidence, ...]


@dataclass(frozen=True)
class StepBudget:
    """Return SSP-RK2 trapezoidal volumes and averaged structure flows."""

    upstream_volume: float
    downstream_volume: float
    pump_outflow_volume: float
    pump_input_energy_kwh: float
    gate_transfer_volume: tuple[tuple[str, float], ...]
    gate_stage_flows: tuple[StructureStageFlow, ...]
    pump_stage_flows: tuple[StructureStageFlow, ...]


@dataclass(frozen=True)
class StepResult:
    """Hold one accepted SSP-RK2 step and its conservative accounting."""

    state: HydraulicState
    dt: float
    maximum_cfl: float
    budget: StepBudget
    diagnostic_flags: tuple[str, ...] = ()


def estimate_cfl_time_step(
    *,
    mesh: FiniteVolumeMesh,
    state: HydraulicState,
    cfl_number: float,
    maximum_dt: float,
) -> CflEstimate:
    """Return ``CFL*dx/(|u|+c)`` with an all-dry maximum-step fallback."""

    if not math.isfinite(cfl_number) or not 0.0 < cfl_number <= 1.0:
        raise ValueError("cfl_number must lie in (0, 1]")
    if not math.isfinite(maximum_dt) or maximum_dt <= 0.0:
        raise ValueError("maximum_dt must be finite and positive")
    candidates: list[tuple[float, float, int]] = []
    for index, (cell, area, discharge) in enumerate(
        zip(mesh.cells, state.area, state.discharge)
    ):
        speed = maximum_signal_speed(ConservedVector(area, discharge), cell.geometry)
        if speed > _EPSILON:
            candidates.append((cfl_number * cell.dx / speed, speed, index))
    if not candidates:
        return CflEstimate(maximum_dt, 0.0, None)
    time_step, _, limiting = min(candidates, key=lambda item: item[0])
    maximum_speed = max(item[1] for item in candidates)
    return CflEstimate(min(time_step, maximum_dt), maximum_speed, limiting)


def cfl_number_for_step(
    *, mesh: FiniteVolumeMesh, state: HydraulicState, dt: float
) -> float:
    """Return the maximum realised cell CFL for a proposed time step."""

    if not math.isfinite(dt) or dt <= 0.0:
        raise ValueError("dt must be finite and positive")
    values = [
        dt
        * maximum_signal_speed(ConservedVector(area, discharge), cell.geometry)
        / cell.dx
        for cell, area, discharge in zip(mesh.cells, state.area, state.discharge)
    ]
    result = max(values, default=0.0)
    if not math.isfinite(result):
        raise StabilityError("realised CFL is non-finite")
    return result


def _structure_context(
    *,
    mesh: FiniteVolumeMesh,
    state: HydraulicState,
    left_index: int,
    right_index: int,
    dt: float,
) -> StructureStageContext:
    """Build the current-head context required by a Gate stage evaluation."""

    upstream_stage = mesh.cells[left_index].geometry.stage_from_area(
        state.area[left_index]
    )
    downstream_stage = mesh.cells[right_index].geometry.stage_from_area(
        state.area[right_index]
    )
    return StructureStageContext(
        time=state.time,
        dt=dt,
        upstream_stage=upstream_stage,
        downstream_stage=downstream_stage,
        upstream_area=state.area[left_index],
        downstream_area=state.area[right_index],
        upstream_discharge=state.discharge[left_index],
        downstream_discharge=state.discharge[right_index],
        upstream_top_width=mesh.cells[left_index].geometry.top_width(upstream_stage),
        downstream_top_width=mesh.cells[right_index].geometry.top_width(
            downstream_stage
        ),
        upstream_pressure_moment=mesh.cells[left_index].geometry.pressure_moment(
            upstream_stage
        ),
        downstream_pressure_moment=mesh.cells[right_index].geometry.pressure_moment(
            downstream_stage
        ),
    )


def _pump_context(
    *,
    mesh: FiniteVolumeMesh,
    state: HydraulicState,
    pump: OnOffPump | HydraulicExternalPump,
    dt: float,
) -> StructureStageContext:
    """Build current absolute source/target stages for one Pump evaluation."""

    source_stage = mesh.cells[pump.cell_index].geometry.stage_from_area(
        state.area[pump.cell_index]
    )
    target_stage = (
        pump.outlet_stage_at(state.time)
        if isinstance(pump, HydraulicExternalPump)
        else source_stage
    )

    return StructureStageContext(
        time=state.time,
        dt=dt,
        upstream_stage=source_stage,
        downstream_stage=target_stage,
        upstream_area=state.area[pump.cell_index],
        downstream_area=state.area[pump.cell_index],
        upstream_discharge=state.discharge[pump.cell_index],
        downstream_discharge=state.discharge[pump.cell_index],
    )


def _forward_euler_stage_raw(
    *,
    mesh: FiniteVolumeMesh,
    state: HydraulicState,
    dt: float,
    dry_depth: float,
    boundaries: BoundaryPair,
    gates: Sequence[FixedGate] = (),
    pumps: Sequence[OnOffPump | HydraulicExternalPump] = (),
    scheme: Literal["hll", "rusanov"] = "hll",
    geometry_source_mode: Literal[
        "hydrostatic-reconstruction-v1",
        "hydraulic-function-linear-face-v1",
    ] = "hydrostatic-reconstruction-v1",
    capture_friction_evidence: bool = False,
) -> EulerStageResult:
    """Evaluate the uncorrected flux/source map for one Euler stage.

    A legacy Gate replaces only the common mass flux of its bound internal
    face.  A versioned completed-interface Gate also supplies the two
    side-specific momentum fluxes and never falls back to the legacy closure.
    Pumps are external sinks and remove local advective momentum with water.
    """

    if not math.isfinite(dt) or dt <= 0.0:
        raise ValueError("Euler stage dt must be finite and positive")
    if not isinstance(capture_friction_evidence, bool):
        raise TypeError("capture_friction_evidence must be boolean")
    if len(state.area) != len(mesh.cells):
        raise NumericalStateError("state and mesh cell counts differ")
    conservative = tuple(
        ConservedVector(area, discharge)
        for area, discharge in zip(state.area, state.discharge)
    )
    upstream_ghost = boundaries.upstream.ghost_state(
        time=state.time,
        interior=conservative[0],
        cell=mesh.cells[0],
    )
    downstream_ghost = boundaries.downstream.ghost_state(
        time=state.time,
        interior=conservative[-1],
        cell=mesh.cells[-1],
    )
    if boundaries.boundary_closure == "subcritical-characteristic-v1":
        upstream_physical = physical_flux(upstream_ghost, mesh.cells[0].geometry)
        face_fluxes: list[InterfaceFlux] = [
            InterfaceFlux(
                mass=upstream_physical.mass,
                momentum_left=upstream_physical.momentum,
                momentum_right=upstream_physical.momentum,
            )
        ]
    else:
        face_fluxes = [
            hydrostatic_interface_flux(
                upstream_ghost,
                conservative[0],
                mesh.cells[0],
                mesh.cells[0],
                scheme=scheme,
            )
        ]
        upstream_q = boundaries.upstream.series.value_at(state.time)
        face_fluxes[0] = InterfaceFlux(
            mass=upstream_q,
            momentum_left=face_fluxes[0].momentum_left,
            momentum_right=face_fluxes[0].momentum_right,
        )
    if geometry_source_mode == "hydrostatic-reconstruction-v1":
        face_fluxes.extend(
            hydrostatic_interface_flux(
                conservative[index],
                conservative[index + 1],
                mesh.cells[index],
                mesh.cells[index + 1],
                scheme=scheme,
            )
            for index in range(len(mesh.cells) - 1)
        )
        face_geometries = None
    elif geometry_source_mode == "hydraulic-function-linear-face-v1":
        face_fluxes.extend(
            hydraulic_path_interface_flux(
                conservative[index],
                conservative[index + 1],
                mesh.cells[index],
                mesh.cells[index + 1],
                scheme=scheme,
            )
            for index in range(len(mesh.cells) - 1)
        )
        face_geometries = mesh_face_geometries(mesh)
    else:
        raise ValueError(
            f"unsupported finite-volume geometry_source_mode: {geometry_source_mode}"
        )
    if boundaries.boundary_closure == "subcritical-characteristic-v1":
        downstream_physical = physical_flux(
            downstream_ghost,
            mesh.cells[-1].geometry,
        )
        face_fluxes.append(
            InterfaceFlux(
                mass=downstream_physical.mass,
                momentum_left=downstream_physical.momentum,
                momentum_right=downstream_physical.momentum,
            )
        )
    else:
        face_fluxes.append(
            hydrostatic_interface_flux(
                conservative[-1],
                downstream_ghost,
                mesh.cells[-1],
                mesh.cells[-1],
                scheme=scheme,
            )
        )

    gate_flows: list[StructureStageFlow] = []
    gate_state: dict[str, object] = dict(state.gate_state)
    used_gate_faces: set[int] = set()
    for gate in gates:
        if gate.face_index >= len(mesh.cells) - 1:
            raise ValueError(f"gate {gate.gate_id} is not bound to an internal face")
        if gate.face_index in used_gate_faces:
            raise ValueError("only one MVP Gate may bind an internal face")
        used_gate_faces.add(gate.face_index)
        result = gate.evaluate_stage(
            _structure_context(
                mesh=mesh,
                state=state,
                left_index=gate.face_index,
                right_index=gate.face_index + 1,
                dt=dt,
            ),
            _committed_structure_state(state.gate_state, gate.gate_id),
        )
        gate_flows.append(result)
        gate_state[gate.gate_id] = result.state
        existing = face_fluxes[gate.face_index + 1]
        if result.completed_interface is None:
            face_fluxes[gate.face_index + 1] = InterfaceFlux(
                mass=result.flow,
                momentum_left=existing.momentum_left,
                momentum_right=existing.momentum_right,
            )
        else:
            face_fluxes[gate.face_index + 1] = InterfaceFlux(
                mass=result.flow,
                momentum_left=result.completed_interface.momentum_flux_left,
                momentum_right=result.completed_interface.momentum_flux_right,
            )

    pump_rate_by_cell = [0.0 for _ in mesh.cells]
    pump_flows: list[StructureStageFlow] = []
    pump_state: dict[str, object] = dict(state.pump_state)
    for pump in pumps:
        if pump.cell_index >= len(mesh.cells):
            raise ValueError(f"pump {pump.pump_id} cell_index is outside the mesh")
        result = pump.evaluate_stage(
            _pump_context(mesh=mesh, state=state, pump=pump, dt=dt),
            _committed_structure_state(state.pump_state, pump.pump_id),
        )
        if result.flow < 0.0:
            raise ValueError("MVP external pump sink flow must be non-negative")
        pump_flows.append(result)
        pump_state[pump.pump_id] = result.state
        pump_rate_by_cell[pump.cell_index] += result.flow

    next_area: list[float] = []
    advective_discharge: list[float] = []
    for index, cell in enumerate(mesh.cells):
        left_flux = face_fluxes[index]
        right_flux = face_fluxes[index + 1]
        pump_rate = pump_rate_by_cell[index]
        area = state.area[index] - dt / cell.dx * (
            right_flux.mass - left_flux.mass + pump_rate
        )
        local_velocity = (
            state.discharge[index] / state.area[index]
            if state.area[index] > _EPSILON
            else 0.0
        )
        discharge = state.discharge[index] - dt / cell.dx * (
            right_flux.momentum_left
            - left_flux.momentum_right
            + pump_rate * local_velocity
        )
        if face_geometries is not None:
            discharge += dt * geometry_pressure_source(
                cell=cell,
                state=conservative[index],
                left_face_geometry=face_geometries[index],
                right_face_geometry=face_geometries[index + 1],
            )
        if not math.isfinite(area) or not math.isfinite(discharge):
            raise NumericalStateError(f"cell {index} produced a non-finite Euler state")
        if area < 0.0:
            raise NumericalStateError(f"cell {index} produced negative area")
        next_area.append(area)
        advective_discharge.append(discharge)
    if capture_friction_evidence:
        friction_discharge, friction_evidence = apply_manning_friction_with_evidence(
            mesh=mesh,
            area=next_area,
            discharge=advective_discharge,
            dt=dt,
        )
    else:
        friction_discharge = apply_manning_friction(
            mesh=mesh,
            area=next_area,
            discharge=advective_discharge,
            dt=dt,
        )
        friction_evidence = ()
    try:
        next_state = HydraulicState.from_conserved(
            mesh=mesh,
            time=state.time + dt,
            area=next_area,
            discharge=friction_discharge,
            dry_depth=dry_depth,
            gate_state=gate_state,
            pump_state=pump_state,
            diagnostics=state.diagnostics,
        )
    except ValueError as exc:
        raise NumericalStateError(str(exc)) from exc
    return EulerStageResult(
        state=next_state,
        budget=StageBudget(
            upstream_flux=face_fluxes[0].mass,
            downstream_flux=face_fluxes[-1].mass,
            pump_outflow=sum(pump_rate_by_cell),
            gate_flows=tuple(gate_flows),
            pump_flows=tuple(pump_flows),
        ),
        friction_evidence=friction_evidence,
    )


def forward_euler_stage(
    *,
    mesh: FiniteVolumeMesh,
    state: HydraulicState,
    dt: float,
    dry_depth: float,
    boundaries: BoundaryPair,
    gates: Sequence[FixedGate] = (),
    pumps: Sequence[OnOffPump | HydraulicExternalPump] = (),
    scheme: Literal["hll", "rusanov"] = "hll",
    equilibrium_reference: HydraulicState | None = None,
    geometry_source_mode: Literal[
        "hydrostatic-reconstruction-v1",
        "hydraulic-function-linear-face-v1",
    ] = "hydrostatic-reconstruction-v1",
    capture_friction_evidence: bool = False,
) -> EulerStageResult:
    """Evaluate one Euler stage, optionally in residual-equilibrium form.

    The optional reference is deliberately not inferred here.  The branch
    orchestrator may supply it only after validating an analytic steady-state
    contract.  For the same discrete Euler map ``Phi`` we advance deviations
    as ``U + (Phi(U)-U) - (Phi(Ueq)-Ueq)``.  Consequently the verified
    reference has exactly zero discrete residual, while a perturbation still
    evolves under the original HLL/hydrostatic/Manning operator.

    This is a deviation well-balancing correction, not a replacement flux and
    not permission to freeze an arbitrary initial state.  Structures are
    excluded because their steady momentum/energy contracts are not closed in
    the MVP.
    """

    raw = _forward_euler_stage_raw(
        mesh=mesh,
        state=state,
        dt=dt,
        dry_depth=dry_depth,
        boundaries=boundaries,
        gates=gates,
        pumps=pumps,
        scheme=scheme,
        geometry_source_mode=geometry_source_mode,
        capture_friction_evidence=capture_friction_evidence,
    )
    if equilibrium_reference is None:
        return raw
    if gates or pumps:
        raise ValueError(
            "residual-equilibrium correction does not support MVP structures"
        )
    if len(equilibrium_reference.area) != len(mesh.cells):
        raise ValueError("equilibrium reference cell count must match the mesh")

    try:
        reference_at_time = HydraulicState.from_conserved(
            mesh=mesh,
            time=state.time,
            area=equilibrium_reference.area,
            discharge=equilibrium_reference.discharge,
            dry_depth=dry_depth,
            diagnostics=equilibrium_reference.diagnostics,
        )
        raw_reference = _forward_euler_stage_raw(
            mesh=mesh,
            state=reference_at_time,
            dt=dt,
            dry_depth=dry_depth,
            boundaries=boundaries,
            scheme=scheme,
            geometry_source_mode=geometry_source_mode,
            capture_friction_evidence=False,
        )
        corrected_area = tuple(
            current
            + (advanced - current)
            - (reference_advanced - reference)
            for current, advanced, reference, reference_advanced in zip(
                state.area,
                raw.state.area,
                reference_at_time.area,
                raw_reference.state.area,
            )
        )
        corrected_discharge = tuple(
            current
            + (advanced - current)
            - (reference_advanced - reference)
            for current, advanced, reference, reference_advanced in zip(
                state.discharge,
                raw.state.discharge,
                reference_at_time.discharge,
                raw_reference.state.discharge,
            )
        )
        corrected = HydraulicState.from_conserved(
            mesh=mesh,
            time=state.time + dt,
            area=corrected_area,
            discharge=corrected_discharge,
            dry_depth=dry_depth,
            gate_state=raw.state.gate_state,
            pump_state=raw.state.pump_state,
            diagnostics=state.diagnostics,
        )
    except ValueError as exc:
        raise NumericalStateError(str(exc)) from exc
    return EulerStageResult(
        state=corrected,
        budget=raw.budget,
        friction_evidence=(),
    )


def ssp_rk2_step(
    *,
    mesh: FiniteVolumeMesh,
    state: HydraulicState,
    dt: float,
    dry_depth: float,
    boundaries: BoundaryPair,
    cfl_limit: float,
    gates: Sequence[FixedGate] = (),
    pumps: Sequence[OnOffPump | HydraulicExternalPump] = (),
    scheme: Literal["hll", "rusanov"] = "hll",
    equilibrium_reference: HydraulicState | None = None,
    geometry_source_mode: Literal[
        "hydrostatic-reconstruction-v1",
        "hydraulic-function-linear-face-v1",
    ] = "hydrostatic-reconstruction-v1",
) -> StepResult:
    """Advance one SSP-RK2 step, recomputing all stage-dependent inputs."""

    initial_cfl = cfl_number_for_step(mesh=mesh, state=state, dt=dt)
    if initial_cfl > cfl_limit + 1.0e-12:
        raise StabilityError("requested step exceeds the configured CFL limit")
    first = forward_euler_stage(
        mesh=mesh,
        state=state,
        dt=dt,
        dry_depth=dry_depth,
        boundaries=boundaries,
        gates=gates,
        pumps=pumps,
        scheme=scheme,
        equilibrium_reference=equilibrium_reference,
        geometry_source_mode=geometry_source_mode,
    )
    stage_cfl = cfl_number_for_step(mesh=mesh, state=first.state, dt=dt)
    maximum_cfl = max(initial_cfl, stage_cfl)
    if maximum_cfl > cfl_limit + 1.0e-12:
        raise StabilityError("SSP-RK2 intermediate stage exceeds the configured CFL limit")
    second = forward_euler_stage(
        mesh=mesh,
        state=first.state,
        dt=dt,
        dry_depth=dry_depth,
        boundaries=boundaries,
        gates=gates,
        pumps=pumps,
        scheme=scheme,
        equilibrium_reference=equilibrium_reference,
        geometry_source_mode=geometry_source_mode,
    )
    final_area = tuple(
        0.5 * (original + evolved)
        for original, evolved in zip(state.area, second.state.area)
    )
    final_discharge = tuple(
        0.5 * (original + evolved)
        for original, evolved in zip(state.discharge, second.state.discharge)
    )
    diagnostics = state.diagnostics.accepted_step(dt=dt, cfl=maximum_cfl)
    try:
        final_state = HydraulicState.from_conserved(
            mesh=mesh,
            time=state.time + dt,
            area=final_area,
            discharge=final_discharge,
            dry_depth=dry_depth,
            gate_state=second.state.gate_state,
            pump_state=second.state.pump_state,
            diagnostics=diagnostics,
        )
    except ValueError as exc:
        raise NumericalStateError(str(exc)) from exc

    def average_flows(
        left: tuple[StructureStageFlow, ...], right: tuple[StructureStageFlow, ...]
    ) -> tuple[tuple[str, float], ...]:
        """Average matching stage flows by stable structure identity."""

        left_map = {item.structure_id: item.flow for item in left}
        right_map = {item.structure_id: item.flow for item in right}
        if left_map.keys() != right_map.keys():
            raise NumericalStateError("structure identities changed inside one RK step")
        return tuple(
            (key, 0.5 * (left_map[key] + right_map[key]))
            for key in sorted(left_map)
        )

    average_gate = average_flows(first.budget.gate_flows, second.budget.gate_flows)
    pump_input_energy_kwh = (
        0.5
        * dt
        * sum(
            evidence.input_power_kw
            for stage in (
                *first.budget.pump_flows,
                *second.budget.pump_flows,
            )
            if (evidence := stage.pump_operating_point) is not None
        )
        / 3600.0
    )
    flags = tuple(
        flag
        for enabled, flag in (
            (
                any(not gate.uses_completed_interface for gate in gates),
                "structure_momentum_closure_mass_only_mvp",
            ),
            (
                any(gate.uses_completed_interface for gate in gates),
                "gate_completed_interface_submerged_orifice_energy_momentum_v1",
            ),
            (
                equilibrium_reference is not None,
                "moving_uniform_manning_residual_equilibrium_v1",
            ),
            (
                geometry_source_mode == "hydraulic-function-linear-face-v1",
                "nonprismatic_hydraulic_function_linear_face_source_v1",
            ),
        )
        if enabled
    )
    return StepResult(
        state=final_state,
        dt=dt,
        maximum_cfl=maximum_cfl,
        budget=StepBudget(
            upstream_volume=0.5
            * dt
            * (first.budget.upstream_flux + second.budget.upstream_flux),
            downstream_volume=0.5
            * dt
            * (first.budget.downstream_flux + second.budget.downstream_flux),
            pump_outflow_volume=0.5
            * dt
            * (first.budget.pump_outflow + second.budget.pump_outflow),
            pump_input_energy_kwh=pump_input_energy_kwh,
            gate_transfer_volume=tuple(
                (structure_id, flow * dt) for structure_id, flow in average_gate
            ),
            gate_stage_flows=first.budget.gate_flows + second.budget.gate_flows,
            pump_stage_flows=first.budget.pump_flows + second.budget.pump_flows,
        ),
        diagnostic_flags=flags,
    )


def advance_with_retries(
    *,
    mesh: FiniteVolumeMesh,
    state: HydraulicState,
    requested_dt: float,
    dry_depth: float,
    boundaries: BoundaryPair,
    cfl_limit: float,
    minimum_dt: float,
    maximum_retries: int,
    gates: Sequence[FixedGate] = (),
    pumps: Sequence[OnOffPump | HydraulicExternalPump] = (),
    scheme: Literal["hll", "rusanov"] = "hll",
    equilibrium_reference: HydraulicState | None = None,
    geometry_source_mode: Literal[
        "hydrostatic-reconstruction-v1",
        "hydraulic-function-linear-face-v1",
    ] = "hydrostatic-reconstruction-v1",
) -> StepResult:
    """Reduce to the CFL step and retry rejected positivity/stability attempts."""

    estimate = estimate_cfl_time_step(
        mesh=mesh,
        state=state,
        cfl_number=cfl_limit,
        maximum_dt=requested_dt,
    )
    dt = estimate.time_step
    working = state
    if dt < requested_dt - 1.0e-12:
        working = working.with_diagnostics(working.diagnostics.reduced_time_step())
    retries = 0
    while True:
        if dt < minimum_dt - 1.0e-15:
            raise StabilityError("required retry time step is below minimum_dt")
        try:
            return ssp_rk2_step(
                mesh=mesh,
                state=working,
                dt=dt,
                dry_depth=dry_depth,
                boundaries=boundaries,
                cfl_limit=cfl_limit,
                gates=gates,
                pumps=pumps,
                scheme=scheme,
                equilibrium_reference=equilibrium_reference,
                geometry_source_mode=geometry_source_mode,
            )
        except (NumericalStateError, StabilityError):
            if retries >= maximum_retries:
                raise StabilityError("finite-volume step exhausted retry budget")
            retries += 1
            working = working.with_diagnostics(working.diagnostics.rejected_step())
            dt *= 0.5
