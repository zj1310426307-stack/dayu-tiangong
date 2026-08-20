"""Strong output-contract tests for ``dayu.hydraulic-result.mvp``."""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from model.core.types import EngineResult
from model.result import MvpHydraulicResult


def make_mvp_result_payload() -> dict:
    """Return one finite, aligned, and exactly balanced MVP result."""

    sections = [
        {
            "section_id": index,
            "section_code": f"CS{index:03d}",
            "time": [0, 60],
            "water_level": [10, 10.1],
            "flow": [5, 5.5],
            "velocity": [0.5, 0.55],
        }
        for index in (1, 2, 3)
    ]
    return {
        "schema_version": "dayu.hydraulic-result.mvp",
        "sections": sections,
        "gates": [
            {
                "gate_id": 51,
                "time": [0, 60],
                "opening": [1, 1],
                "flow": [2, 2.1],
            }
        ],
        "pumps": [
            {
                "pump_id": 61,
                "time": [0, 60],
                "status": ["on", "on"],
                "flow": [1.5, 1.5],
            }
        ],
        "water_balance": {
            "initial_storage": 100,
            "final_storage": 110,
            "upstream_boundary_volume": 20,
            "downstream_boundary_volume": 5,
            "pump_outflow_volume": 5,
            "water_balance_residual": 0,
            "relative_water_balance_error": 0,
            "tolerance": 0.01,
            "status": "pass",
        },
        "diagnostics": {
            "maximum_cfl": 0.7,
            "minimum_dt": 0.25,
            "retry_count": 0,
            "step_count": 240,
            "diagnostic_flags": [],
        },
        "provenance": {
            "input_schema_version": "dayu.model-input.v4-lite",
            "input_snapshot_hash": "a" * 64,
            "mesh_hash": "b" * 64,
            "solver_type": "saint-venant",
            "scheme": "finite-volume-hll",
            "time_integrator": "ssp-rk2",
            "engine_version": "dayu-hydraulic-mvp",
            "engine_commit": "test-commit",
            "validation_policy_version": "v4-lite-1",
        },
    }


def test_mvp_result_is_independent_and_serializes_only_its_own_contract() -> None:
    """The MVP result never inherits EngineResult's v1/v2 branchy serializer."""

    result = MvpHydraulicResult.model_validate(make_mvp_result_payload())
    payload = result.to_dict()

    assert not isinstance(result, EngineResult)
    assert payload["schema_version"] == "dayu.hydraulic-result.mvp"
    assert set(payload) == {
        "schema_version",
        "sections",
        "gates",
        "pumps",
        "water_balance",
        "diagnostics",
        "provenance",
    }
    assert "node_series" not in payload
    assert "solver_policy_hash" not in result.model_dump()["provenance"]
    assert payload["sections"][0]["time"] == [0.0, 60.0]


def test_v1_result_rejects_an_explicit_null_v2_policy_hash() -> None:
    """A v2-only field cannot enter the frozen v1 wire shape as explicit null."""

    payload = make_mvp_result_payload()
    payload["provenance"]["solver_policy_hash"] = None

    with pytest.raises(ValidationError, match="must not add solver_policy_hash"):
        MvpHydraulicResult.model_validate(payload)


@pytest.mark.parametrize(
    "case",
    [
        "misaligned_values",
        "unordered_time",
        "different_section_axis",
        "nonfinite",
        "numeric_string",
        "duplicate_section",
        "extra_key",
        "bad_solver_identity",
        "bad_pump_status",
    ],
)
def test_result_series_and_identity_fail_closed(case: str) -> None:
    """Invalid result bytes cannot masquerade as a durable MVP result."""

    payload = copy.deepcopy(make_mvp_result_payload())
    if case == "misaligned_values":
        payload["sections"][0]["flow"].pop()
    elif case == "unordered_time":
        payload["gates"][0]["time"] = [60, 0]
    elif case == "different_section_axis":
        payload["sections"][1]["time"] = [0, 30]
    elif case == "nonfinite":
        payload["sections"][0]["velocity"][1] = float("inf")
    elif case == "numeric_string":
        payload["diagnostics"]["maximum_cfl"] = "0.7"
    elif case == "duplicate_section":
        payload["sections"][1]["section_id"] = 1
    elif case == "extra_key":
        payload["water_balance"]["gate_volume"] = 1
    elif case == "bad_solver_identity":
        payload["provenance"]["scheme"] = "rusanov"
    elif case == "bad_pump_status":
        payload["pumps"][0]["status"][1] = "enabled"

    with pytest.raises(ValidationError):
        MvpHydraulicResult.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("water_balance_residual", 1),
        ("relative_water_balance_error", 0.001),
        ("status", "fail"),
    ],
)
def test_water_balance_evidence_is_self_consistent(field: str, value: object) -> None:
    """Residual, normalization, and status cannot contradict stored volumes."""

    payload = make_mvp_result_payload()
    payload["water_balance"][field] = value

    with pytest.raises(ValidationError):
        MvpHydraulicResult.model_validate(payload)


