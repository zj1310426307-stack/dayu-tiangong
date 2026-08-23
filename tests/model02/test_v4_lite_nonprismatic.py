"""End-to-end gates for the explicitly bounded non-prismatic lake path."""

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
from model.provenance import snapshot_hash
from tests.model02.test_v4_lite_engine import make_short_v4_lite_payload


def make_nonprismatic_lake_payload() -> dict:
    """Build one fully wet, zero-flow lake with three distinct section shapes."""

    payload = make_short_v4_lite_payload()
    duration = 60.0
    payload["solver"].update(
        {
            "duration_seconds": duration,
            "maximum_time_step_seconds": 2.0,
            "output_interval_seconds": 10.0,
            "geometry_policy": "nonprismatic-section-linear-path-v1",
            "geometry_source": "hydraulic-function-linear-face-v1",
            "bed_elevation_source": "profile-minimum-elevation-v1",
            "equilibrium_policy": "standard-v1",
            "boundary_closure": "subcritical-characteristic-v1",
            "boundary_spatial_support": "nearest-section-cell-face-v1",
        }
    )
    profiles = (
        ((-6.0, 11.0), (-2.0, 8.0), (2.0, 8.0), (6.0, 11.0)),
        ((-7.0, 11.4), (-2.5, 8.2), (2.5, 8.2), (7.0, 11.4)),
        ((-5.5, 10.7), (-1.5, 7.9), (1.5, 7.9), (5.5, 10.7)),
    )
    for section, points in zip(payload["sections"], profiles):
        section["points"] = [
            {"offset_m": offset, "elevation_m": elevation}
            for offset, elevation in points
        ]
        section["default_manning_n"] = 0.03
    payload["initial_state"] = {
        "type": "uniform",
        "water_level_m": 10.0,
        "discharge_m3_s": 0.0,
    }
    payload["boundary"]["upstream"].update(
        {
            "time_seconds": [0.0, duration],
            "flow_m3_s": [0.0, 0.0],
        }
    )
    payload["boundary"]["downstream"].update(
        {
            "time_seconds": [0.0, duration],
            "water_level_m": [10.0, 10.0],
        }
    )
    payload["structures"] = {"gates": [], "pumps": []}
    payload["provenance"]["validation_policy_version"] = "v4-lite-2"
    payload["provenance"]["engine_commit"] = "b2-nonprismatic-test"
    return payload


def test_nonprismatic_lake_runs_through_the_public_v4_lite_entry() -> None:
    """Distinct A/T/I1 sections retain a common stage and zero discharge."""

    payload = make_nonprismatic_lake_payload()
    parsed = parse_v4_lite_input(payload)
    mesh = build_v4_lite_mesh(parsed)
    first, second = (cell.geometry for cell in mesh.cells[:2])
    assert first.area(10.0) != pytest.approx(second.area(10.0))
    assert first.top_width(10.0) != pytest.approx(second.top_width(10.0))
    assert first.pressure_moment(10.0) != pytest.approx(
        second.pressure_moment(10.0)
    )

    result = HydraulicEngine().run(payload)
    levels = tuple(level for section in result.sections for level in section.water_level)
    flows = tuple(flow for section in result.sections for flow in section.flow)
    velocities = tuple(
        velocity for section in result.sections for velocity in section.velocity
    )

    assert max(abs(level - 10.0) for level in levels) <= 1.0e-9
    assert max(abs(flow) for flow in flows) <= 1.0e-9
    assert max(abs(velocity) for velocity in velocities) <= 1.0e-10
    assert result.water_balance.status == "pass"
    assert result.water_balance.relative_water_balance_error <= 1.0e-10
    assert result.diagnostics.retry_count == 0
    assert {
        "boundary_closure_subcritical-characteristic-v1",
        "nonprismatic_hydraulic_function_linear_face_source_v1",
        "boundary_spatial_support_nearest-section-cell-face-v1",
    }.issubset(result.diagnostics.diagnostic_flags)
    assert result.provenance.input_snapshot_hash == snapshot_hash(payload) == (
        "0cf13e30178f0eb6f92721874894c6aa0594610ff3886f1483584c791142cad0"
    )
    assert result.provenance.mesh_hash == (
        "642f4253b0ffeaa856b1c067e8423dfd46aefba52dfc525fa9cd88400d0245a2"
    )
    assert result.provenance.solver_policy_hash == (
        "abd28072f9ac7b9095df840eb1f46e8a2d80803490089c0164618b23f41214eb"
    )


