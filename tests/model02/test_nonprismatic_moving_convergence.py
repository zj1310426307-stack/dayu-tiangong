"""Scientific convergence gates for the restricted moving non-prismatic scope."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import pytest

from model.geometry.sections import RectangularSectionGeometry
from model.solver.finite_volume import (
    BoundaryPair,
    BoundarySeries,
    DownstreamStageBoundary,
    FiniteVolumeCell,
    FiniteVolumeMesh,
    HydraulicState,
    NONPRISMATIC_MOVING_ENERGY_SCOPE,
    SingleBranchConfig,
    UpstreamDischargeBoundary,
    solve_single_branch,
)

_GRAVITY = 9.81
_DOMAIN_LENGTH_M = 1_000.0
_REFERENCE_DISCHARGE_M3_S = 5.0
_REFERENCE_DEPTH_M = 2.0
_END_TIME_S = 5.0


@dataclass(frozen=True)
class MovingReferenceEvidence:
    """Hold one grid's frozen accuracy and quality evidence."""

    stage_l1_relative: float
    discharge_l1_relative: float
    energy_linf_m: float
    relative_water_balance_error: float
    maximum_cfl: float
    retry_count: int


def _width_at(chainage_m: float) -> float:
    """Return the smooth, endpoint-flat manufactured channel width."""

    phase = math.pi * chainage_m / _DOMAIN_LENGTH_M
    return 5.0 + 2.0 * math.sin(phase) ** 2


def _reference_energy_head() -> float:
    """Return the Bernoulli head fixed at width=5 m and depth=2 m."""

    area = 5.0 * _REFERENCE_DEPTH_M
    return _REFERENCE_DEPTH_M + _REFERENCE_DISCHARGE_M3_S**2 / (
        2.0 * _GRAVITY * area**2
    )


def _subcritical_depth(width: float) -> float:
    """Solve the positive subcritical Bernoulli root by deterministic bisection."""

    flow = _REFERENCE_DISCHARGE_M3_S
    energy = _reference_energy_head()
    lower = (flow * flow / (_GRAVITY * width * width)) ** (1.0 / 3.0)
    upper = energy
    for _ in range(100):
        middle = 0.5 * (lower + upper)
        residual = (
            middle
            + flow * flow
            / (2.0 * _GRAVITY * width * width * middle * middle)
            - energy
        )
        if residual > 0.0:
            upper = middle
        else:
            lower = middle
    return 0.5 * (lower + upper)


def _moving_reference_case(
    cell_count: int,
    *,
    maximum_dt: float = 0.1,
    datum: float = 0.0,
) -> tuple[
    FiniteVolumeMesh,
    HydraulicState,
    BoundaryPair,
    SingleBranchConfig,
    tuple[float, ...],
]:
    """Build one uniform-grid, flat-bed, frictionless exact steady solution."""

    dx = _DOMAIN_LENGTH_M / cell_count
    centres = tuple((index + 0.5) * dx for index in range(cell_count))
    widths = tuple(_width_at(chainage) for chainage in centres)
    stages = tuple(datum + _subcritical_depth(width) for width in widths)
    mesh = FiniteVolumeMesh(
        cells=tuple(
            FiniteVolumeCell(
                cell_id=f"moving-{index}",
                dx=dx,
                section_id=index + 1,
                bed_elevation=datum,
                geometry=RectangularSectionGeometry(
                    width=width,
                    bed_elevation=datum,
                ),
                manning_n=0.0,
            )
            for index, width in enumerate(widths)
        )
    )
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=tuple(
            width * (stage - datum)
            for width, stage in zip(widths, stages)
        ),
        discharge=(_REFERENCE_DISCHARGE_M3_S,) * cell_count,
        dry_depth=1.0e-3,
    )
    boundaries = BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries(
                (0.0, _END_TIME_S),
                (_REFERENCE_DISCHARGE_M3_S,) * 2,
                "discharge",
            ),
            boundary_closure="subcritical-characteristic-v1",
        ),
        downstream=DownstreamStageBoundary(
            BoundarySeries(
                (0.0, _END_TIME_S),
                (stages[-1],) * 2,
                "stage",
            ),
            boundary_closure="subcritical-characteristic-v1",
        ),
    )
    config = SingleBranchConfig(
        end_time=_END_TIME_S,
        maximum_dt=maximum_dt,
        output_interval=_END_TIME_S,
        cfl_number=0.5,
        dry_depth=1.0e-3,
        minimum_dt=1.0e-8,
        maximum_retries=20,
        water_balance_tolerance=1.0e-6,
        geometry_source_mode="hydraulic-function-linear-face-v1",
        nonprismatic_scope=NONPRISMATIC_MOVING_ENERGY_SCOPE,
    )
    return mesh, initial, boundaries, config, stages


