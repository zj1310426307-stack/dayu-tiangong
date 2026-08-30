"""Independent D3A-3 science gates for gradually varying engineering Profiles."""

from __future__ import annotations

import math
from dataclasses import dataclass

from model.geometry.sections import TabulatedSectionGeometry
from model.solver.finite_volume import (
    MAX_ADJACENT_HYDRAULIC_RELATIVE_CHANGE,
    BoundaryPair,
    BoundarySeries,
    DownstreamStageBoundary,
    FiniteVolumeCell,
    FiniteVolumeMesh,
    HydraulicState,
    NONPRISMATIC_ENGINEERING_SCOPE,
    SingleBranchConfig,
    UpstreamDischargeBoundary,
    adjacent_hydraulic_relative_change,
    solve_single_branch,
)
from tests.reference.standard_step_1d import ReferenceSection, standard_step_profile

_DOMAIN_LENGTH_M = 1_000.0
_DISCHARGE_M3_S = 4.0
_MANNING_N = 0.02
_BED_SLOPE = 2.0e-4


def _width(chainage_m: float) -> float:
    """Return one smooth contraction and expansion with flat endpoint widths."""

    return 8.0 - 2.0 * math.sin(math.pi * chainage_m / _DOMAIN_LENGTH_M) ** 2


def _points(chainage_m: float) -> tuple[tuple[float, float], ...]:
    bed = 1.0 - _BED_SLOPE * chainage_m
    width = _width(chainage_m)
    return ((0.0, bed + 4.0), (0.5 * width, bed), (width, bed + 4.0))


def _boundaries(
    *,
    end_time: float,
    discharge: float,
    downstream_stage: float,
) -> BoundaryPair:
    return BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries((0.0, end_time), (discharge, discharge), "discharge"),
            boundary_closure="subcritical-characteristic-v1",
        ),
        downstream=DownstreamStageBoundary(
            BoundarySeries(
                (0.0, end_time),
                (downstream_stage, downstream_stage),
                "stage",
            ),
            boundary_closure="subcritical-characteristic-v1",
        ),
    )


def test_p1_nonprismatic_sloping_bed_lake_at_rest_is_well_balanced() -> None:
    """P1: distinct tabulated Profiles and nonzero bed preserve constant H,Q=0."""

    chainages = (0.0, 200.0, 400.0, 600.0, 800.0, 1_000.0)
    geometries = tuple(
        TabulatedSectionGeometry.from_points(_points(chainage))
        for chainage in chainages
    )
    mesh = FiniteVolumeMesh(
        cells=tuple(
            FiniteVolumeCell(
                cell_id=f"p1-{index}",
                dx=200.0,
                section_id=index + 1,
                bed_elevation=geometry.minimum_stage,
                geometry=geometry,
            )
            for index, geometry in enumerate(geometries)
        )
    )
    stage = 2.5
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=tuple(geometry.area(stage) for geometry in geometries),
        discharge=(0.0,) * len(geometries),
        dry_depth=1.0e-3,
    )
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=_boundaries(
            end_time=120.0,
            discharge=0.0,
            downstream_stage=stage,
        ),
        config=SingleBranchConfig(
            end_time=120.0,
            maximum_dt=2.0,
            output_interval=120.0,
            cfl_number=0.5,
            geometry_source_mode="hydraulic-function-linear-face-v1",
        ),
    )

    final = result.states[-1]
    stages = tuple(
        cell.geometry.stage_from_area(area)
        for cell, area in zip(mesh.cells, final.area)
    )
    assert max(abs(value - stage) for value in stages) <= 1.0e-10
    assert max(abs(value) for value in final.discharge) <= 1.0e-10
    assert result.diagnostics.relative_water_balance_error <= 1.0e-12


def test_profile_smoothness_scan_separates_gradual_and_abrupt_families() -> None:
    """Freeze a synthetic scan behind the conservative 0.25 D3A-3 threshold."""

    gradual = tuple(
        TabulatedSectionGeometry.from_points(_points(chainage))
        for chainage in range(0, 1_001, 50)
    )
    gradual_changes = tuple(
        adjacent_hydraulic_relative_change(left, right)
        for left, right in zip(gradual, gradual[1:])
    )
    abrupt = TabulatedSectionGeometry.from_points(
        ((0.0, 4.8), (1.5, 0.8), (3.0, 4.8))
    )
    abrupt_change = adjacent_hydraulic_relative_change(gradual[10], abrupt)

    assert max(gradual_changes) < 0.05
    assert abrupt_change > MAX_ADJACENT_HYDRAULIC_RELATIVE_CHANGE
    assert MAX_ADJACENT_HYDRAULIC_RELATIVE_CHANGE == 0.25


@dataclass(frozen=True)
class _P3Evidence:
    stage_l1_m: float
    discharge_l1_m3_s: float
    velocity_l1_m_s: float
    energy_linf_m: float
    maximum_cfl: float


