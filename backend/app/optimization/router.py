"""Thin Phase 5 HTTP routing for optimization lifecycle and evidence queries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app.optimization import service
from app.optimization.schemas import (
    OptimizationCandidateRecord,
    OptimizationExplanation,
    OptimizationTaskCreate,
    OptimizationTaskRecord,
    ParetoCandidateRecord,
    RecommendationResponse,
)
from app.optimization.tasks import run_optimization_task


router = APIRouter(prefix="/api/v1/optimization", tags=["optimization"])
SessionDependency = Annotated[Session, Depends(get_database_session)]


def _http_error(exc: Exception) -> HTTPException:
    """Map service exceptions to stable HTTP status codes."""

    if isinstance(exc, service.OptimizationNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


@router.post(
    "/tasks",
    response_model=OptimizationTaskRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Create a reproducible optimization task",
)
def create_task(
    payload: OptimizationTaskCreate, session: SessionDependency
) -> OptimizationTaskRecord:
    """Create and freeze a pending PSO task without starting calculation."""

    try:
        return service.create_task(session, payload)
    except (service.OptimizationNotFoundError, service.OptimizationStateError) as exc:
        raise _http_error(exc) from exc


@router.get("/tasks", response_model=list[OptimizationTaskRecord])
def list_tasks(session: SessionDependency) -> list[OptimizationTaskRecord]:
    """List optimization tasks for the monitor page."""

    return service.list_tasks(session)


@router.get("/tasks/{task_id}", response_model=OptimizationTaskRecord)
def get_task(task_id: int, session: SessionDependency) -> OptimizationTaskRecord:
    """Read lifecycle, convergence and provenance metadata."""

    try:
        return service.get_task(session, task_id)
    except service.OptimizationNotFoundError as exc:
        raise _http_error(exc) from exc


@router.post("/tasks/{task_id}/run", response_model=OptimizationTaskRecord, status_code=202)
def run_task(task_id: int, session: SessionDependency) -> OptimizationTaskRecord:
    """Queue optimization and return immediately; simulations execute in workers."""

    try:
        task = service.start_task(session, task_id)
        try:
            job = run_optimization_task.delay(task.id)
        except Exception as exc:
            task.status = "failed"
            task.progress = 100
            task.error_message = "optimization queue broker unavailable"
            task.end_time = datetime.now(UTC)
            session.commit()
            raise HTTPException(status_code=503, detail=task.error_message) from exc
        task.queue_job_id = str(job.id)
        session.commit()
        session.expire_all()
        return service.get_task(session, task_id)
    except (service.OptimizationNotFoundError, service.OptimizationStateError) as exc:
        raise _http_error(exc) from exc


@router.post("/tasks/{task_id}/cancel", response_model=OptimizationTaskRecord)
def cancel_task(task_id: int, session: SessionDependency) -> OptimizationTaskRecord:
    """Request cooperative cancellation without terminating another worker process."""

    try:
        return service.cancel_task(session, task_id)
    except (service.OptimizationNotFoundError, service.OptimizationStateError) as exc:
        raise _http_error(exc) from exc


@router.get(
    "/tasks/{task_id}/candidates", response_model=list[OptimizationCandidateRecord]
)
def list_candidates(
    task_id: int, session: SessionDependency
) -> list[OptimizationCandidateRecord]:
    """List generated plans with objective, constraint and simulation evidence."""

    try:
        return service.list_candidates(session, task_id)
    except service.OptimizationNotFoundError as exc:
        raise _http_error(exc) from exc


@router.get("/tasks/{task_id}/pareto", response_model=list[ParetoCandidateRecord])
def list_pareto(task_id: int, session: SessionDependency) -> list[ParetoCandidateRecord]:
    """Return the first Pareto front for multi-objective comparison."""

    try:
        return service.list_pareto(session, task_id)
    except service.OptimizationNotFoundError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/tasks/{task_id}/recommendation", response_model=RecommendationResponse
)
def get_recommendation(
    task_id: int, session: SessionDependency
) -> RecommendationResponse:
    """Return a human-review recommendation without execution authority."""

    try:
        return service.get_recommendation(session, task_id)
    except service.OptimizationNotFoundError as exc:
        raise _http_error(exc) from exc


@router.get("/tasks/{task_id}/explain", response_model=OptimizationExplanation)
def explain_recommendation(
    task_id: int, session: SessionDependency
) -> OptimizationExplanation:
    """Use the reserved explain surface with a deterministic non-AI template."""

    try:
        return service.explain_recommendation(session, task_id)
    except service.OptimizationNotFoundError as exc:
        raise _http_error(exc) from exc
