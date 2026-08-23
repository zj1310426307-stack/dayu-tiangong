"""Focused scientific contracts for the composable finite-volume MVP core."""

import math

import pytest

from model.geometry.sections import RectangularSectionGeometry, TabulatedSectionGeometry
from model.solver.finite_volume import (
    BoundaryCoverageError,
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
    estimate_cfl_time_step,
    hll_flux,
    physical_flux,
    rusanov_flux,
    semi_implicit_manning,
    solve_single_branch,
)


def make_mesh(
    *,
    beds: tuple[float, ...] = (0.0, 0.2, 0.1, 0.0),
    dx: float = 50.0,
    manning_n: float = 0.0,
) -> FiniteVolumeMesh:
    """Build an ordered rectangular mesh without database or engine coupling."""

    return FiniteVolumeMesh(
        cells=tuple(
            FiniteVolumeCell(
                cell_id=f"cell-{index}",
                dx=dx,
                section_id=f"CS-{index}",
                bed_elevation=bed,
                geometry=RectangularSectionGeometry(width=10.0, bed_elevation=bed),
                manning_n=manning_n,
            )
            for index, bed in enumerate(beds)
        )
    )


def make_state(
    mesh: FiniteVolumeMesh,
    *,
    stage: float = 1.0,
    discharge: float = 0.0,
) -> HydraulicState:
    """Construct a uniform-free-surface conservative state on a variable bed."""

    return HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=[cell.geometry.area(stage) for cell in mesh.cells],
        discharge=[discharge for _ in mesh.cells],
        dry_depth=1.0e-3,
    )


def make_boundaries(*, end_time: float, stage: float = 1.0) -> BoundaryPair:
    """Build complete piecewise-linear Q/H boundaries for one run."""

    return BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries((0.0, end_time), (0.0, 0.0), "discharge")
        ),
        downstream=DownstreamStageBoundary(
            BoundarySeries((0.0, end_time), (stage, stage), "stage")
        ),
    )


def test_hydraulic_state_is_derived_from_but_does_not_own_mesh() -> None:
    """U=(A,Q) remains authoritative while mesh and state stay separate."""

    mesh = make_mesh(beds=(0.0,))
    state = make_state(mesh, stage=1.0, discharge=5.0)

    assert not hasattr(state, "mesh")
    assert state.area == (10.0,)
    assert state.discharge == (5.0,)
    assert state.water_depth == pytest.approx((1.0,))
    assert state.velocity == pytest.approx((0.5,))
    assert state.wet_mask == (True,)

    structured = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=[10.0],
        discharge=[5.0],
        dry_depth=1.0e-3,
        gate_state={"G-1": {"opening": 1.0}},
    )
    with pytest.raises(TypeError):
        structured.gate_state["G-2"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        structured.gate_state["G-1"]["opening"] = 2.0  # type: ignore[index]


def test_hll_and_rusanov_are_consistent_with_the_physical_flux() -> None:
    """Equal wet states must reduce both numerical fluxes to F(U)."""

    geometry = RectangularSectionGeometry(width=5.0, bed_elevation=0.0)
    state = ConservedVector(area=10.0, discharge=4.0)
    expected = physical_flux(state, geometry)

    assert hll_flux(state, state, geometry, geometry) == pytest.approx(expected)
    assert rusanov_flux(state, state, geometry, geometry) == pytest.approx(expected)
    dry = ConservedVector(0.0, 0.0)
    assert hll_flux(dry, dry, geometry, geometry).mass == 0.0
    assert hll_flux(dry, dry, geometry, geometry).momentum == 0.0


def test_dynamic_boundary_interpolates_but_never_extrapolates() -> None:
    """The boundary domain is closed and out-of-range requests fail."""

    series = BoundarySeries((0.0, 5.0, 10.0), (2.0, 7.0, 4.0), "discharge")

    assert series.value_at(2.5) == pytest.approx(4.5)
    assert series.next_breakpoint_after(2.5) == 5.0
    with pytest.raises(BoundaryCoverageError):
        series.value_at(-0.01)
    with pytest.raises(BoundaryCoverageError):
        series.value_at(10.01)


def test_cfl_controller_and_semi_implicit_friction_are_finite_and_sign_safe() -> None:
    """CFL shrinks an unsafe maximum and Manning friction cannot flip Q."""

    mesh = make_mesh(beds=(0.0,), dx=10.0, manning_n=0.035)
    state = make_state(mesh, stage=1.0, discharge=20.0)
    estimate = estimate_cfl_time_step(
        mesh=mesh,
        state=state,
        cfl_number=0.7,
        maximum_dt=100.0,
    )
    positive = semi_implicit_manning(
        area=10.0,
        discharge=20.0,
        geometry=mesh.cells[0].geometry,
        manning_n=0.035,
        dt=1.0,
    )
    negative = semi_implicit_manning(
        area=10.0,
        discharge=-20.0,
        geometry=mesh.cells[0].geometry,
        manning_n=0.035,
        dt=1.0,
    )

    assert 0.0 < estimate.time_step < 100.0
    assert estimate.limiting_cell == 0
    assert 0.0 < positive < 20.0
    assert -20.0 < negative < 0.0
    assert math.isfinite(positive) and negative == pytest.approx(-positive)


def test_ssp_rk2_single_branch_preserves_variable_bed_lake_at_rest() -> None:
    """Hydrostatic reconstruction keeps Q=0 and a horizontal free surface."""

    mesh = make_mesh()
    initial = make_state(mesh)
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=make_boundaries(end_time=10.0),
        config=SingleBranchConfig(
            end_time=10.0,
            maximum_dt=1.0,
            output_interval=5.0,
        ),
    )

    assert [state.time for state in result.states] == pytest.approx([0.0, 5.0, 10.0])
    for state in result.states:
        assert state.discharge == pytest.approx((0.0,) * len(mesh.cells), abs=1.0e-11)
        stages = [
            cell.geometry.stage_from_area(area)
            for cell, area in zip(mesh.cells, state.area)
        ]
        assert stages == pytest.approx((1.0,) * len(mesh.cells), abs=1.0e-11)
    assert result.diagnostics.maximum_cfl <= 0.7 + 1.0e-12
    assert result.diagnostics.relative_water_balance_error < 1.0e-12
    assert result.diagnostics.water_balance_status == "pass"


