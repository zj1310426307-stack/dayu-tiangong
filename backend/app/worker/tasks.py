"""Celery 水动力任务：唯一认领、协作取消、心跳与结果持久化。"""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import OperationalError

from app.database.session import SessionLocal
from app.gis.models import HydraulicTaskArtifact, SimulationTask
from app.model_engine.service import persist_engine_result
from app.model_engine.v4_result import persist_v4_result
from app.worker.celery_app import celery_app
from app.worker.lifecycle import (
    DuplicateClaimError,
    FINALIZATION_ARTIFACT_STATES,
    FINALIZATION_PHASES,
    InvalidTaskRouteError,
    StaleExecutionError,
    cancellation_requested,
    claim_task,
    claim_v4_task,
    handle_infrastructure_failure,
    heartbeat,
    lock_attempt_for_finalization,
    persist_legacy_result_with_attempt_cas,
    transition_attempt_terminal,
)
from model import HydraulicEngine
from model.adapters import V4RuntimeProjection, project_v4_to_v4_lite
from model.build_identity import (
    RuntimeBuildIdentity,
    RuntimeBuildMismatchError,
    assert_runtime_build_matches,
    current_runtime_build_identity,
)
from model.core.errors import HydraulicCancelledError, HydraulicInputError
from model.provenance import snapshot_hash
from model.solver.registry import (
    D1_CAPABILITY_ID,
    D1_SOLVER_ID,
    D3A_1_CAPABILITY_ID,
    D3A_2_CAPABILITY_ID,
    D3A_3_CAPABILITY_ID,
    registry_hash,
    task_solver_provenance,
)


V4_QUEUE = "hydraulic-v4-d1"
V4_WORKER_CAPABILITIES = {
    "supported_solver_ids": (D1_SOLVER_ID,),
    "supported_capability_ids": (
        D1_CAPABILITY_ID,
        D3A_1_CAPABILITY_ID,
        D3A_2_CAPABILITY_ID,
        D3A_3_CAPABILITY_ID,
    ),
}
INFRASTRUCTURE_ERRORS = (ConnectionError, TimeoutError, OSError, OperationalError)


def validate_worker_build_identity(
    task: SimulationTask,
    runtime_identity: RuntimeBuildIdentity | None = None,
) -> RuntimeBuildIdentity:
    """Reject a claimed task unless the executing process is its frozen build."""

    try:
        return assert_runtime_build_matches(
            expected_engine_version=task.engine_version,
            expected_engine_commit=task.engine_commit,
            expected_solver_build_id=task.solver_build_id,
            expected_build_mode=task.build_mode,
            expected_verified=task.build_verified,
            expected_registry_hash=task.registry_hash,
            actual=runtime_identity,
        )
    except RuntimeBuildMismatchError as exc:
        raise HydraulicInputError(str(exc)) from exc


def validate_v4_worker_task(
    task: SimulationTask,
    runtime_identity: RuntimeBuildIdentity | None = None,
) -> V4RuntimeProjection:
    """Recompute every frozen v4 identity after claim and fail closed on drift."""

    validate_worker_build_identity(task, runtime_identity)
    if task.input_snapshot is None or task.input_snapshot_hash is None:
        raise HydraulicInputError("native-v4 task has no frozen input snapshot")
    if not isinstance(task.capability_id, str) or not task.capability_id:
        raise HydraulicInputError("native-v4 task capability_id is missing")
    try:
        registered = task_solver_provenance(
            str(task.input_schema_version),
            capability_id=task.capability_id,
        )
    except HydraulicInputError as exc:
        raise HydraulicInputError(
            f"native-v4 task capability_id is not registered: {task.capability_id!r}"
        ) from exc
    route_mismatches = [
        f"{field}: task={getattr(task, field)!r}, registered={registered[field]!r}"
        for field in (
            "solver_id",
            "capability_id",
            "runtime_adapter_id",
            "result_schema_version",
            "registry_hash",
        )
        if getattr(task, field) != registered[field]
    ]
    if route_mismatches:
        raise HydraulicInputError(
            "native-v4 task route does not exactly match the Registry; "
            + "; ".join(route_mismatches)
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
    execution_token: str,
    status: str,
    message: str,
) -> str:
    """以 attempt CAS 收口 v4 失败，发布窗口异常转入 reconciliation。"""

    session.rollback()
    task = session.get(SimulationTask, task_id)
    if task is None or task.active_execution_token != execution_token:
        session.rollback()
        return "stale"
    reconciliation = (
        task.execution_phase in FINALIZATION_PHASES
        or task.artifact_status in FINALIZATION_ARTIFACT_STATES
    )
    artifact_status = (
        "reconciliation_required"
        if reconciliation
        else "failed"
        if task.artifact_status in {"preparing", "prepared", "publishing"}
        else task.artifact_status
    )
    actual_status = status
    transitioned = transition_attempt_terminal(
        session,
        task_id,
        execution_token=execution_token,
        status=actual_status,
        message=message,
        artifact_status=artifact_status,
        minimum_dt_failure="minimum_dt" in message,
        commit=False,
    )
    if not transitioned and actual_status == "failed":
        actual_status = "cancelled"
        transitioned = transition_attempt_terminal(
            session,
            task_id,
            execution_token=execution_token,
            status=actual_status,
            message=message,
            artifact_status=artifact_status,
            minimum_dt_failure="minimum_dt" in message,
            commit=False,
        )
    if not transitioned:
        session.rollback()
        return "stale"
    session.execute(
        update(HydraulicTaskArtifact)
        .where(
            HydraulicTaskArtifact.task_id == task_id,
            HydraulicTaskArtifact.status != "published",
        )
        .values(
            status="reconciliation_required" if reconciliation else "failed"
        )
    )
    session.commit()
    return actual_status


