"""Scientific contracts for the opt-in subcritical characteristic closure."""

from __future__ import annotations

import math

import pytest

from model.geometry.sections import (
    RectangularSectionGeometry,
    TabulatedSectionGeometry,
)
from model.solver.finite_volume import (
    BoundaryCoverageError,
    BoundaryPair,
    BoundarySeries,
    ConservedVector,
    DownstreamStageBoundary,
    FiniteVolumeCell,
    FiniteVolumeMesh,
    HydraulicState,
    SingleBranchConfig,
    UpstreamDischargeBoundary,
    forward_euler_stage,
    hydrostatic_interface_flux,
    physical_flux,
    solve_single_branch,
)
from model.solver.finite_volume.boundary import (
    SUBCRITICAL_CHARACTERISTIC_ALGORITHM_V1,
    SUBCRITICAL_CHARACTERISTIC_V1,
    ZERO_GRADIENT_COMPANION_ALGORITHM_V1,
    ZERO_GRADIENT_COMPANION_V1,
    boundary_algorithm_id,
)
from model.solver.finite_volume.flux import GRAVITY


def _rectangular_cell(*, dx: float = 50.0) -> FiniteVolumeCell:
    """Return a 10 m rectangular section with an explicit SI mesh length."""

    return FiniteVolumeCell(
        cell_id=f"rect-{dx}",
        dx=dx,
        section_id="CS-1",
        bed_elevation=0.0,
        geometry=RectangularSectionGeometry(width=10.0, bed_elevation=0.0),
    )


def _upstream(
    discharge: float,
    *,
    end_time: float = 10.0,
    closure: str = SUBCRITICAL_CHARACTERISTIC_V1,
) -> UpstreamDischargeBoundary:
    """Return one constant prescribed-Q boundary."""

    return UpstreamDischargeBoundary(
        BoundarySeries((0.0, end_time), (discharge, discharge), "discharge"),
        boundary_closure=closure,  # type: ignore[arg-type]
    )


def _downstream(
    stage: float,
    *,
    end_time: float = 10.0,
    closure: str = SUBCRITICAL_CHARACTERISTIC_V1,
) -> DownstreamStageBoundary:
    """Return one constant prescribed-H boundary."""

    return DownstreamStageBoundary(
        BoundarySeries((0.0, end_time), (stage, stage), "stage"),
        boundary_closure=closure,  # type: ignore[arg-type]
    )


def _rectangular_invariants(state: ConservedVector, *, width: float = 10.0):
    """Evaluate the independent analytic rectangular R-/R+ invariants."""

    depth = state.area / width
    velocity = state.discharge / state.area
    potential = 2.0 * math.sqrt(GRAVITY * depth)
    return velocity - potential, velocity + potential


def _independent_tabulated_phi(
    geometry: TabulatedSectionGeometry,
    stage: float,
    *,
    intervals: int = 100_000,
) -> float:
    """Integrate Phi independently with composite Simpson quadrature.

    The production characteristic implementation is deliberately not called.
    ``stage = bed + s**2`` removes the near-bed square-root singularity from
    ``integral(sqrt(g * T / A), dH)``.  The frozen tabulated A/T functions are
    the physical inputs, while this test owns its quadrature and resolution.
    """

    assert intervals > 0 and intervals % 2 == 0
    assert geometry.minimum_stage < stage <= geometry.maximum_stage
    upper = math.sqrt(stage - geometry.minimum_stage)
    step = upper / intervals
    first_area_slope = (geometry.areas[1] - geometry.areas[0]) / (
        geometry.stages[1] - geometry.stages[0]
    )
    bed_width = geometry.top_width(geometry.minimum_stage)
    assert first_area_slope > 0.0 and bed_width > 0.0
    dry_endpoint_limit = 2.0 * math.sqrt(
        GRAVITY * bed_width / first_area_slope
    )

    def transformed_integrand(index: int) -> float:
        coordinate = index * step
        if index == 0:
            # On the first frozen table interval A=a*h and T=T0+O(h).
            # Therefore 2*s*sqrt(g*T/A), h=s**2, has this finite non-zero
            # one-sided limit for a flat-bottom section.
            return dry_endpoint_limit
        local_stage = geometry.minimum_stage + coordinate * coordinate
        area = geometry.area(local_stage)
        top_width = geometry.top_width(local_stage)
        assert area > 0.0 and top_width > 0.0
        return 2.0 * coordinate * math.sqrt(GRAVITY * top_width / area)

    weighted = transformed_integrand(0) + transformed_integrand(intervals)
    weighted += 4.0 * sum(
        transformed_integrand(index) for index in range(1, intervals, 2)
    )
    weighted += 2.0 * sum(
        transformed_integrand(index) for index in range(2, intervals, 2)
    )
    return weighted * step / 3.0


