"""HTTP routing for the sole production Standard 1D / MASCARET task chain."""

from __future__ import annotations

from datetime import UTC, datetime
from os import getenv
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app.model_engine import service
from app.model_engine.schemas import (
    Hydraulic1DPreviewResponse,
    Hydraulic1DReadinessResponse,
    SimulationResultResponse,
    SimulationTaskCreate,
    SimulationTaskRecord,
    TaskSnapshotResponse,
)
from app.worker.lifecycle import request_cancel
from app.worker.tasks import HYDRAULIC_1D_QUEUE, run_hydraulic_task
from model.hydraulic_1d.contracts import HYDRAULIC_1D_INPUT_SCHEMA


router = APIRouter(prefix="/api/v1/model", tags=["hydraulic-model"])
SessionDependency = Annotated[Session, Depends(get_database_session)]


def _map_error(exc: Exception) -> HTTPException:
    """Map service failures to stable HTTP semantics."""

    code = 404 if isinstance(exc, service.TaskNotFoundError) else 409
    return HTTPException(status_code=code, detail=str(exc))


def _deliver(task: service.SimulationTask):
    """Publish only the registered unified schema to the dedicated worker queue."""

    if task.input_schema_version != HYDRAULIC_1D_INPUT_SCHEMA:
        raise service.TaskStateError(
            "LEGACY_ENGINE_RETIRED: historical custom-solver tasks cannot execute"
        )
    return run_hydraulic_task.apply_async(args=[task.id], queue=HYDRAULIC_1D_QUEUE)


@router.get(
    "/readiness",
    response_model=Hydraulic1DReadinessResponse,
    summary="Check Standard 1D mapping and MASCARET runtime readiness",
)
def readiness(
    session: SessionDependency,
    case_id: int = Query(gt=0),
) -> Hydraulic1DReadinessResponse:
    """Run fail-closed mapping validation without creating a task."""

    return service.assess_readiness(session, case_id)


@router.post(
    "/preview",
    response_model=Hydraulic1DPreviewResponse,
    summary="Preview the unified Standard 1D input",
)
def preview(
    payload: SimulationTaskCreate,
    session: SessionDependency,
) -> Hydraulic1DPreviewResponse:
    """Return the frozen-model candidate without a task or runtime workspace."""

    return service.preview_model(session, payload)


@router.post(
    "/tasks",
    response_model=SimulationTaskRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Create a pending Standard 1D task",
)
def create_task(
    payload: SimulationTaskCreate,
    session: SessionDependency,
) -> SimulationTaskRecord:
    """Freeze a validated solver-neutral model without starting MASCARET."""

    try:
        return service.create_task(session, payload)
    except (service.TaskNotFoundError, service.TaskStateError) as exc:
        raise _map_error(exc) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="task violates database constraints") from exc


@router.get(
    "/tasks",
    response_model=list[SimulationTaskRecord],
    summary="List hydraulic tasks",
)
def list_tasks(
    session: SessionDependency,
    dataset_version_id: int | None = Query(default=None, gt=0),
) -> list[SimulationTaskRecord]:
    """Return newest lifecycle records, optionally scoped by Dataset Version."""

    return service.list_tasks(session, dataset_version_id=dataset_version_id)


@router.get(
    "/tasks/{task_id}",
    response_model=SimulationTaskRecord,
    summary="Read hydraulic task status",
)
def get_task(task_id: int, session: SessionDependency) -> SimulationTaskRecord:
    """Read lifecycle, external-engine identity, and diagnostics."""

    task = service.get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="simulation task does not exist")
    return task


