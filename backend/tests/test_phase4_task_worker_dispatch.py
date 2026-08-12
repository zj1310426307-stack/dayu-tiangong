"""PostGIS-backed acceptance tests for Phase 4 provenance and orchestration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database.session import SessionLocal
from app.gis.models import (
    BoundaryCondition,
    DispatchPlan,
    DispatchRun,
    Gate,
    ModelParameter,
    SimulationCase,
    SimulationCaseBoundary,
    SimulationTask,
)
from app.main import app
from app.model_engine.schemas import SimulationTaskCreate
from app.model_engine.service import create_task
from app.worker.celery_app import celery_app
from app.worker.lifecycle import (
    DuplicateClaimError,
    claim_task,
    recover_stale_tasks,
    request_cancel,
)
from app.worker.tasks import run_hydraulic_task
from model.core.errors import HydraulicCancelledError
from model.provenance import snapshot_hash


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGIS_TESTS") != "1",
    reason="requires the migrated local PostGIS service",
)
client = TestClient(app)


def _demo_case(session) -> SimulationCase:
    case = session.scalar(select(SimulationCase).order_by(SimulationCase.id))
    assert case is not None
    return case


def _delete_tasks(*task_ids: int) -> None:
    with SessionLocal() as session:
        for task_id in task_ids:
            task = session.get(SimulationTask, task_id)
            if task is not None:
                session.delete(task)
        session.commit()


def test_task_snapshot_is_frozen_hashed_and_only_uses_linked_boundaries() -> None:
    """Later business-table edits cannot change a task's executable input."""

    with SessionLocal() as session:
        case = _demo_case(session)
        record = create_task(
            session,
            SimulationTaskCreate(
                case_id=case.id,
                duration_seconds=120,
                output_interval_seconds=60,
                input_schema_version="dayu.model-input.v2",
            ),
        )
        task_id = record.id
        task = session.get(SimulationTask, task_id)
        assert task is not None and task.input_snapshot is not None
        frozen = task.input_snapshot
        digest = task.input_snapshot_hash
        assert digest == snapshot_hash(frozen)
        linked_ids = set(
            session.scalars(
                select(SimulationCaseBoundary.boundary_condition_id).where(
                    SimulationCaseBoundary.case_id == case.id
                )
            ).all()
        )
        assert {item["id"] for item in frozen["boundary_conditions"]} == linked_ids

        parameter = session.scalar(
            select(ModelParameter).where(
                ModelParameter.dataset_version_id == case.dataset_version_id
            )
        )
        assert parameter is not None
        original_value = parameter.value
        parameter.value = original_value + 123.456
        session.commit()
        session.refresh(task)
        assert task.input_snapshot == frozen
        assert task.input_snapshot_hash == digest
        parameter.value = original_value
        session.commit()

    snapshot_response = client.get(f"/api/v1/model/tasks/{task_id}/snapshot")
    assert snapshot_response.status_code == 200
    assert snapshot_response.json()["input_snapshot_hash"] == digest
    _delete_tasks(task_id)


def test_duplicate_case_boundary_for_same_node_and_type_is_rejected() -> None:
    """A case cannot bind two competing conditions to one node/type pair."""

    with SessionLocal() as session:
        case = _demo_case(session)
        existing = session.scalar(
            select(BoundaryCondition)
            .join(
                SimulationCaseBoundary,
                SimulationCaseBoundary.boundary_condition_id == BoundaryCondition.id,
            )
            .where(SimulationCaseBoundary.case_id == case.id)
        )
        assert existing is not None
        duplicate = BoundaryCondition(
            dataset_version_id=existing.dataset_version_id,
            name=f"PHASE4 duplicate boundary {datetime.now(UTC).timestamp()}",
            boundary_type=existing.boundary_type,
            target_node_id=existing.target_node_id,
            values=existing.values,
            unit=existing.unit,
        )
        session.add(duplicate)
        session.flush()
        from app.dataset.service import _validate_case_boundaries

        with pytest.raises(ValueError, match="same|同一|澶氫釜"):
            _validate_case_boundaries(
                session, case.dataset_version_id, [existing.id, duplicate.id]
            )
        session.rollback()


