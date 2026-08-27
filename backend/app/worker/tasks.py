"""Celery 水动力任务：唯一认领、协作取消、心跳与结果持久化。"""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from app.database.session import SessionLocal
from app.gis.models import HydraulicTaskArtifact, SimulationTask
from app.model_engine.service import persist_engine_result
from app.model_engine.v4_result import persist_v4_result
from app.worker.celery_app import celery_app
from app.worker.lifecycle import (
    cancellation_requested,
    claim_task,
    claim_v4_task,
    heartbeat,
)
from model import HydraulicEngine
from model.adapters import V4RuntimeProjection, project_v4_to_v4_lite
from model.core.errors import HydraulicCancelledError, HydraulicInputError
from model.provenance import snapshot_hash
from model.solver.registry import (
    D1_CAPABILITY_ID,
    D1_RUNTIME_ADAPTER_ID,
    D1_SOLVER_ID,
    registry_hash,
    resolve_solver,
)


V4_QUEUE = "hydraulic-v4-d1"
V4_WORKER_CAPABILITIES = {
    "supported_solver_ids": (D1_SOLVER_ID,),
    "supported_capability_ids": (D1_CAPABILITY_ID,),
}


def validate_v4_worker_task(task: SimulationTask) -> V4RuntimeProjection:
    """Recompute every frozen v4 identity after claim and fail closed on drift."""

    if task.input_snapshot is None or task.input_snapshot_hash is None:
        raise HydraulicInputError("native-v4 task has no frozen input snapshot")
    resolve_solver(
        str(task.input_schema_version),
        solver_id=task.solver_id,
        capability_id=task.capability_id,
        runtime_adapter_id=task.runtime_adapter_id,
    )
    actual_source_hash = snapshot_hash(task.input_snapshot)
    if actual_source_hash != task.input_snapshot_hash:
        raise HydraulicInputError(
            "native-v4 authoritative input hash mismatch: "
            f"task={task.input_snapshot_hash}, recomputed={actual_source_hash}"
        )
    projection = project_v4_to_v4_lite(task.input_snapshot)
    expected = {
        "runtime_projection_hash": task.runtime_projection_hash,
        "mesh_hash": task.mesh_hash,
        "solver_policy_hash": task.solver_policy_hash,
        "validation_policy_hash": task.validation_policy_hash,
        "registry_hash": task.registry_hash,
    }
    recomputed = {
        key: projection.manifest[key]
        for key in (
            "runtime_projection_hash",
            "mesh_hash",
            "solver_policy_hash",
            "validation_policy_hash",
            "registry_hash",
        )
    }
    recomputed["registry_hash"] = registry_hash()
    mismatches = [
        f"{key}: task={expected[key]}, recomputed={recomputed[key]}"
        for key in expected
        if expected[key] != recomputed[key]
    ]
    if mismatches:
        raise HydraulicInputError(
            "native-v4 frozen provenance mismatch; " + "; ".join(mismatches)
        )
    return projection


def _finish_v4_failure(
    session: Any,
    task_id: int,
    *,
    status: str,
    message: str,
) -> None:
    """Persist one terminal v4 failure without exposing prepared artifacts."""

    session.rollback()
    task = session.get(SimulationTask, task_id)
    if task is None:
        return
    task.status = status
    task.progress = 100
    task.execution_phase = "finalizing"
    task.error_message = message[:4000]
    task.end_time = datetime.now(UTC)
    task.heartbeat_time = datetime.now(UTC)
    if "minimum_dt" in message:
        task.minimum_dt_failure_count += 1
    for artifact in session.query(HydraulicTaskArtifact).filter(
        HydraulicTaskArtifact.task_id == task_id,
        HydraulicTaskArtifact.status != "published",
    ):
        artifact.status = "failed"
    if task.artifact_status in {"preparing", "prepared"}:
        task.artifact_status = "failed"
    session.commit()


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


