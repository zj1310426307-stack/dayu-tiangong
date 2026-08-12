"""Celery 水动力任务：唯一认领、协作取消、心跳与结果持久化。"""

from __future__ import annotations

import socket
from datetime import UTC, datetime

from app.database.session import SessionLocal
from app.gis.models import SimulationTask
from app.model_engine.service import persist_engine_result
from app.worker.celery_app import celery_app
from app.worker.lifecycle import (
    cancellation_requested,
    claim_task,
    heartbeat,
)
from model import HydraulicEngine
from model.core.errors import HydraulicCancelledError, HydraulicInputError


@celery_app.task(
    bind=True,
    name="dayu.run_hydraulic_task",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def run_hydraulic_task(self, task_id: int) -> dict[str, str | int]:
    """执行冻结输入；数值输入错误不会自动重试，基础设施瞬时错误最多重试两次。"""

    worker_id = f"{socket.gethostname()}:{self.request.id or 'eager'}"
    with SessionLocal() as session:
        task = claim_task(session, task_id, worker_id)
        duration = float(task.config.get("duration_seconds") or 3600.0)

        def cancelled() -> bool:
            """供求解器在安全检查点读取数据库取消标志。"""

            return cancellation_requested(session, task_id)

        def report(simulation_time: float, cfl: float) -> None:
            """按模拟时刻更新心跳和 5–95% 进度。"""

            progress = 5 + int(90 * min(max(simulation_time / max(duration, 1.0), 0.0), 1.0))
            heartbeat(
                session, task_id, progress=progress,
                simulation_time=simulation_time, cfl=cfl,
            )

        try:
            if task.input_snapshot is None:
                raise HydraulicInputError("task has no frozen input snapshot")
            result = HydraulicEngine().run(
                task.input_snapshot,
                task.config,
                cancel_check=cancelled,
                progress_callback=report,
            )
            task = session.get(SimulationTask, task_id)
            if task is None:
                raise LookupError("simulation task disappeared")
            persist_engine_result(session, task, result)
            return {"task_id": task_id, "status": "success"}
        except HydraulicCancelledError as exc:
            session.rollback()
            task = session.get(SimulationTask, task_id)
            if task is not None:
                task.status = "cancelled"
                task.progress = 100
                task.error_message = str(exc)
                task.end_time = datetime.now(UTC)
                session.commit()
            return {"task_id": task_id, "status": "cancelled"}
        except (HydraulicInputError, ValueError) as exc:
            session.rollback()
            task = session.get(SimulationTask, task_id)
            if task is not None:
                task.status = "failed"
                task.progress = 100
                task.error_message = str(exc)[:4000]
                task.end_time = datetime.now(UTC)
                session.commit()
            return {"task_id": task_id, "status": "failed"}
        except (ConnectionError, TimeoutError):
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            task = session.get(SimulationTask, task_id)
            if task is not None:
                task.status = "failed"
                task.progress = 100
                task.error_message = str(exc)[:4000]
                task.end_time = datetime.now(UTC)
                session.commit()
            return {"task_id": task_id, "status": "failed"}
