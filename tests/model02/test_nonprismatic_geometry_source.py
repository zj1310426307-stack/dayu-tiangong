"""Scientific gates for the explicit non-prismatic hydraulic-function path."""

from __future__ import annotations

from dataclasses import replace

import pytest

from model.geometry.sections import (
    RectangularSectionGeometry,
    TabulatedSectionGeometry,
)
from model.solver.finite_volume import (
    BoundaryPair,
    BoundarySeries,
    DownstreamStageBoundary,
    FiniteVolumeCell,
    FiniteVolumeMesh,
    FixedGate,
    HydraulicState,
    SingleBranchConfig,
    UpstreamDischargeBoundary,
    forward_euler_stage,
    internal_face_geometry,
    solve_single_branch,
)


def _mesh(geometries: tuple[object, ...]) -> FiniteVolumeMesh:
    """Build a flat, frictionless mesh from validated section geometries."""

    return FiniteVolumeMesh(
        cells=tuple(
            FiniteVolumeCell(
                cell_id=f"cell-{index}",
                dx=100.0,
                section_id=index + 1,
                bed_elevation=float(geometry.minimum_stage),
                geometry=geometry,
                manning_n=0.0,
            )
            for index, geometry in enumerate(geometries)
        )
    )


def _state(mesh: FiniteVolumeMesh, stage: float) -> HydraulicState:
    """Create one common absolute-stage, zero-discharge state."""

    return HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=tuple(cell.geometry.area(stage) for cell in mesh.cells),
        discharge=(0.0,) * len(mesh.cells),
        dry_depth=1.0e-3,
    )


def _boundaries(
    stage: float,
    end_time: float,
    *,
    closure: str = "subcritical-characteristic-v1",
) -> BoundaryPair:
    """Freeze closed inflow and a matching downstream stage over the run."""

    return BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries((0.0, end_time), (0.0, 0.0), "discharge"),
            boundary_closure=closure,
        ),
        downstream=DownstreamStageBoundary(
            BoundarySeries((0.0, end_time), (stage, stage), "stage"),
            boundary_closure=closure,
        ),
    )


def _config(end_time: float = 60.0) -> SingleBranchConfig:
    """Select the explicit first-order non-prismatic source policy."""

    return SingleBranchConfig(
        end_time=end_time,
        maximum_dt=2.0,
        output_interval=10.0,
        cfl_number=0.5,
        geometry_source_mode="hydraulic-function-linear-face-v1",
    )


def _maximum_stage_drift(
    mesh: FiniteVolumeMesh,
    state: HydraulicState,
    reference_stage: float,
) -> float:
    """Return the largest absolute free-surface drift across the mesh."""

    return max(
        abs(cell.geometry.stage_from_area(area) - reference_stage)
        for cell, area in zip(mesh.cells, state.area)
    )


def test_nonprismatic_rectangular_lake_at_rest_is_well_balanced() -> None:
    """Varying rectangular width must not create spurious mass or momentum."""

    mesh = _mesh(
        tuple(
            RectangularSectionGeometry(width=width, bed_elevation=0.0)
            for width in (4.0, 5.0, 6.0, 5.5, 4.5, 5.0)
        )
    )
    initial = _state(mesh, 2.0)
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=_boundaries(2.0, 60.0),
        config=_config(),
    )

    assert max(abs(value) for value in result.states[-1].velocity) <= 1.0e-10
    assert _maximum_stage_drift(mesh, result.states[-1], 2.0) <= 1.0e-10
    assert result.diagnostics.relative_water_balance_error <= 1.0e-12
    assert (
        "nonprismatic_hydraulic_function_linear_face_source_v1"
        in result.diagnostics.diagnostic_flags
    )


