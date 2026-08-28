"""Worker 启动或运维调用的僵尸任务与投递缺口恢复入口。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Callable

from sqlalchemy import select, update

from app.database.session import SessionLocal
from app.gis.models import SimulationTask
from app.model_engine.v4_reconciliation import reconcile_v4_task
from app.worker.celery_app import celery_app
from app.worker.lifecycle import recover_stale_tasks


Delivery = Callable[[SimulationTask], object]


def recover_stale_running_tasks(stale_seconds: int = 120) -> list[int]:
    """使用独立会话恢复心跳过期任务并返回受影响 ID。"""

    with SessionLocal() as session:
        return recover_stale_tasks(session, stale_seconds)


def reconcile_one_v4_task(task_id: int, *, apply: bool = False) -> dict[str, object]:
    """以默认 dry-run 的独立会话核对单个 native-v4 任务。"""

    with SessionLocal() as session:
        return reconcile_v4_task(session, task_id, apply=apply)


def _deliver(task: SimulationTask) -> object:
    """按冻结 schema 把恢复投递发往与 API 相同的队列。"""

    from app.worker.tasks import V4_QUEUE, run_hydraulic_task, run_hydraulic_v4_task

    if task.input_schema_version == "dayu.model-input.v4":
        return run_hydraulic_v4_task.apply_async(args=[task.id], queue=V4_QUEUE)
    return run_hydraulic_task.delay(task.id)


def redeliver_stale_queued_tasks(
    *,
    stale_seconds: int = 90,
    limit: int = 100,
    deliver: Delivery | None = None,
) -> list[int]:
    """用 queued_time CAS 恢复 DB commit 与 broker publish 之间的投递缺口。"""

    if stale_seconds < 1:
        raise ValueError("stale_seconds must be positive")
    if limit < 1:
        raise ValueError("limit must be positive")
    publish = deliver or _deliver
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
    delivered: list[int] = []
    with SessionLocal() as session:
        candidates = session.execute(
            select(
                SimulationTask.id,
                SimulationTask.queued_time,
            )
            .where(
                SimulationTask.status == "queued",
                SimulationTask.active_execution_token.is_(None),
                SimulationTask.queue_job_id.is_(None),
                SimulationTask.queued_time.is_not(None),
                SimulationTask.queued_time < cutoff,
            )
            .order_by(SimulationTask.queued_time, SimulationTask.id)
            .limit(limit)
        ).all()
        for candidate in candidates:
            reserved_time = datetime.now(UTC)
            reserved = session.execute(
                update(SimulationTask)
                .where(
                    SimulationTask.id == candidate.id,
                    SimulationTask.status == "queued",
                    SimulationTask.active_execution_token.is_(None),
                    SimulationTask.queue_job_id.is_(None),
                    SimulationTask.queued_time == candidate.queued_time,
                )
                .values(queued_time=reserved_time)
            )
            if reserved.rowcount != 1:
                session.rollback()
                continue
            session.commit()
            task = session.get(SimulationTask, candidate.id)
            if task is None:
                continue
            try:
                job = publish(task)
            except Exception as exc:
                session.execute(
                    update(SimulationTask)
                    .where(
                        SimulationTask.id == candidate.id,
                        SimulationTask.status == "queued",
                        SimulationTask.queued_time == reserved_time,
                    )
                    .values(
                        last_infrastructure_error=(
                            "queued delivery recovery publish failed: "
                            f"{type(exc).__name__}: {exc}"
                        )[:4000]
                    )
                )
                session.commit()
                continue
            session.execute(
                update(SimulationTask)
                .where(
                    SimulationTask.id == candidate.id,
                    SimulationTask.status == "queued",
                    SimulationTask.queued_time == reserved_time,
                )
                .values(queue_job_id=str(getattr(job, "id", "recovered-delivery")))
            )
            session.commit()
            delivered.append(candidate.id)
    return delivered


@celery_app.task(
    name="dayu.recover_hydraulic_tasks",
    ignore_result=True,
)
def recover_hydraulic_tasks() -> dict[str, list[int]]:
    """先失效僵尸 attempt，再重投超时 queued；两步均由 CAS 去重。"""

    stale_running = recover_stale_running_tasks()
    redelivered = redeliver_stale_queued_tasks()
    return {
        "stale_running": stale_running,
        "redelivered": redelivered,
    }