def test_nonprismatic_hashes_separate_mesh_policy_and_boundary_identity() -> None:
    """Geometry changes mesh identity while an asset-only boundary change does not."""

    payload = make_nonprismatic_lake_payload()
    parsed = parse_v4_lite_input(payload)
    mesh = build_v4_lite_mesh(parsed)

    boundary_changed = copy.deepcopy(payload)
    boundary_changed["boundary"]["upstream"]["identity"]["id"] += 100
    boundary_parsed = parse_v4_lite_input(boundary_changed)
    boundary_mesh = build_v4_lite_mesh(boundary_parsed)
    assert snapshot_hash(boundary_changed) != snapshot_hash(payload)
    assert v4_lite_mesh_hash(boundary_parsed, boundary_mesh) == v4_lite_mesh_hash(
        parsed,
        mesh,
    )
    assert v4_lite_solver_policy_hash(boundary_parsed) == v4_lite_solver_policy_hash(
        parsed
    )

    geometry_changed = copy.deepcopy(payload)
    geometry_changed["sections"][1]["points"][0]["offset_m"] -= 0.1
    geometry_parsed = parse_v4_lite_input(geometry_changed)
    geometry_mesh = build_v4_lite_mesh(geometry_parsed)
    assert v4_lite_mesh_hash(geometry_parsed, geometry_mesh) != v4_lite_mesh_hash(
        parsed,
        mesh,
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("identical_shapes", "requires at least two distinct hydraulic Profile signatures"),
        ("translated_shapes", "requires at least two distinct hydraulic Profile signatures"),
        (
            "redundant_collinear_points",
            "requires at least two distinct hydraulic Profile signatures",
        ),
        ("moving_initial", "requires zero initial discharge"),
        ("noncommon_stage", "requires one common initial stage"),
        ("nonzero_upstream", "requires zero upstream discharge"),
        ("wrong_downstream", "downstream stage must match"),
        ("with_structure", "does not support structures"),
        ("legacy_boundary", "policy tuple is not implemented"),
        ("legacy_source", "policy tuple is not implemented"),
        ("unknown_boundary_support", "boundary_spatial_support"),
    ],
)
def test_nonprismatic_v4_policy_fails_closed(mutation: str, message: str) -> None:
    """Unverified moving, inferred, mixed-policy, or structure cases are rejected."""

    payload = make_nonprismatic_lake_payload()
    if mutation == "identical_shapes":
        reference = copy.deepcopy(payload["sections"][0]["points"])
        for section in payload["sections"][1:]:
            section["points"] = copy.deepcopy(reference)
    elif mutation == "translated_shapes":
        reference = copy.deepcopy(payload["sections"][0]["points"])
        for index, section in enumerate(payload["sections"][1:], start=1):
            section["points"] = [
                {
                    "offset_m": point["offset_m"] + 10.0 * index,
                    "elevation_m": point["elevation_m"],
                }
                for point in reference
            ]
    elif mutation == "redundant_collinear_points":
        reference = copy.deepcopy(payload["sections"][0]["points"])
        payload["sections"][1]["points"] = [
            copy.deepcopy(reference[0]),
            {"offset_m": -4.0, "elevation_m": 9.5},
            *copy.deepcopy(reference[1:]),
        ]
        payload["sections"][2]["points"] = copy.deepcopy(reference)
    elif mutation == "moving_initial":
        payload["initial_state"]["discharge_m3_s"] = 0.1
    elif mutation == "noncommon_stage":
        payload["initial_state"] = {
            "type": "by-section",
            "values": [
                {
                    "section_id": section["section_id"],
                    "water_level_m": 10.0 + 0.01 * index,
                    "discharge_m3_s": 0.0,
                }
                for index, section in enumerate(payload["sections"])
            ],
        }
    elif mutation == "nonzero_upstream":
        payload["boundary"]["upstream"]["flow_m3_s"] = [0.1, 0.1]
    elif mutation == "wrong_downstream":
        payload["boundary"]["downstream"]["water_level_m"] = [10.1, 10.1]
    elif mutation == "with_structure":
        payload["structures"]["gates"] = [
            {
                "identity": {"namespace": "public.gate", "id": 51},
                "branch_id": 21,
                "interface": {
                    "upstream_section_id": 1,
                    "downstream_section_id": 2,
                },
                "opening_m": 0.0,
                "width_m": 4.0,
                "height_m": 2.0,
                "discharge_coefficient": 0.62,
                "allow_reverse_flow": False,
            }
        ]
    elif mutation == "legacy_boundary":
        payload["solver"]["boundary_closure"] = "zero-gradient-companion-v1"
    elif mutation == "legacy_source":
        payload["solver"]["geometry_source"] = "hydrostatic-reconstruction-v1"
    elif mutation == "unknown_boundary_support":
        payload["solver"]["boundary_spatial_support"] = "node-section-v1"

    with pytest.raises(HydraulicInputError, match=message):
        parse_v4_lite_input(payload)


def test_nonprismatic_absolute_stage_match_is_datum_invariant() -> None:
    """Large absolute elevations cannot introduce a relative-tolerance loophole."""

    payload = make_nonprismatic_lake_payload()
    shift = 1_000_000.0
    for section in payload["sections"]:
        for point in section["points"]:
            point["elevation_m"] += shift
    payload["boundary"]["downstream"]["water_level_m"] = [
        value + shift for value in payload["boundary"]["downstream"]["water_level_m"]
    ]
    payload["initial_state"]["water_level_m"] += shift
    parse_v4_lite_input(payload)
    payload["initial_state"] = {
        "type": "by-section",
        "values": [
            {
                "section_id": section["section_id"],
                "water_level_m": 10.0 + shift + delta,
                "discharge_m3_s": 0.0,
            }
            for section, delta in zip(payload["sections"], (4.0e-5, 2.0e-5, 0.0))
        ],
    }

    with pytest.raises(HydraulicInputError, match="requires one common initial stage"):
        parse_v4_lite_input(payload)
