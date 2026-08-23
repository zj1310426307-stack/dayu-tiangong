"""Contract gates for the direct-engine-only v4-lite input."""

from __future__ import annotations

import copy

import pytest

from model.api import V4_LITE_SOLVER_TUPLE, V4LiteInput, parse_v4_lite_input
from model.core.errors import HydraulicInputError


def make_v4_lite_payload() -> dict:
    """Return one complete single-Branch JSON fixture with explicit identities."""

    sections = []
    for index, chainage in enumerate((0, 500, 1000), start=1):
        sections.append(
            {
                "section_id": index,
                "section_code": f"CS{index:03d}",
                "branch_id": 21,
                "chainage_m": chainage,
                "profile_id": 100 + index,
                "profile_hash": f"{index:064x}",
                "default_manning_n": 0.035,
                "points": [
                    {"offset_m": 0, "elevation_m": 12},
                    {"offset_m": 10, "elevation_m": 9},
                    {"offset_m": 20, "elevation_m": 12},
                ],
            }
        )
    return {
        "schema_version": "dayu.model-input.v4-lite",
        "dataset_version": {"id": 1, "content_hash": "a" * 64},
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
            "duration_seconds": 3600,
            "maximum_time_step_seconds": 10,
            "minimum_time_step_seconds": 0.001,
            "output_interval_seconds": 60,
            "cfl_number": 0.7,
            "dry_depth_m": 0.001,
            "maximum_retries": 8,
            "maximum_steps": 100000,
            "water_balance_tolerance": 0.01,
        },
        "river": {
            "network_id": 11,
            "branch_id": 21,
            "branch_code": "B-001",
            "upstream_node_id": 31,
            "downstream_node_id": 32,
            "start_chainage_m": 0,
            "end_chainage_m": 1000,
            "direction_status": "confirmed",
        },
        "sections": sections,
        "initial_state": {
            "type": "uniform",
            "water_level_m": 10,
            "discharge_m3_s": 5,
        },
        "boundary": {
            "upstream": {
                "identity": {"namespace": "public.boundary_condition", "id": 41},
                "type": "discharge-series",
                "target_node_id": 31,
                "time_seconds": [0, 1800, 3600],
                "flow_m3_s": [5, 10, 5],
                "interpolation": "linear",
                "extrapolation": "error",
            },
            "downstream": {
                "identity": {"namespace": "public.boundary_condition", "id": 42},
                "type": "stage-series",
                "target_node_id": 32,
                "time_seconds": [0, 3600],
                "water_level_m": [10, 10.5],
                "interpolation": "linear",
                "extrapolation": "error",
            },
        },
        "structures": {
            "gates": [
                {
                    "identity": {"namespace": "public.gate", "id": 51},
                    "branch_id": 21,
                    "interface": {
                        "upstream_section_id": 1,
                        "downstream_section_id": 2,
                    },
                    "opening_m": 1,
                    "width_m": 4,
                    "height_m": 2,
                    "discharge_coefficient": 0.62,
                    "allow_reverse_flow": False,
                }
            ],
            "pumps": [
                {
                    "identity": {"namespace": "public.pump", "id": 61},
                    "branch_id": 21,
                    "section_id": 3,
                    "outlet": "external",
                    "status": "on",
                    "design_flow_m3_s": 1.5,
                }
            ],
        },
        "provenance": {
            "engine_version": "dayu-hydraulic-mvp",
            "engine_commit": "test-commit",
            "validation_policy_version": "v4-lite-1",
        },
    }


def make_v4_lite_bracketed_payload() -> dict:
    """Return one short v4-lite-4 case with co-located Gate/Pump monitors."""

    payload = make_v4_lite_payload()
    payload["solver"].update(
        {
            "duration_seconds": 1.0,
            "maximum_time_step_seconds": 0.25,
            "minimum_time_step_seconds": 1.0e-5,
            "output_interval_seconds": 0.5,
            "geometry_policy": "absolute-prismatic-v1",
            "geometry_source": "hydrostatic-reconstruction-v1",
            "bed_elevation_source": "profile-minimum-elevation-v1",
            "equilibrium_policy": "standard-v1",
            "boundary_closure": "subcritical-characteristic-v1",
            "boundary_spatial_support": "nearest-section-cell-face-v1",
            "structure_event_policy": (
                "bracketed-conservative-replay-right-end-v1"
            ),
            "event_time_tolerance_seconds": 0.01,
            "maximum_event_refinements": 30,
            "control_spatial_support": "bound-section-cell-center-v1",
        }
    )
    payload["boundary"]["upstream"].update(
        {"time_seconds": [0, 1], "flow_m3_s": [5, 5]}
    )
    payload["boundary"]["downstream"].update(
        {"time_seconds": [0, 1], "water_level_m": [10, 10]}
    )
    control = {
        "type": "one-shot-stage-above-bracketed-v1",
        "threshold_water_level_m": 10.00001,
    }
    payload["structures"]["gates"][0]["control"] = copy.deepcopy(control)
    payload["structures"]["pumps"][0].update(
        {
            "section_id": 1,
            "status": "off",
            "control": copy.deepcopy(control),
        }
    )
    payload["provenance"]["validation_policy_version"] = "v4-lite-4"
    return payload