def test_default_companion_semantics_are_exact_and_explicitly_versioned() -> None:
    """Omitting closure keeps the pre-B2 ghost states byte-for-byte in meaning."""

    cell = _rectangular_cell()
    interior = ConservedVector(area=20.0, discharge=50.0)
    upstream = UpstreamDischargeBoundary(
        BoundarySeries((0.0, 1.0), (40.0, 40.0), "discharge")
    )
    downstream = DownstreamStageBoundary(
        BoundarySeries((0.0, 1.0), (2.5, 2.5), "stage")
    )
    pair = BoundaryPair(upstream, downstream)

    assert pair.boundary_closure == ZERO_GRADIENT_COMPANION_V1
    assert pair.boundary_algorithm_id == ZERO_GRADIENT_COMPANION_ALGORITHM_V1
    assert upstream.ghost_state(time=0.0, interior=interior, cell=cell) == (
        ConservedVector(20.0, 40.0)
    )
    assert downstream.ghost_state(time=0.0, interior=interior, cell=cell) == (
        ConservedVector(25.0, 50.0)
    )


def test_characteristic_pair_rejects_mixed_or_unknown_versions() -> None:
    """One run cannot silently mix companion and characteristic algorithms."""

    with pytest.raises(ValueError, match="versions must match"):
        BoundaryPair(
            _upstream(20.0),
            _downstream(2.0, closure=ZERO_GRADIENT_COMPANION_V1),
        )
    with pytest.raises(ValueError, match="unsupported.*boundary_closure"):
        _upstream(20.0, closure="characteristic-latest")
    assert (
        boundary_algorithm_id(SUBCRITICAL_CHARACTERISTIC_V1)
        == SUBCRITICAL_CHARACTERISTIC_ALGORITHM_V1
    )


def test_rectangular_q_h_completion_preserves_analytic_riemann_invariants() -> None:
    """Q uses outgoing R- upstream and H uses outgoing R+ downstream."""

    cell = _rectangular_cell()
    interior = ConservedVector(area=20.0, discharge=50.0)
    interior_minus, interior_plus = _rectangular_invariants(interior)

    upstream_ghost = _upstream(45.0).ghost_state(
        time=0.0,
        interior=interior,
        cell=cell,
    )
    downstream_ghost = _downstream(2.2).ghost_state(
        time=0.0,
        interior=interior,
        cell=cell,
    )
    upstream_minus, _ = _rectangular_invariants(upstream_ghost)
    _, downstream_plus = _rectangular_invariants(downstream_ghost)

    assert upstream_ghost.discharge == 45.0
    assert upstream_ghost.area == pytest.approx(19.265426821794, rel=1.0e-12)
    assert upstream_minus == pytest.approx(interior_minus, abs=1.0e-11)
    assert downstream_ghost.area == pytest.approx(22.0, abs=1.0e-12)
    assert downstream_ghost.discharge == pytest.approx(
        45.4873671075197,
        rel=1.0e-12,
    )
    assert downstream_plus == pytest.approx(interior_plus, abs=1.0e-12)


def test_characteristic_trace_is_local_and_independent_of_cell_dx() -> None:
    """The same face state cannot change merely because the adjacent dx changes."""

    interior = ConservedVector(area=20.0, discharge=50.0)
    upstream = _upstream(45.0)
    downstream = _downstream(2.2)
    fine = _rectangular_cell(dx=5.0)
    coarse = _rectangular_cell(dx=500.0)

    assert upstream.ghost_state(time=0.0, interior=interior, cell=fine) == pytest.approx(
        upstream.ghost_state(time=0.0, interior=interior, cell=coarse)
    )
    assert downstream.ghost_state(
        time=0.0,
        interior=interior,
        cell=fine,
    ) == pytest.approx(
        downstream.ghost_state(time=0.0, interior=interior, cell=coarse)
    )


