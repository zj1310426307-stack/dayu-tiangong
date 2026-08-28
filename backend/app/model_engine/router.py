"""Thin HTTP routing for Phase 3 hydraulic task orchestration."""

from os import getenv
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app.model_engine import service
from app.model_engine import v4_result
from app.model_engine import shadow
from app.gis.models import (
    HydraulicTaskControlEvent,
    HydraulicTaskGateResult,
    HydraulicTaskPumpResult,
)
from app.model_engine.schemas import (
    SimulationResultResponse,
    SimulationTaskCreate,
    SimulationTaskRecord,
    TaskSnapshotResponse,
)
from app.model_engine.v4_schemas import (
    V4ArtifactManifest,
    V4ControlEventRecord,
    V4GateResultRecord,
    V4PumpResultRecord,
    V4ResultSummary,
    V4SectionOption,
    V4SectionResultResponse,
    V4ShadowComparison,
    V4ShadowCreate,
    V4ShadowPair,
)
from app.worker.lifecycle import request_cancel
from app.worker.tasks import V4_QUEUE, run_hydraulic_task, run_hydraulic_v4_task


router = APIRouter(prefix="/api/v1/model", tags=["hydraulic-model"])
SessionDependency = Annotated[Session, Depends(get_database_session)]


def _map_error(exc: Exception) -> HTTPException:
    """Map application-level task errors to stable HTTP semantics."""

    if isinstance(exc, service.TaskNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _deliver(task: service.SimulationTask):
    """Route native v4 exclusively to its capability-specific Celery queue."""

    if task.input_schema_version == "dayu.model-input.v4":
        return run_hydraulic_v4_task.apply_async(args=[task.id], queue=V4_QUEUE)
    return run_hydraulic_task.delay(task.id)


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


def _map_v4_read_error(exc: Exception) -> HTTPException:
    """Map v4 result lookup and lifecycle failures without changing legacy routes."""

    code = 404 if isinstance(exc, LookupError) else 409
    return HTTPException(status_code=code, detail=str(exc))


@router.get(
    "/v4/tasks/{task_id}/sections",
    response_model=list[V4SectionOption],
    summary="List native-v4 authoritative Section results",
)
def list_v4_sections(task_id: int, session: SessionDependency) -> list[V4SectionOption]:
    try:
        return v4_result.list_v4_section_options(session, task_id)
    except (LookupError, ValueError) as exc:
        raise _map_v4_read_error(exc) from exc


@router.get(
    "/v4/tasks/{task_id}/sections/{section_id}",
    response_model=V4SectionResultResponse,
    summary="Read one native-v4 Section H/Q/V series",
)
def get_v4_section(
    task_id: int, section_id: int, session: SessionDependency
) -> V4SectionResultResponse:
    try:
        return v4_result.read_v4_section_result(session, task_id, section_id)
    except (LookupError, ValueError) as exc:
        raise _map_v4_read_error(exc) from exc


@router.get(
    "/v4/tasks/{task_id}/gates",
    response_model=list[V4GateResultRecord],
    summary="Read restricted D1 completed-interface Gate results",
)
def get_v4_gates(task_id: int, session: SessionDependency) -> list[V4GateResultRecord]:
    try:
        v4_result.require_successful_v4_task(session, task_id)
    except (LookupError, ValueError) as exc:
        raise _map_v4_read_error(exc) from exc
    rows = session.scalars(
        select(HydraulicTaskGateResult)
        .where(HydraulicTaskGateResult.task_id == task_id)
        .order_by(HydraulicTaskGateResult.time_seconds)
    ).all()
    return [V4GateResultRecord.model_validate(row) for row in rows]


@router.get(
    "/v4/tasks/{task_id}/pumps",
    response_model=list[V4PumpResultRecord],
    summary="Read restricted D1 external Q-H Pump results",
)
def get_v4_pumps(task_id: int, session: SessionDependency) -> list[V4PumpResultRecord]:
    try:
        v4_result.require_successful_v4_task(session, task_id)
    except (LookupError, ValueError) as exc:
        raise _map_v4_read_error(exc) from exc
    rows = session.scalars(
        select(HydraulicTaskPumpResult)
        .where(HydraulicTaskPumpResult.task_id == task_id)
        .order_by(HydraulicTaskPumpResult.time_seconds)
    ).all()
    return [V4PumpResultRecord.model_validate(row) for row in rows]


@router.get(
    "/v4/tasks/{task_id}/events",
    response_model=list[V4ControlEventRecord],
    summary="Read accepted native-v4 Gate/Pump events",
)
def get_v4_events(task_id: int, session: SessionDependency) -> list[V4ControlEventRecord]:
    try:
        v4_result.require_successful_v4_task(session, task_id)
    except (LookupError, ValueError) as exc:
        raise _map_v4_read_error(exc) from exc
    rows = session.scalars(
        select(HydraulicTaskControlEvent)
        .where(HydraulicTaskControlEvent.task_id == task_id)
        .order_by(HydraulicTaskControlEvent.time_seconds)
    ).all()
    return [V4ControlEventRecord.model_validate(row) for row in rows]


@router.get(
    "/v4/tasks/{task_id}/summary",
    response_model=V4ResultSummary,
    summary="Read native-v4 result-v3 provenance and quality summary",
)
def get_v4_summary(task_id: int, session: SessionDependency) -> V4ResultSummary:
    try:
        return v4_result.v4_result_summary(session, task_id)
    except (LookupError, ValueError) as exc:
        raise _map_v4_read_error(exc) from exc


@router.get(
    "/v4/tasks/{task_id}/artifacts",
    response_model=list[V4ArtifactManifest],
    summary="List published native-v4 stage-evidence artifacts",
)
def get_v4_artifacts(task_id: int, session: SessionDependency) -> list[V4ArtifactManifest]:
    try:
        return v4_result.list_v4_artifacts(session, task_id)
    except (LookupError, ValueError) as exc:
        raise _map_v4_read_error(exc) from exc


@router.get(
    "/v4/tasks/{task_id}/artifacts/{artifact_id}/download",
    response_class=FileResponse,
    summary="Download verified native-v4 stage evidence (internal deployment only)",
    description=(
        "Restricted D1 validation artifact download. This endpoint inherits the "
        "current internal-deployment boundary and is not public-production IAM."
    ),
)
def download_v4_artifact(
    task_id: int, artifact_id: int, session: SessionDependency
) -> FileResponse:
    try:
        artifact, path = v4_result.resolve_v4_artifact_download(
            session, task_id, artifact_id
        )
    except (LookupError, ValueError) as exc:
        raise _map_v4_read_error(exc) from exc
    return FileResponse(
        path,
        media_type=artifact.media_type,
        filename=f"task-{task_id}-{artifact.artifact_type}.jsonl.gz",
    )


@router.post(
    "/v4/shadow-pairs",
    response_model=V4ShadowPair,
    status_code=status.HTTP_201_CREATED,
    summary="Create independent legacy-v3/native-v4 diagnostic tasks",
)
def create_v4_shadow_pair(
    payload: V4ShadowCreate, session: SessionDependency
) -> V4ShadowPair:
    """Freeze both tasks only after both builders report ready; neither is truth."""

    try:
        return shadow.create_shadow_pair(session, payload)
    except (LookupError, ValueError, service.TaskStateError) as exc:
        raise _map_v4_read_error(exc) from exc


@router.get(
    "/v4/shadow-pairs/{group_id}",
    response_model=V4ShadowComparison,
    summary="Compare common v3/v4 Section output coordinates diagnostically",
)
def get_v4_shadow_pair(
    group_id: int, session: SessionDependency
) -> V4ShadowComparison:
    try:
        return shadow.compare_shadow_pair(session, group_id)
    except (LookupError, ValueError) as exc:
        raise _map_v4_read_error(exc) from exc


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
        job = _deliver(task)
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
    try:
        task = service.reset_task_for_manual_retry(session, task)
    except service.TaskStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        job = _deliver(task)
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