def test_valid_contract_is_frozen_and_uses_the_only_solver_tuple() -> None:
    """A JSON-shaped payload validates without legacy projection or coercion surprises."""

    parsed = parse_v4_lite_input(make_v4_lite_payload())

    assert isinstance(parsed, V4LiteInput)
    assert (
        parsed.schema_version,
        parsed.solver.type,
        parsed.solver.scheme,
        parsed.solver.time_integrator,
    ) == V4_LITE_SOLVER_TUPLE
    assert isinstance(parsed.sections, tuple)
    assert parsed.sections[0].chainage_m == 0.0
    assert parsed.structures.gates[0].identity.id == 51
    with pytest.raises(Exception):
        parsed.river.branch_id = 99


def test_by_section_initial_state_must_cover_exact_section_identities() -> None:
    """Explicit by-section initialization cannot omit or invent a section identity."""

    payload = make_v4_lite_payload()
    payload["initial_state"] = {
        "type": "by-section",
        "values": [
            {"section_id": index, "water_level_m": 10, "discharge_m3_s": 5}
            for index in (1, 2, 3)
        ],
    }
    assert parse_v4_lite_input(payload).initial_state.type == "by-section"

    payload["initial_state"]["values"][-1]["section_id"] = 999
    with pytest.raises(HydraulicInputError, match=r"unknown=\[999\]"):
        parse_v4_lite_input(payload)


@pytest.mark.parametrize(
    "case",
    [
        "unknown_schema",
        "unknown_solver",
        "extra_key",
        "legacy_gate_mirror",
        "numeric_string",
        "nonfinite",
        "wrong_branch",
        "non_prismatic_profile",
        "disconnected_wet_regions",
        "unordered_sections",
        "incomplete_boundary",
        "boundary_extrapolation",
        "wrong_boundary_node",
        "duplicate_boundary_identity",
        "unknown_gate_namespace",
        "nonadjacent_gate",
        "unknown_pump_section",
        "second_gate",
    ],
)
def test_untrusted_or_ambiguous_input_fails_closed(case: str) -> None:
    """Unsupported semantics never fall through to a legacy or guessed interpretation."""

    payload = copy.deepcopy(make_v4_lite_payload())
    if case == "unknown_schema":
        payload["schema_version"] = "dayu.model-input.v5"
    elif case == "unknown_solver":
        payload["solver"]["scheme"] = "continuity-manning"
    elif case == "extra_key":
        payload["river"]["legacy_river_id"] = 7
    elif case == "legacy_gate_mirror":
        payload["gates"] = payload["structures"]["gates"]
    elif case == "numeric_string":
        payload["solver"]["cfl_number"] = "0.7"
    elif case == "nonfinite":
        payload["sections"][0]["points"][1]["elevation_m"] = float("nan")
    elif case == "wrong_branch":
        payload["sections"][1]["branch_id"] = 999
    elif case == "non_prismatic_profile":
        payload["sections"][1]["points"][1]["elevation_m"] = 8.5
    elif case == "disconnected_wet_regions":
        for section in payload["sections"]:
            section["points"] = [
                {"offset_m": 0, "elevation_m": 12},
                {"offset_m": 5, "elevation_m": 9},
                {"offset_m": 10, "elevation_m": 11},
                {"offset_m": 15, "elevation_m": 9},
                {"offset_m": 20, "elevation_m": 12},
            ]
    elif case == "unordered_sections":
        payload["sections"][1]["chainage_m"] = 0
    elif case == "incomplete_boundary":
        payload["boundary"]["upstream"]["time_seconds"][-1] = 3599
    elif case == "boundary_extrapolation":
        payload["boundary"]["downstream"]["extrapolation"] = "hold"
    elif case == "wrong_boundary_node":
        payload["boundary"]["upstream"]["target_node_id"] = 999
    elif case == "duplicate_boundary_identity":
        payload["boundary"]["downstream"]["identity"]["id"] = 41
    elif case == "unknown_gate_namespace":
        payload["structures"]["gates"][0]["identity"]["namespace"] = "hydraulic.gate"
    elif case == "nonadjacent_gate":
        payload["structures"]["gates"][0]["interface"]["downstream_section_id"] = 3
    elif case == "unknown_pump_section":
        payload["structures"]["pumps"][0]["section_id"] = 999
    elif case == "second_gate":
        payload["structures"]["gates"].append(
            copy.deepcopy(payload["structures"]["gates"][0])
        )

    with pytest.raises(HydraulicInputError):
        parse_v4_lite_input(payload)


