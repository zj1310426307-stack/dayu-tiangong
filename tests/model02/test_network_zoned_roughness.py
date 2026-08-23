"""Scientific acceptance gates for C3c-R1 zoned network Manning friction."""

from __future__ import annotations

from dataclasses import replace

import pytest

import model.solver.finite_volume.network_solver as network_solver_module
from model.geometry.sections import RectangularSectionGeometry
from model.solver.finite_volume import (
    GRAVITY,
    BoundaryPair,
    BoundarySeries,
    BranchDownstreamBoundary,
    ConservedVector,
    DownstreamStageBoundary,
    FiniteVolumeCell,
    FiniteVolumeMesh,
    FiniteVolumeNetwork,
    HydraulicState,
    NetworkBranch,
    OneInTwoOutBoundarySet,
    OneInTwoOutNetworkConfig,
    OneInTwoOutRoughnessPlan,
    PiecewiseManningZoneSolver,
    RoughnessZone,
    UpstreamDischargeBoundary,
    advance_network_with_retries,
    estimate_network_cfl_time_step,
    forward_euler_stage,
    network_storage,
    one_in_two_out_network_ssp_rk2_step,
    solve_one_in_two_out_network,
    subcritical_characteristic_properties,
)

_CHARACTERISTIC = "subcritical-characteristic-v1"
_DX = 100.0
_WIDTH = 10.0
_DEFAULT_COEFFICIENTS = {
    "B0": (0.02, 0.02, 0.04, 0.04, 0.0),
    "B1": (0.0, 0.025, 0.025, 0.045, 0.045),
    "B2": (0.0, 0.03, 0.035, 0.035, 0.05),
}
_JUNCTION_CONTROL_INDEX = {"B0": -1, "B1": 0, "B2": 0}
_FLOW_BY_BRANCH = {"B0": 10.0, "B1": 4.0, "B2": 6.0}


def _base_mesh(branch_id: str, cell_count: int) -> FiniteVolumeMesh:
    """Build one flat prismatic Branch before auditable roughness resolution."""

    geometry = RectangularSectionGeometry(width=_WIDTH, bed_elevation=0.0)
    return FiniteVolumeMesh(
        branch_id=branch_id,
        cells=tuple(
            FiniteVolumeCell(
                cell_id=f"{branch_id}-cell-{index}",
                dx=_DX,
                section_id=f"{branch_id}-section-{index}",
                bed_elevation=0.0,
                geometry=geometry,
                manning_n=0.0,
            )
            for index in range(cell_count)
        ),
    )


def _zones_for_cells(
    branch_id: str,
    coefficients: tuple[float, ...],
) -> tuple[RoughnessZone, ...]:
    """Compress cell coefficients into face-aligned half-open roughness zones."""

    zones = []
    start = 0
    for index in range(1, len(coefficients) + 1):
        if index < len(coefficients) and coefficients[index] == coefficients[start]:
            continue
        zones.append(
            RoughnessZone(
                zone_id=f"{branch_id}-zone-{len(zones)}",
                branch_id=branch_id,
                start_chainage_m=start * _DX,
                end_chainage_m=index * _DX,
                manning_n=coefficients[start],
            )
        )
        start = index
    return tuple(zones)


def _zoned_network(
    coefficients: dict[str, tuple[float, ...]] | None = None,
    *,
    maximum_stage_friction_number: float = 0.1,
) -> tuple[FiniteVolumeNetwork, OneInTwoOutRoughnessPlan]:
    """Resolve three exact zone plans and bind their meshes to a bifurcation."""

    values = coefficients or _DEFAULT_COEFFICIENTS
    if set(values) != {"B0", "B1", "B2"}:
        raise ValueError("test roughness coefficients must cover B0/B1/B2")
    counts = {len(item) for item in values.values()}
    if len(counts) != 1:
        raise ValueError("test Branches must use a common cell count")
    count = counts.pop()
    zoned = tuple(
        PiecewiseManningZoneSolver(
            zones=_zones_for_cells(branch_id, values[branch_id])
        ).resolve_mesh(
            mesh=_base_mesh(branch_id, count),
            branch_start_chainage_m=0.0,
        )
        for branch_id in ("B0", "B1", "B2")
    )
    network = FiniteVolumeNetwork(
        branches=(
            NetworkBranch(zoned[0].mesh, "source", "J1"),
            NetworkBranch(zoned[1].mesh, "J1", "sink-1"),
            NetworkBranch(zoned[2].mesh, "J1", "sink-2"),
        )
    )
    return network, OneInTwoOutRoughnessPlan(
        zoned_meshes=zoned,
        maximum_stage_friction_number=maximum_stage_friction_number,
    )


