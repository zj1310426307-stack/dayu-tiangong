"""Optimization business services; HTTP routes remain lifecycle-only adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.gis.models import (
    OptimizationCandidate,
    OptimizationResult,
    OptimizationTask,
    SimulationCase,
)
from app.optimization.schemas import (
    OptimizationCandidateRecord,
    OptimizationExplanation,
    OptimizationTaskCreate,
    OptimizationTaskRecord,
    ParetoCandidateRecord,
    RecommendationResponse,
)


ALGORITHM_VERSION = "dayu-pso-1.0.0"


class OptimizationNotFoundError(LookupError):
    """Raised when an optimization or referenced model entity does not exist."""


class OptimizationStateError(RuntimeError):
    """Raised when a lifecycle operation is invalid for the current state."""


def _task_record(session: Session, task: OptimizationTask) -> OptimizationTaskRecord:
    """Enrich an optimization task with candidate and recommendation counts."""

    candidate_count = session.scalar(
        select(func.count(OptimizationCandidate.id)).where(OptimizationCandidate.task_id == task.id)
    ) or 0
    pareto_count = session.scalar(
        select(func.count(OptimizationResult.candidate_id)).where(
            OptimizationResult.task_id == task.id,
            OptimizationResult.pareto_level == 1,
            OptimizationResult.recommendation_status.in_(("recommended", "pareto")),
        )
    ) or 0
    recommended_id = session.scalar(
        select(OptimizationResult.candidate_id).where(
            OptimizationResult.task_id == task.id,
            OptimizationResult.recommendation_status == "recommended",
        )
    )
    return OptimizationTaskRecord(
        **{column.name: getattr(task, column.name) for column in task.__table__.columns},
        candidate_count=int(candidate_count),
        pareto_count=int(pareto_count),
        recommended_candidate_id=recommended_id,
    )


def _pareto_record(
    candidate: OptimizationCandidate, result: OptimizationResult
) -> ParetoCandidateRecord:
    """Combine candidate evidence and Pareto metadata for clients."""

    return ParetoCandidateRecord(
        **{column.name: getattr(candidate, column.name) for column in candidate.__table__.columns},
        pareto_level=result.pareto_level,
        rank=result.rank,
        recommendation_status=result.recommendation_status,
        explanation=result.explanation,
    )


def create_task(session: Session, payload: OptimizationTaskCreate) -> OptimizationTaskRecord:
    """Fail closed until optimization controls have a verified MASCARET mapping."""

    case = session.get(SimulationCase, payload.simulation_case_id)
    if case is None:
        raise OptimizationNotFoundError("simulation case does not exist")
    if case.dataset_version_id != payload.dataset_version_id:
        raise OptimizationStateError("simulation case does not belong to dataset version")
    raise OptimizationStateError(
        "UNSUPPORTED_BY_MASCARET_ADAPTER: optimization is disabled until "
        "candidate Gate schedules and Pump controls have a verified mapping"
    )


def list_tasks(
    session: Session, dataset_version_id: int | None = None
) -> list[OptimizationTaskRecord]:
    """Return newest optimization tasks, optionally scoped by Dataset Version."""

    statement = select(OptimizationTask)
    if dataset_version_id is not None:
        statement = statement.where(
            OptimizationTask.dataset_version_id == dataset_version_id
        )
    tasks = session.scalars(statement.order_by(OptimizationTask.id.desc())).all()
    return [_task_record(session, task) for task in tasks]


def get_task(session: Session, task_id: int) -> OptimizationTaskRecord:
    """Read one optimization task without mutating its state."""

    task = session.get(OptimizationTask, task_id)
    if task is None:
        raise OptimizationNotFoundError("optimization task does not exist")
    return _task_record(session, task)


def start_task(session: Session, task_id: int) -> OptimizationTask:
    """Reject execution of historical custom-solver optimization tasks."""

    task = session.get(OptimizationTask, task_id)
    if task is None:
        raise OptimizationNotFoundError("optimization task does not exist")
    raise OptimizationStateError(
        "LEGACY_ENGINE_RETIRED: optimization tasks cannot execute on the removed solver"
    )


def cancel_task(session: Session, task_id: int) -> OptimizationTaskRecord:
    """Cancel pending work immediately or request cooperative running cancellation."""

    task = session.get(OptimizationTask, task_id)
    if task is None:
        raise OptimizationNotFoundError("optimization task does not exist")
    if task.status == "pending":
        task.status = "cancelled"
        task.cancel_requested = True
        task.progress = 100
        task.end_time = datetime.now(UTC)
    elif task.status == "running":
        task.cancel_requested = True
    elif task.status != "cancelled":
        raise OptimizationStateError("only pending or running tasks can be cancelled")
    session.commit()
    return _task_record(session, task)


def list_candidates(session: Session, task_id: int) -> list[OptimizationCandidateRecord]:
    """Return all generated candidate plans and Phase 4 simulation links."""

    if session.get(OptimizationTask, task_id) is None:
        raise OptimizationNotFoundError("optimization task does not exist")
    candidates = session.scalars(
        select(OptimizationCandidate)
        .where(OptimizationCandidate.task_id == task_id)
        .order_by(OptimizationCandidate.generation, OptimizationCandidate.candidate_index)
    ).all()
    return [OptimizationCandidateRecord.model_validate(item) for item in candidates]


def list_pareto(session: Session, task_id: int) -> list[ParetoCandidateRecord]:
    """Return the first Pareto front ordered for 2D/3D visualization."""

    if session.get(OptimizationTask, task_id) is None:
        raise OptimizationNotFoundError("optimization task does not exist")
    rows = session.execute(
        select(OptimizationCandidate, OptimizationResult)
        .join(OptimizationResult, OptimizationResult.candidate_id == OptimizationCandidate.id)
        .where(OptimizationResult.task_id == task_id, OptimizationResult.pareto_level == 1)
        .where(OptimizationCandidate.valid.is_(True))
        .order_by(OptimizationResult.rank)
    ).all()
    return [_pareto_record(candidate, result) for candidate, result in rows]


def get_recommendation(session: Session, task_id: int) -> RecommendationResponse:
    """Return the weighted best Pareto candidate without granting execution authority."""

    task = session.get(OptimizationTask, task_id)
    if task is None:
        raise OptimizationNotFoundError("optimization task does not exist")
    row = session.execute(
        select(OptimizationCandidate, OptimizationResult)
        .join(OptimizationResult, OptimizationResult.candidate_id == OptimizationCandidate.id)
        .where(
            OptimizationResult.task_id == task_id,
            OptimizationResult.recommendation_status == "recommended",
        )
    ).first()
    return RecommendationResponse(
        task_id=task_id,
        candidate=_pareto_record(*row) if row is not None else None,
    )


def explain_recommendation(session: Session, task_id: int) -> OptimizationExplanation:
    """Explain the recommendation with a deterministic template reserved for future AI."""

    recommendation = get_recommendation(session, task_id)
    if recommendation.candidate is None:
        return OptimizationExplanation(
            task_id=task_id,
            candidate_id=None,
            summary="尚无可推荐候选方案。",
            factors=[],
            limitations=["需要任务成功完成并产生满足硬约束的 Pareto 候选。"],
        )
    candidate = recommendation.candidate
    values = (candidate.objective_values or {}).get("values", {})
    comparison = session.scalar(
        select(OptimizationCandidate)
        .join(OptimizationResult, OptimizationResult.candidate_id == OptimizationCandidate.id)
        .where(
            OptimizationResult.task_id == task_id,
            OptimizationResult.pareto_level == 1,
            OptimizationCandidate.valid.is_(True),
            OptimizationCandidate.id != candidate.id,
        )
        .order_by(OptimizationCandidate.score, OptimizationCandidate.id)
    )
    differences = []
    if comparison is not None:
        comparison_values = (comparison.objective_values or {}).get("values", {})
        differences.append(
            "相对候选 "
            f"{comparison.id}：防洪 {float(values.get('flood_risk', 0)) - float(comparison_values.get('flood_risk', 0)):+.4f}，"
            f"能耗 {float(values.get('energy_cost', 0)) - float(comparison_values.get('energy_cost', 0)):+.4f}，"
            f"操作 {float(values.get('operation_cost', 0)) - float(comparison_values.get('operation_cost', 0)):+.4f}"
        )
    return OptimizationExplanation(
        task_id=task_id,
        candidate_id=candidate.id,
        summary=f"候选 {candidate.id} 是第一 Pareto 前沿中加权总分最低的方案。",
        factors=[
            f"防洪风险目标值 {float(values.get('flood_risk', 0)):.4f}",
            f"能耗成本目标值 {float(values.get('energy_cost', 0)):.4f}",
            f"操作成本目标值 {float(values.get('operation_cost', 0)):.4f}",
            *differences,
        ],
        limitations=[
            "解释由确定性模板生成，不是 AI 推理。",
            "推荐仅用于人工复核，不授权 PLC、SCADA 或真实设备执行。",
        ],
    )
