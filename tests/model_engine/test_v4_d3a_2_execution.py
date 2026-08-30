"""Native authoritative-v4 execution gate for D3A-2 explicit slope."""

import copy

import pytest

from model.adapters import project_v4_to_v4_lite, run_v4_lite
from model.core.errors import HydraulicInputError
from model.solver.registry import D3A_2_CAPABILITY_ID, D3A_2_RUNTIME_ADAPTER_ID
from tests.model_engine.helpers import native_v4_d3a_2_payload


def test_native_v4_d3a_2_projects_explicit_bed_and_executes_gate_pump() -> None:
    source = native_v4_d3a_2_payload()
    projection = project_v4_to_v4_lite(source)
    assert projection.source.solver_selection.capability_id == D3A_2_CAPABILITY_ID
    assert projection.manifest["runtime_adapter_id"] == D3A_2_RUNTIME_ADAPTER_ID
    assert projection.runtime.provenance.validation_policy_version == "d3a-2-v1"
    beds = tuple(item.bed_elevation_m for item in projection.runtime.sections)
    assert all(
        left is not None and right is not None and right < left
        for left, right in zip(beds, beds[1:])
    )

    document = run_v4_lite(projection.runtime_snapshot).to_dict()
    assert document["provenance"]["validation_policy_version"] == "d3a-2-v1"
    assert 0.0 < document["diagnostics"]["maximum_friction_number"] <= 0.1
    assert document["water_balance"]["status"] == "pass"
    assert len(document["controlled_gate_coupling_evidence"]) == 1
    assert len(document["pump_coupling_evidence"]) == 1


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_bed", "explicit bed elevation"),
        ("inferred_policy", "policy tuple is not implemented"),
        ("nonlinear_bed", "one linear bed slope"),
        ("local_shape", "identical relative Profile shapes"),
    ],
)
def test_d3a_2_contract_fails_closed_without_authority_or_scope(
    mutation: str, message: str
) -> None:
    payload = native_v4_d3a_2_payload()
    if mutation == "missing_bed":
        payload["cross_sections"][0].pop("bed_elevation_m")
    elif mutation == "inferred_policy":
        payload["numerical_policy"]["bed_elevation_source"] = (
            "profile-minimum-elevation-v1"
        )
    elif mutation == "nonlinear_bed":
        section = payload["cross_sections"][8]
        section["bed_elevation_m"] += 1.0e-5
        for point in section["points"]:
            point["elevation_m"] += 1.0e-5
    else:
        payload["cross_sections"][8]["points"][0]["elevation_m"] += 0.01

    with pytest.raises(HydraulicInputError, match=message):
        project_v4_to_v4_lite(copy.deepcopy(payload))
