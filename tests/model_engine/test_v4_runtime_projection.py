"""Native-v4 contract, direct projection, and domain-hash tests."""

import copy

import pytest

from model.adapters import project_v4_to_v4_lite
from model.api import parse_model_input_v4
from model.core.errors import HydraulicInputError
from model.provenance import snapshot_hash
from tests.model_engine.helpers import native_v4_payload


def test_native_v4_projects_directly_to_frozen_d1_runtime() -> None:
    """Preserve D1 runtime bytes while adding a distinct authoritative platform identity."""

    payload = native_v4_payload()
    parsed = parse_model_input_v4(payload)
    projection = project_v4_to_v4_lite(payload)

    assert parsed.schema_version == "dayu.model-input.v4"
    assert projection.runtime.schema_version == "dayu.model-input.v4-lite"
    assert projection.runtime.provenance.validation_policy_version == "v4-lite-7"
    assert projection.manifest["source_input_hash"] == snapshot_hash(
        parsed.model_dump(mode="json")
    )
    assert projection.manifest["defaulted_fields"] == []
    assert "v3_adapter" in projection.manifest["blocked_fields"]
    for key in (
        "runtime_projection_hash",
        "mesh_hash",
        "solver_policy_hash",
        "validation_policy_hash",
        "registry_hash",
    ):
        assert len(projection.manifest[key]) == 64


def test_authoritative_pump_or_control_change_has_independent_identity() -> None:
    """Keep source and runtime hashes sensitive to every physical Pump/control change."""

    original = native_v4_payload()
    changed = copy.deepcopy(original)
    changed["structures"]["pumps"][0]["head_curve"]["points"][1]["head_m"] = 1.81

    original_projection = project_v4_to_v4_lite(original)
    changed_projection = project_v4_to_v4_lite(changed)
    assert original_projection.manifest["source_input_hash"] != (
        changed_projection.manifest["source_input_hash"]
    )
    assert original_projection.manifest["runtime_projection_hash"] != (
        changed_projection.manifest["runtime_projection_hash"]
    )


def test_registry_or_scope_mismatch_fails_before_projection() -> None:
    """Reject tampered platform provenance and multi-Branch scope without fallback."""

    registry_tamper = native_v4_payload()
    registry_tamper["provenance"]["registry_hash"] = "0" * 64
    with pytest.raises(HydraulicInputError, match="registry hash"):
        project_v4_to_v4_lite(registry_tamper)

    multi_branch = native_v4_payload()
    multi_branch["branches"].append(copy.deepcopy(multi_branch["branches"][0]))
    with pytest.raises(HydraulicInputError, match="at most 1 item"):
        project_v4_to_v4_lite(multi_branch)

