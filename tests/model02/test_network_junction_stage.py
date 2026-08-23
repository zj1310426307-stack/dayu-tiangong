"""Scientific gates for the restricted C3b-J2 synchronized network advance."""

from dataclasses import replace
import math

import pytest

from model.geometry.sections import RectangularSectionGeometry
from model.solver.finite_volume import (
    BoundarySeries,
    BoundaryCoverageError,
    BranchNetworkSolver,
    BranchDownstreamBoundary,
    DownstreamStageBoundary,
    FiniteVolumeCell,
    FiniteVolumeMesh,
    FiniteVolumeNetwork,
    HydraulicState,
    NetworkBranch,
    OneInTwoOutBoundarySet,
    OneInTwoOutJunctionSolver,
    OneInTwoOutNetworkConfig,
    OneInTwoOutNetworkSolver,
    StabilityError,
    UpstreamDischargeBoundary,
    advance_network_with_retries,
    estimate_network_cfl_time_step,
    network_storage,
    one_in_two_out_network_ssp_rk2_step,
    solve_one_in_two_out_network,
)
from model.solver.finite_volume import network_solver as network_solver_module

_CHARACTERISTIC = "subcritical-characteristic-v1"


def make_mesh(
    branch_id: str,
    width: float,
    *,
    dx: float = 100.0,
    cell_count: int = 3,
    manning_n: float = 0.0,
    width_increment: float = 0.0,
) -> FiniteVolumeMesh:
    """Build a flat Branch, optionally violating the prismatic J2 gate."""

    cells = []
    for index in range(cell_count):
        geometry = RectangularSectionGeometry(
            width=width + width_increment * index,
            bed_elevation=0.0,
        )
        cells.append(
            FiniteVolumeCell(
                cell_id=f"{branch_id}-cell-{index}",
                dx=dx,
                section_id=f"{branch_id}-section-{index}",
                bed_elevation=0.0,
                geometry=geometry,
                manning_n=manning_n,
            )
        )
    return FiniteVolumeMesh(branch_id=branch_id, cells=tuple(cells))


def make_network(
    *,
    widths: tuple[float, float, float] = (10.0, 10.0, 10.0),
    dxs: tuple[float, float, float] = (100.0, 100.0, 100.0),
    manning: tuple[float, float, float] = (0.0, 0.0, 0.0),
    width_increments: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> FiniteVolumeNetwork:
    """Build the sole 1-in/2-out graph accepted by C3b-J2."""

    meshes = tuple(
        make_mesh(
            f"B{index}",
            width,
            dx=dx,
            manning_n=manning_n,
            width_increment=width_increment,
        )
        for index, (width, dx, manning_n, width_increment) in enumerate(
            zip(widths, dxs, manning, width_increments)
        )
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
    *,
    stages: tuple[float, float, float] = (2.0, 2.0, 2.0),
    discharges: tuple[float, float, float] = (10.0, 4.0, 6.0),
    time: float = 0.0,
) -> dict[str, HydraulicState]:
    """Build uniform fully wet Branch states against local section widths."""

    result = {}
    for branch, stage, discharge in zip(network.branches, stages, discharges):
        result[branch.branch_id] = HydraulicState.from_conserved(
            mesh=branch.mesh,
            time=time,
            area=tuple(cell.geometry.area(stage) for cell in branch.mesh.cells),
            discharge=tuple(discharge for _ in branch.mesh.cells),
            dry_depth=1.0e-3,
        )
    return result


def make_boundaries(
    *,
    end_time: float,
    upstream_times: tuple[float, ...] | None = None,
    upstream_flows: tuple[float, ...] | None = None,
    downstream_stages: tuple[float, float] = (2.0, 2.0),
) -> OneInTwoOutBoundarySet:
    """Build exact characteristic Q/H processes for the three external ends."""

    times = upstream_times or (0.0, end_time)
    flows = upstream_flows or (10.0, 10.0)
    return OneInTwoOutBoundarySet(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries(times, flows, "discharge"),
            boundary_closure=_CHARACTERISTIC,
        ),
        downstream=tuple(
            BranchDownstreamBoundary(
                branch_id=f"B{index}",
                boundary=DownstreamStageBoundary(
                    BoundarySeries(
                        (0.0, end_time),
                        (stage, stage),
                        "stage",
                    ),
                    boundary_closure=_CHARACTERISTIC,
                ),
            )
            for index, stage in zip((1, 2), downstream_stages)
        ),
    )