def _zero_network(cell_count: int = 5) -> FiniteVolumeNetwork:
    """Build the unchanged all-zero-Manning J2 compatibility network."""

    meshes = tuple(_base_mesh(branch_id, cell_count) for branch_id in ("B0", "B1", "B2"))
    return FiniteVolumeNetwork(
        branches=(
            NetworkBranch(meshes[0], "source", "J1"),
            NetworkBranch(meshes[1], "J1", "sink-1"),
            NetworkBranch(meshes[2], "J1", "sink-2"),
        )
    )


def _states(
    network: FiniteVolumeNetwork,
    *,
    time: float = 0.0,
) -> dict[str, HydraulicState]:
    """Build synchronized, fully wet, forward, subcritical Branch states."""

    result = {}
    for branch in network.branches:
        discharge = _FLOW_BY_BRANCH[branch.branch_id]
        result[branch.branch_id] = HydraulicState.from_conserved(
            mesh=branch.mesh,
            time=time,
            area=tuple(cell.geometry.area(2.0) for cell in branch.mesh.cells),
            discharge=tuple(discharge for _ in branch.mesh.cells),
            dry_depth=1.0e-3,
        )
    return result


def _boundaries(end_time: float) -> OneInTwoOutBoundarySet:
    """Prescribe compatible characteristic Q/H processes without extrapolation."""

    return OneInTwoOutBoundarySet(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries((0.0, end_time), (10.0, 10.0), "discharge"),
            boundary_closure=_CHARACTERISTIC,
        ),
        downstream=tuple(
            BranchDownstreamBoundary(
                branch_id=branch_id,
                boundary=DownstreamStageBoundary(
                    BoundarySeries((0.0, end_time), (2.0, 2.0), "stage"),
                    boundary_closure=_CHARACTERISTIC,
                ),
            )
            for branch_id in ("B1", "B2")
        ),
    )


def _single_step(
    network: FiniteVolumeNetwork,
    plan: OneInTwoOutRoughnessPlan | None,
    *,
    dt: float = 0.5,
):
    """Advance one public SSP-RK2 step with the requested roughness contract."""

    return one_in_two_out_network_ssp_rk2_step(
        network=network,
        states=_states(network),
        dt=dt,
        dry_depth=1.0e-3,
        boundaries=_boundaries(max(dt, 1.0)),
        cfl_limit=0.7,
        roughness_plan=plan,
    )


def test_plan_rejects_incomplete_duplicate_or_weakened_provenance() -> None:
    """The public plan cannot omit/alias a Branch or relax ``mu<=0.1``."""

    _, plan = _zoned_network()
    first, second, third = plan.zoned_meshes
    with pytest.raises(ValueError, match="three zoned Branch meshes"):
        OneInTwoOutRoughnessPlan(zoned_meshes=(first, second))
    with pytest.raises(ValueError, match="identities must be unique"):
        OneInTwoOutRoughnessPlan(zoned_meshes=(first, second, second))
    with pytest.raises(ValueError, match=r"\(0, 0.1\]"):
        OneInTwoOutRoughnessPlan(
            zoned_meshes=(first, second, third),
            maximum_stage_friction_number=0.100001,
        )