def test_atomic_claim_cancel_stale_recovery_and_same_snapshot_retry() -> None:
    """Lifecycle operations are durable and a task can have only one owner."""

    with SessionLocal() as session:
        case = _demo_case(session)
        record = create_task(
            session,
            SimulationTaskCreate(
                case_id=case.id,
                duration_seconds=60,
                input_schema_version="dayu.model-input.v2",
            ),
        )
        task = session.get(SimulationTask, record.id)
        assert task is not None
        original_hash = task.input_snapshot_hash
        task.status = "queued"
        task.queued_time = datetime.now(UTC)
        session.commit()
        claimed = claim_task(session, task.id, "phase4-test-worker-1")
        assert claimed.status == "running"
        with SessionLocal() as competing:
            with pytest.raises(DuplicateClaimError):
                claim_task(competing, task.id, "phase4-test-worker-2")
        request_cancel(session, claimed)
        assert claimed.status == "cancel_requested"
        claimed.heartbeat_time = datetime.now(UTC) - timedelta(minutes=10)
        session.commit()
        assert recover_stale_tasks(session, stale_seconds=120) == [task.id]
        session.refresh(claimed)
        assert claimed.status == "failed"
        assert claimed.input_snapshot_hash == original_hash

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    retry = client.post(f"/api/v1/model/tasks/{record.id}/retry")
    assert retry.status_code == 200
    with SessionLocal() as session:
        retried = session.get(SimulationTask, record.id)
        assert retried is not None
        assert retried.input_snapshot_hash == original_hash
    _delete_tasks(record.id)


def test_queued_task_can_be_cancelled_immediately() -> None:
    """Queued cancellation terminates without asking the numerical engine."""

    with SessionLocal() as session:
        case = _demo_case(session)
        record = create_task(session, SimulationTaskCreate(case_id=case.id))
        task = session.get(SimulationTask, record.id)
        assert task is not None
        task.status = "queued"
        session.commit()
        cancelled = request_cancel(session, task)
        assert cancelled.status == "cancelled"
        assert cancelled.progress == 100
        assert cancelled.cancel_requested is True
    _delete_tasks(record.id)


