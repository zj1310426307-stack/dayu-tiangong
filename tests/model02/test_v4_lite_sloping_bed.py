"""B2 contracts for versioned sloping-bed v4 input and end-to-end Case002."""

from __future__ import annotations

import copy

import pytest

from model.adapters import (
    build_v4_lite_mesh,
    v4_lite_mesh_hash,
    v4_lite_solver_policy_hash,
)
from model.api import parse_v4_lite_input
from model.core.errors import HydraulicInputError
from model.engine import HydraulicEngine
from model.geometry.sections import TabulatedSectionGeometry
from model.provenance import snapshot_hash
from tests.model02.test_v4_lite_engine import make_short_v4_lite_payload


def make_sloping_bed_v4_payload(
    *,
    equilibrium_policy: str = "uniform-manning-reference-v1",
) -> dict:
    """Build one explicit cell-centred, relative-prismatic Manning reference."""

    relative_points = ((0.0, 4.0), (1.0, 0.0), (9.0, 0.0), (10.0, 4.0))
    relative_geometry = TabulatedSectionGeometry.from_points(relative_points)
    normal_depth = 2.0
    discharge = 20.0
    manning_n = 0.03
    area = relative_geometry.area(normal_depth)
    radius = relative_geometry.hydraulic_radius(normal_depth)
    bed_slope = (
        discharge * manning_n / (area * radius ** (2.0 / 3.0))
    ) ** 2
    dx = 50.0
    cell_count = 20
    duration = 120.0
    beds = tuple(
        10.0 - bed_slope * (index + 0.5) * dx for index in range(cell_count)
    )
    sections = [
        {
            "section_id": index + 1,
            "section_code": f"B2-{index + 1:03d}",
            "branch_id": 21,
            "chainage_m": (index + 0.5) * dx,
            "profile_id": 1001 + index,
            "profile_hash": f"{1001 + index:064x}",
            "default_manning_n": manning_n,
            "points": [
                {"offset_m": offset, "elevation_m": bed + relative_height}
                for offset, relative_height in relative_points
            ],
        }
        for index, bed in enumerate(beds)
    ]
    return {
        "schema_version": "dayu.model-input.v4-lite",
        "dataset_version": {"id": 2, "content_hash": "b" * 64},
        "coordinate_reference": {
            "engineering_crs": "EPSG:4547",
            "horizontal_unit": "m",
            "vertical_datum": "1985 National Height Datum",
            "vertical_unit": "m",
        },
        "solver": {
            "type": "saint-venant",
            "scheme": "finite-volume-hll",
            "time_integrator": "ssp-rk2",
            "friction_method": "manning-semi-implicit",
            "duration_seconds": duration,
            "maximum_time_step_seconds": 2.0,
            "minimum_time_step_seconds": 0.0001,
            "output_interval_seconds": 30.0,
            "cfl_number": 0.5,
            "dry_depth_m": 0.001,
            "maximum_retries": 8,
            "maximum_steps": 100000,
            "water_balance_tolerance": 0.01,
            "geometry_policy": "relative-prismatic-linear-bed-v1",
            "geometry_source": "hydrostatic-reconstruction-v1",
            "bed_elevation_source": "profile-minimum-elevation-v1",
            "equilibrium_policy": equilibrium_policy,
            "boundary_closure": "subcritical-characteristic-v1",
            "boundary_spatial_support": "nearest-section-cell-face-v1",
        },
        "river": {
            "network_id": 11,
            "branch_id": 21,
            "branch_code": "B2-SLOPE",
            "upstream_node_id": 31,
            "downstream_node_id": 32,
            "start_chainage_m": 0.0,
            "end_chainage_m": cell_count * dx,
            "direction_status": "confirmed",
        },
        "sections": sections,
        "initial_state": {
            "type": "by-section",
            "values": [
                {
                    "section_id": index + 1,
                    "water_level_m": bed + normal_depth,
                    "discharge_m3_s": discharge,
                }
                for index, bed in enumerate(beds)
            ],
        },
        "boundary": {
            "upstream": {
                "identity": {"namespace": "public.boundary_condition", "id": 41},
                "type": "discharge-series",
                "target_node_id": 31,
                "time_seconds": [0.0, duration],
                "flow_m3_s": [discharge, discharge],
                "interpolation": "linear",
                "extrapolation": "error",
            },
            "downstream": {
                "identity": {"namespace": "public.boundary_condition", "id": 42},
                "type": "stage-series",
                "target_node_id": 32,
                "time_seconds": [0.0, duration],
                "water_level_m": [
                    beds[-1] + normal_depth,
                    beds[-1] + normal_depth,
                ],
                "interpolation": "linear",
                "extrapolation": "error",
            },
        },
        "structures": {"gates": [], "pumps": []},
        "provenance": {
            "engine_version": "dayu-hydraulic-mvp",
            "engine_commit": "b2-test",
            "validation_policy_version": "v4-lite-2",
        },
    }