def test_face_aligned_plan_drives_two_auditable_manning_stages() -> None:
    """Both RK stages expose three Branches and reproducible local damping."""

    network, plan = _zoned_network()
    step = _single_step(network, plan)

    assert len(step.roughness_stages) == 2
    assert len(step.junction_stages) == 2
    assert tuple(stage.stage_time for stage in step.roughness_stages) == pytest.approx(
        (0.0, 0.5)
    )
    assert tuple(stage.dt for stage in step.roughness_stages) == pytest.approx((0.5, 0.5))
    for zoned in plan.zoned_meshes:
        assert len(zoned.mesh.cells) == 5
        assert tuple(item.start_chainage_m for item in zoned.assignments) == pytest.approx(
            (0.0, 100.0, 200.0, 300.0, 400.0)
        )
        assert tuple(item.end_chainage_m for item in zoned.assignments) == pytest.approx(
            (100.0, 200.0, 300.0, 400.0, 500.0)
        )

    for stage in step.roughness_stages:
        assert {item.branch_id for item in stage.branches} == {"B0", "B1", "B2"}
        assert stage.maximum_friction_number <= 0.1 + 1.0e-12
        for branch in stage.branches:
            assert len(branch.assignments) == len(branch.cells) == 5
            expected_control_index = _JUNCTION_CONTROL_INDEX[branch.branch_id]
            expected_control = branch.cells[expected_control_index]
            assert branch.junction_control_cell_id == expected_control.cell_id
            for index, (assignment, evidence) in enumerate(
                zip(branch.assignments, branch.cells)
            ):
                assert assignment.cell_id == evidence.cell_id
                assert assignment.manning_n == evidence.manning_n
                is_control = index == (4 if expected_control_index == -1 else 0)
                if is_control:
                    assert evidence.manning_n == 0.0
                    assert evidence.friction_number == 0.0
                    assert evidence.denominator == 1.0
                    assert evidence.discharge_after == evidence.discharge_before
                    continue

                assert evidence.manning_n > 0.0
                expected_coefficient = (
                    GRAVITY
                    * evidence.manning_n**2
                    / (evidence.area * evidence.hydraulic_radius ** (4.0 / 3.0))
                )
                expected_mu = (
                    evidence.dt
                    * expected_coefficient
                    * abs(evidence.discharge_before)
                )
                expected_after = evidence.discharge_before / (1.0 + expected_mu)
                equation_residual = abs(
                    evidence.discharge_after * (1.0 + expected_mu)
                    - evidence.discharge_before
                ) / max(abs(evidence.discharge_before), 1.0)
                assert evidence.coefficient == pytest.approx(
                    expected_coefficient, rel=1.0e-12, abs=1.0e-15
                )
                assert evidence.friction_number == pytest.approx(
                    expected_mu, rel=1.0e-12, abs=1.0e-15
                )
                assert evidence.discharge_after == pytest.approx(
                    expected_after, rel=1.0e-12, abs=1.0e-12
                )
                assert equation_residual <= 1.0e-12
                assert evidence.discharge_after * evidence.discharge_before > 0.0
                assert abs(evidence.discharge_after) < abs(evidence.discharge_before)

    first_b0 = next(
        item for item in step.roughness_stages[0].branches if item.branch_id == "B0"
    )
    assert first_b0.cells[2].manning_n == 2.0 * first_b0.cells[0].manning_n
    assert first_b0.cells[2].removed_discharge > first_b0.cells[0].removed_discharge


def test_evidence_time_alignment_uses_the_network_sync_tolerance() -> None:
    """A sub-tolerance Branch clock delta is not rejected by stricter evidence."""

    network, plan = _zoned_network()
    states = _states(network)
    states["B1"] = replace(states["B1"], time=5.0e-13)
    step = one_in_two_out_network_ssp_rk2_step(
        network=network,
        states=states,
        dt=0.5,
        dry_depth=1.0e-3,
        boundaries=_boundaries(1.0),
        cfl_limit=0.7,
        roughness_plan=plan,
    )

    assert len(step.roughness_stages) == 2
    assert max(state.time for state in step.states.values()) - min(
        state.time for state in step.states.values()
    ) <= 1.0e-12


def test_uniform_interior_matches_frozen_two_stage_manning_reference() -> None:
    """A flux-uniform centre cell reproduces the independent SSP-stage values."""

    base = _base_mesh("reference", 5)
    mesh = FiniteVolumeMesh(
        branch_id=base.branch_id,
        cells=tuple(replace(cell, manning_n=0.03) for cell in base.cells),
    )
    state = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=(20.0,) * 5,
        discharge=(10.0,) * 5,
        dry_depth=1.0e-3,
    )
    boundaries = BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries((0.0, 2.0), (10.0, 10.0), "discharge"),
            boundary_closure=_CHARACTERISTIC,
        ),
        downstream=DownstreamStageBoundary(
            BoundarySeries((0.0, 2.0), (2.0, 2.0), "stage"),
            boundary_closure=_CHARACTERISTIC,
        ),
    )

    first = forward_euler_stage(
        mesh=mesh,
        state=state,
        dt=1.0,
        dry_depth=1.0e-3,
        boundaries=boundaries,
        capture_friction_evidence=True,
    )
    second = forward_euler_stage(
        mesh=mesh,
        state=first.state,
        dt=1.0,
        dry_depth=1.0e-3,
        boundaries=boundaries,
        capture_friction_evidence=True,
    )
    first_cell = first.friction_evidence[2]
    second_cell = second.friction_evidence[2]
    accepted_discharge = 0.5 * (state.discharge[2] + second.state.discharge[2])

    assert first_cell.discharge_before == pytest.approx(10.0, abs=1.0e-14)
    assert first_cell.discharge_after == pytest.approx(9.972637510499968, abs=1.0e-13)
    assert second_cell.discharge_before == pytest.approx(
        first_cell.discharge_after,
        abs=1.0e-13,
    )
    assert second_cell.discharge_after == pytest.approx(9.945424353555218, abs=1.0e-13)
    assert accepted_discharge == pytest.approx(9.972712176777609, abs=1.0e-13)