def test_integrator_uses_one_completed_trace_flux_not_a_mixed_hll_flux() -> None:
    """Non-matching Q/H traces must supply both mass and momentum face fluxes."""

    cell = _rectangular_cell(dx=50.0)
    mesh = FiniteVolumeMesh((cell,))
    interior = ConservedVector(area=20.0, discharge=50.0)
    state = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=(interior.area,),
        discharge=(interior.discharge,),
        dry_depth=1.0e-3,
    )
    boundaries = BoundaryPair(_upstream(45.0), _downstream(2.2))
    upstream_trace = boundaries.upstream.ghost_state(
        time=0.0,
        interior=interior,
        cell=cell,
    )
    downstream_trace = boundaries.downstream.ghost_state(
        time=0.0,
        interior=interior,
        cell=cell,
    )
    upstream_flux = physical_flux(upstream_trace, cell.geometry)
    downstream_flux = physical_flux(downstream_trace, cell.geometry)
    dt = 0.1

    stage = forward_euler_stage(
        mesh=mesh,
        state=state,
        dt=dt,
        dry_depth=1.0e-3,
        boundaries=boundaries,
    )
    expected_area = interior.area - dt / cell.dx * (
        downstream_flux.mass - upstream_flux.mass
    )
    expected_discharge = interior.discharge - dt / cell.dx * (
        downstream_flux.momentum - upstream_flux.momentum
    )
    assert stage.budget.upstream_flux == upstream_flux.mass
    assert stage.budget.downstream_flux == downstream_flux.mass
    assert stage.state.area == pytest.approx((expected_area,), abs=1.0e-12)
    assert stage.state.discharge == pytest.approx(
        (expected_discharge,),
        abs=1.0e-12,
    )

    # This assertion makes the regression sensitive to the former mixed
    # implementation (characteristic mass with HLL-derived momentum).
    upstream_hll = hydrostatic_interface_flux(
        upstream_trace,
        interior,
        cell,
        cell,
    )
    downstream_hll = hydrostatic_interface_flux(
        interior,
        downstream_trace,
        cell,
        cell,
    )
    mixed_discharge = interior.discharge - dt / cell.dx * (
        downstream_hll.momentum_left - upstream_hll.momentum_right
    )
    assert abs(stage.state.discharge[0] - mixed_discharge) > 1.0e-5


def test_tabulated_characteristic_completion_round_trips_the_same_state() -> None:
    """Numerical Phi quadrature is self-consistent for a tabulated Profile."""

    geometry = TabulatedSectionGeometry.from_points(
        ((0.0, 4.0), (5.0, 0.0), (15.0, 0.0), (20.0, 4.0))
    )
    cell = FiniteVolumeCell(
        cell_id="tabulated",
        dx=50.0,
        section_id="T-1",
        bed_elevation=0.0,
        geometry=geometry,
    )
    interior = ConservedVector(area=geometry.area(2.0), discharge=20.0)

    upstream_ghost = _upstream(20.0).ghost_state(
        time=0.0,
        interior=interior,
        cell=cell,
    )
    downstream_ghost = _downstream(2.0).ghost_state(
        time=0.0,
        interior=interior,
        cell=cell,
    )

    assert upstream_ghost.area == pytest.approx(interior.area, abs=1.0e-10)
    assert upstream_ghost.discharge == interior.discharge
    assert downstream_ghost.area == pytest.approx(interior.area, abs=1.0e-12)
    assert downstream_ghost.discharge == pytest.approx(
        interior.discharge,
        abs=1.0e-12,
    )


