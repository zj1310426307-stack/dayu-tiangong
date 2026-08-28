"""RC1 recomputation tests for frozen control and Pump identities."""

from __future__ import annotations

import copy

import pytest

from app.model_engine.v4_service import (
    dispatch_plan_hash_matches,
    pump_curve_identity_payload,
)
from model.provenance import snapshot_hash


def test_dispatch_plan_hash_is_recomputed_from_the_stored_snapshot() -> None:
    """Reject drift even when the stored digest still has valid SHA-256 syntax."""

    frozen = {
        "schema_version": "dayu.dispatch-plan.v1",
        "plan": {"evaluation_config": {"native_v4": {"gate_id": 7, "pump_id": 8}}},
        "actions": [],
        "rules": [],
    }
    digest = snapshot_hash(frozen)
    assert dispatch_plan_hash_matches(frozen, digest)
    drifted = copy.deepcopy(frozen)
    drifted["plan"]["evaluation_config"]["native_v4"]["gate_id"] = 9
    assert not dispatch_plan_hash_matches(drifted, digest)
    assert not dispatch_plan_hash_matches(frozen, "A" * 64)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("policy_id", "different-policy"),
        ("unit", "US-customary"),
        ("head_points", [{"flow_m3s": 0.0, "head_m": 9.0}]),
        (
            "efficiency_points",
            [{"flow_m3s": 0.0, "efficiency": 0.5}],
        ),
        ("source_revision", "revision-2"),
    ],
)
def test_every_pump_curve_identity_field_changes_the_hash(
    field: str, replacement: object
) -> None:
    """Keep policy, units, curves, and source revision in one hash domain."""

    values = {
        "policy_id": "d1-piecewise-linear-qh-qeta-si-v1",
        "unit": "SI",
        "head_points": [
            {"flow_m3s": 0.0, "head_m": 2.2},
            {"flow_m3s": 0.02, "head_m": 1.8},
        ],
        "efficiency_points": [
            {"flow_m3s": 0.0, "efficiency": 0.6},
            {"flow_m3s": 0.02, "efficiency": 0.75},
        ],
        "source_revision": "revision-1",
    }
    baseline = snapshot_hash(pump_curve_identity_payload(**values))
    values[field] = replacement
    assert snapshot_hash(pump_curve_identity_payload(**values)) != baseline
