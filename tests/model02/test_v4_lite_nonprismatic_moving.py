"""End-to-end gates for the v4-lite-3 moving non-prismatic reference."""

from __future__ import annotations

import copy
import math

import pytest

from model.adapters import build_v4_lite_mesh, v4_lite_solver_policy_hash
from model.api import parse_v4_lite_input
from model.core.errors import HydraulicInputError
from model.engine import HydraulicEngine
from model.geometry.sections import TabulatedSectionGeometry
from model.provenance import snapshot_hash
from model.solver.finite_volume import (
    NONPRISMATIC_MOVING_ENERGY_SCOPE,
    NumericalStateError,
)
from tests.model02.test_v4_lite_contract import make_v4_lite_payload

_GRAVITY = 9.81
_DOMAIN_LENGTH_M = 1_000.0
_FLOW_M3_S = 5.0
_REFERENCE_DEPTH_M = 2.0
_CELL_COUNT = 25


def _width_at(chainage_m: float) -> float:
    """Return the smooth manufactured bottom-width field."""

    phase = math.pi * chainage_m / _DOMAIN_LENGTH_M
    return 5.0 + 2.0 * math.sin(phase) ** 2


def _profile_points(width: float, *, datum: float = 0.0) -> tuple[tuple[float, float], ...]:
    """Return one symmetric 1H:1V trapezoid with a 5 m bank height."""

    half_bottom = 0.5 * width
    return (
        (-half_bottom - 5.0, datum + 5.0),
        (-half_bottom, datum),
        (half_bottom, datum),
        (half_bottom + 5.0, datum + 5.0),
    )


def _geometry(width: float, *, datum: float = 0.0) -> TabulatedSectionGeometry:
    """Build the same table geometry consumed by the public adapter."""

    return TabulatedSectionGeometry.from_points(_profile_points(width, datum=datum))


def _reference_energy_head(*, datum: float = 0.0) -> float:
    """Return the fixed total head at bottom width 5 m and depth 2 m."""

    geometry = _geometry(5.0, datum=datum)
    stage = datum + _REFERENCE_DEPTH_M
    area = geometry.area(stage)
    return stage + _FLOW_M3_S**2 / (2.0 * _GRAVITY * area**2)


def _subcritical_stage(width: float, *, datum: float = 0.0) -> float:
    """Solve the high Bernoulli root against the actual tabulated geometry."""

    geometry = _geometry(width, datum=datum)
    energy = _reference_energy_head(datum=datum)
    lower = datum + 0.5
    upper = datum + 3.0
    for _ in range(100):
        middle = 0.5 * (lower + upper)
        area = geometry.area(middle)
        residual = middle + _FLOW_M3_S**2 / (
            2.0 * _GRAVITY * area**2
        ) - energy
        if residual > 0.0:
            upper = middle
        else:
            lower = middle
    return 0.5 * (lower + upper)


def make_moving_nonprismatic_payload(*, datum: float = 0.0) -> dict:
    """Build the exact v4-lite-3 frictionless-energy reference snapshot."""

    payload = make_v4_lite_payload()
    duration = 5.0
    dx = _DOMAIN_LENGTH_M / _CELL_COUNT
    payload["solver"].update(
        {
            "duration_seconds": duration,
            "maximum_time_step_seconds": 0.1,
            "minimum_time_step_seconds": 1.0e-8,
            "output_interval_seconds": duration,
            "cfl_number": 0.5,
            "water_balance_tolerance": 1.0e-6,
            "geometry_policy": "nonprismatic-frictionless-energy-reference-v1",
            "geometry_source": "hydraulic-function-linear-face-v1",
            "bed_elevation_source": "profile-minimum-elevation-v1",
            "equilibrium_policy": "standard-v1",
            "boundary_closure": "subcritical-characteristic-v1",
            "boundary_spatial_support": "nearest-section-cell-face-v1",
        }
    )
    sections = []
    values = []
    for index in range(_CELL_COUNT):
        chainage = (index + 0.5) * dx
        width = _width_at(chainage)
        stage = _subcritical_stage(width, datum=datum)
        section_id = index + 1
        sections.append(
            {
                "section_id": section_id,
                "section_code": f"MV{section_id:03d}",
                "branch_id": payload["river"]["branch_id"],
                "chainage_m": chainage,
                "profile_id": 10_000 + section_id,
                "profile_hash": f"{10_000 + section_id:064x}",
                "default_manning_n": 0.0,
                "points": [
                    {"offset_m": offset, "elevation_m": elevation}
                    for offset, elevation in _profile_points(width, datum=datum)
                ],
            }
        )
        values.append(
            {
                "section_id": section_id,
                "water_level_m": stage,
                "discharge_m3_s": _FLOW_M3_S,
            }
        )
    payload["sections"] = sections
    payload["initial_state"] = {"type": "by-section", "values": values}
    payload["boundary"]["upstream"].update(
        {
            "time_seconds": [0.0, duration],
            "flow_m3_s": [_FLOW_M3_S, _FLOW_M3_S],
        }
    )
    final_stage = values[-1]["water_level_m"]
    payload["boundary"]["downstream"].update(
        {
            "time_seconds": [0.0, duration],
            "water_level_m": [final_stage, final_stage],
        }
    )
    payload["structures"] = {"gates": [], "pumps": []}
    payload["provenance"].update(
        {
            "validation_policy_version": "v4-lite-3",
            "engine_commit": "c1-moving-nonprismatic-test",
        }
    )
    return payload


