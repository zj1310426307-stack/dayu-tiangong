"""Direct v4-lite contract to finite-volume runtime and MVP result adapter."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from model.api.v4_lite import (
    BySectionInitialState,
    OneShotStageAboveControlInput,
    V4LiteInput,
    parse_v4_lite_input,
)
from model.core.errors import HydraulicInputError
from model.geometry.sections import TabulatedSectionGeometry
from model.provenance import canonical_json, snapshot_hash
from model.result.mvp import (
    HYDRAULIC_RESULT_MVP,
    MvpDiagnostics,
    MvpControlEvent,
    MvpGateSeries,
    MvpHydraulicResult,
    MvpPumpSeries,
    MvpResultProvenance,
    MvpSectionSeries,
    MvpWaterBalance,
)
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
    SingleBranchResult,
    StructureStageContext,
    UpstreamDischargeBoundary,
    solve_single_branch,
)

MESH_HASH_SCHEMA = "dayu.finite-volume-mesh.v1"


def build_v4_lite_mesh(model_input: V4LiteInput) -> FiniteVolumeMesh:
    """Build one deterministic cell-per-section mesh over the full Branch domain.

    Internal faces lie at adjacent-section midpoints.  Domain endpoints are
    the Branch start/end chainages, so endpoint cells use a half-spacing plus
    any explicitly modelled reach from the domain edge to its first/last
    section.  The resulting cell lengths sum exactly to the adopted domain.
    """

    chainages = tuple(section.chainage_m for section in model_input.sections)
    internal_faces = tuple(
        0.5 * (left + right) for left, right in zip(chainages, chainages[1:])
    )
    face_chainages = (
        model_input.river.start_chainage_m,
        *internal_faces,
        model_input.river.end_chainage_m,
    )
    lengths = tuple(
        right - left for left, right in zip(face_chainages, face_chainages[1:])
    )
    if any(not math.isfinite(length) or length <= 0.0 for length in lengths):
        raise HydraulicInputError("v4-lite section spacing produces a non-positive cell length")
    domain_length = model_input.river.end_chainage_m - model_input.river.start_chainage_m
    if not math.isclose(sum(lengths), domain_length, rel_tol=0.0, abs_tol=1.0e-9):
        raise HydraulicInputError("v4-lite finite-volume cells do not preserve Branch length")

    cells: list[FiniteVolumeCell] = []
    for section, length in zip(model_input.sections, lengths):
        geometry = TabulatedSectionGeometry.from_points(
            tuple((point.offset_m, point.elevation_m) for point in section.points)
        )
        cells.append(
            FiniteVolumeCell(
                cell_id=f"branch-{model_input.river.branch_id}-section-{section.section_id}",
                dx=length,
                section_id=section.section_id,
                bed_elevation=geometry.minimum_stage,
                geometry=geometry,
                manning_n=section.default_manning_n,
            )
        )
    return FiniteVolumeMesh(
        cells=tuple(cells),
        branch_id=str(model_input.river.branch_id),
    )


def v4_lite_mesh_hash(model_input: V4LiteInput, mesh: FiniteVolumeMesh) -> str:
    """Hash a stable geometry/identity manifest without serialising Python objects."""

    manifest = {
        "schema_version": MESH_HASH_SCHEMA,
        "geometry_policy": {
            "type": "tabulated-profile-points",
            "vertical_step_m": 0.05,
            "pressure_moment": "piecewise-linear-exact-v1",
            "prismatic_geometry_required": True,
        },
        "network_id": model_input.river.network_id,
        "branch_id": model_input.river.branch_id,
        "start_chainage_m": model_input.river.start_chainage_m,
        "end_chainage_m": model_input.river.end_chainage_m,
        "cells": [
            {
                "cell_id": cell.cell_id,
                "section_id": section.section_id,
                "chainage_m": section.chainage_m,
                "dx_m": cell.dx,
                "bed_elevation_m": cell.bed_elevation,
                "profile_id": section.profile_id,
                "profile_hash": section.profile_hash,
                "profile_points": [
                    {
                        "offset_m": point.offset_m,
                        "elevation_m": point.elevation_m,
                    }
                    for point in section.points
                ],
                "manning_n": cell.manning_n,
            }
            for cell, section in zip(mesh.cells, model_input.sections)
        ],
    }
    return snapshot_hash(manifest)


def _initial_state(model_input: V4LiteInput, mesh: FiniteVolumeMesh) -> HydraulicState:
    """Convert the explicit uniform/by-section H,Q contract to cell U=(A,Q)."""

    if isinstance(model_input.initial_state, BySectionInitialState):
        value_by_id = {
            item.section_id: item for item in model_input.initial_state.values
        }
        levels = tuple(
            value_by_id[section.section_id].water_level_m
            for section in model_input.sections
        )
        discharges = tuple(
            value_by_id[section.section_id].discharge_m3_s
            for section in model_input.sections
        )
    else:
        levels = tuple(
            model_input.initial_state.water_level_m for _ in model_input.sections
        )
        discharges = tuple(
            model_input.initial_state.discharge_m3_s for _ in model_input.sections
        )
    areas = tuple(
        cell.geometry.area(level) for cell, level in zip(mesh.cells, levels)
    )
    try:
        return HydraulicState.from_conserved(
            mesh=mesh,
            time=0.0,
            area=areas,
            discharge=discharges,
            dry_depth=model_input.solver.dry_depth_m,
        )
    except ValueError as exc:
        raise HydraulicInputError(f"v4-lite initial state is not executable: {exc}") from exc


def _boundaries(model_input: V4LiteInput) -> BoundaryPair:
    """Bind the already validated Q(t)/H(t) arrays without extrapolation."""

    upstream = model_input.boundary.upstream
    downstream = model_input.boundary.downstream
    return BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries(
                tuple(upstream.time_seconds),
                tuple(upstream.flow_m3_s),
                "discharge",
            )
        ),
        downstream=DownstreamStageBoundary(
            BoundarySeries(
                tuple(downstream.time_seconds),
                tuple(downstream.water_level_m),
                "stage",
            )
        ),
    )


def _structures(
    model_input: V4LiteInput,
) -> tuple[tuple[FixedGate, ...], tuple[OnOffPump, ...]]:
    """Resolve the single optional Gate face and external Pump cell by identity."""

    index_by_section = {
        section.section_id: index for index, section in enumerate(model_input.sections)
    }
    gates = tuple(
        FixedGate(
            gate_id=str(gate.identity.id),
            face_index=index_by_section[gate.interface.upstream_section_id],
            opening=gate.opening_m,
            width=gate.width_m,
            height=gate.height_m,
            discharge_coefficient=gate.discharge_coefficient,
            allow_reverse=gate.allow_reverse_flow,
            control=(
                OneShotStageThreshold(gate.control.threshold_water_level_m)
                if isinstance(gate.control, OneShotStageAboveControlInput)
                else None
            ),
        )
        for gate in model_input.structures.gates
    )
    pumps = tuple(
        OnOffPump(
            pump_id=str(pump.identity.id),
            cell_index=index_by_section[pump.section_id],
            design_flow=pump.design_flow_m3_s,
            enabled=pump.status == "on",
            control=(
                OneShotStageThreshold(pump.control.threshold_water_level_m)
                if isinstance(pump.control, OneShotStageAboveControlInput)
                else None
            ),
        )
        for pump in model_input.structures.pumps
    )
    return gates, pumps


def _gate_series(
    model_input: V4LiteInput,
    runtime: SingleBranchResult,
    mesh: FiniteVolumeMesh,
    gates: tuple[FixedGate, ...],
) -> tuple[MvpGateSeries, ...]:
    """Project accepted actual opening and current-head flow at output times."""

    if not gates:
        return ()
    gate = gates[0]
    source = model_input.structures.gates[0]
    time = tuple(state.time for state in runtime.states)
    opening: list[float] = []
    flow: list[float] = []
    for state in runtime.states:
        left = gate.face_index
        right = left + 1
        control_state = state.gate_state.get(gate.gate_id)
        if not isinstance(control_state, Mapping):
            raise HydraulicInputError("runtime Gate state is missing or malformed")
        actual_opening = control_state.get("opening")
        if isinstance(actual_opening, bool) or not isinstance(
            actual_opening, (int, float)
        ):
            raise HydraulicInputError("runtime Gate opening is not numeric")
        opening.append(float(actual_opening))
        flow.append(
            gate.evaluate_stage(
                StructureStageContext(
                    time=state.time,
                    dt=max(model_input.solver.minimum_time_step_seconds, 1.0e-12),
                    upstream_stage=mesh.cells[left].geometry.stage_from_area(
                        state.area[left]
                    ),
                    downstream_stage=mesh.cells[right].geometry.stage_from_area(
                        state.area[right]
                    ),
                    upstream_area=state.area[left],
                    downstream_area=state.area[right],
                    upstream_discharge=state.discharge[left],
                    downstream_discharge=state.discharge[right],
                ),
                control_state,
            ).flow
        )
    return (
        MvpGateSeries(
            gate_id=source.identity.id,
            time=time,
            opening=tuple(opening),
            flow=tuple(flow),
        ),
    )


def _pump_series(
    model_input: V4LiteInput,
    runtime: SingleBranchResult,
) -> tuple[MvpPumpSeries, ...]:
    """Project each accepted actual Pump command onto the output time axis."""

    if not model_input.structures.pumps:
        return ()
    pump = model_input.structures.pumps[0]
    time = tuple(state.time for state in runtime.states)
    enabled: list[bool] = []
    for state in runtime.states:
        control_state = state.pump_state.get(str(pump.identity.id))
        if not isinstance(control_state, Mapping):
            raise HydraulicInputError("runtime Pump state is missing or malformed")
        actual_enabled = control_state.get("enabled")
        if not isinstance(actual_enabled, bool):
            raise HydraulicInputError("runtime Pump enabled state is not boolean")
        enabled.append(actual_enabled)
    return (
        MvpPumpSeries(
            pump_id=pump.identity.id,
            time=time,
            status=tuple("on" if item else "off" for item in enabled),
            flow=tuple(pump.design_flow_m3_s if item else 0.0 for item in enabled),
        ),
    )


def _result(
    *,
    input_snapshot_hash: str,
    model_input: V4LiteInput,
    mesh: FiniteVolumeMesh,
    runtime: SingleBranchResult,
    gates: tuple[FixedGate, ...],
) -> MvpHydraulicResult:
    """Build the independent result DTO without legacy EngineResult projection."""

    times = tuple(state.time for state in runtime.states)
    sections = tuple(
        MvpSectionSeries(
            section_id=section.section_id,
            section_code=section.section_code,
            time=times,
            water_level=tuple(
                mesh.cells[index].geometry.stage_from_area(state.area[index])
                for state in runtime.states
            ),
            flow=tuple(state.discharge[index] for state in runtime.states),
            velocity=tuple(state.velocity[index] for state in runtime.states),
        )
        for index, section in enumerate(model_input.sections)
    )
    evidence = runtime.diagnostics
    return MvpHydraulicResult(
        schema_version=HYDRAULIC_RESULT_MVP,
        sections=sections,
        gates=_gate_series(model_input, runtime, mesh, gates),
        pumps=_pump_series(model_input, runtime),
        control_events=tuple(
            MvpControlEvent(
                time=event.time,
                structure_id=int(event.structure_id),
                structure_type=event.structure_type,
                action=event.action,
                threshold_water_level=event.threshold_water_level,
                observed_water_level=event.observed_water_level,
            )
            for event in runtime.control_events
        ),
        water_balance=MvpWaterBalance(
            initial_storage=evidence.initial_storage,
            final_storage=evidence.final_storage,
            upstream_boundary_volume=evidence.upstream_boundary_volume,
            downstream_boundary_volume=evidence.downstream_boundary_volume,
            pump_outflow_volume=evidence.pump_outflow_volume,
            water_balance_residual=evidence.water_balance_residual,
            relative_water_balance_error=evidence.relative_water_balance_error,
            tolerance=model_input.solver.water_balance_tolerance,
            status=evidence.water_balance_status,
        ),
        diagnostics=MvpDiagnostics(
            maximum_cfl=evidence.maximum_cfl,
            minimum_dt=evidence.minimum_dt,
            retry_count=evidence.retry_count,
            step_count=evidence.step_count,
            diagnostic_flags=evidence.diagnostic_flags,
        ),
        provenance=MvpResultProvenance(
            input_schema_version=model_input.schema_version,
            input_snapshot_hash=input_snapshot_hash,
            mesh_hash=v4_lite_mesh_hash(model_input, mesh),
            solver_type=model_input.solver.type,
            scheme=model_input.solver.scheme,
            time_integrator=model_input.solver.time_integrator,
            engine_version=model_input.provenance.engine_version,
            engine_commit=model_input.provenance.engine_commit,
            validation_policy_version=model_input.provenance.validation_policy_version,
        ),
    )


def run_v4_lite(snapshot: Mapping[str, Any]) -> MvpHydraulicResult:
    """Validate and execute the direct v4-lite finite-volume route only."""

    frozen_snapshot = json.loads(canonical_json(snapshot))
    input_snapshot_hash = snapshot_hash(frozen_snapshot)
    model_input = parse_v4_lite_input(frozen_snapshot)
    mesh = build_v4_lite_mesh(model_input)
    gates, pumps = _structures(model_input)
    runtime = solve_single_branch(
        mesh=mesh,
        initial_state=_initial_state(model_input, mesh),
        boundaries=_boundaries(model_input),
        config=SingleBranchConfig(
            end_time=model_input.solver.duration_seconds,
            maximum_dt=model_input.solver.maximum_time_step_seconds,
            output_interval=model_input.solver.output_interval_seconds,
            cfl_number=model_input.solver.cfl_number,
            dry_depth=model_input.solver.dry_depth_m,
            minimum_dt=model_input.solver.minimum_time_step_seconds,
            maximum_retries=model_input.solver.maximum_retries,
            maximum_steps=model_input.solver.maximum_steps,
            water_balance_tolerance=model_input.solver.water_balance_tolerance,
            scheme="hll",
        ),
        gates=gates,
        pumps=pumps,
    )
    return _result(
        input_snapshot_hash=input_snapshot_hash,
        model_input=model_input,
        mesh=mesh,
        runtime=runtime,
        gates=gates,
    )


__all__ = [
    "MESH_HASH_SCHEMA",
    "build_v4_lite_mesh",
    "run_v4_lite",
    "v4_lite_mesh_hash",
]