def test_running_task_cancels_cooperatively(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker 运行中收到取消检查时应持久化 cancelled，而不是 failed。"""

    with SessionLocal() as session:
        case = _demo_case(session)
        record = create_task(session, SimulationTaskCreate(case_id=case.id))
        task = session.get(SimulationTask, record.id)
        assert task is not None
        task.status = "queued"
        session.commit()

    def cancelled_run(*args, **kwargs):
        raise HydraulicCancelledError("cooperative test cancellation")

    monkeypatch.setattr("app.worker.tasks.HydraulicEngine.run", cancelled_run)
    outcome = run_hydraulic_task.run(record.id)
    assert outcome["status"] == "cancelled"
    with SessionLocal() as session:
        task = session.get(SimulationTask, record.id)
        assert task is not None and task.status == "cancelled"
    _delete_tasks(record.id)


def test_worker_input_failure_is_persisted_without_retry() -> None:
    """缺失冻结输入属于数值输入错误，必须一次失败并持久化。"""

    with SessionLocal() as session:
        case = _demo_case(session)
        task = SimulationTask(
            case_id=case.id, status="queued", progress=0, config={},
            input_schema_version="dayu.model-input.v2", input_snapshot=None,
        )
        session.add(task)
        session.commit()
        task_id = task.id
    outcome = run_hydraulic_task.run(task_id)
    assert outcome["status"] == "failed"
    with SessionLocal() as session:
        failed = session.get(SimulationTask, task_id)
        assert failed is not None and failed.status == "failed"
        assert "frozen input" in (failed.error_message or "")
        assert failed.retry_count == 0
    _delete_tasks(task_id)


def test_dispatch_plan_validation_freeze_immutability_clone_and_real_run() -> None:
    """The public API executes the full draft-to-comparison workflow."""

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    with SessionLocal() as session:
        case = _demo_case(session)
        gate = session.scalar(
            select(Gate).where(
                Gate.dataset_version_id == case.dataset_version_id,
                Gate.river_segment_id.is_not(None),
            ).order_by(Gate.id)
        )
        assert gate is not None
        case_id = case.id
        dataset_version_id = case.dataset_version_id

    name = f"PHASE4 acceptance {datetime.now(UTC).timestamp()}"
    created = client.post(
        "/api/v1/dispatch/plans",
        json={
            "dataset_version_id": dataset_version_id,
            "simulation_case_id": case_id,
            "name": name,
            "duration_seconds": 120,
            "evaluation_config": {"warning_level": 200.0},
            "storage_level": "key_sections",
        },
    )
    assert created.status_code == 201
    plan_id = created.json()["id"]
    action_payload = {
        "sequence": 1,
        "time_seconds": 0,
        "structure_type": "gate",
        "gate_id": gate.id,
        "command_type": "gate_opening_m",
        "target_value": min(float(gate.maximum_opening or gate.height), 1.0),
        "interpolation": "step",
        "priority": 10,
    }
    action = client.post(
        f"/api/v1/dispatch/plans/{plan_id}/actions", json=action_payload
    )
    assert action.status_code == 201
    duplicate = client.post(
        f"/api/v1/dispatch/plans/{plan_id}/actions", json=action_payload
    )
    assert duplicate.status_code == 409
    mismatched = client.post(
        f"/api/v1/dispatch/plans/{plan_id}/actions",
        json={
            **action_payload,
            "time_seconds": 60,
            "command_type": "pump_enabled",
            "target_value": 1,
        },
    )
    assert mismatched.status_code == 422
    rule = client.post(
        f"/api/v1/dispatch/plans/{plan_id}/rules",
        json={
            "name": "elapsed time safety opening",
            "observation_type": "elapsed_time",
            "operator": ">=",
            "threshold": 60,
            "hysteresis": 0,
            "minimum_hold_seconds": 0,
            "cooldown_seconds": 60,
            "action_template": {
                "structure_type": "gate",
                "structure_id": gate.id,
                "command_type": "gate_opening_m",
                "target_value": min(float(gate.maximum_opening or gate.height), 0.5),
            },
            "priority": 5,
        },
    )
    assert rule.status_code == 201
    validated = client.post(f"/api/v1/dispatch/plans/{plan_id}/validate")
    assert validated.status_code == 200
    assert validated.json()["valid"] is True
    frozen = client.post(f"/api/v1/dispatch/plans/{plan_id}/freeze")
    assert frozen.status_code == 200
    frozen_hash = frozen.json()["frozen_snapshot_hash"]
    assert len(frozen_hash) == 64
    assert client.patch(
        f"/api/v1/dispatch/plans/{plan_id}", json={"duration_seconds": 240}
    ).status_code == 409

    clone = client.post(f"/api/v1/dispatch/plans/{plan_id}/clone")
    assert clone.status_code == 200
    clone_id = clone.json()["id"]
    assert clone.json()["status"] == "draft"
    assert clone.json()["version"] == 2
    assert clone.json()["action_count"] == 1
    assert clone.json()["rule_count"] == 1

    started = client.post(f"/api/v1/dispatch/plans/{plan_id}/runs")
    assert started.status_code == 202
    run_id = started.json()["id"]
    run = client.get(f"/api/v1/dispatch/runs/{run_id}")
    assert run.status_code == 200
    assert run.json()["status"] == "success"
    comparison = client.get(f"/api/v1/dispatch/runs/{run_id}/comparison")
    assert comparison.status_code == 200
    assert comparison.json()["time"]
    assert "global_balance_residual" in comparison.json()["metrics"]
    events = client.get(f"/api/v1/dispatch/runs/{run_id}/events")
    assert events.status_code == 200
    assert events.json()

    archived = client.patch(
        f"/api/v1/dispatch/plans/{plan_id}", json={"status": "archived"}
    )
    assert archived.status_code == 200
    assert archived.json()["frozen_snapshot_hash"] == frozen_hash

    with SessionLocal() as session:
        run_entity = session.get(DispatchRun, run_id)
        task_ids = [run_entity.baseline_task_id, run_entity.controlled_task_id]
        session.delete(run_entity)
        session.commit()
        for task_id in task_ids:
            task = session.get(SimulationTask, task_id)
            if task is not None:
                session.delete(task)
        for cleanup_plan_id in (clone_id, plan_id):
            plan = session.get(DispatchPlan, cleanup_plan_id)
            if plan is not None:
                session.delete(plan)
        session.commit()
