"""Real DB/Redis Worker-function recovery from one transient delivery failure."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from os import getenv
from types import SimpleNamespace

from celery.exceptions import Retry
import pytest
from redis import Redis
from sqlalchemy import func, select

from app.database.session import SessionLocal
from app.files import configured_storage_root, resolve_within
from app.gis.models import (
    HydraulicTaskArtifact,
    HydraulicTaskControlEvent,
    HydraulicTaskGateResult,
    HydraulicTaskPumpResult,
    HydraulicTaskSectionResult,
    SimulationTask,
)
from app.model_engine.schemas import SimulationTaskCreate
from app.model_engine.service import create_task
from app.worker import recovery as worker_recovery
from app.worker import tasks as worker_tasks
from app.worker.celery_app import celery_app
from app.worker.lifecycle import claim_v4_task, heartbeat
from app.worker.recovery import (
    recover_stale_running_tasks,
    redeliver_stale_queued_tasks,
)
from model.solver.registry import D1_SOLVER_ID
from tests.model_engine.rc1_fault_helpers import (
    delete_task,
    ensure_authoritative_case,
    solved_engine_result,
    task_snapshot,
    write_evidence,
)
from tests.model_engine.test_v4_postgis_worker_integration import CASE_ID, PLAN_ID


requires_fault_services = pytest.mark.skipif(
    getenv("RUN_D2_FAULT_INTEGRATION") != "1",
    reason="requires migrated PostGIS and Redis",
)


def _create_queued_task() -> int:
    ensure_authoritative_case()
    with SessionLocal() as session:
        record = create_task(
            session,
            SimulationTaskCreate(
                case_id=CASE_ID,
                input_schema_version="dayu.model-input.v4",
                solver_id=D1_SOLVER_ID,
                dispatch_plan_id=PLAN_ID,
                execution_mode="validation",
                storage_level="full",
            ),
        )
        task = session.get(SimulationTask, record.id)
        assert task is not None
        task.status = "queued"
        task.queued_time = datetime.now(UTC)
        session.commit()
        return task.id


def test_celery_redelivers_unacknowledged_failures_and_worker_loss() -> None:
    """Broker publish loss must leave the original late-ack delivery recoverable."""

    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_acks_on_failure_or_timeout is False
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.task_routes["dayu.recover_hydraulic_tasks"] == {
        "queue": "celery"
    }
    recovery_schedule = celery_app.conf.beat_schedule[
        "recover-stale-hydraulic-attempts-and-deliveries"
    ]
    assert recovery_schedule["task"] == "dayu.recover_hydraulic_tasks"
    assert recovery_schedule["schedule"] == 30.0
    assert recovery_schedule["options"] == {"expires": 25.0}


@requires_fault_services
def test_transient_worker_failure_requeues_then_second_attempt_publishes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the actual Worker function across two attempts on DB + Redis."""

    broker = getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
    assert Redis.from_url(broker).ping() is True
    solved = solved_engine_result()
    task_id = _create_queued_task()
    artifact_path = None
    calls = 0

    def transient_then_success(_engine, *_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("injected transient after claim")
        return solved

    def record_retry(*_args, **kwargs):
        return Retry(exc=kwargs.get("exc"), when=kwargs.get("countdown"))

    monkeypatch.setattr(worker_tasks.HydraulicEngine, "run", transient_then_success)
    monkeypatch.setattr(worker_tasks.run_hydraulic_v4_task, "retry", record_retry)

    try:
        with pytest.raises(Retry):
            worker_tasks.run_hydraulic_v4_task.run(task_id)
        requeued = task_snapshot(task_id)
        assert requeued["status"] == "queued"
        assert requeued["execution_attempt_count"] == 1
        assert requeued["infrastructure_retry_count"] == 1
        assert requeued["active_execution_token"] is None
        with SessionLocal() as session:
            task = session.get(SimulationTask, task_id)
            assert task is not None
            assert task.queue_job_id is not None

        outcome = worker_tasks.run_hydraulic_v4_task.run(task_id)
        assert outcome == {"task_id": task_id, "status": "success"}
        final = task_snapshot(task_id)
        assert final["status"] == "success"
        assert final["execution_attempt_count"] == 2
        assert final["infrastructure_retry_count"] == 1
        assert final["active_execution_token"] is None

        with SessionLocal() as session:
            assert session.scalar(
                select(func.count(HydraulicTaskSectionResult.id)).where(
                    HydraulicTaskSectionResult.task_id == task_id
                )
            ) == 500
            assert session.scalar(
                select(func.count(HydraulicTaskGateResult.id)).where(
                    HydraulicTaskGateResult.task_id == task_id
                )
            ) == 25
            assert session.scalar(
                select(func.count(HydraulicTaskPumpResult.id)).where(
                    HydraulicTaskPumpResult.task_id == task_id
                )
            ) == 25
            assert session.scalar(
                select(func.count(HydraulicTaskControlEvent.id)).where(
                    HydraulicTaskControlEvent.task_id == task_id
                )
            ) == 3
            artifacts = list(
                session.scalars(
                    select(HydraulicTaskArtifact).where(
                        HydraulicTaskArtifact.task_id == task_id
                    )
                )
            )
            assert len(artifacts) == 1
            assert artifacts[0].status == "published"
            artifact_path = resolve_within(
                configured_storage_root(), artifacts[0].storage_key
            )
        write_evidence("worker-fault-retry-e2e", final)
    finally:
        delete_task(task_id)
        if artifact_path is not None:
            artifact_path.unlink(missing_ok=True)


@requires_fault_services
def test_worker_lost_duplicate_stale_recovery_redelivery_publishes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recover an abandoned lease through the real PostGIS/Redis boundaries."""

    broker = getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
    redis = Redis.from_url(broker)
    assert redis.ping() is True
    solved = solved_engine_result()
    task_id = _create_queued_task()
    queue_name = f"d2-fault-worker-lost-{task_id}"
    redis.delete(queue_name)
    artifact_path = None
    previous_eager = celery_app.conf.task_always_eager

    try:
        with SessionLocal() as session:
            claimed = claim_v4_task(session, task_id, "fault-worker-before-loss")
            first_token = str(claimed.active_execution_token)
            heartbeat(
                session,
                task_id,
                execution_token=first_token,
                progress=41,
                simulation_time=120.0,
                cfl=0.31,
                execution_phase="solving",
            )

        before_duplicate = task_snapshot(task_id)
        assert worker_tasks.run_hydraulic_v4_task.run(task_id) == {
            "task_id": task_id,
            "status": "duplicate",
        }
        after_duplicate = task_snapshot(task_id)
        assert after_duplicate == before_duplicate

        # The original Worker is now considered lost: no process owns the
        # durable lease, and its last heartbeat is made unambiguously stale.
        with SessionLocal() as session:
            abandoned = session.get(SimulationTask, task_id)
            assert abandoned is not None
            abandoned.heartbeat_time = datetime(2000, 1, 1, tzinfo=UTC)
            session.commit()

        stale_window_seconds = 365 * 24 * 60 * 60
        celery_app.conf.task_always_eager = False

        def publish_recovered_delivery(task: SimulationTask) -> object:
            return worker_tasks.run_hydraulic_v4_task.apply_async(
                args=[task.id],
                queue=queue_name,
            )

        monkeypatch.setattr(
            worker_recovery,
            "recover_stale_running_tasks",
            lambda: recover_stale_running_tasks(stale_window_seconds),
        )
        monkeypatch.setattr(
            worker_recovery,
            "redeliver_stale_queued_tasks",
            lambda: redeliver_stale_queued_tasks(
                stale_seconds=stale_window_seconds,
                limit=1,
                deliver=publish_recovered_delivery,
            ),
        )
        first_recovery = worker_recovery.recover_hydraulic_tasks.run()
        assert first_recovery == {
            "stale_running": [task_id],
            "redelivered": [],
        }
        requeued = task_snapshot(task_id)
        assert requeued["status"] == "queued"
        assert requeued["execution_attempt_count"] == 1
        assert requeued["infrastructure_retry_count"] == 1
        assert requeued["active_execution_token"] is None
        assert requeued["last_execution_token"] == first_token

        # Make only this queue intent old enough for the periodic queued-task
        # recovery, then publish its replacement delivery to an isolated real
        # Redis/Celery queue so no concurrently running Worker can consume it.
        with SessionLocal() as session:
            queued = session.get(SimulationTask, task_id)
            assert queued is not None
            queued.queued_time = datetime(2000, 1, 1, tzinfo=UTC)
            session.commit()

        second_recovery = worker_recovery.recover_hydraulic_tasks.run()
        assert second_recovery == {
            "stale_running": [],
            "redelivered": [task_id],
        }
        assert redis.llen(queue_name) == 1
        assert redis.rpop(queue_name) is not None
        assert redis.llen(queue_name) == 0

        monkeypatch.setattr(
            worker_tasks.HydraulicEngine,
            "run",
            lambda _engine, *_args, **_kwargs: solved,
        )
        outcome = worker_tasks.run_hydraulic_v4_task.run(task_id)
        with SessionLocal() as session:
            observed = session.get(SimulationTask, task_id)
            assert observed is not None
            failure_detail = (
                observed.last_infrastructure_error or observed.error_message
            )
        assert outcome == {"task_id": task_id, "status": "success"}, (
            failure_detail
        )

        final = task_snapshot(task_id)
        assert final["status"] == "success"
        assert final["execution_attempt_count"] == 2
        assert final["infrastructure_retry_count"] == 1
        assert final["manual_retry_count"] == 0
        assert final["active_execution_token"] is None

        with SessionLocal() as session:
            assert session.scalar(
                select(func.count(HydraulicTaskSectionResult.id)).where(
                    HydraulicTaskSectionResult.task_id == task_id
                )
            ) == 500
            assert session.scalar(
                select(func.count(HydraulicTaskGateResult.id)).where(
                    HydraulicTaskGateResult.task_id == task_id
                )
            ) == 25
            assert session.scalar(
                select(func.count(HydraulicTaskPumpResult.id)).where(
                    HydraulicTaskPumpResult.task_id == task_id
                )
            ) == 25
            assert session.scalar(
                select(func.count(HydraulicTaskControlEvent.id)).where(
                    HydraulicTaskControlEvent.task_id == task_id
                )
            ) == 3
            artifacts = list(
                session.scalars(
                    select(HydraulicTaskArtifact).where(
                        HydraulicTaskArtifact.task_id == task_id
                    )
                )
            )
            assert len(artifacts) == 1
            assert artifacts[0].status == "published"
            artifact_path = resolve_within(
                configured_storage_root(), artifacts[0].storage_key
            )
        write_evidence(
            "worker-lost-stale-redelivery-e2e",
            {
                "duplicate_delivery": after_duplicate,
                "stale_requeue": requeued,
                "final": final,
            },
        )
    finally:
        celery_app.conf.task_always_eager = previous_eager
        redis.delete(queue_name)
        delete_task(task_id)
        if artifact_path is not None:
            artifact_path.unlink(missing_ok=True)


@requires_fault_services
def test_stale_queued_delivery_is_bounded_even_with_non_null_job_id() -> None:
    """Lost acknowledged messages are retried by lease, interval, and hard limit."""

    task_id = _create_queued_task()
    calls = 0

    def unavailable_then_published(_task: SimulationTask) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("injected broker publish failure")
        return SimpleNamespace(id="recovered-delivery-id")

    try:
        with SessionLocal() as session:
            task = session.get(SimulationTask, task_id)
            assert task is not None
            task.queue_job_id = None
            task.queued_time = datetime.now(UTC) - timedelta(minutes=10)
            session.commit()

        assert redeliver_stale_queued_tasks(
            stale_seconds=60,
            deliver=unavailable_then_published,
        ) == []
        with SessionLocal() as session:
            task = session.get(SimulationTask, task_id)
            assert task is not None
            assert task.status == "queued"
            assert task.queue_job_id is None
            assert task.delivery_attempt_count == 1
            assert "publish failed" in str(task.last_infrastructure_error)
        for _scan in range(5):
            assert redeliver_stale_queued_tasks(
                stale_seconds=60,
                deliver=unavailable_then_published,
            ) == []
        assert calls == 1

        with SessionLocal() as session:
            task = session.get(SimulationTask, task_id)
            assert task is not None
            task.queue_job_id = "acknowledged-but-lost"
            task.last_delivery_time = datetime.now(UTC) - timedelta(minutes=10)
            session.commit()

        assert redeliver_stale_queued_tasks(
            stale_seconds=60,
            deliver=unavailable_then_published,
        ) == [task_id]
        with SessionLocal() as session:
            task = session.get(SimulationTask, task_id)
            assert task is not None
            assert task.status == "queued"
            assert task.queue_job_id == "recovered-delivery-id"
            assert task.delivery_attempt_count == 2
        for _scan in range(5):
            assert redeliver_stale_queued_tasks(
                stale_seconds=60,
                deliver=unavailable_then_published,
            ) == []
        assert calls == 2

        with SessionLocal() as session:
            task = session.get(SimulationTask, task_id)
            assert task is not None
            task.last_delivery_time = datetime.now(UTC) - timedelta(minutes=10)
            session.commit()
        assert redeliver_stale_queued_tasks(
            stale_seconds=60,
            deliver=unavailable_then_published,
        ) == [task_id]
        assert calls == 3

        with SessionLocal() as session:
            task = session.get(SimulationTask, task_id)
            assert task is not None
            assert task.delivery_attempt_count == 3
            assert task.queue_job_id == "recovered-delivery-id"
            task.last_delivery_time = datetime.now(UTC) - timedelta(minutes=10)
            session.commit()
        assert redeliver_stale_queued_tasks(
            stale_seconds=60,
            deliver=unavailable_then_published,
        ) == []
        assert calls == 3
        with SessionLocal() as session:
            task = session.get(SimulationTask, task_id)
            assert task is not None
            assert task.status == "failed"
            assert "D2_DELIVERY_RETRY_LIMIT" in str(task.error_message)
        write_evidence("queued-delivery-recovery", task_snapshot(task_id))
    finally:
        delete_task(task_id)


@requires_fault_services
def test_invalid_queued_v4_route_fails_once_and_is_not_redelivered() -> None:
    """A corrupted queued Registry route is terminal instead of a duplicate loop."""

    task_id = _create_queued_task()
    deliveries = 0

    def unexpected_delivery(_task: SimulationTask) -> object:
        nonlocal deliveries
        deliveries += 1
        return SimpleNamespace(id="must-not-be-published")

    try:
        with SessionLocal() as session:
            task = session.get(SimulationTask, task_id)
            assert task is not None
            task.runtime_adapter_id = None
            task.queue_job_id = None
            task.queued_time = datetime.now(UTC) - timedelta(minutes=10)
            session.commit()

        assert worker_tasks.run_hydraulic_v4_task.run(task_id) == {
            "task_id": task_id,
            "status": "failed",
        }
        with SessionLocal() as session:
            failed = session.get(SimulationTask, task_id)
            assert failed is not None
            assert failed.status == "failed"
            assert failed.execution_attempt_count == 0
            assert failed.active_execution_token is None
            assert "runtime_adapter_id" in str(failed.error_message)
            assert "Registry" in str(failed.error_message)

        assert redeliver_stale_queued_tasks(
            stale_seconds=60,
            deliver=unexpected_delivery,
        ) == []
        assert deliveries == 0
    finally:
        delete_task(task_id)