def _run_reference(cell_count: int, *, maximum_dt: float = 0.1) -> MovingReferenceEvidence:
    """Run one grid and independently calculate the frozen error norms."""

    mesh, initial, boundaries, config, reference_stages = _moving_reference_case(
        cell_count,
        maximum_dt=maximum_dt,
    )
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=boundaries,
        config=config,
    )
    final = result.states[-1]
    dx = mesh.cells[0].dx
    final_stages = tuple(
        cell.geometry.stage_from_area(area)
        for cell, area in zip(mesh.cells, final.area)
    )
    stage_l1 = sum(
        dx * abs(actual - expected)
        for actual, expected in zip(final_stages, reference_stages)
    ) / sum(dx * abs(value) for value in reference_stages)
    discharge_l1 = sum(
        dx * abs(value - _REFERENCE_DISCHARGE_M3_S)
        for value in final.discharge
    ) / (_DOMAIN_LENGTH_M * _REFERENCE_DISCHARGE_M3_S)
    energy_linf = max(
        abs(
            stage
            + discharge * discharge / (2.0 * _GRAVITY * area * area)
            - _reference_energy_head()
        )
        for stage, discharge, area in zip(
            final_stages,
            final.discharge,
            final.area,
        )
    )
    assert all(final.wet_mask)
    assert min(final.discharge) > 0.0
    assert NONPRISMATIC_MOVING_ENERGY_SCOPE in result.diagnostics.diagnostic_flags
    return MovingReferenceEvidence(
        stage_l1_relative=stage_l1,
        discharge_l1_relative=discharge_l1,
        energy_linf_m=energy_linf,
        relative_water_balance_error=(
            result.diagnostics.relative_water_balance_error
        ),
        maximum_cfl=result.diagnostics.maximum_cfl,
        retry_count=result.diagnostics.retry_count,
    )


def _observed_order(coarse: float, fine: float) -> float:
    """Return the r=2 observed order for one positive error norm."""

    return math.log(coarse / fine) / math.log(2.0)


def test_moving_nonprismatic_energy_reference_converges_at_first_order() -> None:
    """Three grids must meet the frozen first-order spatial science gate."""

    evidence = tuple(_run_reference(count) for count in (25, 50, 100))
    stage_orders = tuple(
        _observed_order(coarse.stage_l1_relative, fine.stage_l1_relative)
        for coarse, fine in zip(evidence, evidence[1:])
    )
    discharge_orders = tuple(
        _observed_order(coarse.discharge_l1_relative, fine.discharge_l1_relative)
        for coarse, fine in zip(evidence, evidence[1:])
    )

    assert min(stage_orders) >= 0.8
    assert min(discharge_orders) >= 0.8
    assert evidence[-1].stage_l1_relative <= 1.0e-4
    assert evidence[-1].discharge_l1_relative <= 1.0e-4
    assert evidence[-1].energy_linf_m <= 1.0e-4
    assert max(item.relative_water_balance_error for item in evidence) <= 1.0e-10
    assert max(item.maximum_cfl for item in evidence) <= 0.5 + 1.0e-12
    assert all(item.retry_count == 0 for item in evidence)


def test_moving_reference_time_step_refinement_does_not_degrade_error() -> None:
    """At fixed fine mesh, dt refinement must not conceal a temporal regression."""

    evidence = tuple(
        _run_reference(100, maximum_dt=maximum_dt)
        for maximum_dt in (0.4, 0.2, 0.1)
    )
    assert evidence[1].stage_l1_relative <= evidence[0].stage_l1_relative
    assert evidence[2].stage_l1_relative <= evidence[1].stage_l1_relative
    assert evidence[1].discharge_l1_relative <= evidence[0].discharge_l1_relative
    assert evidence[2].discharge_l1_relative <= evidence[1].discharge_l1_relative