def test_gate_and_pump_arrays_are_individually_aligned() -> None:
    """Structure process arrays carry one state and flow sample per own time value."""

    payload = make_mvp_result_payload()
    payload["pumps"][0]["time"] = [0, 30, 60]
    payload["pumps"][0]["flow"] = [1.5, 1.5, 1.5]

    with pytest.raises(ValidationError, match="Pump result arrays must align"):
        MvpHydraulicResult.model_validate(payload)


@pytest.mark.parametrize("structure_key", ["gates", "pumps"])
def test_structure_time_axis_must_match_sections(structure_key: str) -> None:
    """Gate and Pump series use the same public output times as all sections."""

    payload = make_mvp_result_payload()
    payload[structure_key][0]["time"] = [0, 30]

    with pytest.raises(ValidationError, match="common section output time axis"):
        MvpHydraulicResult.model_validate(payload)


def test_result_contract_is_frozen_and_rejects_a_second_structure() -> None:
    """The MVP remains immutable and limited to one Gate and one Pump."""

    result = MvpHydraulicResult.model_validate(make_mvp_result_payload())
    with pytest.raises(Exception):
        result.schema_version = "changed"

    payload = make_mvp_result_payload()
    payload["gates"].append(copy.deepcopy(payload["gates"][0]))
    with pytest.raises(ValidationError):
        MvpHydraulicResult.model_validate(payload)


def test_typed_control_events_match_the_accepted_device_series() -> None:
    """One-shot evidence is separate from, and consistent with, actual commands."""

    payload = make_mvp_result_payload()
    payload["gates"][0]["opening"] = [0, 1]
    payload["gates"][0]["flow"] = [0, 2.1]
    payload["pumps"][0]["status"] = ["off", "on"]
    payload["pumps"][0]["flow"] = [0, 1.5]
    payload["control_events"] = [
        {
            "time": 30,
            "structure_id": 51,
            "structure_type": "gate",
            "action": "open",
            "threshold_water_level": 10.2,
            "observed_water_level": 10.3,
        },
        {
            "time": 30,
            "structure_id": 61,
            "structure_type": "pump",
            "action": "start",
            "threshold_water_level": 10.2,
            "observed_water_level": 10.3,
        },
    ]

    result = MvpHydraulicResult.model_validate(payload)

    assert tuple(event.action for event in result.control_events) == ("open", "start")
    assert len(result.to_dict()["control_events"]) == 2


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("observed_water_level", 10.2, "must exceed"),
        ("action", "start", "does not match"),
        ("structure_id", 999, "unknown result structure"),
        ("time", 61, "outside the result interval"),
    ],
)
def test_control_event_evidence_fails_closed(
    field: str,
    value: object,
    message: str,
) -> None:
    """Impossible timing, identity, crossing, and action evidence is rejected."""

    payload = make_mvp_result_payload()
    payload["gates"][0]["opening"] = [0, 1]
    payload["gates"][0]["flow"] = [0, 2.1]
    payload["control_events"] = [
        {
            "time": 30,
            "structure_id": 51,
            "structure_type": "gate",
            "action": "open",
            "threshold_water_level": 10.2,
            "observed_water_level": 10.3,
        }
    ]
    payload["control_events"][0][field] = value

    with pytest.raises(ValidationError, match=message):
        MvpHydraulicResult.model_validate(payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("gate_change_without_event", "opening changes without a control event"),
        ("pump_change_without_event", "status changes without a control event"),
        ("closed_gate_nonzero_flow", "flow must be zero while opening is zero"),
        ("on_pump_zero_flow", "flow must be positive while status is on"),
        ("on_pump_variable_flow", "design flow must remain constant"),
    ],
)
def test_structure_command_series_cannot_forge_missing_event_evidence(
    mutation: str,
    message: str,
) -> None:
    """Command changes require an event and impossible state/flow pairs fail."""

    payload = make_mvp_result_payload()
    if mutation == "gate_change_without_event":
        payload["gates"][0]["opening"] = [0, 1]
        payload["gates"][0]["flow"][0] = 0
    elif mutation == "pump_change_without_event":
        payload["pumps"][0]["status"] = ["off", "on"]
        payload["pumps"][0]["flow"] = [0, 1.5]
    elif mutation == "closed_gate_nonzero_flow":
        payload["gates"][0]["opening"] = [0, 0]
    elif mutation == "on_pump_zero_flow":
        payload["pumps"][0]["flow"] = [0, 0]
    elif mutation == "on_pump_variable_flow":
        payload["pumps"][0]["flow"] = [1.5, 1.6]

    with pytest.raises(ValidationError, match=message):
        MvpHydraulicResult.model_validate(payload)


