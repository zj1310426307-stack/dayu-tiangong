"""CFL control, forward-Euler stages and SSP-RK2 composition."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Sequence

from model.solver.finite_volume.boundary import BoundaryPair
from model.solver.finite_volume.diagnostics import NumericalStateError, StabilityError
from model.solver.finite_volume.flux import ConservedVector, maximum_signal_speed
from model.solver.finite_volume.friction import apply_manning_friction
from model.solver.finite_volume.mesh import FiniteVolumeMesh
from model.solver.finite_volume.reconstruction import InterfaceFlux, hydrostatic_interface_flux
from model.solver.finite_volume.state import HydraulicState
from model.solver.finite_volume.structures import (
    FixedGate,
    OnOffPump,
    StructureStageContext,
    StructureStageFlow,
)

_EPSILON = 1.0e-12


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
    """Return one positivity-checked Euler state and its stage budget."""

    state: HydraulicState
    budget: StageBudget


@dataclass(frozen=True)
class StepBudget:
    """Return SSP-RK2 trapezoidal volumes and averaged structure flows."""

    upstream_volume: float
    downstream_volume: float
    pump_outflow_volume: float
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

    return StructureStageContext(
        time=state.time,
        dt=dt,
        upstream_stage=mesh.cells[left_index].geometry.stage_from_area(
            state.area[left_index]
        ),
        downstream_stage=mesh.cells[right_index].geometry.stage_from_area(
            state.area[right_index]
        ),
        upstream_area=state.area[left_index],
        downstream_area=state.area[right_index],
        upstream_discharge=state.discharge[left_index],
        downstream_discharge=state.discharge[right_index],
    )


def _pump_context(
    *, state: HydraulicState, cell_index: int, dt: float
) -> StructureStageContext:
    """Build a same-cell context for the fixed external pump sink."""

    return StructureStageContext(
        time=state.time,
        dt=dt,
        upstream_stage=state.water_depth[cell_index],
        downstream_stage=state.water_depth[cell_index],
        upstream_area=state.area[cell_index],
        downstream_area=state.area[cell_index],
        upstream_discharge=state.discharge[cell_index],
        downstream_discharge=state.discharge[cell_index],
    )


def forward_euler_stage(
    *,
    mesh: FiniteVolumeMesh,
    state: HydraulicState,
    dt: float,
    dry_depth: float,
    boundaries: BoundaryPair,
    gates: Sequence[FixedGate] = (),
    pumps: Sequence[OnOffPump] = (),
    scheme: Literal["hll", "rusanov"] = "hll",
) -> EulerStageResult:
    """Evaluate flux, boundary, Gate, Pump and friction at one RK stage.

    Gate flow replaces only the common mass flux of its bound internal face;
    the default hydrostatic HLL momentum terms are retained and reported by
    the orchestrator as the explicit MVP-not-strongly-coupled limitation.
    Pumps are external sinks and remove local advective momentum with water.
    """

    if not math.isfinite(dt) or dt <= 0.0:
        raise ValueError("Euler stage dt must be finite and positive")
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
    face_fluxes: list[InterfaceFlux] = [
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
            )
        )
        gate_flows.append(result)
        gate_state[gate.gate_id] = result.state
        existing = face_fluxes[gate.face_index + 1]
        face_fluxes[gate.face_index + 1] = InterfaceFlux(
            mass=result.flow,
            momentum_left=existing.momentum_left,
            momentum_right=existing.momentum_right,
        )

    pump_rate_by_cell = [0.0 for _ in mesh.cells]
    pump_flows: list[StructureStageFlow] = []
    pump_state: dict[str, object] = dict(state.pump_state)
    for pump in pumps:
        if pump.cell_index >= len(mesh.cells):
            raise ValueError(f"pump {pump.pump_id} cell_index is outside the mesh")
        result = pump.evaluate_stage(
            _pump_context(state=state, cell_index=pump.cell_index, dt=dt)
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
        if not math.isfinite(area) or not math.isfinite(discharge):
            raise NumericalStateError(f"cell {index} produced a non-finite Euler state")
        if area < 0.0:
            raise NumericalStateError(f"cell {index} produced negative area")
        next_area.append(area)
        advective_discharge.append(discharge)
    friction_discharge = apply_manning_friction(
        mesh=mesh,
        area=next_area,
        discharge=advective_discharge,
        dt=dt,
    )
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
    pumps: Sequence[OnOffPump] = (),
    scheme: Literal["hll", "rusanov"] = "hll",
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
    flags = (
        ("structure_momentum_closure_mass_only_mvp",)
        if gates
        else ()
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
    pumps: Sequence[OnOffPump] = (),
    scheme: Literal["hll", "rusanov"] = "hll",
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
            )
        except (NumericalStateError, StabilityError):
            if retries >= maximum_retries:
                raise StabilityError("finite-volume step exhausted retry budget")
            retries += 1
            working = working.with_diagnostics(working.diagnostics.rejected_step())
            dt *= 0.5