def test_nonprismatic_face_weight_uses_nonuniform_cell_centre_distance() -> None:
    """The face path location is dx_left / (dx_left + dx_right), not 0.5."""

    left = FiniteVolumeCell(
        cell_id="left",
        dx=3.0,
        section_id=1,
        bed_elevation=0.0,
        geometry=RectangularSectionGeometry(width=4.0, bed_elevation=0.0),
    )
    right = FiniteVolumeCell(
        cell_id="right",
        dx=100.0,
        section_id=2,
        bed_elevation=0.0,
        geometry=RectangularSectionGeometry(width=7.0, bed_elevation=0.0),
    )

    face = internal_face_geometry(left, right)

    assert face.right_weight == pytest.approx(3.0 / 103.0, abs=1.0e-15)


def test_nonprismatic_tabulated_lake_at_rest_and_perturbation_evolves() -> None:
    """The path preserves rest but must not freeze a nearby perturbed state."""

    profiles = (
        ((-6.0, 3.0), (-2.0, 0.0), (2.0, 0.0), (6.0, 3.0)),
        ((-7.0, 3.2), (-2.5, 0.0), (2.5, 0.0), (7.0, 3.2)),
        ((-5.5, 2.8), (-1.5, 0.0), (1.5, 0.0), (5.5, 2.8)),
        ((-6.5, 3.1), (-2.2, 0.0), (2.2, 0.0), (6.5, 3.1)),
    )
    mesh = _mesh(
        tuple(TabulatedSectionGeometry.from_points(points) for points in profiles)
    )
    comparison_geometries = (mesh.cells[0].geometry, mesh.cells[1].geometry)
    areas = {geometry.area(1.5) for geometry in comparison_geometries}
    widths = {
        geometry.top_width(1.5)
        for geometry in comparison_geometries
    }
    moments = {
        geometry.pressure_moment(1.5)
        for geometry in comparison_geometries
    }
    assert len(areas) == len(widths) == len(moments) == 2
    initial = _state(mesh, 1.5)
    rest = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=_boundaries(1.5, 20.0),
        config=_config(20.0),
    )
    assert max(abs(value) for value in rest.states[-1].velocity) <= 1.0e-10
    assert _maximum_stage_drift(mesh, rest.states[-1], 1.5) <= 1.0e-10

    perturbed_area = list(initial.area)
    perturbed_area[1] *= 1.001
    perturbed = replace(
        initial,
        area=tuple(perturbed_area),
        water_depth=tuple(
            cell.geometry.stage_from_area(area) - cell.bed_elevation
            for cell, area in zip(mesh.cells, perturbed_area)
        ),
    )
    evolved = forward_euler_stage(
        mesh=mesh,
        state=perturbed,
        dt=0.1,
        dry_depth=1.0e-3,
        boundaries=_boundaries(1.5, 2.0),
        geometry_source_mode="hydraulic-function-linear-face-v1",
    )
    assert evolved.state.area != pytest.approx(perturbed.area, abs=1.0e-12)
    assert max(abs(value) for value in evolved.state.discharge) > 1.0e-8


def test_nonprismatic_shape_and_bed_variation_preserve_common_absolute_stage() -> None:
    """The same path must balance simultaneous bed and section-shape variation."""

    relative_profiles = (
        ((-6.0, 3.0), (-2.0, 0.0), (2.0, 0.0), (6.0, 3.0)),
        ((-7.0, 3.2), (-2.5, 0.0), (2.5, 0.0), (7.0, 3.2)),
        ((-5.5, 2.8), (-1.5, 0.0), (1.5, 0.0), (5.5, 2.8)),
        ((-6.5, 3.1), (-2.2, 0.0), (2.2, 0.0), (6.5, 3.1)),
    )
    beds = (0.0, 0.15, 0.30, 0.10)
    geometries = tuple(
        TabulatedSectionGeometry.from_points(
            tuple((offset, relative + bed) for offset, relative in profile)
        )
        for profile, bed in zip(relative_profiles, beds)
    )
    mesh = _mesh(geometries)
    initial = _state(mesh, 1.5)
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=_boundaries(1.5, 30.0),
        config=_config(30.0),
    )

    assert max(abs(value) for value in result.states[-1].velocity) <= 1.0e-10
    assert _maximum_stage_drift(mesh, result.states[-1], 1.5) <= 1.0e-10
    assert result.diagnostics.relative_water_balance_error <= 1.0e-12