def test_moving_reference_energy_gate_is_ulp_safe_at_large_datum() -> None:
    """A valid 1e6 m datum runs, while a physical 4e-5 m defect still fails."""

    mesh, initial, boundaries, config, stages = _moving_reference_case(
        25,
        datum=1_000_000.0,
    )
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=boundaries,
        config=config,
    )
    assert result.diagnostics.retry_count == 0
    assert result.diagnostics.relative_water_balance_error <= 1.0e-10

    defective_stages = list(stages)
    defective_stages[5] += 4.0e-5
    defective = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=tuple(
            cell.geometry.area(stage)
            for cell, stage in zip(mesh.cells, defective_stages)
        ),
        discharge=initial.discharge,
        dry_depth=config.dry_depth,
    )
    with pytest.raises(ValueError, match="constant total energy head"):
        solve_single_branch(
            mesh=mesh,
            initial_state=defective,
            boundaries=boundaries,
            config=config,
        )


def test_moving_reference_grid_gate_has_no_large_dx_relative_slack() -> None:
    """A 50 m defect cannot hide behind a 1e12 m cell-length scale."""

    mesh, initial, boundaries, config, _ = _moving_reference_case(25)
    cells = tuple(replace(cell, dx=1.0e12) for cell in mesh.cells)
    defective = list(cells)
    defective[5] = replace(defective[5], dx=1.0e12 + 50.0)
    large_mesh = replace(mesh, cells=tuple(defective))

    with pytest.raises(ValueError, match="uniform cell-centre grid"):
        solve_single_branch(
            mesh=large_mesh,
            initial_state=initial,
            boundaries=boundaries,
            config=config,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("initial", "constant initial discharge"),
        ("dynamic_boundary", "constant upstream Q boundary"),
        ("boundary_match", "upstream Q must match initial discharge"),
    ],
)
def test_moving_reference_large_q_gate_has_no_relative_slack(
    mutation: str,
    message: str,
) -> None:
    """A 0.2 m3/s defect remains material at the 5e9 m3/s scale."""

    mesh, initial, boundaries, config, _ = _moving_reference_case(25)
    scale = 1.0e9
    scaled_cells = tuple(
        replace(
            cell,
            geometry=RectangularSectionGeometry(
                width=cell.geometry.width * scale,
                bed_elevation=cell.bed_elevation,
            ),
        )
        for cell in mesh.cells
    )
    mesh = replace(mesh, cells=scaled_cells)
    discharges = [_REFERENCE_DISCHARGE_M3_S * scale] * len(mesh.cells)
    upstream_values = [_REFERENCE_DISCHARGE_M3_S * scale] * 2
    if mutation == "initial":
        discharges[5] += 0.2
    elif mutation == "dynamic_boundary":
        upstream_values[-1] += 0.2
    elif mutation == "boundary_match":
        upstream_values = [value + 0.2 for value in upstream_values]
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=tuple(area * scale for area in initial.area),
        discharge=discharges,
        dry_depth=config.dry_depth,
    )
    boundaries = BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries(
                boundaries.upstream.series.times,
                tuple(upstream_values),
                "discharge",
            ),
            boundary_closure="subcritical-characteristic-v1",
        ),
        downstream=boundaries.downstream,
    )

    with pytest.raises(ValueError, match=message):
        solve_single_branch(
            mesh=mesh,
            initial_state=initial,
            boundaries=boundaries,
            config=config,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("default_lake_scope", "zero initial discharge"),
        ("roughness", "requires Manning n=0"),
        ("energy", "constant total energy head"),
        ("nonuniform_grid", "uniform cell-centre grid"),
    ],
)
def test_moving_nonprismatic_core_scope_fails_closed(
    mutation: str,
    message: str,
) -> None:
    """Direct core callers cannot bypass the restricted reference preflight."""

    mesh, initial, boundaries, config, _ = _moving_reference_case(25)
    if mutation == "default_lake_scope":
        config = replace(config, nonprismatic_scope="lake-at-rest-v1")
    elif mutation == "roughness":
        cells = list(mesh.cells)
        cells[5] = replace(cells[5], manning_n=0.01)
        mesh = replace(mesh, cells=tuple(cells))
    elif mutation == "energy":
        areas = list(initial.area)
        areas[5] *= 1.001
        initial = HydraulicState.from_conserved(
            mesh=mesh,
            time=0.0,
            area=areas,
            discharge=initial.discharge,
            dry_depth=config.dry_depth,
        )
    elif mutation == "nonuniform_grid":
        cells = list(mesh.cells)
        cells[5] = replace(cells[5], dx=cells[5].dx * 1.01)
        mesh = replace(mesh, cells=tuple(cells))

    with pytest.raises(ValueError, match=message):
        solve_single_branch(
            mesh=mesh,
            initial_state=initial,
            boundaries=boundaries,
            config=config,
        )
