"""End-to-end v4-lite-5 contracts for the restricted C2b Gate closure."""

from __future__ import annotations

import copy

import pytest

from model import HydraulicEngine
from model.adapters import (
    build_v4_lite_mesh,
    v4_lite_mesh_hash,
    v4_lite_solver_policy_hash,
)
from model.api import parse_v4_lite_input
from model.core.errors import HydraulicInputError
from model.provenance import snapshot_hash
from model.result import MvpHydraulicResult
from tests.model02.test_v4_lite_contract import make_v4_lite_payload


def make_v4_lite_completed_gate_payload() -> dict:
    """Return the single fixed, submerged, flat/prismatic C2b reference case."""

    payload = make_v4_lite_payload()
    payload["solver"].update(
        {
            "duration_seconds": 2.0,
            "maximum_time_step_seconds": 0.1,
            "minimum_time_step_seconds": 1.0e-6,
            "output_interval_seconds": 1.0,
            "cfl_number": 0.5,
            "geometry_policy": "absolute-prismatic-v1",
            "geometry_source": "hydrostatic-reconstruction-v1",
            "bed_elevation_source": "profile-minimum-elevation-v1",
            "equilibrium_policy": "standard-v1",
            "boundary_closure": "subcritical-characteristic-v1",
            "boundary_spatial_support": "nearest-section-cell-face-v1",
            "gate_coupling_policy": "submerged-orifice-energy-momentum-v1",
            "gate_equation_tolerance_m": 1.0e-10,
            "gate_maximum_iterations": 80,
            "gate_spatial_support": "bound-internal-section-face-v1",
        }
    )
    for section in payload["sections"]:
        section["default_manning_n"] = 0.0
    payload["initial_state"] = {
        "type": "by-section",
        "values": [
            {"section_id": 1, "water_level_m": 11.0, "discharge_m3_s": 0.0},
            {"section_id": 2, "water_level_m": 11.0, "discharge_m3_s": 0.0},
            {"section_id": 3, "water_level_m": 10.5, "discharge_m3_s": 0.0},
        ],
    }
    payload["boundary"]["upstream"].update(
        {"time_seconds": [0.0, 2.0], "flow_m3_s": [0.0, 0.0]}
    )
    payload["boundary"]["downstream"].update(
        {"time_seconds": [0.0, 2.0], "water_level_m": [10.5, 10.5]}
    )
    payload["structures"]["gates"][0].update(
        {
            "interface": {
                "upstream_section_id": 2,
                "downstream_section_id": 3,
            },
            "opening_m": 0.5,
            "width_m": 2.0,
            "height_m": 1.0,
            "control": {"type": "fixed"},
            "sill_elevation_m": 9.0,
        }
    )
    payload["structures"]["pumps"] = []
    payload["provenance"]["validation_policy_version"] = "v4-lite-5"
    return payload


def test_v4_lite_5_completed_gate_result_is_self_auditing() -> None:
    """The public direct route persists every RK closure and exact transfer volume."""

    payload = make_v4_lite_completed_gate_payload()
    result = HydraulicEngine().run(payload)
    assert isinstance(result, MvpHydraulicResult)
    document = result.to_dict()

    assert document["provenance"]["input_snapshot_hash"] == snapshot_hash(payload)
    assert document["provenance"]["input_snapshot_hash"] == (
        "b3cdf80d199ea643fcc763254c8c4878a843b6fb725f475f21a298dca2b541af"
    )
    assert document["provenance"]["mesh_hash"] == (
        "5be802aaa262a02deb2419c45b1e4b30d88ed1f9f12f7eb43ad3a8e29b9c1e33"
    )
    assert document["provenance"]["solver_policy_hash"] == (
        "cb36f8c8989313a69261ab139471d8f05058a88383486033e29ebf5c71c55625"
    )
    assert document["provenance"]["validation_policy_version"] == "v4-lite-5"
    assert document["water_balance"]["status"] == "pass"
    assert document["water_balance"]["relative_water_balance_error"] < 1.0e-12
    assert len(document["gate_coupling_evidence"]) == 1
    coupling = document["gate_coupling_evidence"][0]
    assert coupling["coupling_policy"] == "submerged-orifice-energy-momentum-v1"
    assert coupling["total_transfer_volume"] > 0.0
    assert coupling["total_transfer_volume"] == pytest.approx(3.870714801327459)
    assert coupling["maximum_absolute_energy_residual"] <= 1.0e-10
    assert len(coupling["stage_evaluations"]) == 2 * document["diagnostics"]["step_count"]
    assert all(
        row["reaction_force_per_density"]
        == pytest.approx(row["momentum_flux_right"] - row["momentum_flux_left"])
        for row in coupling["stage_evaluations"]
    )
    flags = set(document["diagnostics"]["diagnostic_flags"])
    assert "gate_completed_interface_submerged_orifice_energy_momentum_v1" in flags
    assert "structure_momentum_closure_mass_only_mvp" not in flags
    assert "control_events" not in document