def test_legacy_geometry_source_default_remains_the_original_operator() -> None:
    """The old default must retain its documented non-prismatic limitation."""

    mesh = _mesh(
        tuple(
            RectangularSectionGeometry(width=width, bed_elevation=0.0)
            for width in (4.0, 5.0, 6.0, 5.0)
        )
    )
    initial = _state(mesh, 2.0)
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=_boundaries(
            2.0,
            5.0,
            closure="zero-gradient-companion-v1",
        ),
        config=replace(_config(5.0), geometry_source_mode="hydrostatic-reconstruction-v1"),
    )

    assert max(abs(value) for value in result.states[-1].velocity) > 1.0e-3
    assert _maximum_stage_drift(mesh, result.states[-1], 2.0) > 1.0e-4


def test_nonprismatic_public_scope_rejects_moving_or_legacy_boundary_inputs() -> None:
    """The orchestrator must not expose unvalidated moving-water combinations."""

    mesh = _mesh(
        tuple(
            RectangularSectionGeometry(width=width, bed_elevation=0.0)
            for width in (4.0, 5.0, 6.0)
        )
    )
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=tuple(cell.geometry.area(2.0) for cell in mesh.cells),
        discharge=(1.0, 1.0, 1.0),
        dry_depth=1.0e-3,
    )
    with pytest.raises(ValueError, match="zero initial discharge"):
        solve_single_branch(
            mesh=mesh,
            initial_state=initial,
            boundaries=_boundaries(2.0, 5.0),
            config=_config(5.0),
        )

    with pytest.raises(ValueError, match="requires characteristic boundaries"):
        solve_single_branch(
            mesh=mesh,
            initial_state=_state(mesh, 2.0),
            boundaries=_boundaries(
                2.0,
                5.0,
                closure="zero-gradient-companion-v1",
            ),
            config=_config(5.0),
        )

    with pytest.raises(ValueError, match="does not support structures"):
        solve_single_branch(
            mesh=mesh,
            initial_state=_state(mesh, 2.0),
            boundaries=_boundaries(2.0, 5.0),
            config=_config(5.0),
            gates=(
                FixedGate(
                    gate_id="gate-1",
                    face_index=0,
                    opening=0.5,
                    width=1.0,
                    height=1.0,
                ),
            ),
        )

    shallow = _state(mesh, 5.0e-4)
    with pytest.raises(ValueError, match="every cell fully wet"):
        solve_single_branch(
            mesh=mesh,
            initial_state=shallow,
            boundaries=_boundaries(5.0e-4, 5.0),
            config=_config(5.0),
        )


def test_nonprismatic_core_stage_match_is_not_scaled_by_vertical_datum() -> None:
    """The core preflight uses absolute H tolerance on a large vertical datum."""

    shift = 1_000_000.0
    mesh = _mesh(
        tuple(
            RectangularSectionGeometry(width=width, bed_elevation=shift)
            for width in (4.0, 5.0, 6.0)
        )
    )
    stages = (shift + 2.0 + 4.0e-5, shift + 2.0 + 2.0e-5, shift + 2.0)
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=tuple(
            cell.geometry.area(stage) for cell, stage in zip(mesh.cells, stages)
        ),
        discharge=(0.0, 0.0, 0.0),
        dry_depth=1.0e-3,
    )

    with pytest.raises(ValueError, match="constant non-prismatic initial stage"):
        solve_single_branch(
            mesh=mesh,
            initial_state=initial,
            boundaries=_boundaries(shift + 2.0, 5.0),
            config=_config(5.0),
        )
