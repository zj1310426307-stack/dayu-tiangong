"""Execution-attempt lease gates for duplicate delivery and stale workers."""

from __future__ import annotations

import inspect
from os import getenv

import pytest

from app.worker import tasks as worker_tasks
from app.database.session import SessionLocal
from app.gis.models import SimulationTask
from app.worker.lifecycle import (
    DuplicateClaimError,
    StaleExecutionError,
    claim_task,
    claim_v4_task,
    heartbeat,
    lock_attempt_for_finalization,
    persist_legacy_result_with_attempt_cas,
    transition_attempt_terminal,
)
from tests.model_engine.rc1_fault_helpers import (
    create_claimed_v4_task,
    delete_task,
    ensure_authoritative_case,
    task_snapshot,
    write_evidence,
)
from tests.model_engine.test_v4_postgis_worker_integration import CASE_ID, DATASET_ID


def test_celery_tasks_do_not_use_autoretry_wrapper() -> None:
    """A retry is allowed only after the database has requeued the attempt."""

    source = inspect.getsource(worker_tasks)
    assert "autoretry_for" not in source


@pytest.mark.skipif(
    getenv("RUN_D2_FAULT_INTEGRATION") != "1",
    reason="requires migrated PostGIS",
)
def test_duplicate_claim_and_old_token_cannot_mutate_new_attempt() -> None:
    task_id, first_token, _projection = create_claimed_v4_task("attempt-worker-1")
    try:
        first = task_snapshot(task_id)
        assert first["execution_attempt_count"] == 1
        assert len(first_token) == 32
        with SessionLocal() as competing:
            with pytest.raises(DuplicateClaimError):
                claim_v4_task(competing, task_id, "attempt-worker-duplicate")

        with SessionLocal() as session:
            task = session.get(SimulationTask, task_id)
            assert task is not None
            task.status = "queued"
            task.last_execution_token = first_token
            task.active_execution_token = None
            session.commit()
            second = claim_v4_task(session, task_id, "attempt-worker-2")
            second_token = str(second.active_execution_token)
        assert second_token != first_token
        assert task_snapshot(task_id)["execution_attempt_count"] == 2

        with SessionLocal() as stale:
            with pytest.raises(StaleExecutionError):
                heartbeat(
                    stale,
                    task_id,
                    execution_token=first_token,
                    progress=80,
                    simulation_time=999.0,
                    cfl=9.0,
                )
        with SessionLocal() as stale:
            assert not transition_attempt_terminal(
                stale,
                task_id,
                execution_token=first_token,
                status="failed",
                message="old delivery",
            )
        current = task_snapshot(task_id)
        assert current["status"] == "running"
        assert current["active_execution_token"] == second_token
        write_evidence("execution-attempt", current)
    finally:
        delete_task(task_id)


def _create_claimed_legacy_task() -> tuple[int, str]:
    ensure_authoritative_case()
    with SessionLocal() as session:
        task = SimulationTask(
            case_id=CASE_ID,
            dataset_version_id=DATASET_ID,
            status="queued",
            progress=0,
            config={},
            input_schema_version="dayu.model-input.v2",
            input_snapshot={"schema_version": "dayu.model-input.v2"},
        )
        session.add(task)
        session.commit()
        claimed = claim_task(session, task.id, "legacy-final-cas")
        return task.id, str(claimed.active_execution_token)


@pytest.mark.skipif(
    getenv("RUN_D2_FAULT_INTEGRATION") != "1",
    reason="requires migrated PostGIS",
)
def test_legacy_success_and_token_transfer_share_one_transaction() -> None:
    task_id, token = _create_claimed_legacy_task()

    def fake_persist(session, task, _result) -> None:
        task.status = "success"
        task.progress = 100
        task.diagnostics = {"test": "legacy-atomic-finalization"}
        task.result_path = f"database://simulation_result?task_id={task.id}"
        session.commit()
        session.refresh(task)

    try:
        with SessionLocal() as session:
            task = lock_attempt_for_finalization(
                session, task_id, execution_token=token
            )
            persist_legacy_result_with_attempt_cas(
                session,
                task,
                object(),
                execution_token=token,
                persist=fake_persist,
            )
        final = task_snapshot(task_id)
        assert final["status"] == "success"
        assert final["active_execution_token"] is None
        assert final["last_execution_token"] == token
        write_evidence("legacy-final-success-cas", final)
    finally:
        delete_task(task_id)


@pytest.mark.skipif(
    getenv("RUN_D2_FAULT_INTEGRATION") != "1",
    reason="requires migrated PostGIS",
)
def test_legacy_crash_after_result_flush_cannot_leave_success_with_active_token() -> None:
    task_id, token = _create_claimed_legacy_task()

    def fake_persist(session, task, _result) -> None:
        task.status = "success"
        task.progress = 100
        task.result_path = f"database://simulation_result?task_id={task.id}"
        session.commit()
        session.refresh(task)

    def crash(point: str) -> None:
        if point == "after_legacy_result_flush":
            raise RuntimeError("injected legacy crash after result flush")

    try:
        with SessionLocal() as session:
            task = lock_attempt_for_finalization(
                session, task_id, execution_token=token
            )
            with pytest.raises(RuntimeError, match="injected legacy crash"):
                persist_legacy_result_with_attempt_cas(
                    session,
                    task,
                    object(),
                    execution_token=token,
                    persist=fake_persist,
                    fault_hook=crash,
                )
            with SessionLocal() as observer:
                durable = observer.get(SimulationTask, task_id)
                assert durable is not None
                assert durable.status == "running"
                assert durable.active_execution_token == token
            session.rollback()
        write_evidence("legacy-final-crash-rollback", task_snapshot(task_id))
    finally:
        delete_task(task_id)