def test_compatible_network_state_survives_synchronized_short_run() -> None:
    """Uniform 10=4+6 flow remains steady across both RK Junction solves."""

    network = make_network()
    initial = make_states(network)
    result = solve_one_in_two_out_network(
        network=network,
        initial_states=initial,
        boundaries=make_boundaries(end_time=20.0),
        config=OneInTwoOutNetworkConfig(
            end_time=20.0,
            maximum_dt=2.0,
            output_interval=5.0,
        ),
    )

    final = result.snapshots[-1].states
    for branch in network.branches:
        branch_id = branch.branch_id
        assert final[branch_id].area == pytest.approx(
            initial[branch_id].area,
            abs=2.0e-9,
        )
        assert final[branch_id].discharge == pytest.approx(
            initial[branch_id].discharge,
            abs=2.0e-8,
        )
    assert [snapshot.time for snapshot in result.snapshots] == pytest.approx(
        [0.0, 5.0, 10.0, 15.0, 20.0]
    )
    assert result.diagnostics.step_count == len(result.steps)
    assert result.diagnostics.junction_stage_count == 2 * len(result.steps)
    assert result.diagnostics.relative_water_balance_error < 1.0e-12
    assert result.diagnostics.water_balance_status == "pass"
    assert any(
        "vector_momentum_not_evaluated" in flag
        for flag in result.diagnostics.diagnostic_flags
    )


def test_each_rk_stage_resolves_junction_from_its_synchronized_states() -> None:
    """A nonuniform state produces two ordered node solves at t and t+dt."""

    network = make_network(widths=(12.0, 8.0, 6.0))
    states = make_states(
        network,
        stages=(2.2, 1.8, 1.6),
        discharges=(12.0, 5.0, 4.0),
    )
    result = one_in_two_out_network_ssp_rk2_step(
        network=network,
        states=states,
        dt=0.5,
        dry_depth=1.0e-3,
        boundaries=make_boundaries(
            end_time=1.0,
            upstream_flows=(12.0, 12.0),
            downstream_stages=(1.8, 1.6),
        ),
        cfl_limit=0.7,
    )

    first, second = result.junction_stages
    assert (first.time, second.time) == pytest.approx((0.0, 0.5))
    assert second.evidence.common_stage != pytest.approx(
        first.evidence.common_stage,
        abs=1.0e-12,
    )
    assert first.preclosure.preliminary_passed
    assert second.preclosure.preliminary_passed
    assert set(result.states) == {"B0", "B1", "B2"}
    assert {state.time for state in result.states.values()} == {0.5}


def test_global_cfl_reports_the_limiting_branch_and_cell() -> None:
    """The smallest Branch cell owns one shared network time step."""

    network = make_network(dxs=(100.0, 100.0, 10.0))
    states = make_states(network)
    estimate = estimate_network_cfl_time_step(
        network=network,
        states=states,
        cfl_number=0.7,
        maximum_dt=100.0,
    )

    assert estimate.limiting_branch_id == "B2"
    assert estimate.limiting_cell == 0
    assert 0.0 < estimate.time_step < 2.0
    assert estimate.maximum_signal_speed > 0.0