def test_short_rough_network_run_is_dissipative_and_closes_water_ledgers() -> None:
    """Roughness removes momentum only while wet/forward flow conserves water."""

    network, plan = _zoned_network()
    initial = _states(network)
    result = solve_one_in_two_out_network(
        network=network,
        initial_states=initial,
        boundaries=_boundaries(2.0),
        config=OneInTwoOutNetworkConfig(
            end_time=2.0,
            maximum_dt=0.5,
            output_interval=1.0,
        ),
        roughness_plan=plan,
    )

    final = result.snapshots[-1].states
    for branch in network.branches:
        state = final[branch.branch_id]
        assert all(state.wet_mask)
        assert all(discharge > 0.0 for discharge in state.discharge)
        for cell, area, discharge in zip(branch.mesh.cells, state.area, state.discharge):
            properties = subcritical_characteristic_properties(
                state=_conserved(area, discharge),
                cell=cell,
                label=f"R1 final {branch.branch_id}",
            )
            assert properties.froude < 1.0

    removed = sum(
        cell.removed_discharge
        for step in result.steps
        for stage in step.roughness_stages
        for branch in stage.branches
        for cell in branch.cells
        if cell.manning_n > 0.0
    )
    assert removed > 0.0
    assert any(
        final[branch_id].discharge[index] < initial[branch_id].discharge[index]
        for branch_id, index in (("B0", 2), ("B1", 2), ("B2", 2))
    )

    diagnostics = result.diagnostics
    storage_change = network_storage(network, final) - network_storage(network, initial)
    external_net = diagnostics.upstream_boundary_volume - sum(
        value for _, value in diagnostics.downstream_boundary_volumes
    )
    independent_adjusted = (
        storage_change - external_net + diagnostics.junction_mass_residual_volume
    )
    scale = max(
        abs(diagnostics.initial_storage),
        abs(external_net),
        1.0,
    )
    assert storage_change - external_net == pytest.approx(
        diagnostics.water_balance_residual, abs=1.0e-12
    )
    assert independent_adjusted == pytest.approx(
        diagnostics.closure_adjusted_residual, abs=1.0e-12
    )
    assert abs(independent_adjusted) / scale <= 1.0e-11
    assert diagnostics.relative_water_balance_error <= 1.0e-10
    assert diagnostics.roughness_stage_count == 2 * diagnostics.step_count
    assert diagnostics.junction_stage_count == 2 * diagnostics.step_count
    assert diagnostics.maximum_friction_number <= 0.1 + 1.0e-12
    for step in result.steps:
        for junction in step.junction_stages:
            assert junction.evidence.normalized_mass_residual <= 1.0e-10
            assert junction.evidence.maximum_normalized_invariant_residual <= 1.0e-10


def _conserved(area: float, discharge: float) -> ConservedVector:
    """Construct a public conserved vector without obscuring test equations."""

    return ConservedVector(area, discharge)


def test_friction_number_rejection_retries_all_branches_and_discards_trial_evidence() -> None:
    """A source-accuracy rejection halves one global dt and returns accepted evidence only."""

    coefficients = {
        "B0": (0.2, 0.2, 0.2, 0.2, 0.0),
        "B1": (0.0, 0.2, 0.2, 0.2, 0.2),
        "B2": (0.0, 0.2, 0.2, 0.2, 0.2),
    }
    network, plan = _zoned_network(coefficients)
    states = _states(network)
    area = states["B0"].area[0]
    radius = network.branch("B0").mesh.cells[0].geometry.hydraulic_radius(2.0)
    rejected_mu = GRAVITY * 0.2**2 * 10.0 / (area * radius ** (4.0 / 3.0))
    assert rejected_mu > 0.1
    assert estimate_network_cfl_time_step(
        network=network,
        states=states,
        cfl_number=0.7,
        maximum_dt=1.0,
    ).time_step == pytest.approx(1.0)

    accepted = advance_network_with_retries(
        network=network,
        states=states,
        requested_dt=1.0,
        dry_depth=1.0e-3,
        boundaries=_boundaries(2.0),
        cfl_limit=0.7,
        minimum_dt=1.0e-6,
        maximum_retries=2,
        roughness_plan=plan,
    )

    assert accepted.dt == pytest.approx(0.5)
    assert len(accepted.roughness_stages) == 2
    assert tuple(stage.stage_time for stage in accepted.roughness_stages) == pytest.approx(
        (0.0, 0.5)
    )
    assert all(stage.dt == pytest.approx(0.5) for stage in accepted.roughness_stages)
    assert all(
        stage.maximum_friction_number <= 0.1 + 1.0e-12
        for stage in accepted.roughness_stages
    )
    assert {state.diagnostics.retry_count for state in accepted.states.values()} == {1}
    assert {
        state.diagnostics.rejected_step_count for state in accepted.states.values()
    } == {1}
    assert {state.diagnostics.step_count for state in accepted.states.values()} == {1}
    assert {state.time for state in states.values()} == {0.0}


