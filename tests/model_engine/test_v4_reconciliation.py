"""Deterministic reconciliation cases for the local native-v4 Artifact backend."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from os import getenv

import pytest

from app.database.session import SessionLocal
from app.files import configured_storage_root, resolve_within
from app.gis.models import SimulationTask
from app.model_engine.v4_reconciliation import (
    expected_v4_artifact_storage_key,
    reconcile_v4_task,
)
from app.model_engine.v4_result import persist_v4_result, require_successful_v4_task
from app.worker.lifecycle import recover_stale_tasks, transition_attempt_terminal
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


class InjectedCrash(RuntimeError):
    pass


def _crash_at(point: str):
    def hook(actual: str) -> None:
        if actual == point:
            raise InjectedCrash(point)

    return hook


def _persist_until_crash(point: str) -> tuple[int, str]:
    task_id, token, projection = create_claimed_v4_task(f"reconcile-{point}")
    with SessionLocal() as session:
        task = session.get(SimulationTask, task_id)
        assert task is not None
        with pytest.raises(InjectedCrash, match=point):
            persist_v4_result(
                session,
                task,
                solved_engine_result(),
                projection,
                execution_token=token,
                phase_callback=phase_callback(task_id, token),
                fault_hook=_crash_at(point),
            )
        session.rollback()
    return task_id, token


def _stale_recover(task_id: int) -> None:
    with SessionLocal() as session:
        task = session.get(SimulationTask, task_id)
        assert task is not None
        task.heartbeat_time = datetime.now(UTC) - timedelta(minutes=10)
        session.commit()
        assert task_id in recover_stale_tasks(session, stale_seconds=120)


def _target(task_id: int):
    return resolve_within(
        configured_storage_root(), expected_v4_artifact_storage_key(task_id)
    )


def test_prepared_metadata_without_final_file_becomes_clean_failed_artifact() -> None:
    task_id, _token = _persist_until_crash("after_db_prepared_commit")
    try:
        _stale_recover(task_id)
        with SessionLocal() as session:
            before = task_snapshot(task_id)
            dry_run = reconcile_v4_task(session, task_id)
            assert dry_run["outcome"] == "prepared_artifact_missing"
            assert task_snapshot(task_id) == before
        with SessionLocal() as session:
            applied = reconcile_v4_task(session, task_id, apply=True)
        assert applied["outcome"] == "prepared_artifact_missing"
        assert task_snapshot(task_id)["artifact_status"] == "failed"
        write_evidence("reconciliation-prepared-file-missing", applied)
    finally:
        delete_task(task_id)


def test_no_metadata_and_no_file_is_clean_and_dry_run_is_read_only() -> None:
    task_id, token, _projection = create_claimed_v4_task("reconcile-clean")
    try:
        with SessionLocal() as session:
            assert transition_attempt_terminal(
                session,
                task_id,
                execution_token=token,
                status="failed",
                message="clean pre-artifact failure",
                artifact_status="none",
            )
        before = task_snapshot(task_id)
        with SessionLocal() as session:
            report = reconcile_v4_task(session, task_id)
        assert report["outcome"] == "clean_no_artifact"
        assert task_snapshot(task_id) == before
        write_evidence("reconciliation-clean-no-artifact", report)
    finally:
        delete_task(task_id)


def test_final_file_with_correct_hash_completes_prepared_publication() -> None:
    task_id, _token = _persist_until_crash("after_final_publish_rename")
    try:
        _stale_recover(task_id)
        with SessionLocal() as session:
            dry_run = reconcile_v4_task(session, task_id)
        assert dry_run["outcome"] == "publishable_prepared_artifact"
        assert task_snapshot(task_id)["status"] == "failed"
        with SessionLocal() as session:
            applied = reconcile_v4_task(session, task_id, apply=True)
            assert require_successful_v4_task(session, task_id).status == "success"
        assert applied["outcome"] == "publishable_prepared_artifact"
        final = task_snapshot(task_id)
        assert final["status"] == "success"
        assert final["artifact_status"] == "published"
        write_evidence("reconciliation-complete-publication", applied)
    finally:
        delete_task(task_id)


def test_hash_mismatch_is_quarantined_and_never_promoted() -> None:
    task_id, _token = _persist_until_crash("after_final_publish_rename")
    try:
        _target(task_id).write_bytes(b"corrupt-stage-evidence")
        _stale_recover(task_id)
        with SessionLocal() as session:
            applied = reconcile_v4_task(session, task_id, apply=True)
        assert applied["outcome"] == "artifact_integrity_mismatch"
        assert applied["quarantined_files"]
        final = task_snapshot(task_id)
        assert final["status"] == "failed"
        assert final["artifact_status"] == "failed"
        assert not _target(task_id).exists()
        write_evidence("reconciliation-hash-mismatch", applied)
    finally:
        delete_task(task_id)


def test_success_with_missing_published_file_becomes_integrity_incident() -> None:
    task_id, token, projection = create_claimed_v4_task("reconcile-case-e")
    try:
        with SessionLocal() as session:
            task = session.get(SimulationTask, task_id)
            assert task is not None
            persist_v4_result(
                session,
                task,
                solved_engine_result(),
                projection,
                execution_token=token,
                phase_callback=phase_callback(task_id, token),
            )
        _target(task_id).unlink()
        with SessionLocal() as session:
            dry_run = reconcile_v4_task(session, task_id)
            assert dry_run["outcome"] == "published_artifact_missing"
            assert require_successful_v4_task(session, task_id).status == "success"
        with SessionLocal() as session:
            applied = reconcile_v4_task(session, task_id, apply=True)
            with pytest.raises(ValueError, match="result/artifact publication"):
                require_successful_v4_task(session, task_id)
        assert applied["outcome"] == "published_artifact_missing"
        assert task_snapshot(task_id)["artifact_status"] == "failed"
        write_evidence("reconciliation-published-file-missing", applied)
    finally:
        delete_task(task_id)


def test_orphan_final_file_without_metadata_is_quarantined() -> None:
    task_id, token, _projection = create_claimed_v4_task("reconcile-orphan")
    try:
        with SessionLocal() as session:
            assert transition_attempt_terminal(
                session,
                task_id,
                execution_token=token,
                status="failed",
                message="pre-artifact failure",
                artifact_status="none",
            )
        target = _target(task_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"orphan")
        with SessionLocal() as session:
            applied = reconcile_v4_task(session, task_id, apply=True)
        assert applied["outcome"] == "orphan_final_file"
        assert applied["quarantined_files"]
        assert not target.exists()
        assert task_snapshot(task_id)["artifact_status"] == "none"
        write_evidence("reconciliation-orphan-final", applied)
    finally:
        delete_task(task_id)
