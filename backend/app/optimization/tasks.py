"""Fail-closed worker tombstone for pre-MASCARET optimization messages."""

from __future__ import annotations

from datetime import UTC, datetime

from app.database.session import SessionLocal
from app.gis.models import OptimizationTask
from app.worker.celery_app import celery_app


@celery_app.task(name="dayu.run_optimization_task")
def run_optimization_task(task_id: int) -> dict[str, str | int]:
    """Terminate historical messages without invoking any retired numerical code."""

    with SessionLocal() as session:
        task = session.get(OptimizationTask, task_id)
        if task is None:
            return {"task_id": task_id, "status": "missing"}
        if task.status in {"success", "failed", "cancelled"}:
            return {"task_id": task_id, "status": "duplicate"}
        task.status = "failed"
        task.progress = 100
        task.error_message = (
            "LEGACY_ENGINE_RETIRED: optimization execution is disabled until "
            "the MASCARET adapter supports its control semantics"
        )
        task.end_time = datetime.now(UTC)
        session.commit()
        return {"task_id": task_id, "status": "failed"}


__all__ = ["run_optimization_task"]
