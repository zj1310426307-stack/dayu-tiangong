"""Native authoritative-v4 execution gate for D3A-3 engineering Profiles."""

import copy

import pytest

from model.adapters import project_v4_to_v4_lite, run_v4_lite
from model.core.errors import HydraulicInputError
from model.solver.finite_volume import NONPRISMATIC_ENGINEERING_SCOPE
from model.solver.registry import D3A_3_CAPABILITY_ID, D3A_3_RUNTIME_ADAPTER_ID
from tests.model_engine.helpers import native_v4_d3a_3_payload


def test_native_v4_d3a_3_executes_different_profile_gate_and_pump() -> None:
    """Run the six-hour mild contraction/expansion Gate/Pump integration case."""

    source = native_v4_d3a_3_payload()
    projection = project_v4_to_v4_lite(source)
    assert projection.source.solver_selection.capability_id == D3A_3_CAPABILITY_ID
    assert projection.manifest["runtime_adapter_id"] == D3A_3_RUNTIME_ADAPTER_ID
    assert projection.runtime.provenance.validation_policy_version == "d3a-3-v1"
    assert projection.runtime.solver.geometry_source == (
        "hydraulic-function-linear-face-v1"
    )

    document = run_v4_lite(projection.runtime_snapshot).to_dict()
    assert document["provenance"]["validation_policy_version"] == "d3a-3-v1"
    assert document["water_balance"]["status"] == "pass"
    assert NONPRISMATIC_ENGINEERING_SCOPE in document["diagnostics"][
        "diagnostic_flags"
    ]
    assert 0.0 < document["diagnostics"]["maximum_friction_number"] <= 0.1

    gate = document["controlled_gate_coupling_evidence"][0]
    assert any(
        row["upstream_top_width"] != row["downstream_top_width"]
        and row["upstream_area"] != row["downstream_area"]
        and row["upstream_pressure_moment"] != row["downstream_pressure_moment"]
        for row in gate["stage_evaluations"]
    )
    pump = document["pumps"][0]
    assert "on" in pump["control_state"]
    assert max(pump["source_stage_m"]) > min(pump["source_stage_m"])
    assert len(document["pump_coupling_evidence"]) == 1


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("identical", "non-identical local Profile shapes"),
        ("abrupt", "adjacent Profile change"),
        ("source", "policy tuple is not implemented"),
    ],
)
def test_d3a_3_contract_rejects_unverified_profile_compositions(
    mutation: str,
    message: str,
) -> None:
    """Fail closed for prismatic, abrupt, or mismatched-source declarations."""

    payload = native_v4_d3a_3_payload()
    if mutation == "identical":
        reference = payload["cross_sections"][0]
        for section in payload["cross_sections"][1:]:
            bed = section["bed_elevation_m"]
            section["points"] = [
                {
                    "offset_m": point["offset_m"],
                    "elevation_m": bed
                    + point["elevation_m"]
                    - reference["bed_elevation_m"],
                }
                for point in reference["points"]
            ]
    elif mutation == "abrupt":
        section = payload["cross_sections"][10]
        bed = section["bed_elevation_m"]
        section["points"] = [
            {"offset_m": 0.0, "elevation_m": bed + 3.0},
            {"offset_m": 1.5, "elevation_m": bed},
            {"offset_m": 3.0, "elevation_m": bed + 3.0},
        ]
    else:
        payload["numerical_policy"]["geometry_source"] = (
            "hydrostatic-reconstruction-v1"
        )

    with pytest.raises(HydraulicInputError, match=message):
        project_v4_to_v4_lite(copy.deepcopy(payload))