def test_nonmatching_tabulated_traces_match_independent_phi_reference() -> None:
    """Non-rectangular Q/H traces preserve R-/R+ against independent Phi."""

    geometry = TabulatedSectionGeometry.from_points(
        (
            (0.0, 5.0),
            (2.0, 1.0),
            (4.0, 0.0),
            (8.0, 0.5),
            (12.0, 0.0),
            (15.0, 3.0),
            (20.0, 5.0),
        )
    )
    cell = FiniteVolumeCell(
        cell_id="compound-tabulated",
        dx=50.0,
        section_id="T-compound",
        bed_elevation=0.0,
        geometry=geometry,
    )
    interior_stage = 2.0
    interior = ConservedVector(
        area=geometry.area(interior_stage),
        discharge=9.625,
    )
    upstream = _upstream(11.06875).ghost_state(
        time=0.0,
        interior=interior,
        cell=cell,
    )
    downstream_stage = 2.1
    downstream = _downstream(downstream_stage).ghost_state(
        time=0.0,
        interior=interior,
        cell=cell,
    )

    interior_phi = _independent_tabulated_phi(geometry, interior_stage)
    upstream_phi = _independent_tabulated_phi(
        geometry,
        geometry.stage_from_area(upstream.area),
    )
    downstream_phi = _independent_tabulated_phi(geometry, downstream_stage)
    interior_velocity = interior.discharge / interior.area
    upstream_velocity = upstream.discharge / upstream.area
    downstream_velocity = downstream.discharge / downstream.area

    assert upstream.discharge == 11.06875
    assert upstream.area != pytest.approx(interior.area, abs=1.0e-6)
    assert downstream.area == pytest.approx(geometry.area(downstream_stage))
    assert downstream.discharge != pytest.approx(interior.discharge, abs=1.0e-6)
    assert upstream_velocity - upstream_phi == pytest.approx(
        interior_velocity - interior_phi,
        abs=2.0e-8,
    )
    assert downstream_velocity + downstream_phi == pytest.approx(
        interior_velocity + interior_phi,
        abs=2.0e-8,
    )


@pytest.mark.parametrize("froude", [1.0, 1.1])
def test_characteristic_boundary_rejects_critical_and_supercritical_interior(
    froude: float,
) -> None:
    """A one-condition subcritical closure cannot run at or above criticality."""

    cell = _rectangular_cell()
    area = 20.0
    celerity = math.sqrt(GRAVITY * area / 10.0)
    interior = ConservedVector(area, froude * area * celerity)

    with pytest.raises(ValueError, match="strictly subcritical"):
        _upstream(50.0).ghost_state(time=0.0, interior=interior, cell=cell)
    with pytest.raises(ValueError, match="strictly subcritical"):
        _downstream(2.0).ghost_state(time=0.0, interior=interior, cell=cell)


def test_characteristic_boundary_rejects_dry_reverse_and_supercritical_completion() -> None:
    """Dry states, reverse upstream Q and a supercritical completed root fail closed."""

    cell = _rectangular_cell()
    dry = ConservedVector(0.0, 0.0)
    interior = ConservedVector(20.0, 50.0)
    reverse_interior = ConservedVector(20.0, -10.0)

    with pytest.raises(ValueError, match="must be wet"):
        _upstream(10.0).ghost_state(time=0.0, interior=dry, cell=cell)
    with pytest.raises(ValueError, match="does not support reverse discharge"):
        _upstream(10.0).ghost_state(
            time=0.0,
            interior=reverse_interior,
            cell=cell,
        )
    with pytest.raises(ValueError, match="does not support reverse upstream Q"):
        _upstream(-1.0).ghost_state(time=0.0, interior=interior, cell=cell)
    with pytest.raises(ValueError, match="does not support reverse discharge"):
        _downstream(3.5).ghost_state(time=0.0, interior=interior, cell=cell)
    with pytest.raises(ValueError, match="completed upstream.*strictly subcritical"):
        _upstream(300.0).ghost_state(time=0.0, interior=interior, cell=cell)
    with pytest.raises(ValueError, match="completed downstream.*strictly subcritical"):
        _downstream(0.05).ghost_state(time=0.0, interior=interior, cell=cell)


