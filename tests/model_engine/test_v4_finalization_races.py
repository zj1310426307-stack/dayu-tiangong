"""Cancellation races at every native-v4 result/artifact fault boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from os import getenv
from queue import Queue
from threading import Event, Thread

import pytest
from sqlalchemy import update

from app.database.session import SessionLocal
from app.gis.models import HydraulicTaskArtifact, SimulationTask
from app.model_engine.v4_reconciliation import reconcile_v4_task
from app.model_engine.v4_result import persist_v4_result, require_successful_v4_task
from app.model_engine.service import can_retry_task, reset_task_for_manual_retry
from app.worker.lifecycle import (
    StaleExecutionError,
    cancellation_requested,
    claim_v4_task,
    recover_stale_tasks,
    request_cancel,
    transition_attempt_terminal,
)
from model.core.errors import HydraulicCancelledError
from tests.model_engine.rc1_fault_helpers import (
    create_claimed_v4_task,
    delete_task,
    phase_callback,
    solved_engine_result,
    task_snapshot,
    write_evidence,
)


pytestmark = pytest.mark.skipif(
    getenv("RUN_D2_FAULT_INTEGRATION") != "1",
    reason="requires migrated PostGIS and a bounded DAYU_STORAGE_ROOT",
)


FAULT_POINTS = (
    "after_artifact_temp_ready",
    "after_db_prepared_commit",
    "after_atomic_rename",
    "before_final_cas",
)


@pytest.mark.parametrize("fault_point", FAULT_POINTS)
def test_accepted_cancel_never_becomes_success(fault_point: str) -> None:
    task_id, token, projection = create_claimed_v4_task(f"cancel-{fault_point}")
    cancellation_accepted = False

    def fault_hook(actual: str) -> None:
        nonlocal cancellation_accepted
        if actual != fault_point:
            return
        with SessionLocal() as cancelling:
            task = cancelling.get(SimulationTask, task_id)
            assert task is not None
            cancelled = request_cancel(cancelling, task)
            cancellation_accepted = cancelled.status in {
                "cancel_requested",
                "cancelled",
            }

    try:
        with SessionLocal() as session:
            task = session.get(SimulationTask, task_id)
            assert task is not None

            def cancelled() -> bool:
                return cancellation_requested(
                    session,
                    task_id,
                    execution_token=token,
                )

            with pytest.raises((HydraulicCancelledError, StaleExecutionError)):
                persist_v4_result(
                    session,
                    task,
                    solved_engine_result(),
                    projection,
                    execution_token=token,
                    cancel_check=cancelled,
                    phase_callback=phase_callback(task_id, token),
                    fault_hook=fault_hook,
                )
            session.rollback()
        assert cancellation_accepted is True
        assert task_snapshot(task_id)["status"] == "cancel_requested"

        with SessionLocal() as session:
            assert transition_attempt_terminal(
                session,
                task_id,
                execution_token=token,
                status="cancelled",
                message=f"accepted cancellation at {fault_point}",
                artifact_status="reconciliation_required",
                commit=False,
            )
            session.execute(
                update(HydraulicTaskArtifact)
                .where(
                    HydraulicTaskArtifact.task_id == task_id,
                    HydraulicTaskArtifact.status != "published",
                )
                .values(status="reconciliation_required")
            )
            session.commit()
            with pytest.raises(ValueError, match="result/artifact publication"):
                require_successful_v4_task(session, task_id)

        with SessionLocal() as session:
            report = reconcile_v4_task(session, task_id, apply=True)
        final = task_snapshot(task_id)
        assert final["status"] == "cancelled"
        assert final["status"] != "success"
        assert final["artifact_status"] in {"none", "failed"}
        write_evidence(
            f"finalization-cancel-{fault_point}",
            {"fault_point": fault_point, "reconciliation": report, "task": final},
        )
    finally:
        delete_task(task_id)


def test_stale_recovery_wins_attempt_stage_race_without_touching_new_attempt() -> None:
    """An expired worker can neither publish canonical bytes nor race its successor."""

    task_id, old_token, projection = create_claimed_v4_task("stale-rename-old")
    engine_result = solved_engine_result()
    attempt_staged = Event()
    release_old_worker = Event()
    failures: Queue[BaseException] = Queue()

    def pause_after_attempt_rename(point: str) -> None:
        if point != "after_atomic_rename":
            return
        attempt_staged.set()
        if not release_old_worker.wait(timeout=20):
            raise TimeoutError("test did not release stale native-v4 worker")

    def old_worker() -> None:
        try:
            with SessionLocal() as session:
                task = session.get(SimulationTask, task_id)
                assert task is not None
                persist_v4_result(
                    session,
                    task,
                    engine_result,
                    projection,
                    execution_token=old_token,
                    phase_callback=phase_callback(task_id, old_token),
                    fault_hook=pause_after_attempt_rename,
                )
        except BaseException as exc:  # captured for deterministic thread assertions
            failures.put(exc)

    worker = Thread(target=old_worker, name="stale-v4-publisher", daemon=True)
    worker.start()
    try:
        if not attempt_staged.wait(timeout=20):
            worker.join(timeout=1)
            if not failures.empty():
                raise failures.get_nowait()
            pytest.fail("old worker did not reach attempt staging barrier")
        with SessionLocal() as session:
            task = session.get(SimulationTask, task_id)
            assert task is not None
            task.heartbeat_time = datetime.now(UTC) - timedelta(minutes=10)
            session.commit()
            recovered = recover_stale_tasks(session, stale_seconds=120)
            assert task_id in recovered
            session.expire_all()
            stale = session.get(SimulationTask, task_id)
            assert stale is not None
            assert stale.artifact_status == "reconciliation_required"
            assert not can_retry_task(stale)

        with SessionLocal() as session:
            dry_run = reconcile_v4_task(session, task_id)
            assert dry_run["outcome"] == "staged_attempt_requires_quarantine"
            task = session.get(SimulationTask, task_id)
            assert task is not None
            assert not can_retry_task(task)
        with SessionLocal() as session:
            reconciled = reconcile_v4_task(session, task_id, apply=True)
            assert reconciled["quarantined_files"]
            task = session.get(SimulationTask, task_id)
            assert task is not None
            assert can_retry_task(task)
            queued = reset_task_for_manual_retry(session, task)
            claimed = claim_v4_task(session, queued.id, "stale-rename-new")
            new_token = str(claimed.active_execution_token)
            assert new_token != old_token

        # Let the expired worker resume only after the successor owns the lease.
        # Its next phase heartbeat must fail before any canonical-path mutation.
        release_old_worker.set()
        worker.join(timeout=20)
        assert not worker.is_alive()
        old_failure = failures.get_nowait()
        assert isinstance(old_failure, StaleExecutionError)
        current = task_snapshot(task_id)
        assert current["status"] == "running"
        assert current["active_execution_token"] == new_token
        assert current["artifact_status"] == "none"

        with SessionLocal() as session:
            task = session.get(SimulationTask, task_id)
            assert task is not None
            persist_v4_result(
                session,
                task,
                engine_result,
                projection,
                execution_token=new_token,
                phase_callback=phase_callback(task_id, new_token),
            )
            assert require_successful_v4_task(session, task_id).status == "success"
        final = task_snapshot(task_id)
        assert final["last_execution_token"] == new_token
        assert final["artifact_status"] == "published"
        write_evidence(
            "finalization-stale-rename-race",
            {
                "reconciliation": reconciled,
                "old_failure": type(old_failure).__name__,
                "task": final,
            },
        )
    finally:
        release_old_worker.set()
        worker.join(timeout=20)
        delete_task(task_id)
