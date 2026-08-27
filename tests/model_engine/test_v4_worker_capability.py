"""Dedicated native-v4 Worker routing and frozen-provenance gates."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.worker.celery_app import celery_app
from app.worker.tasks import V4_QUEUE, V4_WORKER_CAPABILITIES, validate_v4_worker_task
from model.adapters import project_v4_to_v4_lite
from model.core.errors import HydraulicInputError
from model.provenance import snapshot_hash
from model.solver.registry import D1_CAPABILITY_ID, D1_RUNTIME_ADAPTER_ID, D1_SOLVER_ID
from tests.model_engine.helpers import native_v4_payload


def _task(**changes):
    snapshot = native_v4_payload()
    projection = project_v4_to_v4_lite(snapshot)
    values = {
        "input_schema_version": "dayu.model-input.v4",
        "input_snapshot": projection.source_snapshot,
        "input_snapshot_hash": snapshot_hash(projection.source_snapshot),
        "solver_id": D1_SOLVER_ID,
        "capability_id": D1_CAPABILITY_ID,
        "runtime_adapter_id": D1_RUNTIME_ADAPTER_ID,
        "runtime_projection_hash": projection.manifest["runtime_projection_hash"],
        "mesh_hash": projection.manifest["mesh_hash"],
        "solver_policy_hash": projection.manifest["solver_policy_hash"],
        "validation_policy_hash": projection.manifest["validation_policy_hash"],
        "registry_hash": projection.manifest["registry_hash"],
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_v4_worker_declares_only_the_d1_capability_and_queue() -> None:
    assert V4_WORKER_CAPABILITIES == {
        "supported_solver_ids": (D1_SOLVER_ID,),
        "supported_capability_ids": (D1_CAPABILITY_ID,),
    }
    assert celery_app.conf.task_routes["dayu.run_hydraulic_v4_task"]["queue"] == V4_QUEUE


def test_worker_recomputes_all_frozen_hash_domains() -> None:
    projection = validate_v4_worker_task(_task())
    assert projection.source.schema_version == "dayu.model-input.v4"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("solver_id", "legacy-network-continuity-manning-v1", "not registered"),
        ("runtime_projection_hash", "0" * 64, "runtime_projection_hash"),
        ("mesh_hash", "1" * 64, "mesh_hash"),
        ("input_snapshot_hash", "2" * 64, "authoritative input hash mismatch"),
    ],
)
def test_worker_rejects_capability_or_snapshot_drift(
    field: str, value: str, message: str
) -> None:
    with pytest.raises(HydraulicInputError, match=message):
        validate_v4_worker_task(_task(**{field: value}))