def test_unified_retry_does_not_swallow_permanent_contract_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A programming/provenance ``ValueError`` escapes without futile dt halving."""

    network, plan = _zoned_network()
    calls = 0

    def invalid_contract(**_: object):
        nonlocal calls
        calls += 1
        raise ValueError("synthetic evidence contract failure")

    monkeypatch.setattr(
        network_solver_module,
        "one_in_two_out_network_ssp_rk2_step",
        invalid_contract,
    )
    with pytest.raises(ValueError, match="evidence contract failure"):
        advance_network_with_retries(
            network=network,
            states=_states(network),
            requested_dt=1.0,
            dry_depth=1.0e-3,
            boundaries=_boundaries(2.0),
            cfl_limit=0.7,
            minimum_dt=1.0e-6,
            maximum_retries=4,
            roughness_plan=plan,
        )
    assert calls == 1


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("no-plan", "unless an R1 roughness plan"),
        ("plan-mesh-mismatch", "provenance contradicts"),
        ("junction-nonzero", "Junction-adjacent control cells"),
        ("non-junction-zero", "non-Junction cells"),
        ("too-few-cells", "at least three cells"),
    ),
)
def test_roughness_scope_violations_fail_closed(case: str, message: str) -> None:
    """Missing provenance and every forbidden coefficient layout reject preflight."""

    if case == "junction-nonzero":
        coefficients = dict(_DEFAULT_COEFFICIENTS)
        coefficients["B0"] = (0.02, 0.02, 0.04, 0.04, 0.01)
        network, plan = _zoned_network(coefficients)
    elif case == "non-junction-zero":
        coefficients = dict(_DEFAULT_COEFFICIENTS)
        coefficients["B0"] = (0.0, 0.02, 0.04, 0.04, 0.0)
        network, plan = _zoned_network(coefficients)
    elif case == "too-few-cells":
        network, plan = _zoned_network(
            {
                "B0": (0.03, 0.0),
                "B1": (0.0, 0.03),
                "B2": (0.0, 0.03),
            }
        )
    else:
        network, plan = _zoned_network()

    if case == "no-plan":
        plan = None
    elif case == "plan-mesh-mismatch":
        branch = network.branch("B0")
        cells = list(branch.mesh.cells)
        cells[0] = replace(cells[0], manning_n=cells[0].manning_n + 0.001)
        mismatched_mesh = FiniteVolumeMesh(
            branch_id=branch.branch_id,
            cells=tuple(cells),
        )
        network = FiniteVolumeNetwork(
            branches=tuple(
                replace(item, mesh=mismatched_mesh)
                if item.branch_id == "B0"
                else item
                for item in network.branches
            )
        )

    with pytest.raises(ValueError, match=message):
        _single_step(network, plan)


def test_all_zero_manning_j2_path_remains_evidence_free_and_steady() -> None:
    """The legacy J2 opt-in keeps its compatible state and emits no R1 evidence."""

    network = _zero_network()
    initial = _states(network)
    result = solve_one_in_two_out_network(
        network=network,
        initial_states=initial,
        boundaries=_boundaries(1.0),
        config=OneInTwoOutNetworkConfig(
            end_time=1.0,
            maximum_dt=0.5,
            output_interval=1.0,
        ),
    )

    final = result.snapshots[-1].states
    for branch_id in ("B0", "B1", "B2"):
        assert final[branch_id].area == pytest.approx(initial[branch_id].area, abs=2.0e-10)
        assert final[branch_id].discharge == pytest.approx(
            initial[branch_id].discharge, abs=2.0e-9
        )
    assert all(not step.roughness_stages for step in result.steps)
    assert result.diagnostics.roughness_stage_count == 0
    assert result.diagnostics.maximum_friction_number == 0.0
    assert result.diagnostics.roughness_policy == "zero-friction-j2-v1"
    assert result.diagnostics.relative_water_balance_error <= 1.0e-12