def _finish_legacy_failure(
    session: Any,
    task_id: int,
    *,
    execution_token: str,
    status: str,
    message: str,
) -> str:
    """以相同 lease 规则完成 legacy cancelled/failed 终态。"""

    session.rollback()
    actual_status = status
    transitioned = transition_attempt_terminal(
        session,
        task_id,
        execution_token=execution_token,
        status=actual_status,
        message=message,
    )
    if not transitioned and actual_status == "failed":
        actual_status = "cancelled"
        transitioned = transition_attempt_terminal(
            session,
            task_id,
            execution_token=execution_token,
            status=actual_status,
            message=message,
        )
    return actual_status if transitioned else "stale"


def _handle_infrastructure_error(
    celery_task: Any,
    session: Any,
    task_id: int,
    execution_token: str,
    exc: BaseException,
) -> str:
    """先完成数据库状态转换，再由 Celery 投递同一任务的新 attempt。"""

    session.rollback()
    outcome = handle_infrastructure_failure(
        session,
        task_id,
        execution_token=execution_token,
        message=f"{type(exc).__name__}: {exc}",
    )
    if outcome == "requeued":
        delivery_time = datetime.now(UTC)
        reserved = session.execute(
            update(SimulationTask)
            .where(
                SimulationTask.id == task_id,
                SimulationTask.status == "queued",
                SimulationTask.active_execution_token.is_(None),
            )
            .values(
                delivery_attempt_count=SimulationTask.delivery_attempt_count + 1,
                last_delivery_time=delivery_time,
            )
        )
        if reserved.rowcount != 1:
            session.rollback()
            return "stale"
        session.commit()
        retry_signal = celery_task.retry(exc=exc, countdown=1, throw=False)
        request_id = getattr(getattr(celery_task, "request", None), "id", None)
        queue_job_id = str(request_id or f"retry-task-{task_id}")
        recorded = session.execute(
            update(SimulationTask)
            .where(
                SimulationTask.id == task_id,
                SimulationTask.status == "queued",
                SimulationTask.active_execution_token.is_(None),
                SimulationTask.queue_job_id.is_(None),
                SimulationTask.last_delivery_time == delivery_time,
            )
            .values(queue_job_id=queue_job_id)
        )
        if recorded.rowcount == 1:
            session.commit()
        else:
            session.rollback()
        raise retry_signal
    return outcome


