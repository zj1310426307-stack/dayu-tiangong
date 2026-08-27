"""数据库驱动的唯一认领、心跳、取消、重试和僵尸恢复。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.gis.models import SimulationTask


class DuplicateClaimError(RuntimeError):
    """同一队列任务已被其他 Worker 认领。"""


def claim_task(session: Session, task_id: int, worker_id: str) -> SimulationTask:
    """以条件 UPDATE 原子地把 queued 任务唯一认领为 running。"""

    now = datetime.now(UTC)
    result = session.execute(
        update(SimulationTask)
        .where(
            SimulationTask.id == task_id,
            SimulationTask.status == "queued",
            SimulationTask.input_schema_version != "dayu.model-input.v4",
        )
        .values(
            status="running", progress=5, worker_id=worker_id,
            start_time=now, heartbeat_time=now, error_message=None,
        )
    )
    if result.rowcount != 1:
        session.rollback()
        raise DuplicateClaimError("task is not queued or was already claimed")
    session.commit()
    task = session.get(SimulationTask, task_id)
    if task is None:
        raise LookupError("simulation task does not exist")
    return task


def claim_v4_task(session: Session, task_id: int, worker_id: str) -> SimulationTask:
    """Atomically claim only the exact D1 native-v4 solver capability."""

    from model.solver.registry import D1_CAPABILITY_ID, D1_SOLVER_ID

    now = datetime.now(UTC)
    result = session.execute(
        update(SimulationTask)
        .where(
            SimulationTask.id == task_id,
            SimulationTask.status == "queued",
            SimulationTask.input_schema_version == "dayu.model-input.v4",
            SimulationTask.solver_id == D1_SOLVER_ID,
            SimulationTask.capability_id == D1_CAPABILITY_ID,
        )
        .values(
            status="running",
            progress=5,
            worker_id=worker_id,
            start_time=now,
            heartbeat_time=now,
            execution_phase="validating_snapshot",
            error_message=None,
        )
    )
    if result.rowcount != 1:
        session.rollback()
        raise DuplicateClaimError("task is not a supported queued native-v4 task")
    session.commit()
    task = session.get(SimulationTask, task_id)
    if task is None:
        raise LookupError("simulation task does not exist")
    return task


def heartbeat(
    session: Session, task_id: int, *, progress: int,
    simulation_time: float | None = None, cfl: float | None = None,
    execution_phase: str | None = None,
    accepted_step_count: int | None = None,
    retry_count: int | None = None,
    cfl_reduction_count: int | None = None,
    positivity_retry_count: int | None = None,
    event_refinement_count: int | None = None,
    gate_solver_retry_count: int | None = None,
    pump_solver_retry_count: int | None = None,
    minimum_dt_failure_count: int | None = None,
    last_event: dict[str, object] | None = None,
) -> None:
    """更新 Worker 心跳、进度和当前数值时刻。"""

    session.expire_all()
    task = session.get(SimulationTask, task_id)
    bounded_progress = max(0, min(progress, 99))
    values: dict[str, object] = {
        "heartbeat_time": datetime.now(UTC),
        "progress": max(task.progress, bounded_progress) if task is not None else bounded_progress,
        "current_simulation_time": simulation_time,
        "current_cfl": cfl,
    }
    optional_values = {
        "execution_phase": execution_phase,
        "accepted_step_count": accepted_step_count,
        "retry_count": retry_count,
        "cfl_reduction_count": cfl_reduction_count,
        "positivity_retry_count": positivity_retry_count,
        "event_refinement_count": event_refinement_count,
        "gate_solver_retry_count": gate_solver_retry_count,
        "pump_solver_retry_count": pump_solver_retry_count,
        "minimum_dt_failure_count": minimum_dt_failure_count,
        "last_event": last_event,
    }
    values.update({key: value for key, value in optional_values.items() if value is not None})
    session.execute(
        update(SimulationTask)
        .where(
            SimulationTask.id == task_id,
            SimulationTask.status.in_(("running", "cancel_requested")),
        )
        .values(**values)
    )
    session.commit()


def cancellation_requested(session: Session, task_id: int) -> bool:
    """读取协作式取消标志；每次读取前使会话状态失效。"""

    session.expire_all()
    task = session.get(SimulationTask, task_id)
    return bool(task is None or task.cancel_requested or task.status == "cancel_requested")


def request_cancel(session: Session, task: SimulationTask) -> SimulationTask:
    """队列中任务直接取消，运行中任务进入 cancel_requested 等待安全停止。"""

    if task.status == "queued":
        task.status = "cancelled"
        task.progress = 100
        task.cancel_requested = True
        task.end_time = datetime.now(UTC)
    elif task.status == "running":
        task.status = "cancel_requested"
        task.cancel_requested = True
    elif task.status not in {"cancel_requested", "cancelled"}:
        raise ValueError("only queued or running tasks can be cancelled")
    session.commit()
    session.refresh(task)
    return task


def recover_stale_tasks(session: Session, stale_seconds: int = 120) -> list[int]:
    """把心跳超时的运行任务标记失败，供人工审核后重试。"""

    cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
    tasks = list(
        session.scalars(
            select(SimulationTask).where(
                SimulationTask.status.in_(("running", "cancel_requested")),
                SimulationTask.heartbeat_time < cutoff,
            )
        ).all()
    )
    for task in tasks:
        task.status = "failed"
        task.progress = 100
        phase = task.execution_phase or "unknown"
        reconciliation = phase in {"persisting", "publishing_artifact", "finalizing"}
        task.error_message = (
            f"worker heartbeat stale during {phase}; "
            + (
                "result/artifact reconciliation required before retry"
                if reconciliation
                else "manual retry required"
            )
        )
        task.end_time = datetime.now(UTC)
    session.commit()
    return [task.id for task in tasks]