def test_profile_range_and_dry_state_are_validated_before_meshing() -> None:
    """Profile extrapolation and non-zero dry discharge are rejected at the contract edge."""

    payload = make_v4_lite_payload()
    payload["initial_state"]["water_level_m"] = 13
    with pytest.raises(HydraulicInputError, match="outside its Profile range"):
        parse_v4_lite_input(payload)

    payload = make_v4_lite_payload()
    payload["initial_state"]["water_level_m"] = 9
    payload["initial_state"]["discharge_m3_s"] = 1
    with pytest.raises(HydraulicInputError, match="zero initial discharge"):
        parse_v4_lite_input(payload)


def test_input_parser_does_not_mutate_the_untrusted_mapping() -> None:
    """Validation is observational and leaves frozen-input hashing to the caller."""

    payload = make_v4_lite_payload()
    before = copy.deepcopy(payload)

    parse_v4_lite_input(payload)

    assert payload == before


def test_one_shot_structure_control_is_explicit_and_mutually_exclusive() -> None:
    """A discriminator selects fixed or one-shot control with no guessed fallback."""

    payload = make_v4_lite_payload()
    payload["structures"]["gates"][0]["control"] = {
        "type": "one-shot-stage-above",
        "threshold_water_level_m": 10.25,
    }
    payload["structures"]["pumps"][0]["status"] = "off"
    payload["structures"]["pumps"][0]["control"] = {
        "type": "one-shot-stage-above",
        "threshold_water_level_m": 10.5,
    }

    parsed = parse_v4_lite_input(payload)

    assert parsed.structures.gates[0].control.type == "one-shot-stage-above"
    assert parsed.structures.pumps[0].control.type == "one-shot-stage-above"

    payload["structures"]["gates"][0]["control"]["type"] = "threshold"
    with pytest.raises(HydraulicInputError):
        parse_v4_lite_input(payload)


def test_v4_lite_4_requires_one_complete_bracketed_event_policy() -> None:
    """The continuous locator is explicit and cannot reinterpret an older snapshot."""

    payload = make_v4_lite_bracketed_payload()
    parsed = parse_v4_lite_input(payload)

    assert parsed.provenance.validation_policy_version == "v4-lite-4"
    assert parsed.solver.structure_event_policy == (
        "bracketed-conservative-replay-right-end-v1"
    )
    assert parsed.structures.gates[0].control.type == (
        "one-shot-stage-above-bracketed-v1"
    )
    assert parsed.structures.pumps[0].control.type == (
        "one-shot-stage-above-bracketed-v1"
    )

    missing = make_v4_lite_bracketed_payload()
    missing["solver"].pop("event_time_tolerance_seconds")
    with pytest.raises(HydraulicInputError, match="event policy field"):
        parse_v4_lite_input(missing)

    legacy = make_v4_lite_bracketed_payload()
    legacy["provenance"]["validation_policy_version"] = "v4-lite-1"
    with pytest.raises(HydraulicInputError, match="explicit versioned policy"):
        parse_v4_lite_input(legacy)


@pytest.mark.parametrize(
    "mutation",
    ["discrete_control", "fixed_control", "initial_equality", "tolerance_below_dt"],
)
def test_v4_lite_4_event_semantics_fail_closed(mutation: str) -> None:
    """Ambiguous controller, initial and locator states never reach the solver."""

    payload = make_v4_lite_bracketed_payload()
    if mutation == "discrete_control":
        payload["structures"]["gates"][0]["control"]["type"] = (
            "one-shot-stage-above"
        )
    elif mutation == "fixed_control":
        payload["structures"]["pumps"][0]["control"] = {"type": "fixed"}
    elif mutation == "initial_equality":
        payload["structures"]["gates"][0]["control"][
            "threshold_water_level_m"
        ] = 10
    elif mutation == "tolerance_below_dt":
        payload["solver"]["event_time_tolerance_seconds"] = 1.0e-6

    with pytest.raises(HydraulicInputError):
        parse_v4_lite_input(payload)


@pytest.mark.parametrize(
    ("structure", "mutation", "message"),
    [
        (
            "gate",
            {"opening_m": 0.0, "threshold_water_level_m": 10.0},
            "target opening_m must be positive",
        ),
        (
            "gate",
            {"opening_m": 1.0, "threshold_water_level_m": 12.0},
            "control threshold must satisfy",
        ),
        (
            "pump",
            {"status": "on", "threshold_water_level_m": 10.0},
            "initial status 'off'",
        ),
        (
            "pump",
            {"status": "off", "threshold_water_level_m": 8.0},
            "control threshold must satisfy",
        ),
    ],
)
def test_one_shot_structure_control_fails_closed(
    structure: str,
    mutation: dict[str, object],
    message: str,
) -> None:
    """Contradictory commands and unreachable Profile thresholds are rejected."""

    payload = make_v4_lite_payload()
    key = "gates" if structure == "gate" else "pumps"
    item = payload["structures"][key][0]
    threshold = mutation["threshold_water_level_m"]
    item.update(
        {
            field: value
            for field, value in mutation.items()
            if field != "threshold_water_level_m"
        }
    )
    item["control"] = {
        "type": "one-shot-stage-above",
        "threshold_water_level_m": threshold,
    }

    with pytest.raises(HydraulicInputError, match=message):
        parse_v4_lite_input(payload)