def test_gate_policy_changes_solver_hash_but_not_mesh_identity() -> None:
    """Numerical policy and immutable geometry retain separate hash domains."""

    payload = make_v4_lite_completed_gate_payload()
    parsed = parse_v4_lite_input(payload)
    mesh = build_v4_lite_mesh(parsed)
    changed = copy.deepcopy(payload)
    changed["solver"]["gate_equation_tolerance_m"] = 1.0e-9
    changed_parsed = parse_v4_lite_input(changed)
    changed_mesh = build_v4_lite_mesh(changed_parsed)

    assert v4_lite_mesh_hash(parsed, mesh) == v4_lite_mesh_hash(
        changed_parsed,
        changed_mesh,
    )
    assert v4_lite_solver_policy_hash(parsed) != v4_lite_solver_policy_hash(
        changed_parsed
    )


def test_completed_gate_result_rejects_missing_or_forged_momentum_evidence() -> None:
    """The durable result cannot claim v5 while dropping or rewriting its reaction."""

    document = HydraulicEngine().run(
        make_v4_lite_completed_gate_payload()
    ).to_dict()
    missing = copy.deepcopy(document)
    missing.pop("gate_coupling_evidence")
    with pytest.raises(ValueError, match="requires one Gate coupling evidence"):
        MvpHydraulicResult.model_validate(missing)

    forged = copy.deepcopy(document)
    forged["gate_coupling_evidence"][0]["stage_evaluations"][0][
        "reaction_force_per_density"
    ] += 1.0
    with pytest.raises(ValueError, match="reaction is inconsistent"):
        MvpHydraulicResult.model_validate(forged)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_sill", "requires explicit sill_elevation_m"),
        ("pump", "exactly one Gate and no Pump"),
        ("controlled", "requires fixed Gate control"),
        ("friction", "requires zero Manning friction"),
        ("not_submerged", "must be submerged initially"),
        ("reverse_head", "requires positive forward head"),
        ("missing_policy", "requires every Gate coupling field explicitly"),
    ],
)
def test_v4_lite_5_gate_scope_fails_closed(mutation: str, message: str) -> None:
    """Every unsupported physical or policy combination is rejected before solve."""

    payload = make_v4_lite_completed_gate_payload()
    if mutation == "missing_sill":
        payload["structures"]["gates"][0].pop("sill_elevation_m")
    elif mutation == "pump":
        payload["structures"]["pumps"] = make_v4_lite_payload()["structures"]["pumps"]
    elif mutation == "controlled":
        payload["structures"]["gates"][0]["control"] = {
            "type": "one-shot-stage-above",
            "threshold_water_level_m": 11.5,
        }
    elif mutation == "friction":
        payload["sections"][1]["default_manning_n"] = 0.03
    elif mutation == "not_submerged":
        payload["structures"]["gates"][0]["sill_elevation_m"] = 10.25
    elif mutation == "reverse_head":
        payload["initial_state"]["values"][1]["water_level_m"] = 10.25
    elif mutation == "missing_policy":
        payload["solver"].pop("gate_equation_tolerance_m")
    with pytest.raises(HydraulicInputError, match=message):
        parse_v4_lite_input(payload)


def test_pre_v5_contract_rejects_the_new_sill_field() -> None:
    """The added Gate datum cannot silently alter frozen v1-v4 input semantics."""

    payload = make_v4_lite_payload()
    payload["structures"]["gates"][0]["sill_elevation_m"] = 9.0
    with pytest.raises(HydraulicInputError, match="pre-v5 Gate"):
        parse_v4_lite_input(payload)
