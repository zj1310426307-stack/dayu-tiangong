"""Scientific acceptance tests for the HYDRO-MODEL-02-C3a foundation."""

from dataclasses import replace

import pytest

from model.geometry.sections import RectangularSectionGeometry
from model.solver.finite_volume import (
    FiniteVolumeCell,
    FiniteVolumeMesh,
    FiniteVolumeNetwork,
    GatePlacement,
    HydraulicState,
    InternalStructureStageEvidence,
    JunctionTrace,
    NetworkBranch,
    PiecewiseManningZoneSolver,
    PumpPlacement,
    RoughnessZone,
    RoughnessZoneSolver,
    StructurePlacementPlan,
    apply_manning_friction,
    inspect_junction_preclosure,
)


def make_branch_mesh(branch_id: str, *, cell_count: int = 3) -> FiniteVolumeMesh:
    """Build one identity-stable rectangular Branch mesh."""

    geometry = RectangularSectionGeometry(width=10.0, bed_elevation=0.0)
    return FiniteVolumeMesh(
        branch_id=branch_id,
        cells=tuple(
            FiniteVolumeCell(
                cell_id=f"{branch_id}-cell-{index}",
                dx=100.0,
                section_id=f"{branch_id}-section-{index}",
                bed_elevation=0.0,
                geometry=geometry,
            )
            for index in range(cell_count)
        ),
    )


def make_bifurcation_network() -> FiniteVolumeNetwork:
    """Build one connected 1-in/2-out acyclic topology."""

    return FiniteVolumeNetwork(
        branches=(
            NetworkBranch(make_branch_mesh("B0"), "source", "J1"),
            NetworkBranch(make_branch_mesh("B1"), "J1", "sink-1"),
            NetworkBranch(make_branch_mesh("B2"), "J1", "sink-2"),
        )
    )


def make_state(mesh: FiniteVolumeMesh, *, time: float = 0.0) -> HydraulicState:
    """Build one fully wet accepted Branch state."""

    return HydraulicState.from_conserved(
        mesh=mesh,
        time=time,
        area=[cell.geometry.area(1.0) for cell in mesh.cells],
        discharge=[0.0 for _ in mesh.cells],
        dry_depth=1.0e-3,
    )


def test_network_foundation_derives_incidence_and_deterministic_order() -> None:
    """A bifurcation keeps exact directed incidence without legacy routing."""

    network = make_bifurcation_network()
    junction = network.incidence("J1")

    assert network.topological_branch_order == ("B0", "B1", "B2")
    assert junction.incoming_branch_ids == ("B0",)
    assert junction.outgoing_branch_ids == ("B1", "B2")
    assert junction.is_internal


def test_network_foundation_rejects_cycles_and_disconnected_components() -> None:
    """The C3a DAG boundary fails closed before a network solve can start."""

    with pytest.raises(ValueError, match="directed cycle"):
        FiniteVolumeNetwork(
            branches=(
                NetworkBranch(make_branch_mesh("B0"), "N0", "N1"),
                NetworkBranch(make_branch_mesh("B1"), "N1", "N0"),
            )
        )

    with pytest.raises(ValueError, match="weakly connected"):
        FiniteVolumeNetwork(
            branches=(
                NetworkBranch(make_branch_mesh("B0"), "N0", "N1"),
                NetworkBranch(make_branch_mesh("B1"), "N2", "N3"),
            )
        )


def test_network_states_must_exactly_cover_branches_at_one_time() -> None:
    """Future orchestration cannot mix missing, stale, or wrong-sized states."""

    network = make_bifurcation_network()
    states = {
        branch.branch_id: make_state(branch.mesh, time=12.5)
        for branch in network.branches
    }

    assert network.validate_synchronized_states(states) == pytest.approx(12.5)
    with pytest.raises(ValueError, match="exactly cover"):
        network.validate_synchronized_states({"B0": states["B0"]})
    stale = {**states, "B2": make_state(network.branch("B2").mesh, time=12.0)}
    with pytest.raises(ValueError, match="one accepted time"):
        network.validate_synchronized_states(stale)


def test_junction_preclosure_proves_mass_and_stage_but_not_momentum() -> None:
    """A mass-balanced node remains explicitly below strong-coupling status."""

    network = make_bifurcation_network()
    traces = (
        JunctionTrace("J1", "B0", "downstream", 10.0, 20.0, 10.0),
        JunctionTrace("J1", "B1", "upstream", 10.0, 12.0, 6.0),
        JunctionTrace("J1", "B2", "upstream", 10.0, 8.0, 4.0),
    )

    evidence = inspect_junction_preclosure(
        network=network,
        node_id="J1",
        traces=traces,
        time=30.0,
        stage_tolerance=1.0e-9,
        mass_tolerance=1.0e-12,
    )

    assert evidence.preliminary_passed
    assert evidence.net_flow_into_node == pytest.approx(0.0)
    assert evidence.maximum_stage_spread == pytest.approx(0.0)
    assert evidence.momentum_compatibility == "not-implemented"
    assert evidence.strong_coupling_ready is False