def test_one_shot_gate_target_cannot_change_after_its_event() -> None:
    """The accepted one-shot command is a latch, not a hidden opening schedule."""

    payload = make_mvp_result_payload()
    payload["gates"][0]["opening"] = [1, 2]
    payload["control_events"] = [
        {
            "time": 0,
            "structure_id": 51,
            "structure_type": "gate",
            "action": "open",
            "threshold_water_level": 10.2,
            "observed_water_level": 10.3,
        }
    ]

    with pytest.raises(ValidationError, match="target opening changes"):
        MvpHydraulicResult.model_validate(payload)


def _make_v4_bracketed_result_payload() -> dict:
    """Upgrade the compact result fixture to one valid v4-lite-4 event."""

    payload = make_mvp_result_payload()
    payload["provenance"].update(
        {
            "validation_policy_version": "v4-lite-4",
            "solver_policy_hash": "c" * 64,
        }
    )
    payload["gates"][0]["opening"] = [0, 1]
    payload["gates"][0]["flow"] = [0, 2.1]
    payload["control_events"] = [
        {
            "time": 30,
            "structure_id": 51,
            "structure_type": "gate",
            "action": "open",
            "threshold_water_level": 10.2,
            "observed_water_level": 10.2001,
            "previous_time": 29.995,
            "previous_observed_water_level": 10.1999,
            "bracket_end_time": 30,
            "event_time_tolerance": 0.01,
            "locator_policy": "bracketed-conservative-replay-right-end-v1",
            "refinement_count": 8,
            "monitored_section_id": 1,
            "spatial_support": "bound-section-cell-center-v1",
        }
    ]
    return payload


def test_v4_bracketed_result_preserves_complete_crossing_evidence() -> None:
    """The durable DTO carries one bounded bracket without requiring an output knot."""

    payload = _make_v4_bracketed_result_payload()
    result = MvpHydraulicResult.model_validate(payload)
    event = result.to_dict()["control_events"][0]

    assert event["time"] == 30.0
    assert event["previous_time"] == 29.995
    assert event["bracket_end_time"] == event["time"]
    assert event["monitored_section_id"] == 1


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_field", "must be complete"),
        ("wide_bracket", "exceeds event_time_tolerance"),
        ("wrong_end", "must equal bracket_end_time"),
        ("pre_above", "must start at or below threshold"),
        ("unknown_section", "unknown monitored section"),
        ("pre_v4_evidence", "pre-v4 control events must not add bracket evidence"),
    ],
)
def test_v4_bracketed_result_spoofing_fails_closed(
    mutation: str,
    message: str,
) -> None:
    """Partial, impossible, mis-versioned or unbound brackets are rejected."""

    payload = _make_v4_bracketed_result_payload()
    event = payload["control_events"][0]
    if mutation == "missing_field":
        event.pop("previous_time")
    elif mutation == "wide_bracket":
        event["previous_time"] = 29
    elif mutation == "wrong_end":
        event["bracket_end_time"] = 29.999
    elif mutation == "pre_above":
        event["previous_observed_water_level"] = 10.21
    elif mutation == "unknown_section":
        event["monitored_section_id"] = 999
    elif mutation == "pre_v4_evidence":
        payload["provenance"].pop("solver_policy_hash")
        payload["provenance"]["validation_policy_version"] = "v4-lite-1"

    with pytest.raises(ValidationError, match=message):
        MvpHydraulicResult.model_validate(payload)