def test_v4_lite_3_moving_reference_runs_with_frozen_quality_evidence() -> None:
    """The public route must retain the exact restricted moving reference."""

    payload = make_moving_nonprismatic_payload()
    parsed = parse_v4_lite_input(payload)
    mesh = build_v4_lite_mesh(parsed)
    result = HydraulicEngine().run(payload)
    final_index = -1
    reference_stages = tuple(
        value["water_level_m"] for value in payload["initial_state"]["values"]
    )
    final_stages = tuple(
        section.water_level[final_index] for section in result.sections
    )
    final_flows = tuple(section.flow[final_index] for section in result.sections)
    dx = mesh.cells[0].dx
    stage_l1 = sum(
        dx * abs(actual - expected)
        for actual, expected in zip(final_stages, reference_stages)
    ) / sum(dx * abs(value) for value in reference_stages)
    discharge_l1 = sum(
        dx * abs(value - _FLOW_M3_S) for value in final_flows
    ) / (_DOMAIN_LENGTH_M * _FLOW_M3_S)
    energy_linf = max(
        abs(
            stage
            + flow * flow
            / (
                2.0
                * _GRAVITY
                * cell.geometry.area(stage) ** 2
            )
            - _reference_energy_head()
        )
        for cell, stage, flow in zip(mesh.cells, final_stages, final_flows)
    )

    assert tuple(cell.dx for cell in mesh.cells) == pytest.approx((40.0,) * 25)
    assert stage_l1 <= 1.0e-4
    assert discharge_l1 <= 1.0e-4
    assert energy_linf <= 1.0e-4
    assert result.water_balance.relative_water_balance_error <= 1.0e-10
    assert result.diagnostics.retry_count == 0
    assert result.diagnostics.maximum_cfl <= 0.5 + 1.0e-12
    assert {
        NONPRISMATIC_MOVING_ENERGY_SCOPE,
        "boundary_closure_subcritical-characteristic-v1",
        "nonprismatic_hydraulic_function_linear_face_source_v1",
        "boundary_spatial_support_nearest-section-cell-face-v1",
        "moving_reference_preservation_quality_v1",
    }.issubset(result.diagnostics.diagnostic_flags)
    assert result.provenance.input_snapshot_hash == snapshot_hash(payload)
    assert result.provenance.input_snapshot_hash == (
        "96eb4e4d28bc05c865c3f5e8f24e3b0169b4d29f95bfe515e22e72237bf2bec1"
    )
    assert result.provenance.validation_policy_version == "v4-lite-3"
    assert result.provenance.solver_policy_hash == v4_lite_solver_policy_hash(parsed)
    assert result.provenance.mesh_hash == (
        "056f3bc492bf64a12ecb9c1be66d0f2935ff941214c8c0e8c318db90d433f4ea"
    )
    assert result.provenance.solver_policy_hash == (
        "c788c33c40f800fc469af1260a4a94150d16623a800c0083b56e15ad9c032618"
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("v2_provenance", "v4-lite-2 policy tuple is not implemented"),
        ("lake_policy", "v4-lite-3 policy tuple is not implemented"),
        ("uniform_initial", "requires by-section initial_state"),
        ("nonuniform_grid", "uniform cell-centre section grid"),
        ("sloping_bed", "requires one flat bed elevation"),
        ("roughness", "requires Manning n=0"),
        ("nonconstant_q", "requires constant initial discharge"),
        ("zero_q", "requires positive downstream discharge"),
        ("shallow", "frozen wet margin"),
        ("supercritical", "Froude number <= 0.8"),
        ("energy", "constant total energy head"),
        ("identical_profiles", "distinct hydraulic Profile signatures"),
        ("dynamic_upstream", "constant upstream discharge boundary"),
        ("wrong_upstream", "upstream boundary must match initial discharge"),
        ("dynamic_downstream", "constant downstream stage boundary"),
        ("wrong_downstream", "downstream stage must match"),
        ("with_structure", "does not support structures"),
    ],
)
def test_v4_lite_3_moving_reference_fails_closed(
    mutation: str,
    message: str,
) -> None:
    """Every broader moving, inferred, frictional, or structured state is rejected."""

    payload = make_moving_nonprismatic_payload()
    values = payload["initial_state"]["values"]
    if mutation == "v2_provenance":
        payload["provenance"]["validation_policy_version"] = "v4-lite-2"
    elif mutation == "lake_policy":
        payload["solver"]["geometry_policy"] = (
            "nonprismatic-section-linear-path-v1"
        )
    elif mutation == "uniform_initial":
        payload["initial_state"] = {
            "type": "uniform",
            "water_level_m": values[0]["water_level_m"],
            "discharge_m3_s": _FLOW_M3_S,
        }
    elif mutation == "nonuniform_grid":
        payload["sections"][5]["chainage_m"] += 0.1
    elif mutation == "sloping_bed":
        for point in payload["sections"][5]["points"]:
            point["elevation_m"] += 0.01
        values[5]["water_level_m"] += 0.01
    elif mutation == "roughness":
        payload["sections"][5]["default_manning_n"] = 0.01
    elif mutation == "nonconstant_q":
        values[5]["discharge_m3_s"] += 0.01
    elif mutation == "zero_q":
        for value in values:
            value["discharge_m3_s"] = 0.0
        payload["boundary"]["upstream"]["flow_m3_s"] = [0.0, 0.0]
    elif mutation == "shallow":
        for section, value in zip(payload["sections"], values):
            value["water_level_m"] = min(
                point["elevation_m"] for point in section["points"]
            ) + 0.05
        payload["boundary"]["downstream"]["water_level_m"] = [
            values[-1]["water_level_m"],
            values[-1]["water_level_m"],
        ]
    elif mutation == "supercritical":
        for value in values:
            value["discharge_m3_s"] = 100.0
        payload["boundary"]["upstream"]["flow_m3_s"] = [100.0, 100.0]
    elif mutation == "energy":
        values[5]["water_level_m"] += 0.001
    elif mutation == "identical_profiles":
        reference = copy.deepcopy(payload["sections"][0]["points"])
        stage = values[0]["water_level_m"]
        for section, value in zip(payload["sections"], values):
            section["points"] = copy.deepcopy(reference)
            value["water_level_m"] = stage
        payload["boundary"]["downstream"]["water_level_m"] = [stage, stage]
    elif mutation == "dynamic_upstream":
        payload["boundary"]["upstream"]["flow_m3_s"][-1] += 0.1
    elif mutation == "wrong_upstream":
        payload["boundary"]["upstream"]["flow_m3_s"] = [4.9, 4.9]
    elif mutation == "dynamic_downstream":
        payload["boundary"]["downstream"]["water_level_m"][-1] += 0.001
    elif mutation == "wrong_downstream":
        payload["boundary"]["downstream"]["water_level_m"] = [2.1, 2.1]
    elif mutation == "with_structure":
        payload["structures"]["gates"] = [
            {
                "identity": {"namespace": "public.gate", "id": 51},
                "branch_id": payload["river"]["branch_id"],
                "interface": {
                    "upstream_section_id": 1,
                    "downstream_section_id": 2,
                },
                "opening_m": 0.5,
                "width_m": 1.0,
                "height_m": 1.0,
                "discharge_coefficient": 0.62,
                "allow_reverse_flow": False,
            }
        ]

    with pytest.raises(HydraulicInputError, match=message):
        parse_v4_lite_input(payload)


