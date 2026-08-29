"""Shared builders for native-v4 platform contract tests."""

from __future__ import annotations

import copy
import runpy
from pathlib import Path

from model.build_identity import current_runtime_build_identity
from model.provenance import CANONICALIZATION_ID, snapshot_hash
from model.solver.registry import (
    D1_CAPABILITY,
    D1_CAPABILITY_ID,
    D1_KNOWN_LIMITATIONS,
    D1_RUNTIME_ADAPTER_ID,
    D1_SOLVER_ID,
    D3A_1_CAPABILITY,
    D3A_1_CAPABILITY_ID,
    D3A_1_KNOWN_LIMITATIONS,
    D3A_1_RUNTIME_ADAPTER_ID,
    D3A_2_CAPABILITY,
    D3A_2_CAPABILITY_ID,
    D3A_2_KNOWN_LIMITATIONS,
    D3A_2_RUNTIME_ADAPTER_ID,
    registry_hash,
)


TEST_BUILD_IDENTITY = current_runtime_build_identity()


def d1_runtime_payload() -> dict:
    """Load the checked-in six-hour D1 example without importing a hyphenated package."""

    path = (
        Path(__file__).parents[2]
        / "examples"
        / "hydraulic"
        / "gate-pump-strong-coupling"
        / "case.py"
    )
    build_case = runpy.run_path(str(path))["build_case"]
    return build_case()


def native_v4_payload() -> dict:
    """Wrap the D1 runtime fixture in the authoritative platform-v4 contract."""

    runtime = d1_runtime_payload()
    sections = runtime["sections"]
    return {
        "schema_version": "dayu.model-input.v4",
        "solver_selection": {
            "solver_id": D1_SOLVER_ID,
            "capability_id": D1_CAPABILITY_ID,
            "runtime_adapter_id": D1_RUNTIME_ADAPTER_ID,
        },
        "dataset_version": runtime["dataset_version"],
        "simulation_case": {"id": 71, "name": "D1 platform integration"},
        "coordinate_reference": runtime["coordinate_reference"],
        "network": {"id": runtime["river"]["network_id"], "code": "NW-D1"},
        "branches": [runtime["river"]],
        "reaches": [
            {
                "id": 81,
                "branch_id": runtime["river"]["branch_id"],
                "reach_code": "R-D1",
                "start_chainage_m": runtime["river"]["start_chainage_m"],
                "end_chainage_m": runtime["river"]["end_chainage_m"],
            }
        ],
        "cross_sections": sections,
        "cross_section_profiles": [
            {
                "id": item["profile_id"],
                "cross_section_id": item["section_id"],
                "profile_hash": item["profile_hash"],
            }
            for item in sections
        ],
        "initial_state": runtime["initial_state"],
        "boundaries": runtime["boundary"],
        "structures": runtime["structures"],
        "control_plan": {
            "id": 91,
            "frozen_snapshot_hash": snapshot_hash(
                {"schema_version": "dayu.dispatch-plan.v1", "id": 91}
            ),
            "policy_id": "d1-gate-pump-control-v1",
        },
        "numerical_policy": runtime["solver"],
        "validation": {
            "validation_policy_version": "v4-lite-7",
            "capability_id": D1_CAPABILITY_ID,
            "water_balance_tolerance": runtime["solver"]["water_balance_tolerance"],
        },
        "provenance": {
            **TEST_BUILD_IDENTITY.provenance(),
            "canonicalization_id": CANONICALIZATION_ID,
            "registry_hash": registry_hash(),
        },
        "capability_scope": list(D1_CAPABILITY.scope),
        "capability_exclusions": list(D1_CAPABILITY.exclusions),
        "case_notes": ["fixture-owned operational note"],
        "known_limitations": list(D1_KNOWN_LIMITATIONS),
    }


def native_v4_d3a_1_payload() -> dict:
    """Select D3A-1 explicitly and change only effective section roughness."""

    payload = copy.deepcopy(native_v4_payload())
    payload["solver_selection"] = {
        "solver_id": D1_SOLVER_ID,
        "capability_id": D3A_1_CAPABILITY_ID,
        "runtime_adapter_id": D3A_1_RUNTIME_ADAPTER_ID,
    }
    for section in payload["cross_sections"]:
        section["default_manning_n"] = 0.025
    payload["control_plan"]["policy_id"] = "d3a-1-gate-pump-control-v1"
    payload["validation"] = {
        "validation_policy_version": "d3a-1-v1",
        "capability_id": D3A_1_CAPABILITY_ID,
        "water_balance_tolerance": payload["numerical_policy"][
            "water_balance_tolerance"
        ],
    }
    payload["capability_scope"] = list(D3A_1_CAPABILITY.scope)
    payload["capability_exclusions"] = list(D3A_1_CAPABILITY.exclusions)
    payload["known_limitations"] = list(D3A_1_KNOWN_LIMITATIONS)
    return payload


def native_v4_d3a_2_payload() -> dict:
    """Select D3A-2 and add only explicit linear-bed authority and translation."""

    payload = copy.deepcopy(native_v4_d3a_1_payload())
    payload["solver_selection"] = {
        "solver_id": D1_SOLVER_ID,
        "capability_id": D3A_2_CAPABILITY_ID,
        "runtime_adapter_id": D3A_2_RUNTIME_ADAPTER_ID,
    }
    for section in payload["cross_sections"]:
        bed = 9.0 - 1.0e-7 * section["chainage_m"]
        vertical_shift = bed - 9.0
        for point in section["points"]:
            point["elevation_m"] += vertical_shift
        section["profile_hash"] = f"{200 + section['section_id']:064x}"
        section["bed_elevation_m"] = bed
        section["bed_elevation_source"] = "synthetic"
        section["bed_elevation_confirmed_by"] = "HYDRO-MODEL-02-D3A-2"
        section["bed_elevation_confirmed_at"] = "2026-08-29T00:00:00Z"
    payload["cross_section_profiles"] = [
        {
            "id": item["profile_id"],
            "cross_section_id": item["section_id"],
            "profile_hash": item["profile_hash"],
        }
        for item in payload["cross_sections"]
    ]
    payload["numerical_policy"]["geometry_policy"] = (
        "relative-prismatic-linear-bed-v1"
    )
    payload["numerical_policy"]["bed_elevation_source"] = (
        "explicit-section-bed-elevation-v1"
    )
    payload["boundaries"]["downstream"]["water_level_m"] = [9.8, 9.8, 9.8]
    for value in payload["initial_state"]["values"]:
        if value["section_id"] >= 9:
            value["water_level_m"] = 9.8
    pump_control = payload["structures"]["pumps"][0]["control"]
    pump_control["start_level_m"] = 9.782
    pump_control["stop_level_m"] = 9.778
    pump_control["minimum_stop_seconds"] = 4000.0
    payload["control_plan"]["policy_id"] = "d3a-2-gate-pump-control-v1"
    payload["validation"] = {
        "validation_policy_version": "d3a-2-v1",
        "capability_id": D3A_2_CAPABILITY_ID,
        "water_balance_tolerance": payload["numerical_policy"][
            "water_balance_tolerance"
        ],
    }
    payload["capability_scope"] = list(D3A_2_CAPABILITY.scope)
    payload["capability_exclusions"] = list(D3A_2_CAPABILITY.exclusions)
    payload["known_limitations"] = list(D3A_2_KNOWN_LIMITATIONS)
    return payload