@celery_app.task(
    bind=True,
    name="dayu.run_hydraulic_v4_task",
    queue=V4_QUEUE,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def run_hydraulic_v4_task(self, task_id: int) -> dict[str, str | int]:
    """Execute only the declared D1 native-v4 capability on its dedicated queue."""

    worker_id = f"{socket.gethostname()}:{self.request.id or 'eager'}:{D1_SOLVER_ID}"
    with SessionLocal() as session:
        task = claim_v4_task(session, task_id, worker_id)
        last_write_time = monotonic()
        last_progress = 5

        def cancelled() -> bool:
            return cancellation_requested(session, task_id)

        def phase(value: str) -> None:
            nonlocal last_write_time
            phase_progress = {
                "validating_snapshot": 5,
                "projecting_runtime": 8,
                "solving": max(last_progress, 10),
                "serializing": 87,
                "persisting": 91,
                "publishing_artifact": 96,
                "finalizing": 99,
            }[value]
            heartbeat(
                session,
                task_id,
                progress=phase_progress,
                execution_phase=value,
            )
            last_write_time = monotonic()

        try:
            phase("validating_snapshot")
            projection = validate_v4_worker_task(task)
            phase("projecting_runtime")
            duration = float(projection.runtime.solver.duration_seconds)
            phase("solving")

            def report(
                simulation_time: float,
                cfl: float,
                details: dict[str, object],
            ) -> None:
                """Throttle durable writes while preserving accepted-step semantics."""

                nonlocal last_progress, last_write_time
                candidate = 10 + int(
                    75
                    * min(
                        max(simulation_time / max(duration, 1.0), 0.0),
                        1.0,
                    )
                )
                now = monotonic()
                should_write = (
                    candidate >= last_progress + 2
                    or now - last_write_time >= 1.0
                    or simulation_time >= duration
                )
                if not should_write:
                    return
                heartbeat(
                    session,
                    task_id,
                    progress=candidate,
                    simulation_time=simulation_time,
                    cfl=cfl,
                    execution_phase="solving",
                    accepted_step_count=int(details["accepted_step_count"]),
                    retry_count=int(details["retry_count"]),
                    cfl_reduction_count=int(details["cfl_reduction_count"]),
                    positivity_retry_count=int(details["positivity_retry_count"]),
                    event_refinement_count=int(details["event_refinement_count"]),
                    gate_solver_retry_count=int(details["gate_solver_retry_count"]),
                    pump_solver_retry_count=int(details["pump_solver_retry_count"]),
                    minimum_dt_failure_count=int(details["minimum_dt_failure_count"]),
                    last_event=details.get("last_event")
                    if isinstance(details.get("last_event"), dict)
                    else None,
                )
                last_progress = max(last_progress, candidate)
                last_write_time = now

            result = HydraulicEngine().run(
                projection.runtime_snapshot,
                cancel_check=cancelled,
                progress_callback=report,
            )
            task = session.get(SimulationTask, task_id)
            if task is None:
                raise LookupError("native-v4 task disappeared")
            persist_v4_result(
                session,
                task,
                result,
                projection,
                cancel_check=cancelled,
                phase_callback=phase,
            )
            return {"task_id": task_id, "status": "success"}
        except HydraulicCancelledError as exc:
            _finish_v4_failure(
                session,
                task_id,
                status="cancelled",
                message=str(exc),
            )
            return {"task_id": task_id, "status": "cancelled"}
        except (HydraulicInputError, ValueError) as exc:
            _finish_v4_failure(
                session,
                task_id,
                status="failed",
                message=str(exc),
            )
            return {"task_id": task_id, "status": "failed"}
        except (ConnectionError, TimeoutError):
            session.rollback()
            raise
        except Exception as exc:
            _finish_v4_failure(
                session,
                task_id,
                status="failed",
                message=str(exc),
            )
            return {"task_id": task_id, "status": "failed"}
