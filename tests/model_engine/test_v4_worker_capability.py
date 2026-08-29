"""Dedicated native-v4 Worker routing and frozen-provenance gates."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.worker import tasks as worker_tasks
from app.worker.celery_app import celery_app
from app.worker.lifecycle import (
    DuplicateClaimError,
    InvalidTaskRouteError,
    claim_v4_task,
)
from app.worker.tasks import V4_QUEUE, V4_WORKER_CAPABILITIES, validate_v4_worker_task
from model.adapters import project_v4_to_v4_lite
from model.core.errors import HydraulicInputError
from model.provenance import snapshot_hash
from model.solver.registry import (
    D1_CAPABILITY_ID,
    D1_RUNTIME_ADAPTER_ID,
    D1_SOLVER_ID,
    task_solver_provenance,
)
from tests.model_engine.helpers import TEST_BUILD_IDENTITY, native_v4_payload


def _task(**changes):
    snapshot = native_v4_payload()
    projection = project_v4_to_v4_lite(snapshot)
    values = {
        "input_schema_version": "dayu.model-input.v4",
        "input_snapshot": projection.source_snapshot,
        "input_snapshot_hash": snapshot_hash(projection.source_snapshot),
        **task_solver_provenance("dayu.model-input.v4"),
        "runtime_projection_hash": projection.manifest["runtime_projection_hash"],
        "mesh_hash": projection.manifest["mesh_hash"],
        "solver_policy_hash": projection.manifest["solver_policy_hash"],
        "validation_policy_hash": projection.manifest["validation_policy_hash"],
        "registry_hash": projection.manifest["registry_hash"],
        "engine_version": TEST_BUILD_IDENTITY.engine_version,
        "engine_commit": TEST_BUILD_IDENTITY.engine_commit,
        "solver_build_id": TEST_BUILD_IDENTITY.solver_build_id,
        "build_mode": TEST_BUILD_IDENTITY.build_mode,
        "build_verified": TEST_BUILD_IDENTITY.verified,
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
        ("solver_id", None, "solver_id"),
        ("solver_id", "legacy-network-continuity-manning-v1", "solver_id"),
        ("capability_id", None, "capability_id"),
        ("capability_id", "wrong-capability", "capability_id"),
        ("runtime_adapter_id", None, "runtime_adapter_id"),
        ("runtime_adapter_id", "wrong-adapter", "runtime_adapter_id"),
        ("result_schema_version", None, "result_schema_version"),
        ("result_schema_version", "wrong-result", "result_schema_version"),
        ("registry_hash", None, "registry_hash"),
        ("registry_hash", "f" * 64, "registry_hash"),
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


def test_v4_claim_predicate_requires_the_exact_registered_route() -> None:
    """The atomic claim gate includes all five Registry provenance fields."""

    class RejectedClaimSession:
        statement = None
        rollback_count = 0

        def execute(self, statement):
            self.statement = statement
            return SimpleNamespace(rowcount=0)

        def rollback(self) -> None:
            self.rollback_count += 1

        def get(self, *_args):
            return None

    session = RejectedClaimSession()
    with pytest.raises(DuplicateClaimError, match="supported queued native-v4"):
        claim_v4_task(session, 91, "worker-route-contract")  # type: ignore[arg-type]

    where_clause = str(session.statement.whereclause)
    assert "simulation_task.solver_id" in where_clause
    assert "simulation_task.capability_id" in where_clause
    assert "simulation_task.runtime_adapter_id" in where_clause
    assert "simulation_task.result_schema_version" in where_clause
    assert "simulation_task.registry_hash" in where_clause
    parameter_values = set(session.statement.compile().params.values())
    assert set(task_solver_provenance("dayu.model-input.v4").values()) <= parameter_values
    assert session.rollback_count == 1


@pytest.mark.parametrize(
    ("celery_task", "claim_name"),
    [
        (worker_tasks.run_hydraulic_task, "claim_task"),
        (worker_tasks.run_hydraulic_v4_task, "claim_v4_task"),
    ],
)
def test_duplicate_delivery_is_an_idempotent_worker_noop(
    monkeypatch, celery_task, claim_name: str
) -> None:
    """A failed atomic claim returns normally and performs no state mutation."""

    class NoMutationSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def __getattr__(self, name: str):
            raise AssertionError(f"duplicate delivery accessed Session.{name}")

    def reject_duplicate(*_args, **_kwargs):
        raise DuplicateClaimError("already owned")

    monkeypatch.setattr(worker_tasks, "SessionLocal", lambda: NoMutationSession())
    monkeypatch.setattr(worker_tasks, claim_name, reject_duplicate)

    assert celery_task.run(907) == {"task_id": 907, "status": "duplicate"}


def test_invalid_queued_v4_route_is_not_reported_as_duplicate(monkeypatch) -> None:
    """A claim-time Registry rejection is terminal, not an endlessly redelivered no-op."""

    class RejectedRouteSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    def reject_route(*_args, **_kwargs):
        raise InvalidTaskRouteError("route mismatch")

    monkeypatch.setattr(worker_tasks, "SessionLocal", lambda: RejectedRouteSession())
    monkeypatch.setattr(worker_tasks, "claim_v4_task", reject_route)

    assert worker_tasks.run_hydraulic_v4_task.run(908) == {
        "task_id": 908,
        "status": "failed",
    }