def test_v4_lite_3_energy_gate_is_not_scaled_by_vertical_datum() -> None:
    """A valid large datum runs but cannot hide a physical 4e-5 m defect."""

    payload = make_moving_nonprismatic_payload(datum=1_000_000.0)
    parsed = parse_v4_lite_input(payload)
    result = HydraulicEngine().run(payload)
    assert result.provenance.solver_policy_hash == v4_lite_solver_policy_hash(parsed)
    assert result.diagnostics.retry_count == 0
    assert result.water_balance.relative_water_balance_error <= 1.0e-10

    defective = copy.deepcopy(payload)
    defective["initial_state"]["values"][5]["water_level_m"] += 4.0e-5

    with pytest.raises(HydraulicInputError, match="constant total energy head"):
        parse_v4_lite_input(defective)


def test_v4_lite_3_rejects_an_observation_window_too_short_for_evidence() -> None:
    """The reference policy cannot pass before a frozen wave-transit fraction."""

    payload = make_moving_nonprismatic_payload()
    payload["solver"]["duration_seconds"] = 1.0
    payload["solver"]["output_interval_seconds"] = 1.0
    payload["boundary"]["upstream"]["time_seconds"] = [0.0, 1.0]
    payload["boundary"]["downstream"]["time_seconds"] = [0.0, 1.0]

    with pytest.raises(HydraulicInputError, match="observation fraction"):
        parse_v4_lite_input(payload)


