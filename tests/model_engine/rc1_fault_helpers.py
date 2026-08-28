"""Shared real-PostGIS helpers for the D2 RC1 fault-recovery suite."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from os import getenv
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from app.database.session import SessionLocal
from app.gis.models import DatasetVersion, SimulationTask
from app.model_engine.schemas import SimulationTaskCreate
from app.model_engine.service import create_task
from app.worker.lifecycle import claim_v4_task, heartbeat
from app.worker.tasks import validate_v4_worker_task
from model import HydraulicEngine
from model.solver.registry import D1_SOLVER_ID
from tests.model_engine.test_v4_postgis_worker_integration import (
    CASE_ID,
    DATASET_ID,
    PLAN_ID,
    _seed_authoritative_case,
)


_SOLVED: tuple[Any, Any] | None = None


def ensure_authoritative_case() -> int:
    with SessionLocal() as session:
        if session.get(DatasetVersion, DATASET_ID) is not None:
            return PLAN_ID
    return _seed_authoritative_case()


def create_claimed_v4_task(worker_id: str) -> tuple[int, str, Any]:
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
        claimed = claim_v4_task(session, task.id, worker_id)
        token = str(claimed.active_execution_token)
        projection = validate_v4_worker_task(claimed)
        return task.id, token, projection


def solved_engine_result() -> Any:
    global _SOLVED
    if _SOLVED is None:
        task_id, _token, projection = create_claimed_v4_task("rc1-solve-cache")
        result = HydraulicEngine().run(projection.runtime_snapshot)
        _SOLVED = (projection, result)
        delete_task(task_id)
    return _SOLVED[1]


def phase_callback(task_id: int, token: str) -> Callable[[str], None]:
    progress = {
        "serializing": 87,
        "persisting": 91,
        "publishing_artifact": 96,
        "finalizing": 99,
    }

    def update_phase(value: str) -> None:
        with SessionLocal() as session:
            heartbeat(
                session,
                task_id,
                execution_token=token,
                progress=progress[value],
                execution_phase=value,
            )

    return update_phase


def write_evidence(name: str, payload: dict[str, Any]) -> None:
    configured = getenv("D2_FAULT_EVIDENCE_DIR", "").strip()
    if not configured:
        return
    root = Path(configured)
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def delete_task(task_id: int) -> None:
    with SessionLocal() as session:
        task = session.get(SimulationTask, task_id)
        if task is not None:
            session.delete(task)
            session.commit()


def task_snapshot(task_id: int) -> dict[str, Any]:
    with SessionLocal() as session:
        task = session.scalar(select(SimulationTask).where(SimulationTask.id == task_id))
        assert task is not None
        return {
            "id": task.id,
            "status": task.status,
            "progress": task.progress,
            "artifact_status": task.artifact_status,
            "execution_phase": task.execution_phase,
            "execution_attempt_count": task.execution_attempt_count,
            "manual_retry_count": task.manual_retry_count,
            "infrastructure_retry_count": task.infrastructure_retry_count,
            "numerical_retry_count": task.numerical_retry_count,
            "queue_job_id": task.queue_job_id,
            "active_execution_token": task.active_execution_token,
            "last_execution_token": task.last_execution_token,
            "current_simulation_time": task.current_simulation_time,
            "current_cfl": task.current_cfl,
            "error_message": task.error_message,
            "last_infrastructure_error": task.last_infrastructure_error,
        }