def test_transient_run_closes_external_and_junction_storage_ledgers() -> None:
    """A small inflow ramp conserves water with node transfer kept internal."""

    network = make_network()
    result = solve_one_in_two_out_network(
        network=network,
        initial_states=make_states(network),
        boundaries=make_boundaries(
            end_time=10.0,
            upstream_times=(0.0, 5.0, 10.0),
            upstream_flows=(10.0, 10.5, 10.0),
        ),
        config=OneInTwoOutNetworkConfig(
            end_time=10.0,
            maximum_dt=1.0,
            output_interval=2.0,
        ),
    )

    diagnostics = result.diagnostics
    storage_change = diagnostics.final_storage - diagnostics.initial_storage
    external_net = diagnostics.upstream_boundary_volume - sum(
        value for _, value in diagnostics.downstream_boundary_volumes
    )
    assert storage_change - external_net == pytest.approx(
        diagnostics.water_balance_residual,
        abs=1.0e-12,
    )
    assert diagnostics.water_balance_residual == pytest.approx(
        -diagnostics.junction_mass_residual_volume,
        abs=2.0e-10,
    )
    assert diagnostics.closure_adjusted_residual == pytest.approx(0.0, abs=2.0e-10)
    assert diagnostics.relative_water_balance_error < 1.0e-10
    assert network_storage(network, result.snapshots[-1].states) == pytest.approx(
        diagnostics.final_storage
    )


