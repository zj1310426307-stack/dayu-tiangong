"""Worker 启动或运维调用的僵尸任务与投递缺口恢复入口。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Callable

from sqlalchemy import or_, select, update

from app.database.session import SessionLocal
from app.gis.models import SimulationTask
from app.worker.celery_app import celery_app
from app.worker.lifecycle import recover_stale_tasks
from model.hydraulic_1d.contracts import HYDRAULIC_1D_INPUT_SCHEMA


Delivery = Callable[[SimulationTask], object]
MAX_DELIVERY_ATTEMPTS = 3
DELIVERY_RETRY_LIMIT_CODE = "D2_DELIVERY_RETRY_LIMIT"


def recover_stale_running_tasks(stale_seconds: int = 120) -> list[int]:
    """使用独立会话恢复心跳过期任务并返回受影响 ID。"""

    with SessionLocal() as session:
        return recover_stale_tasks(session, stale_seconds)


def _deliver(task: SimulationTask) -> object:
    """Publish only the unified schema to the same queue as the API."""

    from app.worker.tasks import HYDRAULIC_1D_QUEUE, run_hydraulic_task

    if task.input_schema_version != HYDRAULIC_1D_INPUT_SCHEMA:
        raise ValueError("LEGACY_ENGINE_RETIRED")
    return run_hydraulic_task.apply_async(args=[task.id], queue=HYDRAULIC_1D_QUEUE)


def redeliver_stale_queued_tasks(
    *,
    stale_seconds: int = 90,
    limit: int = 100,
    deliver: Delivery | None = None,
) -> list[int]:
    """Boundedly redeliver stale queued work, including lost published messages.

    ``queue_job_id`` records a broker acknowledgement, not durable evidence that
    its message still exists.  Attempt/time leases own retry eligibility instead.
    """

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
                SimulationTask.last_delivery_time,
                SimulationTask.delivery_attempt_count,
                SimulationTask.input_schema_version,
            )
            .where(
                SimulationTask.status == "queued",
                SimulationTask.active_execution_token.is_(None),
                SimulationTask.cancel_requested.is_(False),
                or_(
                    SimulationTask.last_delivery_time < cutoff,
                    (
                        SimulationTask.last_delivery_time.is_(None)
                        & SimulationTask.queued_time.is_not(None)
                        & (SimulationTask.queued_time < cutoff)
                    ),
                ),
            )
            .order_by(
                SimulationTask.last_delivery_time.nullsfirst(),
                SimulationTask.queued_time,
                SimulationTask.id,
            )
            .limit(limit)
        ).all()
        for candidate in candidates:
            last_delivery_predicate = (
                SimulationTask.last_delivery_time == candidate.last_delivery_time
                if candidate.last_delivery_time is not None
                else SimulationTask.last_delivery_time.is_(None)
            )
            if candidate.input_schema_version != HYDRAULIC_1D_INPUT_SCHEMA:
                retired = session.execute(
                    update(SimulationTask)
                    .where(
                        SimulationTask.id == candidate.id,
                        SimulationTask.status == "queued",
                        SimulationTask.active_execution_token.is_(None),
                        last_delivery_predicate,
                    )
                    .values(
                        status="failed",
                        progress=100,
                        queue_job_id=None,
                        error_message=(
                            "LEGACY_ENGINE_RETIRED: historical custom-solver tasks "
                            "cannot be redelivered"
                        ),
                        end_time=datetime.now(UTC),
                    )
                )
                if retired.rowcount == 1:
                    session.commit()
                else:
                    session.rollback()
                continue
            if candidate.delivery_attempt_count >= MAX_DELIVERY_ATTEMPTS:
                failed = session.execute(
                    update(SimulationTask)
                    .where(
                        SimulationTask.id == candidate.id,
                        SimulationTask.status == "queued",
                        SimulationTask.active_execution_token.is_(None),
                        SimulationTask.cancel_requested.is_(False),
                        SimulationTask.delivery_attempt_count
                        == candidate.delivery_attempt_count,
                        last_delivery_predicate,
                    )
                    .values(
                        status="failed",
                        progress=100,
                        queue_job_id=None,
                        error_message=(
                            f"{DELIVERY_RETRY_LIMIT_CODE}: queued delivery remained "
                            f"unclaimed after {MAX_DELIVERY_ATTEMPTS} attempts"
                        ),
                        last_infrastructure_error=DELIVERY_RETRY_LIMIT_CODE,
                        end_time=datetime.now(UTC),
                    )
                )
                if failed.rowcount == 1:
                    session.commit()
                else:
                    session.rollback()
                continue
            reserved_time = datetime.now(UTC)
            reserved = session.execute(
                update(SimulationTask)
                .where(
                    SimulationTask.id == candidate.id,
                    SimulationTask.status == "queued",
                    SimulationTask.active_execution_token.is_(None),
                    SimulationTask.cancel_requested.is_(False),
                    SimulationTask.delivery_attempt_count
                    == candidate.delivery_attempt_count,
                    last_delivery_predicate,
                )
                .values(
                    queue_job_id=None,
                    delivery_attempt_count=candidate.delivery_attempt_count + 1,
                    last_delivery_time=reserved_time,
                )
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
                        SimulationTask.delivery_attempt_count
                        == candidate.delivery_attempt_count + 1,
                        SimulationTask.last_delivery_time == reserved_time,
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
                    SimulationTask.delivery_attempt_count
                    == candidate.delivery_attempt_count + 1,
                    SimulationTask.last_delivery_time == reserved_time,
                )
                .values(
                    queue_job_id=str(getattr(job, "id", "recovered-delivery")),
                    last_infrastructure_error=None,
                )
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


__all__ = [
    "DELIVERY_RETRY_LIMIT_CODE",
    "MAX_DELIVERY_ATTEMPTS",
    "recover_hydraulic_tasks",
    "recover_stale_running_tasks",
    "redeliver_stale_queued_tasks",
]
