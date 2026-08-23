"""Scientific contracts for the restricted C3b-J1 Junction solve."""

from dataclasses import replace
import math

import pytest

from model.geometry.sections import RectangularSectionGeometry, TabulatedSectionGeometry
from model.solver.finite_volume import (
    GRAVITY,
    FiniteVolumeCell,
    FiniteVolumeMesh,
    FiniteVolumeNetwork,
    HydraulicState,
    JunctionSolverConfig,
    NetworkBranch,
    NodeSolver,
    OneInTwoOutJunctionSolver,
    solve_one_in_two_out_junction,
)


def make_mesh(
    branch_id: str,
    geometry: RectangularSectionGeometry | TabulatedSectionGeometry,
    *,
    manning_n: float = 0.0,
) -> FiniteVolumeMesh:
    """Build a two-cell Branch with stable global cell identities."""

    return FiniteVolumeMesh(
        branch_id=branch_id,
        cells=tuple(
            FiniteVolumeCell(
                cell_id=f"{branch_id}-cell-{index}",
                dx=100.0,
                section_id=f"{branch_id}-section-{index}",
                bed_elevation=float(geometry.minimum_stage),
                geometry=geometry,
                manning_n=manning_n,
            )
            for index in range(2)
        ),
    )


def make_network(
    geometries: tuple[
        RectangularSectionGeometry | TabulatedSectionGeometry,
        RectangularSectionGeometry | TabulatedSectionGeometry,
        RectangularSectionGeometry | TabulatedSectionGeometry,
    ],
    *,
    manning: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> FiniteVolumeNetwork:
    """Build one directed 1-in/2-out Junction topology."""

    meshes = tuple(
        make_mesh(f"B{index}", geometry, manning_n=coefficient)
        for index, (geometry, coefficient) in enumerate(zip(geometries, manning))
    )
    return FiniteVolumeNetwork(
        branches=(
            NetworkBranch(meshes[0], "source", "J1"),
            NetworkBranch(meshes[1], "J1", "sink-1"),
            NetworkBranch(meshes[2], "J1", "sink-2"),
        )
    )


def make_states(
    network: FiniteVolumeNetwork,
    stages: tuple[float, float, float],
    discharges: tuple[float, float, float],
    *,
    time: float = 30.0,
) -> dict[str, HydraulicState]:
    """Build uniform Branch states while preserving each local geometry."""

    result = {}
    for branch, stage, discharge in zip(network.branches, stages, discharges):
        result[branch.branch_id] = HydraulicState.from_conserved(
            mesh=branch.mesh,
            time=time,
            area=[cell.geometry.area(stage) for cell in branch.mesh.cells],
            discharge=[discharge for _ in branch.mesh.cells],
            dry_depth=1.0e-3,
        )
    return result


def rectangular_network(
    widths: tuple[float, float, float] = (10.0, 10.0, 10.0),
    *,
    maximum_stage: float | None = None,
) -> FiniteVolumeNetwork:
    """Build a flat-datum rectangular Junction network."""

    return make_network(
        tuple(
            RectangularSectionGeometry(
                width=width,
                bed_elevation=0.0,
                maximum_stage=maximum_stage,
            )
            for width in widths
        )
    )


def independent_rectangular_reference(
    *,
    widths: tuple[float, float, float],
    stages: tuple[float, float, float],
    discharges: tuple[float, float, float],
) -> tuple[float, tuple[float, float, float]]:
    """Solve the rectangular Junction without calling production Phi code."""

    invariants = (
        discharges[0] / (widths[0] * stages[0])
        + 2.0 * math.sqrt(GRAVITY * stages[0]),
        discharges[1] / (widths[1] * stages[1])
        - 2.0 * math.sqrt(GRAVITY * stages[1]),
        discharges[2] / (widths[2] * stages[2])
        - 2.0 * math.sqrt(GRAVITY * stages[2]),
    )

    def flows(stage: float) -> tuple[float, float, float]:
        potential = 2.0 * math.sqrt(GRAVITY * stage)
        return (
            widths[0] * stage * (invariants[0] - potential),
            widths[1] * stage * (invariants[1] + potential),
            widths[2] * stage * (invariants[2] + potential),
        )

    lower = 1.0e-8
    upper = 8.0
    for _ in range(200):
        midpoint = 0.5 * (lower + upper)
        values = flows(midpoint)
        if values[0] - values[1] - values[2] > 0.0:
            lower = midpoint
        else:
            upper = midpoint
    stage = 0.5 * (lower + upper)
    return stage, flows(stage)


def test_rectangular_balanced_state_round_trips_exact_junction_traces() -> None:
    """A compatible state returns the same common stage and 10=4+6 split."""

    network = rectangular_network()
    states = make_states(network, (2.0, 2.0, 2.0), (10.0, 4.0, 6.0))
    solver = OneInTwoOutJunctionSolver()

    assert isinstance(solver, NodeSolver)
    result = solver.solve_node_stage(network=network, node_id="J1", states=states)
    by_branch = {state.branch_id: state for state in result.boundary_states}

    assert result.evidence.common_stage == pytest.approx(2.0, abs=1.0e-9)
    assert by_branch["B0"].discharge == pytest.approx(10.0, abs=1.0e-8)
    assert by_branch["B1"].discharge == pytest.approx(4.0, abs=1.0e-8)
    assert by_branch["B2"].discharge == pytest.approx(6.0, abs=1.0e-8)
    assert result.preclosure.preliminary_passed
    assert result.evidence.characteristic_compatibility_ready
    assert result.evidence.momentum_compatibility == (
        "not-evaluated-no-branch-angle-v1"
    )
    assert result.evidence.strong_coupling_ready is False
    assert result.evidence.maximum_normalized_invariant_residual <= 1.0e-12
    assert result.evidence.mass_residual_stage_derivative < 0.0
    assert result.evidence.bracket_start_mass_residual >= 0.0
    assert result.evidence.bracket_end_mass_residual <= 0.0


def test_rectangular_perturbation_matches_independent_analytic_reference() -> None:
    """Non-equilibrium interior traces match an independent analytic bisection."""

    widths = (12.0, 8.0, 6.0)
    stages = (2.2, 1.8, 1.6)
    discharges = (12.0, 5.0, 4.0)
    expected_stage, expected_flows = independent_rectangular_reference(
        widths=widths,
        stages=stages,
        discharges=discharges,
    )
    network = rectangular_network(widths)
    result = solve_one_in_two_out_junction(
        network=network,
        node_id="J1",
        states=make_states(network, stages, discharges),
    )
    actual = {state.branch_id: state.discharge for state in result.boundary_states}

    assert result.evidence.common_stage == pytest.approx(expected_stage, abs=2.0e-10)
    assert actual["B0"] == pytest.approx(expected_flows[0], abs=2.0e-8)
    assert actual["B1"] == pytest.approx(expected_flows[1], abs=2.0e-8)
    assert actual["B2"] == pytest.approx(expected_flows[2], abs=2.0e-8)
    assert actual["B0"] == pytest.approx(actual["B1"] + actual["B2"], abs=2.0e-8)
    assert result.evidence.maximum_froude < 1.0
    assert all(state.momentum_flux_per_density > 0.0 for state in result.boundary_states)


def test_nonmatching_tabulated_sections_round_trip_one_common_stage() -> None:
    """The same characteristic closure supports three different Profile shapes."""

    geometries = (
        TabulatedSectionGeometry.from_points(((-5.0, 4.0), (0.0, 0.0), (5.0, 4.0))),
        TabulatedSectionGeometry.from_points(
            ((-4.0, 4.0), (-1.0, 0.0), (3.0, 0.0), (6.0, 4.0))
        ),
        TabulatedSectionGeometry.from_points(((-3.0, 3.0), (0.0, 0.2), (4.0, 3.0))),
    )
    network = make_network(geometries)
    states = make_states(network, (2.2, 2.2, 2.2), (6.0, 2.5, 3.5))

    result = solve_one_in_two_out_junction(
        network=network,
        node_id="J1",
        states=states,
    )
    by_branch = {state.branch_id: state for state in result.boundary_states}

    assert result.evidence.common_stage == pytest.approx(2.2, abs=2.0e-9)
    assert by_branch["B0"].discharge == pytest.approx(6.0, abs=2.0e-8)
    assert by_branch["B1"].discharge == pytest.approx(2.5, abs=2.0e-8)
    assert by_branch["B2"].discharge == pytest.approx(3.5, abs=2.0e-8)
    assert {state.invariant_family for state in result.boundary_states} == {"R+", "R-"}


@pytest.mark.parametrize(
    "stage_tolerance,mass_tolerance",
    ((1.0e-4, 1.0e-4), (1.0e-6, 1.0e-6), (1.0e-8, 1.0e-8)),
)
def test_junction_root_respects_refined_stage_and_mass_tolerances(
    stage_tolerance: float,
    mass_tolerance: float,
) -> None:
    """Every accepted root carries a bracket and residual below its own policy."""

    widths = (12.0, 8.0, 6.0)
    stages = (2.2, 1.8, 1.6)
    discharges = (12.0, 5.0, 4.0)
    expected_stage, _ = independent_rectangular_reference(
        widths=widths,
        stages=stages,
        discharges=discharges,
    )
    network = rectangular_network(widths)
    result = solve_one_in_two_out_junction(
        network=network,
        node_id="J1",
        states=make_states(network, stages, discharges),
        config=JunctionSolverConfig(
            stage_tolerance_m=stage_tolerance,
            normalized_mass_tolerance=mass_tolerance,
        ),
    )

    assert abs(result.evidence.common_stage - expected_stage) <= stage_tolerance
    assert result.evidence.final_bracket_width <= stage_tolerance
    assert result.evidence.normalized_mass_residual <= mass_tolerance


def test_junction_rejects_wrong_topology_reverse_supercritical_and_friction() -> None:
    """Every assumption named by C3b-J1 is enforced before accepting a root."""

    geometry = RectangularSectionGeometry(width=10.0, bed_elevation=0.0)
    merger = FiniteVolumeNetwork(
        branches=(
            NetworkBranch(make_mesh("B0", geometry), "source-0", "J1"),
            NetworkBranch(make_mesh("B1", geometry), "source-1", "J1"),
            NetworkBranch(make_mesh("B2", geometry), "J1", "sink"),
        )
    )
    with pytest.raises(ValueError, match="one incoming and two outgoing"):
        solve_one_in_two_out_junction(
            network=merger,
            node_id="J1",
            states=make_states(merger, (2.0, 2.0, 2.0), (4.0, 6.0, 10.0)),
        )

    network = rectangular_network()
    reverse = make_states(network, (2.0, 2.0, 2.0), (10.0, -1.0, 11.0))
    with pytest.raises(ValueError, match="reverse discharge"):
        solve_one_in_two_out_junction(network=network, node_id="J1", states=reverse)

    supercritical = make_states(network, (0.1, 2.0, 2.0), (2.0, 1.0, 1.0))
    with pytest.raises(ValueError, match="strictly subcritical"):
        solve_one_in_two_out_junction(
            network=network,
            node_id="J1",
            states=supercritical,
        )

    rough_network = make_network((geometry, geometry, geometry), manning=(0.0, 0.03, 0.0))
    with pytest.raises(ValueError, match="zero-friction endpoint"):
        solve_one_in_two_out_junction(
            network=rough_network,
            node_id="J1",
            states=make_states(rough_network, (2.0, 2.0, 2.0), (10.0, 4.0, 6.0)),
        )


def test_junction_rejects_no_common_domain_outside_root_and_nonconvergence() -> None:
    """Finite Profile ceilings and iteration limits fail closed."""

    low_profile = TabulatedSectionGeometry.from_points(
        ((-2.0, 1.0), (0.0, 0.0), (2.0, 1.0))
    )
    high_profile = TabulatedSectionGeometry.from_points(
        ((-2.0, 3.0), (0.0, 1.5), (2.0, 3.0))
    )
    network = make_network((low_profile, high_profile, high_profile))
    with pytest.raises(ValueError, match="no common wet stage domain"):
        solve_one_in_two_out_junction(
            network=network,
            node_id="J1",
            states=make_states(network, (0.8, 2.0, 2.0), (0.2, 0.08, 0.12)),
        )

    finite_network = rectangular_network(maximum_stage=2.03)
    with pytest.raises(ValueError, match="outside the common section domain"):
        solve_one_in_two_out_junction(
            network=finite_network,
            node_id="J1",
            states=make_states(finite_network, (2.0, 2.0, 2.0), (10.0, 1.0, 1.0)),
        )

    unbounded = rectangular_network((12.0, 8.0, 6.0))
    with pytest.raises(ValueError, match="did not converge"):
        solve_one_in_two_out_junction(
            network=unbounded,
            node_id="J1",
            states=make_states(unbounded, (2.2, 1.8, 1.6), (12.0, 5.0, 4.0)),
            config=JunctionSolverConfig(maximum_iterations=1),
        )


def test_junction_evidence_cannot_be_relabelled_as_vector_momentum_closure() -> None:
    """Characteristic compatibility remains distinct from full node momentum."""

    network = rectangular_network()
    result = solve_one_in_two_out_junction(
        network=network,
        node_id="J1",
        states=make_states(network, (2.0, 2.0, 2.0), (10.0, 4.0, 6.0)),
    )

    with pytest.raises(ValueError, match="must not claim vector momentum"):
        replace(result.evidence, momentum_compatibility="balanced")
    with pytest.raises(ValueError, match="not a full momentum-coupled"):
        replace(result.evidence, strong_coupling_ready=True)
    with pytest.raises(ValueError, match="mass residual exceeds"):
        replace(
            result.evidence,
            normalized_mass_residual=1.0,
            absolute_mass_residual=1.0,
        )
    with pytest.raises(ValueError, match="decrease locally"):
        replace(result.evidence, mass_residual_stage_derivative=1.0)
    with pytest.raises(ValueError, match="lower bracket"):
        replace(result.evidence, bracket_start_mass_residual=-1.0)