def _vertical_shift(payload: dict, shift: float) -> dict:
    """Shift all absolute vertical values while retaining the relative shape."""

    shifted = copy.deepcopy(payload)
    for section in shifted["sections"]:
        for point in section["points"]:
            point["elevation_m"] += shift
    for value in shifted["initial_state"]["values"]:
        value["water_level_m"] += shift
    shifted["boundary"]["downstream"]["water_level_m"] = [
        value + shift
        for value in shifted["boundary"]["downstream"]["water_level_m"]
    ]
    return shifted


def test_legacy_v4_bytes_and_mesh_hash_remain_unchanged() -> None:
    """Missing policy fields retain the exact v4-lite-1 snapshot and mesh identity."""

    payload = make_short_v4_lite_payload()
    parsed = parse_v4_lite_input(payload)
    mesh = build_v4_lite_mesh(parsed)

    assert parsed.solver.policy_tuple == (
        "absolute-prismatic-v1",
        "hydrostatic-reconstruction-v1",
        "profile-minimum-elevation-v1",
        "standard-v1",
        "zero-gradient-companion-v1",
        "nearest-section-cell-face-v1",
    )
    assert snapshot_hash(payload) == (
        "9e7306e97cd02bee640f8d474e8230c01f42c7b516d75ffa341bb16251d4438c"
    )
    assert v4_lite_mesh_hash(parsed, mesh) == (
        "e0647e54e6444e641ad30bfe0eadae25471e4b666883677ade04f6419a15e551"
    )
    assert "solver_policy_hash" not in (
        HydraulicEngine().run(payload).to_dict()["provenance"]
    )


def test_v2_relative_profiles_build_a_linear_cell_centred_bed() -> None:
    """Absolute Profile shifts become explicit beds without changing relative shape."""

    payload = make_sloping_bed_v4_payload()
    parsed = parse_v4_lite_input(payload)
    mesh = build_v4_lite_mesh(parsed)

    assert parsed.provenance.validation_policy_version == "v4-lite-2"
    assert tuple(cell.dx for cell in mesh.cells) == pytest.approx((50.0,) * 20)
    assert tuple(cell.bed_elevation for cell in mesh.cells) == pytest.approx(
        tuple(section.minimum_stage_m for section in parsed.sections)
    )
    relative_shapes = {
        tuple(
            (point.offset_m, point.elevation_m - section.minimum_stage_m)
            for point in section.points
        )
        for section in parsed.sections
    }
    assert len(relative_shapes) == 1


def test_v2_geometry_and_solver_policy_hashes_have_distinct_authority() -> None:
    """Mesh binds geometry while a separate hash binds the execution policy."""

    payload = make_sloping_bed_v4_payload()
    parsed = parse_v4_lite_input(payload)
    mesh = build_v4_lite_mesh(parsed)
    shifted_payload = _vertical_shift(payload, 100.0)
    shifted = parse_v4_lite_input(shifted_payload)
    shifted_mesh = build_v4_lite_mesh(shifted)
    standard_payload = make_sloping_bed_v4_payload(
        equilibrium_policy="standard-v1"
    )
    standard = parse_v4_lite_input(standard_payload)
    standard_mesh = build_v4_lite_mesh(standard)

    assert snapshot_hash(payload) != snapshot_hash(shifted_payload)
    assert v4_lite_mesh_hash(parsed, mesh) != v4_lite_mesh_hash(
        shifted, shifted_mesh
    )
    assert v4_lite_mesh_hash(parsed, mesh) == v4_lite_mesh_hash(
        standard, standard_mesh
    )
    assert v4_lite_solver_policy_hash(parsed) != v4_lite_solver_policy_hash(
        standard
    )