def test_retry_rejects_all_branches_and_keeps_diagnostics_synchronized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One rejected trial increments every Branch once before a smaller retry."""

    network = make_network()
    states = make_states(network)
    original = network_solver_module.one_in_two_out_network_ssp_rk2_step
    calls = 0

    def fail_once(**kwargs: object):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise StabilityError("synthetic synchronized rejection")
        return original(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        network_solver_module,
        "one_in_two_out_network_ssp_rk2_step",
        fail_once,
    )
    result = advance_network_with_retries(
        network=network,
        states=states,
        requested_dt=1.0,
        dry_depth=1.0e-3,
        boundaries=make_boundaries(end_time=2.0),
        cfl_limit=0.7,
        minimum_dt=1.0e-6,
        maximum_retries=2,
    )

    assert calls == 2
    assert result.dt == pytest.approx(0.5)
    assert {state.diagnostics.retry_count for state in result.states.values()} == {1}
    assert {state.diagnostics.rejected_step_count for state in result.states.values()} == {1}
    assert {state.diagnostics.step_count for state in result.states.values()} == {1}
    assert {state.time for state in states.values()} == {0.0}


@pytest.mark.parametrize(
    ("network", "states", "message"),
    (
        (
            make_network(manning=(0.0, 0.03, 0.0)),
            None,
            "zero-friction",
        ),
        (
            make_network(width_increments=(0.0, 0.1, 0.0)),
            None,
            "flat prismatic",
        ),
    ),
)
def test_run_fails_closed_outside_frictionless_prismatic_scope(
    network: FiniteVolumeNetwork,
    states: object,
    message: str,
) -> None:
    """Roughness and non-prismatic Branches stay beyond the J2 gate."""

    del states
    with pytest.raises(ValueError, match=message):
        solve_one_in_two_out_network(
            network=network,
            initial_states=make_states(network),
            boundaries=make_boundaries(end_time=1.0),
            config=OneInTwoOutNetworkConfig(
                end_time=1.0,
                maximum_dt=0.5,
                output_interval=1.0,
            ),
        )


@pytest.mark.parametrize(
    ("stages", "discharges", "message"),
    (
        ((2.0, 2.0, 2.0), (10.0, -1.0, 11.0), "reverse discharge"),
        ((0.1, 2.0, 2.0), (2.0, 1.0, 1.0), "strictly subcritical"),
        ((5.0e-4, 2.0, 2.0), (1.0e-12, 0.4, 0.6), "fully wet"),
    ),
)
def test_run_fails_closed_outside_wet_forward_subcritical_scope(
    stages: tuple[float, float, float],
    discharges: tuple[float, float, float],
    message: str,
) -> None:
    """Wet/dry, reverse, and supercritical states are explicit NO-GO cases."""

    network = make_network()
    with pytest.raises(ValueError, match=message):
        solve_one_in_two_out_network(
            network=network,
            initial_states=make_states(
                network,
                stages=stages,
                discharges=discharges,
            ),
            boundaries=make_boundaries(end_time=1.0),
            config=OneInTwoOutNetworkConfig(
                end_time=1.0,
                maximum_dt=0.5,
                output_interval=1.0,
            ),
        )


def test_boundary_identity_coverage_and_retry_exhaustion_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """External mapping, extrapolation, and node retry failures never pass silently."""

    network = make_network()
    states = make_states(network)
    wrong = replace(
        make_boundaries(end_time=1.0),
        downstream=(
            BranchDownstreamBoundary(
                "wrong",
                make_boundaries(end_time=1.0).downstream[0].boundary,
            ),
            make_boundaries(end_time=1.0).downstream[1],
        ),
    )
    with pytest.raises(ValueError, match="must match outgoing"):
        solve_one_in_two_out_network(
            network=network,
            initial_states=states,
            boundaries=wrong,
            config=OneInTwoOutNetworkConfig(
                end_time=1.0,
                maximum_dt=0.5,
                output_interval=1.0,
            ),
        )

    with pytest.raises(BoundaryCoverageError, match="outside"):
        solve_one_in_two_out_network(
            network=network,
            initial_states=states,
            boundaries=make_boundaries(end_time=0.5),
            config=OneInTwoOutNetworkConfig(
                end_time=1.0,
                maximum_dt=0.5,
                output_interval=1.0,
            ),
        )

    def always_fail(**kwargs: object):
        del kwargs
        raise ValueError("synthetic Junction failure")

    monkeypatch.setattr(
        network_solver_module,
        "one_in_two_out_network_ssp_rk2_step",
        always_fail,
    )
    with pytest.raises(StabilityError, match="unified retry budget"):
        advance_network_with_retries(
            network=network,
            states=states,
            requested_dt=1.0,
            dry_depth=1.0e-3,
            boundaries=make_boundaries(end_time=2.0),
            cfl_limit=0.7,
            minimum_dt=1.0e-6,
            maximum_retries=1,
        )


def test_network_result_does_not_claim_strong_junction_or_structures() -> None:
    """Accepted stage evidence remains characteristic-only and opt-in."""

    network = make_network()
    result = solve_one_in_two_out_network(
        network=network,
        initial_states=make_states(network),
        boundaries=make_boundaries(end_time=1.0),
        config=OneInTwoOutNetworkConfig(
            end_time=1.0,
            maximum_dt=0.5,
            output_interval=1.0,
        ),
    )

    evidence = result.steps[0].junction_stages[0].evidence
    assert evidence.strong_coupling_ready is False
    assert evidence.momentum_compatibility == "not-evaluated-no-branch-angle-v1"
    assert all(
        math.isfinite(value)
        for step in result.steps
        for value in (
            step.budget.upstream_volume,
            step.budget.total_downstream_volume,
            step.budget.junction_mass_residual_volume,
        )
    )


def test_restricted_solver_implements_branch_advance_contract() -> None:
    """The bound J2 solver advances all Branches to one exact target time."""

    network = make_network()
    solver = OneInTwoOutNetworkSolver(
        network=network,
        boundaries=make_boundaries(end_time=2.0),
        config=OneInTwoOutNetworkConfig(
            end_time=2.0,
            maximum_dt=0.5,
            output_interval=1.0,
        ),
    )

    assert isinstance(solver, BranchNetworkSolver)
    advanced = solver.advance_branches(
        states=make_states(network),
        target_time=1.25,
    )
    assert set(advanced) == {"B0", "B1", "B2"}
    assert {state.time for state in advanced.values()} == {1.25}