def test_prismatic_tabulated_section_preserves_lake_at_rest() -> None:
    """The supported non-rectangular, prismatic Profile subset stays at rest."""

    geometry = TabulatedSectionGeometry.from_points(
        ((0.0, 4.0), (5.0, 0.0), (15.0, 0.0), (20.0, 4.0))
    )
    mesh = FiniteVolumeMesh(
        tuple(
            FiniteVolumeCell(
                cell_id=f"tabulated-{index}",
                dx=50.0,
                section_id=f"TCS-{index}",
                bed_elevation=0.0,
                geometry=geometry,
                manning_n=0.0,
            )
            for index in range(10)
        )
    )
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=(geometry.area(2.0),) * 10,
        discharge=(0.0,) * 10,
        dry_depth=1.0e-3,
    )
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=make_boundaries(end_time=60.0, stage=2.0),
        config=SingleBranchConfig(
            end_time=60.0,
            maximum_dt=2.0,
            output_interval=20.0,
        ),
    )

    assert result.diagnostics.relative_water_balance_error < 1.0e-12
    for state in result.states:
        assert state.discharge == pytest.approx((0.0,) * 10, abs=1.0e-11)
        assert tuple(geometry.stage_from_area(area) for area in state.area) == pytest.approx(
            (2.0,) * 10,
            abs=1.0e-11,
        )


def test_gate_and_pump_stage_contracts_are_explicitly_mvp_mass_flows() -> None:
    """Fixed devices compute stage flows without claiming momentum strong coupling."""

    context = StructureStageContext(
        time=0.0,
        dt=1.0,
        upstream_stage=2.0,
        downstream_stage=1.0,
        upstream_area=20.0,
        downstream_area=10.0,
        upstream_discharge=0.0,
        downstream_discharge=0.0,
    )
    gate = FixedGate(
        gate_id="G-1",
        face_index=0,
        opening=0.5,
        width=2.0,
        height=1.0,
        discharge_coefficient=0.6,
    )
    pump_on = OnOffPump("P-1", cell_index=0, design_flow=0.2, enabled=True)
    pump_off = OnOffPump("P-2", cell_index=0, design_flow=0.2, enabled=False)

    gate_flow = gate.evaluate_stage(context)
    assert gate_flow.flow == pytest.approx(0.6 * 1.0 * math.sqrt(2.0 * 9.81))
    assert gate_flow.momentum_closure == "mass_only_mvp_not_strongly_coupled"
    assert pump_on.evaluate_stage(context).flow == 0.2
    assert pump_off.evaluate_stage(context).flow == 0.0


def test_external_pump_sink_is_included_in_dynamic_storage_balance() -> None:
    """An ON pump removes equal accounted volume and emits the MVP limitation flag."""

    mesh = make_mesh(beds=(0.0, 0.0, 0.0), dx=100.0)
    initial = make_state(mesh)
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=make_boundaries(end_time=2.0),
        config=SingleBranchConfig(
            end_time=2.0,
            maximum_dt=0.25,
            output_interval=1.0,
        ),
        gates=(
            FixedGate(
                gate_id="G-1",
                face_index=0,
                opening=0.5,
                width=2.0,
                height=1.0,
            ),
        ),
        pumps=(OnOffPump("P-1", cell_index=1, design_flow=0.1, enabled=True),),
    )

    assert result.diagnostics.pump_outflow_volume == pytest.approx(0.2)
    assert result.diagnostics.relative_water_balance_error < 1.0e-10
    assert "structure_momentum_closure_mass_only_mvp" in result.diagnostics.diagnostic_flags
    assert result.diagnostics.final_storage < result.diagnostics.initial_storage
