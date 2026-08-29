"""Native-v4 readiness and bounded preview tests."""

import copy

import pytest

from app.model_engine.v4_service import (
    assess_native_v4_snapshot,
    preview_from_assessment,
)
from tests.model_engine.helpers import native_v4_d3a_1_payload, native_v4_payload


def _codes(payload: dict) -> set[str]:
    """Return stable error codes for one mutated candidate."""

    return {
        item.code for item in assess_native_v4_snapshot(payload).readiness.errors
    }


def test_valid_d1_candidate_is_ready_and_preview_is_bounded() -> None:
    """Expose only counts, identities, time range, hashes, and limitations in preview."""

    assessment = assess_native_v4_snapshot(native_v4_payload())
    assert assessment.readiness.ready is True
    assert not assessment.readiness.errors
    assert assessment.readiness.snapshot_summary["section_count"] == 20
    preview = preview_from_assessment(assessment)
    assert preview.schema_version == "dayu.model-input.v4"
    assert preview.section_count == 20
    assert preview.gate["id"] == 51
    assert preview.pump["id"] == 61
    assert preview.boundary_time_range["upstream_end"] == 21600.0
    assert "runtime_projection_hash" in preview.hashes
    assert not hasattr(preview, "snapshot")


def test_valid_d3a_1_candidate_is_explicitly_ready() -> None:
    """Positive roughness is accepted only through the named D3A-1 route."""

    assessment = assess_native_v4_snapshot(native_v4_d3a_1_payload())
    assert assessment.readiness.ready is True
    assert assessment.readiness.capability_id == (
        "single-branch-gate-pump-manning-v1"
    )
    assert assessment.projection is not None
    assert assessment.projection.runtime.provenance.validation_policy_version == (
        "d3a-1-v1"
    )
    preview = preview_from_assessment(assessment)
    assert preview.capability_id == assessment.readiness.capability_id
    assert "positive-section-effective-manning" in preview.capability_scope


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("multi_branch", "D2_BRANCH_COUNT_UNSUPPORTED"),
        ("manning", "D2_MANNING_NONZERO"),
        ("profile", "D2_PROFILE_MISMATCH"),
        ("missing_gate", "D2_GATE_COUNT_UNSUPPORTED"),
        ("missing_pump", "D2_PUMP_COUNT_UNSUPPORTED"),
        ("internal_pump", "D2_INTERNAL_OR_NONHYDRAULIC_PUMP"),
        ("curve", "D2_PUMP_CONTRACT_INCOMPLETE"),
        ("boundary", "D2_BOUNDARY_COVERAGE_INCOMPLETE"),
        ("placement", "D2_GATE_PUMP_PLACEMENT_CONFLICT"),
        ("policy", "D2_NUMERICAL_POLICY_UNREGISTERED"),
    ],
)
def test_readiness_fails_closed_with_actionable_codes(
    mutation: str, expected: str
) -> None:
    """Reject every documented D1 scope violation before task creation."""

    payload = native_v4_payload()
    if mutation == "multi_branch":
        payload["branches"].append(copy.deepcopy(payload["branches"][0]))
    elif mutation == "manning":
        payload["cross_sections"][0]["default_manning_n"] = 0.02
    elif mutation == "profile":
        payload["cross_sections"][0]["points"][1]["elevation_m"] = 9.1
    elif mutation == "missing_gate":
        payload["structures"]["gates"] = []
    elif mutation == "missing_pump":
        payload["structures"]["pumps"] = []
    elif mutation == "internal_pump":
        payload["structures"]["pumps"][0]["outlet"] = "internal"
    elif mutation == "curve":
        payload["structures"]["pumps"][0].pop("head_curve")
    elif mutation == "boundary":
        payload["boundaries"]["upstream"]["time_seconds"][-1] = 21599.0
    elif mutation == "placement":
        payload["structures"]["pumps"][0]["section_id"] = 8
    elif mutation == "policy":
        payload["numerical_policy"]["pump_curve_policy"] = "unknown"
    assert expected in _codes(payload)