def test_case002_v4_lite_uniform_manning_reference_scientific_gate() -> None:
    """Run the analytic moving equilibrium through the public v4-lite entry."""

    payload = make_sloping_bed_v4_payload()
    result = HydraulicEngine().run(payload)
    expected_depth = 2.0
    expected_flow = 20.0
    beds = tuple(
        min(point["elevation_m"] for point in section["points"])
        for section in payload["sections"]
    )
    depth_errors = tuple(
        abs(level - bed - expected_depth)
        for section, bed in zip(result.sections, beds)
        for level in section.water_level
    )
    flow_errors = tuple(
        abs(flow - expected_flow)
        for section in result.sections
        for flow in section.flow
    )

    assert result.provenance.input_snapshot_hash == (
        "c801df9b35a826454be1ec626663b7da8af91ce4761e6f5d007f5f9630ab1d24"
    )
    assert result.provenance.mesh_hash == (
        "285ff28c4d7ee4628240537156d81b82b79de5b85bc86fe74fa7f5cdb335dae0"
    )
    assert result.provenance.solver_policy_hash == (
        "b5725ce8c6e9437592c942af0a3b533844e8109948078c530119469dc2ea4185"
    )
    assert max(depth_errors) <= 1.0e-9
    assert max(flow_errors) <= 1.0e-9
    assert result.water_balance.status == "pass"
    assert result.water_balance.relative_water_balance_error <= 1.0e-10
    assert result.diagnostics.maximum_cfl <= payload["solver"]["cfl_number"]
    assert result.diagnostics.retry_count == 0
    assert {
        "boundary_closure_subcritical-characteristic-v1",
        "moving_uniform_manning_residual_equilibrium_v1",
        "boundary_spatial_support_nearest-section-cell-face-v1",
    }.issubset(result.diagnostics.diagnostic_flags)
    assert result.to_dict()["provenance"]["solver_policy_hash"] == (
        result.provenance.solver_policy_hash
    )


def test_case002_absolute_stage_match_is_not_scaled_by_vertical_datum() -> None:
    """A large datum shift must not make a 4e-5 m H mismatch look equal."""

    payload = _vertical_shift(make_sloping_bed_v4_payload(), 1_000_000.0)
    parse_v4_lite_input(payload)
    payload["boundary"]["downstream"]["water_level_m"] = [
        value + 4.0e-5
        for value in payload["boundary"]["downstream"]["water_level_m"]
    ]

    with pytest.raises(HydraulicInputError, match="downstream boundary must match"):
        parse_v4_lite_input(payload)


