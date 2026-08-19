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
    assert payload["sections"][0]["time"] == [0.0, 60.0]


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
