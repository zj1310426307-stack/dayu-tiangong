"""D3A-1 independent Manning science, convergence and retry gates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import pytest

from model.geometry import RectangularSectionGeometry
from model.solver.finite_volume import (
    GRAVITY,
    BoundaryPair,
    BoundarySeries,
    DownstreamStageBoundary,
    FiniteVolumeCell,
    FiniteVolumeMesh,
    HydraulicState,
    SingleBranchConfig,
    UpstreamDischargeBoundary,
    semi_implicit_manning,
    solve_single_branch,
)
from tests.reference.standard_step_1d import (
    RectangularReferenceSection,
    StandardStepPoint,
    standard_step_profile,
)


def test_m1_friction_source_matches_analytic_decay_and_exact_inactive_limits() -> None:
    """The source-only update is dissipative and exact for constant A/R/n."""

    geometry = RectangularSectionGeometry(width=10.0, bed_elevation=0.0)
    area = 25.0
    initial_discharge = 20.0
    manning_n = 0.035
    duration = 900.0
    stage = geometry.stage_from_area(area)
    radius = geometry.hydraulic_radius(stage)
    coefficient = GRAVITY * manning_n**2 / (area * radius ** (4.0 / 3.0))
    analytic = initial_discharge / (
        1.0 + coefficient * initial_discharge * duration
    )

    errors: list[float] = []
    for dt in (30.0, 15.0, 7.5):
        discharge = initial_discharge
        history = [discharge]
        for _ in range(round(duration / dt)):
            discharge = semi_implicit_manning(
                area=area,
                discharge=discharge,
                geometry=geometry,
                manning_n=manning_n,
                dt=dt,
            )
            history.append(discharge)
        errors.append(abs(discharge - analytic))
        assert all(right < left for left, right in zip(history, history[1:]))
        assert all(value > 0.0 for value in history)
        assert area > 0.0

    # For constant K the accepted rational stage formula composes to the
    # analytic solution to round-off, so refinement may not expose a non-zero
    # truncation slope.  All three levels must nevertheless independently pass.
    assert max(errors) <= 2.0e-13
    assert errors[-1] <= errors[0] + 2.0e-13
    assert semi_implicit_manning(
        area=area,
        discharge=initial_discharge,
        geometry=geometry,
        manning_n=0.0,
        dt=30.0,
    ) == initial_discharge
    assert semi_implicit_manning(
        area=area,
        discharge=0.0,
        geometry=geometry,
        manning_n=manning_n,
        dt=30.0,
    ) == 0.0


@dataclass(frozen=True, slots=True)
class ManningReachMetrics:
    """Collect exact D3A-1 refinement outputs for assertion and reporting."""

    cell_count: int
    cfl_target: float
    l1_stage_error_m: float
    linf_stage_error_m: float
    l1_discharge_error_m3_s: float
    mass_error: float
    maximum_friction_number: float
    friction_retry_count: int
    friction_predictor_reduction_count: int
    step_count: int
    production_energy_loss_m: float
    reference: tuple[StandardStepPoint, ...]


@lru_cache(maxsize=None)
def _run_flat_bed_manning_reach(
    cell_count: int,
    cfl_target: float,
    friction_predictor_safety_factor: float | None = None,
) -> ManningReachMetrics:
    length_m = 1200.0
    width_m = 10.0
    bed_m = 0.0
    manning_n = 0.03
    discharge_m3_s = 20.0
    downstream_stage_m = 2.5
    dx = length_m / cell_count
    chainages = tuple((index + 0.5) * dx for index in range(cell_count))
    references = tuple(
        RectangularReferenceSection(
            chainage_m=chainage,
            bed_elevation_m=bed_m,
            manning_n=manning_n,
            width_m=width_m,
            maximum_depth_m=8.0,
        )
        for chainage in chainages
    )
    profile = standard_step_profile(
        references,
        discharge_m3_s=discharge_m3_s,
        downstream_stage_m=downstream_stage_m,
    )
    geometry = RectangularSectionGeometry(width=width_m, bed_elevation=bed_m)
    mesh = FiniteVolumeMesh(
        tuple(
            FiniteVolumeCell(
                cell_id=f"manning-{cell_count}-{index}",
                dx=dx,
                section_id=index + 1,
                bed_elevation=bed_m,
                geometry=geometry,
                manning_n=manning_n,
            )
            for index in range(cell_count)
        )
    )
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=tuple(geometry.area(point.water_level_m) for point in profile),
        discharge=(discharge_m3_s,) * cell_count,
        dry_depth=1.0e-3,
    )
    duration = 600.0
    boundaries = BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries((0.0, duration), (discharge_m3_s,) * 2, "discharge"),
            boundary_closure="subcritical-characteristic-v1",
        ),
        downstream=DownstreamStageBoundary(
            BoundarySeries((0.0, duration), (downstream_stage_m,) * 2, "stage"),
            boundary_closure="subcritical-characteristic-v1",
        ),
    )
    config = SingleBranchConfig(
        end_time=duration,
        maximum_dt=30.0,
        output_interval=duration,
        cfl_number=cfl_target,
        water_balance_tolerance=1.0e-8,
        maximum_friction_number=0.1,
        friction_predictor_safety_factor=friction_predictor_safety_factor,
    )
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=boundaries,
        config=config,
    )
    final = result.states[-1]
    stages = tuple(
        cell.geometry.stage_from_area(area)
        for cell, area in zip(mesh.cells, final.area)
    )
    stage_errors = tuple(
        abs(stage - point.water_level_m)
        for stage, point in zip(stages, profile)
    )
    discharge_errors = tuple(
        abs(discharge - discharge_m3_s) for discharge in final.discharge
    )
    energy_grade = tuple(
        stage + (discharge / area) ** 2 / (2.0 * GRAVITY)
        for stage, discharge, area in zip(stages, final.discharge, final.area)
    )
    return ManningReachMetrics(
        cell_count=cell_count,
        cfl_target=cfl_target,
        l1_stage_error_m=sum(stage_errors) / cell_count,
        linf_stage_error_m=max(stage_errors),
        l1_discharge_error_m3_s=sum(discharge_errors) / cell_count,
        mass_error=result.diagnostics.relative_water_balance_error,
        maximum_friction_number=result.diagnostics.maximum_friction_number,
        friction_retry_count=result.diagnostics.friction_retry_count,
        friction_predictor_reduction_count=(
            result.diagnostics.friction_predictor_reduction_count
        ),
        step_count=result.diagnostics.step_count,
        production_energy_loss_m=energy_grade[0] - energy_grade[-1],
        reference=profile,
    )


def test_m2_flat_bed_reach_matches_independent_standard_step_and_grid_refines() -> None:
    """Three spatial levels must converge toward the independent steady profile."""

    coarse, medium, fine = (
        _run_flat_bed_manning_reach(count, 0.6) for count in (12, 24, 48)
    )
    assert fine.l1_stage_error_m < medium.l1_stage_error_m < coarse.l1_stage_error_m
    assert fine.linf_stage_error_m < coarse.linf_stage_error_m
    assert fine.l1_discharge_error_m3_s < coarse.l1_discharge_error_m3_s
    assert fine.l1_stage_error_m <= 0.02
    assert fine.linf_stage_error_m <= 0.05
    assert fine.l1_discharge_error_m3_s <= 0.25
    assert fine.mass_error <= 1.0e-8
    assert 0.0 < fine.maximum_friction_number <= 0.1 + 1.0e-12
    assert fine.production_energy_loss_m > 0.0
    assert all(
        left.energy_grade_m > right.energy_grade_m
        for left, right in zip(fine.reference, fine.reference[1:])
    )
    assert all(
        point.discharge_m3_s == pytest.approx(20.0) for point in fine.reference
    )


def test_m2_flat_bed_reach_cfl_refinement_does_not_degrade_solution() -> None:
    """A half-CFL run must preserve the same verified physical solution."""

    target = _run_flat_bed_manning_reach(48, 0.6)
    half = _run_flat_bed_manning_reach(48, 0.3)
    assert half.l1_stage_error_m <= 1.05 * target.l1_stage_error_m
    assert half.linf_stage_error_m <= 1.05 * target.linf_stage_error_m
    assert half.l1_discharge_error_m3_s <= 1.05 * target.l1_discharge_error_m3_s
    assert half.mass_error <= 1.0e-8
    assert half.maximum_friction_number < target.maximum_friction_number


def test_manning_friction_number_gate_retries_and_reports_only_accepted_steps() -> None:
    """An over-limit trial halves dt and exposes no discarded friction evidence."""

    geometry = RectangularSectionGeometry(width=2.0, bed_elevation=0.0)
    mesh = FiniteVolumeMesh(
        tuple(
            FiniteVolumeCell(
                cell_id=f"retry-{index}",
                dx=20.0,
                section_id=index + 1,
                bed_elevation=0.0,
                geometry=geometry,
                manning_n=0.08,
            )
            for index in range(3)
        )
    )
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=(2.0,) * 3,
        discharge=(1.0,) * 3,
        dry_depth=1.0e-3,
    )
    boundaries = BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries((0.0, 1.0), (1.0, 1.0), "discharge")
        ),
        downstream=DownstreamStageBoundary(
            BoundarySeries((0.0, 1.0), (1.0, 1.0), "stage")
        ),
    )
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=boundaries,
        config=SingleBranchConfig(
            end_time=1.0,
            maximum_dt=1.0,
            output_interval=1.0,
            cfl_number=0.9,
            minimum_dt=1.0e-5,
            maximum_retries=12,
            water_balance_tolerance=1.0e-8,
            maximum_friction_number=0.01,
        ),
    )
    assert result.diagnostics.friction_retry_count > 0
    assert result.diagnostics.maximum_friction_number <= 0.01 + 1.0e-12
    assert result.diagnostics.retry_count >= result.diagnostics.friction_retry_count
    assert all(step.maximum_friction_number <= 0.01 + 1.0e-12 for step in result.steps)


def test_manning_dt_predictor_preserves_solution_and_avoids_reactive_retries() -> None:
    """Predictor ON stays within science tolerance while reducing retry work."""

    without = _run_flat_bed_manning_reach(48, 0.6, None)
    with_predictor = _run_flat_bed_manning_reach(48, 0.6, 0.8)
    assert with_predictor.friction_predictor_reduction_count > 0
    assert with_predictor.friction_retry_count <= without.friction_retry_count
    assert (
        with_predictor.friction_retry_count / with_predictor.step_count < 0.25
    )
    assert with_predictor.l1_stage_error_m == pytest.approx(
        without.l1_stage_error_m,
        rel=0.01,
        abs=1.0e-6,
    )
    assert with_predictor.l1_discharge_error_m3_s == pytest.approx(
        without.l1_discharge_error_m3_s,
        rel=0.01,
        abs=1.0e-6,
    )
    assert with_predictor.mass_error <= 1.0e-8
