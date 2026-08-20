"""C2b scientific gates for one fixed completed-interface Gate."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from model.geometry.sections import RectangularSectionGeometry
from model.solver.finite_volume import (
    BoundaryPair,
    BoundarySeries,
    ConservedVector,
    DownstreamStageBoundary,
    FiniteVolumeCell,
    FiniteVolumeMesh,
    FixedGate,
    HydraulicState,
    OnOffPump,
    SingleBranchConfig,
    StructureStageContext,
    UpstreamDischargeBoundary,
    forward_euler_stage,
    physical_flux,
    solve_single_branch,
)

GRAVITY = 9.81


def _context(*, upstream_stage: float = 2.0, downstream_stage: float = 1.5):
    geometry = RectangularSectionGeometry(width=10.0, bed_elevation=0.0)
    return StructureStageContext(
        time=0.0,
        dt=0.1,
        upstream_stage=upstream_stage,
        downstream_stage=downstream_stage,
        upstream_area=geometry.area(upstream_stage),
        downstream_area=geometry.area(downstream_stage),
        upstream_discharge=0.0,
        downstream_discharge=0.0,
        upstream_top_width=geometry.top_width(upstream_stage),
        downstream_top_width=geometry.top_width(downstream_stage),
        upstream_pressure_moment=geometry.pressure_moment(upstream_stage),
        downstream_pressure_moment=geometry.pressure_moment(downstream_stage),
    )


def _completed_gate(**changes) -> FixedGate:
    values = {
        "gate_id": "gate-1",
        "face_index": 9,
        "opening": 0.5,
        "width": 2.0,
        "height": 1.0,
        "discharge_coefficient": 0.62,
        "coupling_policy": "submerged-orifice-energy-momentum-v1",
        "sill_elevation": 0.0,
        "equation_tolerance": 1.0e-12,
        "maximum_iterations": 80,
    }
    values.update(changes)
    return FixedGate(**values)


def _mesh() -> FiniteVolumeMesh:
    geometry = RectangularSectionGeometry(width=10.0, bed_elevation=0.0)
    return FiniteVolumeMesh(
        cells=tuple(
            FiniteVolumeCell(
                cell_id=f"cell-{index}",
                dx=50.0,
                section_id=index,
                bed_elevation=0.0,
                geometry=geometry,
                manning_n=0.0,
            )
            for index in range(20)
        )
    )


def _boundaries(end_time: float) -> BoundaryPair:
    return BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries((0.0, end_time), (0.0, 0.0), "discharge"),
            boundary_closure="subcritical-characteristic-v1",
        ),
        downstream=DownstreamStageBoundary(
            BoundarySeries((0.0, end_time), (1.5, 1.5), "stage"),
            boundary_closure="subcritical-characteristic-v1",
        ),
    )


def test_completed_gate_solves_energy_and_both_momentum_fluxes() -> None:
    """Independent algebra must reproduce Q, head loss, I1 fluxes and reaction."""

    gate = _completed_gate(face_index=0)
    context = _context()
    result = gate.evaluate_stage(context)
    evidence = result.completed_interface
    assert evidence is not None

    opening_area = gate.width * gate.opening
    coefficient = (
        1.0 / (gate.discharge_coefficient * opening_area) ** 2
        - 1.0 / context.upstream_area**2
        + 1.0 / context.downstream_area**2
    )
    expected_flow = math.sqrt(
        2.0
        * GRAVITY
        * (context.upstream_stage - context.downstream_stage)
        / coefficient
    )
    expected_loss = expected_flow**2 / (
        2.0 * GRAVITY * (gate.discharge_coefficient * opening_area) ** 2
    )
    expected_left = (
        expected_flow**2 / context.upstream_area
        + GRAVITY * float(context.upstream_pressure_moment)
    )
    expected_right = (
        expected_flow**2 / context.downstream_area
        + GRAVITY * float(context.downstream_pressure_moment)
    )

    assert result.flow == pytest.approx(expected_flow, rel=1.0e-11)
    assert evidence.head_loss == pytest.approx(expected_loss, rel=1.0e-11)
    assert abs(evidence.energy_residual) <= gate.equation_tolerance
    assert evidence.momentum_flux_left == pytest.approx(expected_left, rel=1.0e-11)
    assert evidence.momentum_flux_right == pytest.approx(expected_right, rel=1.0e-11)
    assert evidence.reaction_force_per_density == pytest.approx(
        expected_right - expected_left,
        rel=1.0e-11,
    )
    assert result.momentum_closure == "submerged_orifice_energy_momentum_v1"


def test_completed_gate_recomputes_both_rk_stages_and_preserves_global_mass() -> None:
    """Two stage heads drive two closures while Gate transfer remains internal."""

    mesh = _mesh()
    stages = (2.0,) * 10 + (1.5,) * 10
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=tuple(cell.geometry.area(stage) for cell, stage in zip(mesh.cells, stages)),
        discharge=(0.0,) * len(mesh.cells),
        dry_depth=1.0e-3,
    )
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=_boundaries(2.0),
        config=SingleBranchConfig(
            end_time=2.0,
            maximum_dt=0.1,
            output_interval=1.0,
            cfl_number=0.5,
        ),
        gates=(_completed_gate(),),
    )

    stage_rows = [
        flow
        for step in result.steps
        for flow in step.budget.gate_stage_flows
    ]
    assert len(stage_rows) == 2 * len(result.steps)
    assert all(flow.completed_interface is not None for flow in stage_rows)
    first, second = stage_rows[:2]
    assert first.completed_interface.upstream_stage != pytest.approx(
        second.completed_interface.upstream_stage
    )
    transfer = sum(
        volume
        for step in result.steps
        for structure_id, volume in step.budget.gate_transfer_volume
        if structure_id == "gate-1"
    )
    independent_transfer = sum(
        0.5
        * step.dt
        * (
            step.budget.gate_stage_flows[0].flow
            + step.budget.gate_stage_flows[1].flow
        )
        for step in result.steps
    )
    assert transfer == pytest.approx(independent_transfer, rel=1.0e-12)
    assert result.diagnostics.relative_water_balance_error < 1.0e-12
    assert (
        "gate_completed_interface_submerged_orifice_energy_momentum_v1"
        in result.diagnostics.diagnostic_flags
    )
    assert (
        "structure_momentum_closure_mass_only_mvp"
        not in result.diagnostics.diagnostic_flags
    )


def test_completed_gate_side_specific_momentum_enters_each_adjacent_cell() -> None:
    """One Euler update must consume left/right momentum, not a common HLL value."""

    mesh = FiniteVolumeMesh(cells=_mesh().cells[:2])
    state = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=(20.0, 15.0),
        discharge=(0.0, 0.0),
        dry_depth=1.0e-3,
    )
    boundaries = _boundaries(1.0)
    dt = 0.1
    stage = forward_euler_stage(
        mesh=mesh,
        state=state,
        dt=dt,
        dry_depth=1.0e-3,
        boundaries=boundaries,
        gates=(_completed_gate(face_index=0),),
    )
    closure = stage.budget.gate_flows[0].completed_interface
    assert closure is not None
    left_state = ConservedVector(state.area[0], state.discharge[0])
    right_state = ConservedVector(state.area[1], state.discharge[1])
    upstream = boundaries.upstream.ghost_state(
        time=0.0,
        interior=left_state,
        cell=mesh.cells[0],
    )
    downstream = boundaries.downstream.ghost_state(
        time=0.0,
        interior=right_state,
        cell=mesh.cells[1],
    )
    upstream_flux = physical_flux(upstream, mesh.cells[0].geometry)
    downstream_flux = physical_flux(downstream, mesh.cells[1].geometry)
    expected_left = -dt / mesh.cells[0].dx * (
        closure.momentum_flux_left - upstream_flux.momentum
    )
    expected_right = -dt / mesh.cells[1].dx * (
        downstream_flux.momentum - closure.momentum_flux_right
    )
    assert stage.state.discharge[0] == pytest.approx(expected_left, rel=1.0e-12)
    assert stage.state.discharge[1] == pytest.approx(expected_right, rel=1.0e-12)
    assert closure.momentum_flux_left != pytest.approx(closure.momentum_flux_right)


@pytest.mark.parametrize(
    ("gate", "context", "message"),
    [
        (_completed_gate(face_index=0), _context(downstream_stage=0.4), "submerged"),
        (
            _completed_gate(face_index=0),
            _context(upstream_stage=1.5, downstream_stage=2.0),
            "positive forward head",
        ),
        (
            _completed_gate(face_index=0, maximum_iterations=1, equation_tolerance=1e-20),
            _context(),
            "did not converge",
        ),
        (
            _completed_gate(face_index=0),
            replace(_context(), upstream_area=0.5, downstream_area=10.0),
            "no positive root",
        ),
        (
            _completed_gate(
                face_index=0,
                width=10.0,
                discharge_coefficient=1.0,
            ),
            replace(
                _context(),
                upstream_area=1.0,
                downstream_area=1.0,
                upstream_top_width=10.0,
                downstream_top_width=10.0,
            ),
            "subcritical traces",
        ),
    ],
)
def test_completed_gate_invalid_physics_never_falls_back(
    gate: FixedGate,
    context: StructureStageContext,
    message: str,
) -> None:
    """Invalid submerged/forward/root states must reject, never use mass-only."""

    with pytest.raises(ValueError, match=message):
        gate.evaluate_stage(context)


def test_completed_gate_scope_rejects_pump_and_friction() -> None:
    """The core repeats API scope checks for direct Python callers."""

    mesh = _mesh()
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=(20.0,) * 10 + (15.0,) * 10,
        discharge=(0.0,) * 20,
        dry_depth=1.0e-3,
    )
    config = SingleBranchConfig(2.0, 0.1, 1.0)
    with pytest.raises(ValueError, match="exactly one Gate and no Pump"):
        solve_single_branch(
            mesh=mesh,
            initial_state=initial,
            boundaries=_boundaries(2.0),
            config=config,
            gates=(_completed_gate(),),
            pumps=(OnOffPump("pump-1", 5, 0.1, True),),
        )
    rough = replace(
        mesh,
        cells=tuple(replace(cell, manning_n=0.03) for cell in mesh.cells),
    )
    with pytest.raises(ValueError, match="zero Manning friction"):
        solve_single_branch(
            mesh=rough,
            initial_state=initial,
            boundaries=_boundaries(2.0),
            config=config,
            gates=(_completed_gate(),),
        )


def test_legacy_gate_formula_and_closure_remain_frozen() -> None:
    """The pre-C2b mass-only Gate keeps its exact numerical and diagnostic identity."""

    gate = FixedGate("gate-1", 0, 0.5, 2.0, 1.0, 0.62)
    result = gate.evaluate_stage(_context())
    expected = 0.62 * 2.0 * 0.5 * math.sqrt(2.0 * GRAVITY * 0.5)
    assert result.flow == pytest.approx(expected, rel=1.0e-12)
    assert result.completed_interface is None
    assert result.momentum_closure == "mass_only_mvp_not_strongly_coupled"