@router.get(
    "/tasks/{task_id}/snapshot",
    response_model=TaskSnapshotResponse,
    summary="Read the immutable unified task input",
)
def get_task_snapshot(task_id: int, session: SessionDependency) -> TaskSnapshotResponse:
    """Return the exact input and build identity used by the worker."""

    task = session.get(service.SimulationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="simulation task does not exist")
    if (
        task.input_schema_version != HYDRAULIC_1D_INPUT_SCHEMA
        or task.input_snapshot is None
        or task.input_snapshot_hash is None
    ):
        raise HTTPException(status_code=409, detail="LEGACY_ENGINE_RETIRED")
    try:
        service.parse_frozen_task_model(task)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TaskSnapshotResponse(
        task_id=task.id,
        input_schema_version=task.input_schema_version,
        input_snapshot_hash=task.input_snapshot_hash,
        engine_version=task.engine_version or "unknown",
        engine_commit=task.engine_commit or "unknown",
        solver_build_id=task.solver_build_id,
        build_mode=task.build_mode,
        build_verified=task.build_verified,
        snapshot=task.input_snapshot,
    )


@router.post(
    "/tasks/{task_id}/run",
    response_model=SimulationTaskRecord,
    summary="Run a pending hydraulic task synchronously",
    deprecated=True,
)
def run_task(task_id: int, session: SessionDependency) -> SimulationTaskRecord:
    """Permit synchronous execution only in explicitly enabled diagnostic environments."""

    if getenv("ENABLE_SYNC_MODEL_RUN", "0") != "1" and getenv("RUN_POSTGIS_TESTS") != "1":
        raise HTTPException(status_code=409, detail="synchronous model execution is disabled")
    try:
        return service.run_task(session, task_id)
    except (service.TaskNotFoundError, service.TaskStateError) as exc:
        raise _map_error(exc) from exc


@router.post(
    "/tasks/{task_id}/enqueue",
    response_model=SimulationTaskRecord,
    summary="Queue a frozen Standard 1D task",
)
def enqueue_task(task_id: int, session: SessionDependency) -> SimulationTaskRecord:
    """Transition pending to queued and publish one dedicated worker message."""

    task = session.get(service.SimulationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="simulation task does not exist")
    if task.input_schema_version != HYDRAULIC_1D_INPUT_SCHEMA:
        raise HTTPException(status_code=409, detail="LEGACY_ENGINE_RETIRED")
    if task.status != "pending":
        raise HTTPException(status_code=409, detail="only a pending task can be queued")
    task.status = "queued"
    task.queued_time = datetime.now(UTC)
    task.delivery_attempt_count += 1
    task.last_delivery_time = task.queued_time
    session.commit()
    try:
        job = _deliver(task)
    except service.TaskStateError as exc:
        raise _map_error(exc) from exc
    except Exception as exc:
        task.queue_job_id = None
        task.last_infrastructure_error = "queue broker unavailable; recovery pending"
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
    """Cancel queued work or signal the active external process to terminate."""

    task = session.get(service.SimulationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="simulation task does not exist")
    try:
        return service._record(request_cancel(session, task))
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/tasks/{task_id}/retry",
    response_model=SimulationTaskRecord,
    summary="Retry a failed or cancelled frozen task",
)
def retry_task(task_id: int, session: SessionDependency) -> SimulationTaskRecord:
    """Preserve the immutable snapshot and publish a fresh execution attempt."""

    task = session.get(service.SimulationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="simulation task does not exist")
    try:
        task = service.reset_task_for_manual_retry(session, task)
    except service.TaskStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    task.delivery_attempt_count += 1
    task.last_delivery_time = datetime.now(UTC)
    session.commit()
    try:
        job = _deliver(task)
    except Exception as exc:
        task.queue_job_id = None
        task.last_infrastructure_error = "queue broker unavailable; recovery pending"
        session.commit()
        raise HTTPException(status_code=503, detail="queue broker unavailable") from exc
    task.queue_job_id = str(job.id)
    session.commit()
    session.refresh(task)
    return service._record(task)


@router.get(
    "/results/{task_id}",
    response_model=SimulationResultResponse,
    summary="Read one Cross Section Standard 1D result",
)
def get_result(
    task_id: int,
    session: SessionDependency,
    section_id: int | None = Query(default=None, gt=0),
) -> SimulationResultResponse:
    """Return aligned H/depth/Q/V/area series and available sections."""

    try:
        return service.get_result(session, task_id, section_id)
    except (service.TaskNotFoundError, service.TaskStateError) as exc:
        raise _map_error(exc) from exc
