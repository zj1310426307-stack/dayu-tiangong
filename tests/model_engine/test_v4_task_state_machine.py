"""Database-owned v4 retry, heartbeat, cancellation, and stale recovery states."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from os import getenv

import pytest

from app.database.session import SessionLocal
from app.gis.models import SimulationTask
from app.worker.lifecycle import (
    claim_v4_task,
    handle_infrastructure_failure,
    heartbeat,
    recover_stale_tasks,
    request_cancel,
)
from tests.model_engine.rc1_fault_helpers import (
    create_claimed_v4_task,
    delete_task,
    task_snapshot,
    write_evidence,
)


pytestmark = pytest.mark.skipif(
    getenv("RUN_D2_FAULT_INTEGRATION") != "1",
    reason="requires migrated PostGIS",
)


def test_clean_infrastructure_failure_requeues_one_new_attempt() -> None:
    task_id, first_token, _projection = create_claimed_v4_task("infra-worker-1")
    try:
        with SessionLocal() as session:
            heartbeat(
                session,
                task_id,
                execution_token=first_token,
                progress=40,
                simulation_time=120.0,
                cfl=0.42,
                numerical_retry_count=3,
                execution_phase="solving",
            )
            assert handle_infrastructure_failure(
                session,
                task_id,
                execution_token=first_token,
                message="ConnectionError: transient broker/database path",
            ) == "requeued"
        requeued = task_snapshot(task_id)
        assert requeued["status"] == "queued"
        assert requeued["infrastructure_retry_count"] == 1
        assert requeued["execution_attempt_count"] == 1
        assert requeued["numerical_retry_count"] == 0
        assert requeued["current_simulation_time"] is None
        assert requeued["current_cfl"] is None
        assert requeued["active_execution_token"] is None
        assert requeued["last_execution_token"] == first_token

        with SessionLocal() as session:
            claimed = claim_v4_task(session, task_id, "infra-worker-2")
            second_token = str(claimed.active_execution_token)
        assert second_token != first_token
        second = task_snapshot(task_id)
        assert second["execution_attempt_count"] == 2
        assert second["infrastructure_retry_count"] == 1
        write_evidence("task-state-infrastructure-retry", second)
    finally:
        delete_task(task_id)


def test_phase_heartbeat_preserves_last_accepted_hydraulic_telemetry() -> None:
    task_id, token, _projection = create_claimed_v4_task("phase-heartbeat-worker")
    try:
        with SessionLocal() as session:
            heartbeat(
                session,
                task_id,
                execution_token=token,
                progress=73,
                simulation_time=840.0,
                cfl=0.37,
                execution_phase="solving",
            )
            heartbeat(
                session,
                task_id,
                execution_token=token,
                progress=87,
                execution_phase="serializing",
            )
            heartbeat(
                session,
                task_id,
                execution_token=token,
                progress=91,
                execution_phase="persisting",
            )
        current = task_snapshot(task_id)
        assert current["status"] == "running"
        assert current["current_simulation_time"] == pytest.approx(840.0)
        assert current["current_cfl"] == pytest.approx(0.37)
        write_evidence("task-state-phase-heartbeat", current)
    finally:
        delete_task(task_id)


def test_stale_solving_attempt_requeues_and_resets_attempt_telemetry() -> None:
    task_id, token, _projection = create_claimed_v4_task("stale-worker")
    try:
        with SessionLocal() as session:
            heartbeat(
                session,
                task_id,
                execution_token=token,
                progress=73,
                simulation_time=840.0,
                cfl=0.37,
                execution_phase="solving",
            )
            task = session.get(SimulationTask, task_id)
            assert task is not None
            task.heartbeat_time = datetime.now(UTC) - timedelta(minutes=10)
            session.commit()
            assert task_id in recover_stale_tasks(session, stale_seconds=120)
        stale = task_snapshot(task_id)
        assert stale["status"] == "queued"
        assert stale["infrastructure_retry_count"] == 1
        assert stale["current_simulation_time"] is None
        assert stale["current_cfl"] is None
        assert stale["active_execution_token"] is None
        assert stale["last_execution_token"] == token
        write_evidence("task-state-stale-recovery", stale)
    finally:
        delete_task(task_id)


def test_stale_cancel_request_finishes_cancelled_not_failed() -> None:
    task_id, _token, _projection = create_claimed_v4_task("cancel-worker")
    try:
        with SessionLocal() as session:
            task = session.get(SimulationTask, task_id)
            assert task is not None
            request_cancel(session, task)
            task = session.get(SimulationTask, task_id)
            assert task is not None
            task.heartbeat_time = datetime.now(UTC) - timedelta(minutes=10)
            session.commit()
            assert task_id in recover_stale_tasks(session, stale_seconds=120)
        cancelled = task_snapshot(task_id)
        assert cancelled["status"] == "cancelled"
        assert cancelled["active_execution_token"] is None
        write_evidence("task-state-stale-cancel", cancelled)
    finally:
        delete_task(task_id)