@celery_app.task(
    bind=True,
    name="dayu.run_hydraulic_task",
    max_retries=None,
)
def run_hydraulic_task(self, task_id: int) -> dict[str, str | int]:
    """执行 legacy 冻结输入；数据库状态机拥有重试和 execution lease。"""

    worker_id = f"{socket.gethostname()}:{self.request.id or 'eager'}"
    with SessionLocal() as session:
        try:
            task = claim_task(session, task_id, worker_id)
        except DuplicateClaimError:
            # Redelivery after an acknowledged attempt is an idempotent no-op.
            # In particular, do not enter failure/retry handling and mutate the
            # active owner or create a duplicate delivery loop.
            return {"task_id": task_id, "status": "duplicate"}
        execution_token = str(task.active_execution_token or "")
        if not execution_token:
            raise StaleExecutionError("claimed legacy task has no execution token")
        duration = float(task.config.get("duration_seconds") or 3600.0)

        def cancelled() -> bool:
            """供求解器在安全检查点读取数据库取消标志。"""

            return cancellation_requested(
                session, task_id, execution_token=execution_token
            )

        def report(simulation_time: float, cfl: float) -> None:
            """按模拟时刻更新心跳和 5–95% 进度。"""

            progress = 5 + int(90 * min(max(simulation_time / max(duration, 1.0), 0.0), 1.0))
            heartbeat(
                session, task_id, execution_token=execution_token, progress=progress,
                simulation_time=simulation_time, cfl=cfl,
            )

        try:
            executed_build_identity = validate_worker_build_identity(task)
            if task.input_snapshot is None:
                raise HydraulicInputError("task has no frozen input snapshot")
            result = HydraulicEngine().run(
                task.input_snapshot,
                task.config,
                cancel_check=cancelled,
                progress_callback=report,
            )
            task = lock_attempt_for_finalization(
                session, task_id, execution_token=execution_token
            )
            persist_legacy_result_with_attempt_cas(
                session,
                task,
                result,
                execution_token=execution_token,
                persist=lambda active_session, active_task, active_result: (
                    persist_engine_result(
                        active_session,
                        active_task,
                        active_result,
                        executed_build_identity=executed_build_identity,
                    )
                ),
            )
            return {"task_id": task_id, "status": "success"}
        except HydraulicCancelledError as exc:
            outcome = _finish_legacy_failure(
                session,
                task_id,
                execution_token=execution_token,
                status="cancelled",
                message=str(exc),
            )
            return {"task_id": task_id, "status": outcome}
        except StaleExecutionError as exc:
            outcome = _finish_legacy_failure(
                session,
                task_id,
                execution_token=execution_token,
                status="cancelled",
                message=str(exc),
            )
            return {"task_id": task_id, "status": outcome}
        except (HydraulicInputError, ValueError) as exc:
            outcome = _finish_legacy_failure(
                session,
                task_id,
                execution_token=execution_token,
                status="failed",
                message=str(exc),
            )
            return {"task_id": task_id, "status": outcome}
        except INFRASTRUCTURE_ERRORS as exc:
            outcome = _handle_infrastructure_error(
                self, session, task_id, execution_token, exc
            )
            return {"task_id": task_id, "status": outcome}
        except Exception as exc:
            outcome = _finish_legacy_failure(
                session,
                task_id,
                execution_token=execution_token,
                status="failed",
                message=str(exc),
            )
            return {"task_id": task_id, "status": outcome}


@celery_app.task(
    bind=True,
    name="dayu.run_hydraulic_v4_task",
    queue=V4_QUEUE,
    max_retries=None,
)
def run_hydraulic_v4_task(self, task_id: int) -> dict[str, str | int]:
    """Execute only the declared D1 native-v4 capability on its dedicated queue."""

    worker_id = f"{socket.gethostname()}:{self.request.id or 'eager'}:{D1_SOLVER_ID}"
    with SessionLocal() as session:
        try:
            task = claim_v4_task(session, task_id, worker_id)
        except InvalidTaskRouteError:
            return {"task_id": task_id, "status": "failed"}
        except DuplicateClaimError:
            return {"task_id": task_id, "status": "duplicate"}
        execution_token = str(task.active_execution_token or "")
        if not execution_token:
            raise StaleExecutionError("claimed native-v4 task has no execution token")
        last_write_time = monotonic()
        last_progress = 5

        def cancelled() -> bool:
            return cancellation_requested(
                session, task_id, execution_token=execution_token
            )

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
                execution_token=execution_token,
                progress=phase_progress,
                execution_phase=value,
            )
            last_write_time = monotonic()

        try:
            phase("validating_snapshot")
            executed_build_identity = current_runtime_build_identity()
            projection = validate_v4_worker_task(task, executed_build_identity)
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
                    execution_token=execution_token,
                    progress=candidate,
                    simulation_time=simulation_time,
                    cfl=cfl,
                    execution_phase="solving",
                    accepted_step_count=int(details["accepted_step_count"]),
                    numerical_retry_count=int(details["retry_count"]),
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
                execution_token=execution_token,
                executed_build_identity=executed_build_identity,
                cancel_check=cancelled,
                phase_callback=phase,
            )
            return {"task_id": task_id, "status": "success"}
        except HydraulicCancelledError as exc:
            outcome = _finish_v4_failure(
                session,
                task_id,
                execution_token=execution_token,
                status="cancelled",
                message=str(exc),
            )
            return {"task_id": task_id, "status": outcome}
        except StaleExecutionError as exc:
            outcome = _finish_v4_failure(
                session,
                task_id,
                execution_token=execution_token,
                status="cancelled",
                message=str(exc),
            )
            return {"task_id": task_id, "status": outcome}
        except (HydraulicInputError, ValueError) as exc:
            outcome = _finish_v4_failure(
                session,
                task_id,
                execution_token=execution_token,
                status="failed",
                message=str(exc),
            )
            return {"task_id": task_id, "status": outcome}
        except INFRASTRUCTURE_ERRORS as exc:
            outcome = _handle_infrastructure_error(
                self, session, task_id, execution_token, exc
            )
            return {"task_id": task_id, "status": outcome}
        except Exception as exc:
            outcome = _finish_v4_failure(
                session,
                task_id,
                execution_token=execution_token,
                status="failed",
                message=str(exc),
            )
            return {"task_id": task_id, "status": outcome}