def _p3_run(cell_count: int, *, maximum_dt: float) -> _P3Evidence:
    dx = _DOMAIN_LENGTH_M / cell_count
    chainages = tuple((index + 0.5) * dx for index in range(cell_count))
    reference_sections = tuple(
        ReferenceSection(
            chainage_m=chainage,
            bed_elevation_m=1.0 - _BED_SLOPE * chainage,
            manning_n=_MANNING_N,
            points=_points(chainage),
        )
        for chainage in chainages
    )
    downstream_stage = reference_sections[-1].bed_elevation_m + 2.0
    reference = standard_step_profile(
        reference_sections,
        discharge_m3_s=_DISCHARGE_M3_S,
        downstream_stage_m=downstream_stage,
    )
    geometries = tuple(
        TabulatedSectionGeometry.from_points(section.points)
        for section in reference_sections
    )
    mesh = FiniteVolumeMesh(
        cells=tuple(
            FiniteVolumeCell(
                cell_id=f"p3-{index}",
                dx=dx,
                section_id=index + 1,
                bed_elevation=section.bed_elevation_m,
                geometry=geometry,
                manning_n=_MANNING_N,
            )
            for index, (section, geometry) in enumerate(
                zip(reference_sections, geometries)
            )
        )
    )
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=tuple(point.area_m2 for point in reference),
        discharge=(_DISCHARGE_M3_S,) * cell_count,
        dry_depth=1.0e-3,
    )
    end_time = 30.0
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=_boundaries(
            end_time=end_time,
            discharge=_DISCHARGE_M3_S,
            downstream_stage=downstream_stage,
        ),
        config=SingleBranchConfig(
            end_time=end_time,
            maximum_dt=maximum_dt,
            output_interval=end_time,
            cfl_number=0.5,
            minimum_dt=1.0e-8,
            maximum_retries=20,
            water_balance_tolerance=1.0e-6,
            maximum_friction_number=0.1,
            geometry_source_mode="hydraulic-function-linear-face-v1",
            nonprismatic_scope=NONPRISMATIC_ENGINEERING_SCOPE,
        ),
    )
    final = result.states[-1]
    stages = tuple(
        cell.geometry.stage_from_area(area)
        for cell, area in zip(mesh.cells, final.area)
    )
    velocities = tuple(q / area for q, area in zip(final.discharge, final.area))
    energies = tuple(
        stage + velocity * velocity / (2.0 * 9.81)
        for stage, velocity in zip(stages, velocities)
    )
    return _P3Evidence(
        stage_l1_m=sum(
            abs(actual - expected.water_level_m)
            for actual, expected in zip(stages, reference)
        )
        / cell_count,
        discharge_l1_m3_s=sum(
            abs(actual - _DISCHARGE_M3_S) for actual in final.discharge
        )
        / cell_count,
        velocity_l1_m_s=sum(
            abs(actual - expected.velocity_m_s)
            for actual, expected in zip(velocities, reference)
        )
        / cell_count,
        energy_linf_m=max(
            abs(actual - expected.energy_grade_m)
            for actual, expected in zip(energies, reference)
        ),
        maximum_cfl=result.diagnostics.maximum_cfl,
    )


def test_p3_variable_profile_manning_slope_converges_to_standard_step() -> None:
    """P3: H/Q/V/energy errors decrease against an independent standard step."""

    evidence = tuple(_p3_run(count, maximum_dt=0.2) for count in (20, 40, 80))
    assert evidence[1].stage_l1_m < evidence[0].stage_l1_m
    assert evidence[2].stage_l1_m < evidence[1].stage_l1_m
    assert evidence[1].discharge_l1_m3_s < evidence[0].discharge_l1_m3_s
    assert evidence[2].discharge_l1_m3_s < evidence[1].discharge_l1_m3_s
    stage_orders = tuple(
        math.log(coarse.stage_l1_m / fine.stage_l1_m, 2.0)
        for coarse, fine in zip(evidence, evidence[1:])
    )
    discharge_orders = tuple(
        math.log(coarse.discharge_l1_m3_s / fine.discharge_l1_m3_s, 2.0)
        for coarse, fine in zip(evidence, evidence[1:])
    )
    assert min(stage_orders) >= 0.8
    assert min(discharge_orders) >= 0.8
    assert evidence[-1].stage_l1_m <= 1.0e-3
    assert evidence[-1].discharge_l1_m3_s <= 1.0e-2
    assert evidence[-1].velocity_l1_m_s <= 2.0e-3
    assert evidence[-1].energy_linf_m <= 5.0e-3
    assert max(item.maximum_cfl for item in evidence) <= 0.5 + 1.0e-12


def test_p3_time_refinement_does_not_degrade_reference_error() -> None:
    """A fixed fine grid must remain stable as the maximum time step is halved."""

    coarse = _p3_run(80, maximum_dt=0.4)
    fine = _p3_run(80, maximum_dt=0.2)
    assert fine.stage_l1_m <= coarse.stage_l1_m * 1.01
    assert fine.discharge_l1_m3_s <= coarse.discharge_l1_m3_s * 1.01
