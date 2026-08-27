"""Native-v4 authoritative and runtime identity freeze tests."""

import copy

from app.model_engine.v4_service import assess_native_v4_snapshot
from model.provenance import snapshot_hash
from tests.model_engine.helpers import native_v4_payload


def test_same_candidate_recomputes_all_hash_domains() -> None:
    """Require deterministic authoritative/projection/mesh/policy identities."""

    left = assess_native_v4_snapshot(native_v4_payload())
    right = assess_native_v4_snapshot(native_v4_payload())
    assert left.readiness.ready and right.readiness.ready
    assert left.readiness.candidate_hashes == right.readiness.candidate_hashes
    assert left.projection.manifest["source_input_hash"] == snapshot_hash(left.snapshot)


def test_control_change_updates_authoritative_and_runtime_hashes() -> None:
    """Ensure a frozen control change cannot reuse the previous execution identity."""

    original = native_v4_payload()
    changed = copy.deepcopy(original)
    changed["structures"]["pumps"][0]["control"]["start_level_m"] = 9.983
    left = assess_native_v4_snapshot(original)
    right = assess_native_v4_snapshot(changed)
    assert left.readiness.ready and right.readiness.ready
    assert left.projection.manifest["source_input_hash"] != right.projection.manifest[
        "source_input_hash"
    ]
    assert left.projection.manifest["runtime_projection_hash"] != right.projection.manifest[
        "runtime_projection_hash"
    ]