def test_roundoff_negative_q_is_zeroed_but_material_reverse_flow_is_rejected() -> None:
    """Only an area-celerity-scaled round-off band may normalize to Q=0."""

    cell = _rectangular_cell()
    roundoff_state = ConservedVector(20.0, -1.0e-13)
    upstream = _upstream(-1.0e-13).ghost_state(
        time=0.0,
        interior=roundoff_state,
        cell=cell,
    )
    downstream = _downstream(2.0).ghost_state(
        time=0.0,
        interior=roundoff_state,
        cell=cell,
    )

    assert upstream.area == pytest.approx(20.0, abs=1.0e-11)
    assert upstream.discharge == 0.0
    assert downstream.area == 20.0
    assert downstream.discharge == pytest.approx(0.0, abs=1.0e-14)
    with pytest.raises(ValueError, match="does not support reverse discharge"):
        _upstream(0.0).ghost_state(
            time=0.0,
            interior=ConservedVector(20.0, -1.0e-6),
            cell=cell,
        )


def test_characteristic_boundary_rejects_no_root_and_out_of_domain_stage() -> None:
    """Finite Profile limits are hard domains, not extrapolation suggestions."""

    geometry = TabulatedSectionGeometry.from_points(
        ((0.0, 4.0), (5.0, 0.0), (15.0, 0.0), (20.0, 4.0))
    )
    cell = FiniteVolumeCell(
        cell_id="finite-tabulated",
        dx=50.0,
        section_id="T-1",
        bed_elevation=0.0,
        geometry=geometry,
    )
    interior = ConservedVector(geometry.area(2.0), 20.0)

    with pytest.raises(ValueError, match="root lies outside the section domain"):
        _upstream(10_000.0).ghost_state(time=0.0, interior=interior, cell=cell)
    with pytest.raises(ValueError, match="H lies outside the section domain"):
        _downstream(5.0).ghost_state(time=0.0, interior=interior, cell=cell)
    with pytest.raises(ValueError, match="H must be above the bed"):
        _downstream(0.0).ghost_state(time=0.0, interior=interior, cell=cell)


def test_dynamic_characteristic_series_interpolates_without_extrapolation() -> None:
    """Characteristic completion retains the frozen series coverage contract."""

    cell = _rectangular_cell()
    interior = ConservedVector(20.0, 50.0)
    boundary = UpstreamDischargeBoundary(
        BoundarySeries((0.0, 5.0, 10.0), (40.0, 50.0, 45.0), "discharge"),
        boundary_closure=SUBCRITICAL_CHARACTERISTIC_V1,
    )

    completed = boundary.ghost_state(time=2.5, interior=interior, cell=cell)
    assert completed.discharge == 45.0
    with pytest.raises(BoundaryCoverageError):
        boundary.ghost_state(time=-0.01, interior=interior, cell=cell)
    with pytest.raises(BoundaryCoverageError):
        boundary.ghost_state(time=10.01, interior=interior, cell=cell)


@pytest.mark.parametrize(
    ("cell_count", "dx", "maximum_dt"),
    [(8, 100.0, 1.0), (32, 25.0, 0.25)],
)
def test_characteristic_uniform_flow_residual_survives_grid_and_dt_refinement(
    cell_count: int,
    dx: float,
    maximum_dt: float,
) -> None:
    """A matching flat-bed subcritical state has zero boundary residual."""

    cells = tuple(
        FiniteVolumeCell(
            cell_id=f"cell-{index}",
            dx=dx,
            section_id=f"CS-{index}",
            bed_elevation=0.0,
            geometry=RectangularSectionGeometry(10.0, 0.0),
            manning_n=0.0,
        )
        for index in range(cell_count)
    )
    mesh = FiniteVolumeMesh(cells)
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=(20.0,) * cell_count,
        discharge=(20.0,) * cell_count,
        dry_depth=1.0e-3,
    )
    boundaries = BoundaryPair(_upstream(20.0), _downstream(2.0))
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=boundaries,
        config=SingleBranchConfig(
            end_time=10.0,
            maximum_dt=maximum_dt,
            output_interval=5.0,
        ),
    )

    final = result.states[-1]
    assert final.area == pytest.approx(initial.area, abs=1.0e-11)
    assert final.discharge == pytest.approx(initial.discharge, abs=1.0e-11)
    assert result.diagnostics.relative_water_balance_error < 1.0e-12
