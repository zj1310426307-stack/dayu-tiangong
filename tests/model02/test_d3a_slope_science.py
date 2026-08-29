"""D3A-2 S1/S2/S3 explicit-slope independent science gates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import pytest

from model.geometry import RectangularSectionGeometry, TabulatedSectionGeometry
from model.solver.finite_volume import (
    BoundaryPair,
    BoundarySeries,
    DownstreamStageBoundary,
    FiniteVolumeCell,
    FiniteVolumeMesh,
    HydraulicState,
    SingleBranchConfig,
    UpstreamDischargeBoundary,
    solve_single_branch,
)
from tests.reference.standard_step_1d import (
    RectangularReferenceSection,
    standard_step_profile,
)


def _boundaries(
    duration: float,
    discharge_m3_s: float,
    downstream_stage_m: float,
) -> BoundaryPair:
    return BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries(
                (0.0, duration),
                (discharge_m3_s, discharge_m3_s),
                "discharge",
            ),
            boundary_closure="subcritical-characteristic-v1",
        ),
        downstream=DownstreamStageBoundary(
            BoundarySeries(
                (0.0, duration),
                (downstream_stage_m, downstream_stage_m),
                "stage",
            ),
            boundary_closure="subcritical-characteristic-v1",
        ),
    )


def test_s1_long_tabulated_slope_lake_at_rest_is_machine_balanced() -> None:
    """A translated tabulated Profile must preserve absolute H and Q=0."""

    count = 24
    dx = 100.0
    slope = 2.0e-4
    stage = 12.0
    cells = []
    for index in range(count):
        bed = 10.0 - slope * (index + 0.5) * dx
        geometry = TabulatedSectionGeometry.from_points(
            (
                (0.0, bed + 3.0),
                (5.0, bed),
                (15.0, bed),
                (20.0, bed + 3.0),
            )
        )
        cells.append(
            FiniteVolumeCell(
                cell_id=f"s1-{index}",
                dx=dx,
                section_id=index + 1,
                bed_elevation=bed,
                geometry=geometry,
                manning_n=0.03,
            )
        )
    mesh = FiniteVolumeMesh(tuple(cells))
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=tuple(cell.geometry.area(stage) for cell in mesh.cells),
        discharge=(0.0,) * count,
        dry_depth=1.0e-3,
    )
    duration = 3600.0
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=_boundaries(duration, 0.0, stage),
        config=SingleBranchConfig(
            end_time=duration,
            maximum_dt=10.0,
            output_interval=600.0,
            maximum_friction_number=0.1,
            water_balance_tolerance=1.0e-10,
        ),
    )
    discharges = tuple(
        abs(value) for state_value in result.states for value in state_value.discharge
    )
    stages = tuple(
        cell.geometry.stage_from_area(state_value.area[index])
        for state_value in result.states
        for index, cell in enumerate(mesh.cells)
    )
    assert max(discharges) <= 1.0e-10
    assert max(stages) - min(stages) <= 1.0e-10
    assert max(abs(value - stage) for value in stages) <= 1.0e-10
    assert result.diagnostics.relative_water_balance_error <= 1.0e-12


def _normal_depth_root(
    *, width_m: float, manning_n: float, slope: float, discharge_m3_s: float
) -> float:
    """Independent rectangular Manning root with no production imports."""

    def residual(depth_m: float) -> float:
        area = width_m * depth_m
        radius = area / (width_m + 2.0 * depth_m)
        flow = area * radius ** (2.0 / 3.0) * math.sqrt(slope) / manning_n
        return flow - discharge_m3_s

    lower, upper = 1.0e-6, 20.0
    for _ in range(180):
        middle = 0.5 * (lower + upper)
        if residual(middle) > 0.0:
            upper = middle
        else:
            lower = middle
    return 0.5 * (lower + upper)


def test_s2_independent_manning_root_preserves_uniform_normal_flow() -> None:
    """The restricted equilibrium must match Q(A,R,n,S0) and stay stable."""

    width = 10.0
    manning = 0.03
    slope = 8.0e-4
    discharge = 20.0
    depth = _normal_depth_root(
        width_m=width,
        manning_n=manning,
        slope=slope,
        discharge_m3_s=discharge,
    )
    count, dx = 40, 50.0
    cells = tuple(
        FiniteVolumeCell(
            cell_id=f"s2-{index}",
            dx=dx,
            section_id=index + 1,
            bed_elevation=(bed := 10.0 - slope * (index + 0.5) * dx),
            geometry=RectangularSectionGeometry(width=width, bed_elevation=bed),
            manning_n=manning,
        )
        for index in range(count)
    )
    mesh = FiniteVolumeMesh(cells)
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=(width * depth,) * count,
        discharge=(discharge,) * count,
        dry_depth=1.0e-3,
    )
    duration = 3600.0
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=_boundaries(
            duration,
            discharge,
            mesh.cells[-1].bed_elevation + depth,
        ),
        config=SingleBranchConfig(
            end_time=duration,
            maximum_dt=5.0,
            output_interval=600.0,
            equilibrium_mode="uniform-manning-reference",
            maximum_friction_number=0.1,
            water_balance_tolerance=1.0e-10,
        ),
    )
    depth_errors = tuple(
        abs(cell.geometry.stage_from_area(area) - cell.bed_elevation - depth)
        for state_value in result.states
        for cell, area in zip(mesh.cells, state_value.area)
    )
    flow_errors = tuple(
        abs(value - discharge)
        for state_value in result.states
        for value in state_value.discharge
    )
    area = width * depth
    radius = area / (width + 2.0 * depth)
    friction_slope = (
        manning**2 * discharge**2 / (area**2 * radius ** (4.0 / 3.0))
    )
    assert friction_slope == pytest.approx(slope, rel=1.0e-12)
    assert max(depth_errors) <= 1.0e-9
    assert max(flow_errors) <= 1.0e-9
    assert result.diagnostics.maximum_friction_number == 0.0
    assert result.diagnostics.friction_retry_count == 0


@dataclass(frozen=True, slots=True)
class BackwaterMetrics:
    stage_l1_m: float
    stage_linf_m: float
    discharge_l1_m3_s: float
    mass_error: float


@lru_cache(maxsize=None)
def _run_s3_backwater(cell_count: int, cfl_number: float) -> BackwaterMetrics:
    length = 1200.0
    width = 10.0
    manning = 0.03
    bed_slope = 2.0e-4
    discharge = 20.0
    downstream_depth = 2.5
    dx = length / cell_count
    chainages = tuple((index + 0.5) * dx for index in range(cell_count))
    beds = tuple(1.0 - bed_slope * chainage for chainage in chainages)
    references = tuple(
        RectangularReferenceSection(
            chainage_m=chainage,
            bed_elevation_m=bed,
            manning_n=manning,
            width_m=width,
            maximum_depth_m=8.0,
        )
        for chainage, bed in zip(chainages, beds)
    )
    reference = standard_step_profile(
        references,
        discharge_m3_s=discharge,
        downstream_stage_m=beds[-1] + downstream_depth,
    )
    cells = tuple(
        FiniteVolumeCell(
            cell_id=f"s3-{cell_count}-{index}",
            dx=dx,
            section_id=index + 1,
            bed_elevation=bed,
            geometry=RectangularSectionGeometry(width=width, bed_elevation=bed),
            manning_n=manning,
        )
        for index, bed in enumerate(beds)
    )
    mesh = FiniteVolumeMesh(cells)
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=tuple(cell.geometry.area(point.water_level_m) for cell, point in zip(cells, reference)),
        discharge=(discharge,) * cell_count,
        dry_depth=1.0e-3,
    )
    duration = 600.0
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=_boundaries(duration, discharge, reference[-1].water_level_m),
        config=SingleBranchConfig(
            end_time=duration,
            maximum_dt=30.0,
            output_interval=duration,
            cfl_number=cfl_number,
            maximum_friction_number=0.1,
            water_balance_tolerance=1.0e-8,
        ),
    )
    final = result.states[-1]
    stage_errors = tuple(
        abs(cell.geometry.stage_from_area(area) - point.water_level_m)
        for cell, area, point in zip(cells, final.area, reference)
    )
    discharge_errors = tuple(abs(value - discharge) for value in final.discharge)
    return BackwaterMetrics(
        stage_l1_m=sum(stage_errors) / cell_count,
        stage_linf_m=max(stage_errors),
        discharge_l1_m3_s=sum(discharge_errors) / cell_count,
        mass_error=result.diagnostics.relative_water_balance_error,
    )


def test_s3_mild_slope_backwater_matches_independent_standard_step_and_refines() -> None:
    """H/Q errors must reduce with grid refinement against the independent path."""

    coarse, medium, fine = (
        _run_s3_backwater(count, 0.6) for count in (12, 24, 48)
    )
    assert fine.stage_l1_m < medium.stage_l1_m < coarse.stage_l1_m
    assert fine.stage_linf_m < coarse.stage_linf_m
    assert fine.discharge_l1_m3_s < coarse.discharge_l1_m3_s
    assert fine.stage_l1_m <= 0.02
    assert fine.stage_linf_m <= 0.05
    assert fine.discharge_l1_m3_s <= 0.25
    assert fine.mass_error <= 1.0e-8

    half_cfl = _run_s3_backwater(48, 0.3)
    assert half_cfl.stage_l1_m <= 1.05 * fine.stage_l1_m
    assert half_cfl.stage_linf_m <= 1.05 * fine.stage_linf_m
    assert half_cfl.discharge_l1_m3_s <= 1.05 * fine.discharge_l1_m3_s