@pytest.mark.parametrize("shape", ["smooth_extreme", "alternating_extreme"])
def test_v4_lite_3_runtime_quality_gate_rejects_extreme_profiles(
    shape: str,
) -> None:
    """Water balance and CFL cannot disguise an inaccurate reference evolution."""

    payload = make_moving_nonprismatic_payload()
    if shape == "smooth_extreme":
        widths = tuple(
            0.2
            + 499.8
            * math.sin(
                math.pi * section["chainage_m"] / _DOMAIN_LENGTH_M
            )
            ** 2
            for section in payload["sections"]
        )
    else:
        widths = tuple(
            0.2 if index % 2 == 0 else 500.0
            for index in range(len(payload["sections"]))
        )
    for section, value, width in zip(
        payload["sections"],
        payload["initial_state"]["values"],
        widths,
    ):
        section["points"] = [
            {"offset_m": offset, "elevation_m": elevation}
            for offset, elevation in _profile_points(width)
        ]
        value["water_level_m"] = _subcritical_stage(width)
    final_stage = payload["initial_state"]["values"][-1]["water_level_m"]
    payload["boundary"]["downstream"]["water_level_m"] = [
        final_stage,
        final_stage,
    ]

    parse_v4_lite_input(payload)
    with pytest.raises(NumericalStateError, match="moving reference .* quality gate"):
        HydraulicEngine().run(payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("initial", "constant initial discharge"),
        ("dynamic_boundary", "constant upstream discharge boundary"),
        ("boundary_match", "upstream boundary must match initial discharge"),
    ],
)
def test_v4_lite_3_large_q_gate_has_no_relative_slack(
    mutation: str,
    message: str,
) -> None:
    """Scaled geometry/Q cannot hide a 0.2 m3/s C1 reference defect."""

    payload = make_moving_nonprismatic_payload()
    scale = 1.0e9
    for section in payload["sections"]:
        for point in section["points"]:
            point["offset_m"] *= scale
    for value in payload["initial_state"]["values"]:
        value["discharge_m3_s"] *= scale
    upstream = payload["boundary"]["upstream"]["flow_m3_s"]
    payload["boundary"]["upstream"]["flow_m3_s"] = [
        value * scale for value in upstream
    ]
    if mutation == "initial":
        payload["initial_state"]["values"][5]["discharge_m3_s"] += 0.2
    elif mutation == "dynamic_boundary":
        payload["boundary"]["upstream"]["flow_m3_s"][-1] += 0.2
    elif mutation == "boundary_match":
        payload["boundary"]["upstream"]["flow_m3_s"] = [
            value + 0.2
            for value in payload["boundary"]["upstream"]["flow_m3_s"]
        ]

    with pytest.raises(HydraulicInputError, match=message):
        parse_v4_lite_input(payload)