def test_case002_contract_uses_the_core_equilibrium_tolerance() -> None:
    """A shape delta rejected by the core cannot pass the public v4 contract."""

    payload = make_sloping_bed_v4_payload()
    payload["sections"][3]["points"][0]["elevation_m"] += 5.0e-10

    with pytest.raises(HydraulicInputError, match="identical relative Profile shapes"):
        HydraulicEngine().run(payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("wrong_manning_slope", "does not satisfy Manning equilibrium"),
        ("supercritical", "requires subcritical flow"),
    ],
)
def test_case002_engine_preflight_does_not_freeze_arbitrary_constant_states(
    mutation: str,
    message: str,
) -> None:
    """Structurally valid but non-equilibrium references fail before stepping."""

    payload = make_sloping_bed_v4_payload()
    if mutation == "wrong_manning_slope":
        first_bed = min(
            point["elevation_m"] for point in payload["sections"][0]["points"]
        )
        second_bed = min(
            point["elevation_m"] for point in payload["sections"][1]["points"]
        )
        base_drop = first_bed - second_bed
        final_shift = 0.0
        for index, (section, initial) in enumerate(
            zip(payload["sections"], payload["initial_state"]["values"])
        ):
            current_bed = min(
                point["elevation_m"] for point in section["points"]
            )
            target_bed = first_bed - 1.1 * base_drop * index
            shift = target_bed - current_bed
            for point in section["points"]:
                point["elevation_m"] += shift
            initial["water_level_m"] += shift
            final_shift = shift
        payload["boundary"]["downstream"]["water_level_m"] = [
            value + final_shift
            for value in payload["boundary"]["downstream"]["water_level_m"]
        ]
    else:
        for initial in payload["initial_state"]["values"]:
            initial["discharge_m3_s"] = 200.0
        payload["boundary"]["upstream"]["flow_m3_s"] = [200.0, 200.0]

    parse_v4_lite_input(payload)
    with pytest.raises(ValueError, match=message):
        HydraulicEngine().run(payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("v1_shifted_profile", "identical absolute Profile points"),
        ("v1_explicit_policy", "does not accept explicit versioned policy fields"),
        ("v2_missing_policy", "every versioned policy field explicitly"),
        (
            "v2_policy_with_v1_provenance",
            "does not accept explicit versioned policy fields",
        ),
        ("relative_shape_mismatch", "identical relative Profile shapes"),
        ("nonlinear_bed", "one linear bed slope"),
        ("non_descending_bed", "strictly descending bed"),
        ("non_cell_centred", "finite-volume cell centers"),
        ("uniform_initial_state", "requires by-section initial_state"),
        ("dynamic_upstream", "constant upstream discharge boundary"),
        ("wrong_downstream", "downstream boundary must match"),
        ("unknown_policy_mix", "policy tuple is not implemented"),
    ],
)
def test_v2_sloping_bed_contract_fails_closed(mutation: str, message: str) -> None:
    """Missing, mixed, inferred, or physically inconsistent B2 inputs are rejected."""

    if mutation == "v1_shifted_profile":
        payload = make_short_v4_lite_payload()
        payload["sections"][1]["points"] = [
            {
                "offset_m": point["offset_m"],
                "elevation_m": point["elevation_m"] - 0.1,
            }
            for point in payload["sections"][1]["points"]
        ]
    elif mutation == "v1_explicit_policy":
        payload = make_short_v4_lite_payload()
        payload["solver"]["geometry_policy"] = "absolute-prismatic-v1"
    else:
        payload = make_sloping_bed_v4_payload()
    if mutation == "v2_missing_policy":
        payload["solver"].pop("bed_elevation_source")
    elif mutation == "v2_policy_with_v1_provenance":
        payload["provenance"]["validation_policy_version"] = "v4-lite-1"
    elif mutation == "relative_shape_mismatch":
        payload["sections"][3]["points"][0]["elevation_m"] += 0.1
    elif mutation in {"nonlinear_bed", "non_descending_bed"}:
        section = payload["sections"][8]
        shift = 0.001 if mutation == "nonlinear_bed" else 1.0
        for point in section["points"]:
            point["elevation_m"] += shift
    elif mutation == "non_cell_centred":
        payload["river"]["start_chainage_m"] = 10.0
    elif mutation == "uniform_initial_state":
        first = payload["initial_state"]["values"][0]
        payload["initial_state"] = {
            "type": "uniform",
            "water_level_m": first["water_level_m"],
            "discharge_m3_s": first["discharge_m3_s"],
        }
    elif mutation == "dynamic_upstream":
        payload["boundary"]["upstream"]["flow_m3_s"][1] += 0.1
    elif mutation == "wrong_downstream":
        reference = payload["boundary"]["downstream"]["water_level_m"][0]
        payload["boundary"]["downstream"]["water_level_m"] = [
            reference + 0.1,
            reference + 0.1,
        ]
    elif mutation == "unknown_policy_mix":
        payload["solver"]["geometry_source"] = "hydraulic-function-linear-face-v1"

    with pytest.raises(HydraulicInputError, match=message):
        parse_v4_lite_input(payload)
