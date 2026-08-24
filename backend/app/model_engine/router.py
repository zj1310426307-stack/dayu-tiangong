"""Thin HTTP routing for Phase 3 hydraulic task orchestration."""

from os import getenv
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app.model_engine import service
from app.model_engine.schemas import (
    SimulationResultResponse,
    SimulationTaskCreate,
    SimulationTaskRecord,
    TaskSnapshotResponse,
)
from app.worker.lifecycle import request_cancel
from app.worker.tasks import run_hydraulic_task


router = APIRouter(prefix="/api/v1/model", tags=["hydraulic-model"])
SessionDependency = Annotated[Session, Depends(get_database_session)]


def _map_error(exc: Exception) -> HTTPException:
    """Map application-level task errors to stable HTTP semantics."""

    if isinstance(exc, service.TaskNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/tasks",
    response_model=SimulationTaskRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Create a pending hydraulic task",
)
def create_task(
    payload: SimulationTaskCreate, session: SessionDependency
) -> SimulationTaskRecord:
    """Create a task without starting the numerical calculation."""

    try:
        return service.create_task(session, payload)
    except (service.TaskNotFoundError, service.TaskStateError) as exc:
        raise _map_error(exc) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="task violates database constraints") from exc


@router.get("/tasks", response_model=list[SimulationTaskRecord], summary="List hydraulic tasks")
def list_tasks(
    session: SessionDependency,
    dataset_version_id: int | None = Query(default=None, gt=0),
) -> list[SimulationTaskRecord]:
    """Return newest task lifecycle records, optionally scoped by data version."""

    return service.list_tasks(session, dataset_version_id=dataset_version_id)


@router.post(
    "/tasks/{task_id}/run",
    response_model=SimulationTaskRecord,
    summary="Run a pending hydraulic task",
    deprecated=True,
)
def run_task(task_id: int, session: SessionDependency) -> SimulationTaskRecord:
    """仅为 Phase 3 回归保留；生产配置默认禁用同步等待。"""

    if getenv("ENABLE_SYNC_MODEL_RUN", "0") != "1" and getenv("RUN_POSTGIS_TESTS") != "1":
        raise HTTPException(status_code=409, detail="synchronous model execution is disabled")
    try:
        return service.run_task(session, task_id)
    except (service.TaskNotFoundError, service.TaskStateError) as exc:
        raise _map_error(exc) from exc


@router.get(
    "/tasks/{task_id}",
    response_model=SimulationTaskRecord,
    summary="Read hydraulic task status",
)
def get_task(task_id: int, session: SessionDependency) -> SimulationTaskRecord:
    """Read progress, timestamps, diagnostics and any error message."""

    task = service.get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="simulation task does not exist")
    return task


@router.get(
    "/results/{task_id}",
    response_model=SimulationResultResponse,
    summary="Read one section hydraulic result",
)
def get_result(
    task_id: int,
    session: SessionDependency,
    section_id: int | None = Query(default=None, gt=0),
) -> SimulationResultResponse:
    """Return aligned stage, discharge and velocity arrays for charting."""

    try:
        return service.get_result(session, task_id, section_id)
    except (service.TaskNotFoundError, service.TaskStateError) as exc:
        raise _map_error(exc) from exc


@router.get(
    "/tasks/{task_id}/snapshot",
    response_model=TaskSnapshotResponse,
    summary="Download the frozen task input",
)
def get_task_snapshot(task_id: int, session: SessionDependency) -> TaskSnapshotResponse:
    """返回创建时冻结的完整输入和来源信息，不重新查询业务表。"""

    task = session.get(service.SimulationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="simulation task does not exist")
    if task.input_snapshot is None or task.input_snapshot_hash is None:
        raise HTTPException(status_code=409, detail="legacy task has no frozen snapshot")
    return TaskSnapshotResponse(
        task_id=task.id,
        input_schema_version=task.input_schema_version or "unknown",
        input_snapshot_hash=task.input_snapshot_hash,
        engine_version=task.engine_version or "unknown",
        engine_commit=task.engine_commit or "unknown",
        snapshot=task.input_snapshot,
    )


@router.post(
    "/tasks/{task_id}/enqueue",
    response_model=SimulationTaskRecord,
    summary="Queue a frozen hydraulic task",
)
def enqueue_task(task_id: int, session: SessionDependency) -> SimulationTaskRecord:
    """只执行状态转换和消息投递，立即返回而不等待数值计算。"""

    task = session.get(service.SimulationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="simulation task does not exist")
    if task.status != "pending":
        raise HTTPException(status_code=409, detail="only a pending task can be queued")
    task.status = "queued"
    task.queued_time = datetime.now(UTC)
    session.commit()
    try:
        job = run_hydraulic_task.delay(task.id)
    except Exception as exc:
        task.status = "failed"
        task.progress = 100
        task.error_message = "queue broker unavailable"
        task.end_time = datetime.now(UTC)
        session.commit()
        raise HTTPException(status_code=503, detail="queue broker unavailable") from exc
    task.queue_job_id = str(job.id)
    session.commit()
    session.refresh(task)
    return service._record(task)


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=SimulationTaskRecord,
    summary="Request cooperative task cancellation",
)
def cancel_task(task_id: int, session: SessionDependency) -> SimulationTaskRecord:
    """对 queued 直接取消，对 running 设置协作式取消标志。"""

    task = session.get(service.SimulationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="simulation task does not exist")
    try:
        return service._record(request_cancel(session, task))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/tasks/{task_id}/retry",
    response_model=SimulationTaskRecord,
    summary="Retry a failed or cancelled frozen task",
)
def retry_task(task_id: int, session: SessionDependency) -> SimulationTaskRecord:
    """保留同一冻结快照，清理运行状态并重新入队。"""

    task = session.get(service.SimulationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="simulation task does not exist")
    if task.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="only failed or cancelled tasks can be retried")
    task.status = "queued"
    task.progress = 0
    task.cancel_requested = False
    task.retry_count += 1
    task.retry_reason = task.error_message
    task.error_message = None
    task.queued_time = datetime.now(UTC)
    task.start_time = None
    task.end_time = None
    session.commit()
    job = run_hydraulic_task.delay(task.id)
    task.queue_job_id = str(job.id)
    session.commit()
    session.refresh(task)
    return service._record(task)