def test_junction_preclosure_reports_failed_mass_or_stage_and_rejects_wrong_side() -> None:
    """Pre-closure cannot hide a residual or contradict Branch orientation."""

    network = make_bifurcation_network()
    failed = inspect_junction_preclosure(
        network=network,
        node_id="J1",
        traces=(
            JunctionTrace("J1", "B0", "downstream", 10.0, 20.0, 10.0),
            JunctionTrace("J1", "B1", "upstream", 10.01, 12.0, 5.0),
            JunctionTrace("J1", "B2", "upstream", 10.0, 8.0, 4.0),
        ),
        time=30.0,
        stage_tolerance=1.0e-3,
        mass_tolerance=1.0e-3,
    )
    assert failed.preliminary_passed is False
    assert failed.net_flow_into_node == pytest.approx(1.0)
    with pytest.raises(ValueError, match="contradicts its residuals"):
        replace(failed, preliminary_passed=True)

    with pytest.raises(ValueError, match="orientation"):
        inspect_junction_preclosure(
            network=network,
            node_id="J1",
            traces=(
                JunctionTrace("J1", "B0", "upstream", 10.0, 20.0, 10.0),
                JunctionTrace("J1", "B1", "upstream", 10.0, 12.0, 6.0),
                JunctionTrace("J1", "B2", "upstream", 10.0, 8.0, 4.0),
            ),
            time=30.0,
            stage_tolerance=1.0e-9,
            mass_tolerance=1.0e-12,
        )


def test_piecewise_manning_zones_resolve_exact_cells_and_drive_friction() -> None:
    """Resolved cell coefficients are consumed by the existing stage friction."""

    mesh = make_branch_mesh("B0")
    solver = PiecewiseManningZoneSolver(
        zones=(
            RoughnessZone("R0", "B0", 0.0, 100.0, 0.02),
            RoughnessZone("R1", "B0", 100.0, 300.0, 0.04),
        )
    )

    assert isinstance(solver, RoughnessZoneSolver)
    resolved = solver.resolve_mesh(mesh=mesh, branch_start_chainage_m=0.0)
    assert tuple(cell.manning_n for cell in resolved.mesh.cells) == (0.02, 0.04, 0.04)
    assert tuple(item.zone_id for item in resolved.assignments) == ("R0", "R1", "R1")
    damped = apply_manning_friction(
        mesh=resolved.mesh,
        area=(10.0, 10.0, 10.0),
        discharge=(5.0, 5.0, 5.0),
        dt=10.0,
    )
    assert damped[1] == pytest.approx(damped[2])
    assert 0.0 < damped[1] < damped[0] < 5.0


@pytest.mark.parametrize(
    "zones, message",
    (
        (
            (
                RoughnessZone("R0", "B0", 0.0, 100.0, 0.02),
                RoughnessZone("R1", "B0", 101.0, 300.0, 0.04),
            ),
            "gaps or overlaps",
        ),
        (
            (
                RoughnessZone("R0", "B0", 0.0, 150.0, 0.02),
                RoughnessZone("R1", "B0", 150.0, 300.0, 0.04),
            ),
            "align with finite-volume faces",
        ),
    ),
)
def test_piecewise_manning_zones_reject_gaps_and_cell_splits(
    zones: tuple[RoughnessZone, ...],
    message: str,
) -> None:
    """A zone partition cannot silently interpolate or split a control volume."""

    solver = PiecewiseManningZoneSolver(zones=zones)
    with pytest.raises(ValueError, match=message):
        solver.resolve_mesh(mesh=make_branch_mesh("B0"), branch_start_chainage_m=0.0)


def test_structure_placement_plan_resolves_gate_and_internal_pump_targets() -> None:
    """Stable identities replace face/cell guessing before strong coupling."""

    network = make_bifurcation_network()
    plan = StructurePlacementPlan(
        network=network,
        gates=(GatePlacement("G1", "B0", "B0-cell-0", "B0-cell-1"),),
        pumps=(
            PumpPlacement(
                "P1",
                "B1",
                "B1-cell-0",
                "network-cell",
                "B2",
                "B2-cell-0",
            ),
        ),
    )

    assert plan.requires_internal_pump_coupling
    with pytest.raises(ValueError, match="ordered adjacent-cell"):
        StructurePlacementPlan(
            network=network,
            gates=(GatePlacement("G2", "B0", "B0-cell-1", "B0-cell-0"),),
        )


def test_internal_gate_and_pump_evidence_requires_every_strong_closure() -> None:
    """Only common mass plus energy/device-work and momentum may pass."""

    gate = InternalStructureStageEvidence(
        structure_id="G1",
        structure_type="gate",
        evaluation_time=1.0,
        source_outflow=10.0,
        target_inflow=10.0,
        source_area=20.0,
        target_area=18.0,
        source_total_head=12.0,
        target_total_head=11.5,
        device_head_gain=0.0,
        hydraulic_head_loss=0.5,
        source_momentum_flux=100.0,
        target_momentum_flux=90.0,
        reaction_force_per_density=-10.0,
        equation_iterations=20,
    )
    pump = InternalStructureStageEvidence(
        structure_id="P1",
        structure_type="pump",
        evaluation_time=1.0,
        source_outflow=3.0,
        target_inflow=3.0,
        source_area=12.0,
        target_area=9.0,
        source_total_head=10.0,
        target_total_head=12.0,
        device_head_gain=2.2,
        hydraulic_head_loss=0.2,
        source_momentum_flux=80.0,
        target_momentum_flux=85.0,
        reaction_force_per_density=5.0,
        equation_iterations=12,
    )

    assert gate.strong_coupling_ready
    assert pump.strong_coupling_ready
    assert gate.mass_residual == pytest.approx(0.0)
    assert pump.energy_residual == pytest.approx(0.0, abs=1.0e-12)
    with pytest.raises(ValueError, match="mass closure"):
        replace(gate, target_inflow=9.9)
    with pytest.raises(ValueError, match="energy closure"):
        replace(pump, device_head_gain=1.0)
    with pytest.raises(ValueError, match="momentum closure"):
        replace(gate, reaction_force_per_density=-9.0)
    with pytest.raises(ValueError, match="must not invent"):
        replace(gate, device_head_gain=0.1, target_total_head=11.6)
