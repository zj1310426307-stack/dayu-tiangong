"""数据库驱动的执行租约、心跳、取消、重试和僵尸恢复。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import case, or_, select, update
from sqlalchemy.orm import Session

from app.gis.models import HydraulicTaskArtifact, SimulationTask


FINALIZATION_PHASES = frozenset(
    {"persisting", "publishing_artifact", "finalizing"}
)
FINALIZATION_ARTIFACT_STATES = frozenset(
    {"prepared", "publishing", "published", "orphaned", "reconciliation_required"}
)
MAX_INFRASTRUCTURE_RETRIES = 2


class DuplicateClaimError(RuntimeError):
    """同一队列任务已被其他 Worker 认领。"""


class InvalidTaskRouteError(RuntimeError):
    """queued native-v4 task 的冻结 Registry 路由不完整或已漂移。"""


class StaleExecutionError(RuntimeError):
    """当前 Worker 的 execution token 已失效或任务状态已改变。"""


class _DeferredLegacyCommitSession:
    """将 legacy persistence 的 commit 收缩为 flush，由 attempt CAS 统一提交。"""

    def __init__(self, session: Session, task: SimulationTask) -> None:
        self._session = session
        self._task = task
        self._initial = {
            "status": task.status,
            "progress": task.progress,
            "diagnostics": task.diagnostics,
            "result_path": task.result_path,
            "end_time": task.end_time,
            "heartbeat_time": task.heartbeat_time,
        }
        self.final_values: dict[str, object] | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    def commit(self) -> None:
        """捕获 persistence 的成功值，但不让 ORM 提前写入 success。"""

        if self.final_values is not None:
            raise RuntimeError("legacy result persistence attempted multiple commits")
        self.final_values = {
            "status": self._task.status,
            "progress": self._task.progress,
            "diagnostics": self._task.diagnostics,
            "result_path": self._task.result_path,
            "end_time": self._task.end_time,
            "heartbeat_time": self._task.heartbeat_time,
        }
        for key, value in self._initial.items():
            setattr(self._task, key, value)
        self._session.flush()

    def refresh(self, _instance: object, *args: object, **kwargs: object) -> None:
        """Persistence 的刷新必须等到真实 CAS commit 后。"""

        return None


def _claim_values(worker_id: str, *, execution_phase: str | None) -> dict[str, object]:
    """构造一次新执行 attempt 的原子认领字段。"""

    now = datetime.now(UTC)
    return {
        "status": "running",
        "progress": 5,
        "worker_id": worker_id,
        "start_time": now,
        "end_time": None,
        "heartbeat_time": now,
        "execution_phase": execution_phase,
        "error_message": None,
        "cancel_requested": False,
        "execution_attempt_count": SimulationTask.execution_attempt_count + 1,
        "active_execution_token": uuid4().hex,
    }


def claim_task(session: Session, task_id: int, worker_id: str) -> SimulationTask:
    """原子认领 legacy queued 任务并生成唯一 execution token。"""

    result = session.execute(
        update(SimulationTask)
        .where(
            SimulationTask.id == task_id,
            SimulationTask.status == "queued",
            or_(
                SimulationTask.input_schema_version.is_(None),
                SimulationTask.input_schema_version != "dayu.model-input.v4",
            ),
        )
        .values(**_claim_values(worker_id, execution_phase=None))
    )
    if result.rowcount != 1:
        session.rollback()
        raise DuplicateClaimError("task is not queued or was already claimed")
    session.commit()
    session.expire_all()
    task = session.get(SimulationTask, task_id)
    if task is None:
        raise LookupError("simulation task does not exist")
    return task


def claim_v4_task(session: Session, task_id: int, worker_id: str) -> SimulationTask:
    """原子认领精确、显式的 native-v4 capability 并生成 execution token。"""

    from model.solver.registry import (
        MODEL_INPUT_V4,
        task_solver_provenance,
    )
    from model.core.errors import HydraulicInputError

    observed = session.get(SimulationTask, task_id)
    if observed is None:
        raise DuplicateClaimError("task is not a supported queued native-v4 task")
    route_fields = (
        "solver_id",
        "capability_id",
        "runtime_adapter_id",
        "result_schema_version",
        "registry_hash",
    )
    try:
        expected = task_solver_provenance(
            MODEL_INPUT_V4,
            capability_id=observed.capability_id,
        )
    except HydraulicInputError as exc:
        message = f"queued native-v4 task route is not registered: {exc}"[:4000]
        rejected = session.execute(
            update(SimulationTask)
            .where(
                SimulationTask.id == task_id,
                SimulationTask.status == "queued",
                SimulationTask.active_execution_token.is_(None),
                SimulationTask.input_schema_version == MODEL_INPUT_V4,
                *(
                    getattr(SimulationTask, field) == getattr(observed, field)
                    for field in route_fields
                ),
            )
            .values(
                status="failed",
                progress=100,
                queue_job_id=None,
                execution_phase="validating_snapshot",
                error_message=message,
                end_time=datetime.now(UTC),
                heartbeat_time=datetime.now(UTC),
            )
        )
        if rejected.rowcount == 1:
            session.commit()
            raise InvalidTaskRouteError(message) from exc
        session.rollback()
        raise DuplicateClaimError(
            "task is not a supported queued native-v4 task"
        ) from exc
    result = session.execute(
        update(SimulationTask)
        .where(
            SimulationTask.id == task_id,
            SimulationTask.status == "queued",
            SimulationTask.input_schema_version == MODEL_INPUT_V4,
            *(getattr(SimulationTask, field) == expected[field] for field in route_fields),
        )
        .values(**_claim_values(worker_id, execution_phase="validating_snapshot"))
    )
    if result.rowcount != 1:
        session.rollback()
        task = session.get(SimulationTask, task_id)
        if (
            task is not None
            and task.status == "queued"
            and task.active_execution_token is None
            and task.input_schema_version == MODEL_INPUT_V4
        ):
            mismatches = [
                f"{field}: task={getattr(task, field)!r}, registered={expected[field]!r}"
                for field in route_fields
                if getattr(task, field) != expected[field]
            ]
            if mismatches:
                message = (
                    "queued native-v4 task route does not exactly match the Registry; "
                    + "; ".join(mismatches)
                )[:4000]
                observed_route = [
                    (
                        getattr(SimulationTask, field).is_(None)
                        if getattr(task, field) is None
                        else getattr(SimulationTask, field) == getattr(task, field)
                    )
                    for field in route_fields
                ]
                rejected = session.execute(
                    update(SimulationTask)
                    .where(
                        SimulationTask.id == task_id,
                        SimulationTask.status == "queued",
                        SimulationTask.active_execution_token.is_(None),
                        SimulationTask.input_schema_version == MODEL_INPUT_V4,
                        *observed_route,
                    )
                    .values(
                        status="failed",
                        progress=100,
                        queue_job_id=None,
                        execution_phase="validating_snapshot",
                        error_message=message,
                        end_time=datetime.now(UTC),
                        heartbeat_time=datetime.now(UTC),
                    )
                )
                if rejected.rowcount == 1:
                    session.commit()
                    raise InvalidTaskRouteError(message)
                session.rollback()
        raise DuplicateClaimError("task is not a supported queued native-v4 task")
    session.commit()
    session.expire_all()
    task = session.get(SimulationTask, task_id)
    if task is None:
        raise LookupError("simulation task does not exist")
    return task


def heartbeat(
    session: Session,
    task_id: int,
    *,
    execution_token: str,
    progress: int,
    simulation_time: float | None = None,
    cfl: float | None = None,
    execution_phase: str | None = None,
    accepted_step_count: int | None = None,
    numerical_retry_count: int | None = None,
    cfl_reduction_count: int | None = None,
    positivity_retry_count: int | None = None,
    event_refinement_count: int | None = None,
    gate_solver_retry_count: int | None = None,
    pump_solver_retry_count: int | None = None,
    minimum_dt_failure_count: int | None = None,
    last_event: dict[str, object] | None = None,
) -> None:
    """仅允许 active attempt 更新心跳；缺省遥测不会清空最后接受值。"""

    bounded_progress = max(0, min(progress, 99))
    values: dict[str, object] = {
        "heartbeat_time": datetime.now(UTC),
        "progress": case(
            (SimulationTask.progress > bounded_progress, SimulationTask.progress),
            else_=bounded_progress,
        ),
    }
    optional_values = {
        "current_simulation_time": simulation_time,
        "current_cfl": cfl,
        "execution_phase": execution_phase,
        "accepted_step_count": accepted_step_count,
        "numerical_retry_count": numerical_retry_count,
        "cfl_reduction_count": cfl_reduction_count,
        "positivity_retry_count": positivity_retry_count,
        "event_refinement_count": event_refinement_count,
        "gate_solver_retry_count": gate_solver_retry_count,
        "pump_solver_retry_count": pump_solver_retry_count,
        "minimum_dt_failure_count": minimum_dt_failure_count,
        "last_event": last_event,
    }
    values.update({key: value for key, value in optional_values.items() if value is not None})
    result = session.execute(
        update(SimulationTask)
        .where(
            SimulationTask.id == task_id,
            SimulationTask.active_execution_token == execution_token,
            SimulationTask.status == "running",
            SimulationTask.cancel_requested.is_(False),
        )
        .values(**values)
    )
    if result.rowcount != 1:
        session.rollback()
        raise StaleExecutionError("heartbeat rejected for stale execution attempt")
    session.commit()


def cancellation_requested(
    session: Session, task_id: int, *, execution_token: str
) -> bool:
    """把取消、终态、任务消失或 token 漂移统一视为停止信号。"""

    session.expire_all()
    row = session.execute(
        select(
            SimulationTask.status,
            SimulationTask.cancel_requested,
            SimulationTask.active_execution_token,
        ).where(SimulationTask.id == task_id)
    ).one_or_none()
    if row is None or row.active_execution_token != execution_token:
        return True
    return bool(
        row.cancel_requested
        or row.status == "cancel_requested"
        or row.status not in {"running", "cancel_requested"}
    )


def request_cancel(session: Session, task: SimulationTask) -> SimulationTask:
    """用 CAS 接受 queued/running 取消，避免把并发 success 覆盖回非终态。"""

    task_id = task.id
    now = datetime.now(UTC)
    result = session.execute(
        update(SimulationTask)
        .where(SimulationTask.id == task_id, SimulationTask.status == "queued")
        .values(
            status="cancelled",
            progress=100,
            cancel_requested=True,
            end_time=now,
        )
    )
    if result.rowcount != 1:
        result = session.execute(
            update(SimulationTask)
            .where(SimulationTask.id == task_id, SimulationTask.status == "running")
            .values(status="cancel_requested", cancel_requested=True)
        )
    if result.rowcount == 1:
        session.commit()
    else:
        session.rollback()
    session.expire_all()
    current = session.get(SimulationTask, task_id)
    if current is None:
        raise LookupError("simulation task does not exist")
    if current.status not in {"cancel_requested", "cancelled"}:
        raise ValueError("only queued or running tasks can be cancelled")
    return current


def transition_attempt_terminal(
    session: Session,
    task_id: int,
    *,
    execution_token: str,
    status: str,
    message: str,
    artifact_status: str | None = None,
    minimum_dt_failure: bool = False,
    commit: bool = True,
) -> bool:
    """以 token/status CAS 完成 cancelled/failed，并可加入调用方事务。"""

    if status not in {"cancelled", "failed"}:
        raise ValueError("terminal attempt status must be cancelled or failed")
    predicates = [
        SimulationTask.id == task_id,
        SimulationTask.active_execution_token == execution_token,
    ]
    if status == "failed":
        predicates.extend(
            [SimulationTask.status == "running", SimulationTask.cancel_requested.is_(False)]
        )
    else:
        predicates.append(
            SimulationTask.status.in_(("running", "cancel_requested"))
        )
    values: dict[str, object] = {
        "status": status,
        "progress": 100,
        "execution_phase": "finalizing",
        "error_message": message[:4000],
        "end_time": datetime.now(UTC),
        "heartbeat_time": datetime.now(UTC),
        "last_execution_token": execution_token,
        "active_execution_token": None,
    }
    if status == "cancelled":
        values["cancel_requested"] = True
    if artifact_status is not None:
        values["artifact_status"] = artifact_status
    if minimum_dt_failure:
        values["minimum_dt_failure_count"] = (
            SimulationTask.minimum_dt_failure_count + 1
        )
    result = session.execute(
        update(SimulationTask).where(*predicates).values(**values)
    )
    if result.rowcount != 1:
        if commit:
            session.rollback()
        return False
    if commit:
        session.commit()
    return True


def lock_attempt_for_finalization(
    session: Session, task_id: int, *, execution_token: str
) -> SimulationTask:
    """锁定一个仍可成功发布的 attempt，使 cancel/recovery 与其串行。"""

    task = session.scalar(
        select(SimulationTask)
        .where(
            SimulationTask.id == task_id,
            SimulationTask.status == "running",
            SimulationTask.cancel_requested.is_(False),
            SimulationTask.active_execution_token == execution_token,
        )
        .with_for_update()
    )
    if task is None:
        session.rollback()
        raise StaleExecutionError("task attempt is no longer eligible for finalization")
    return task


def persist_legacy_result_with_attempt_cas(
    session: Session,
    task: SimulationTask,
    engine_result: Any,
    *,
    execution_token: str,
    persist: Callable[[Any, SimulationTask, Any], object],
    fault_hook: Callable[[str], None] | None = None,
) -> None:
    """在一个事务中持久 legacy 结果并完成 success/token CAS。"""

    if (
        task.status != "running"
        or task.cancel_requested
        or task.active_execution_token != execution_token
    ):
        session.rollback()
        raise StaleExecutionError("legacy attempt is no longer eligible for success")
    deferred = _DeferredLegacyCommitSession(session, task)
    persist(deferred, task, engine_result)
    if deferred.final_values is None:
        session.rollback()
        raise RuntimeError("legacy result persistence did not reach its commit boundary")
    if fault_hook is not None:
        fault_hook("after_legacy_result_flush")
    final_values = deferred.final_values
    if final_values["status"] != "success" or final_values["progress"] != 100:
        session.rollback()
        raise RuntimeError("legacy result persistence produced an invalid success state")
    if fault_hook is not None:
        fault_hook("before_legacy_final_cas")
    finalized = session.execute(
        update(SimulationTask)
        .where(
            SimulationTask.id == task.id,
            SimulationTask.status == "running",
            SimulationTask.cancel_requested.is_(False),
            SimulationTask.active_execution_token == execution_token,
        )
        .values(
            status="success",
            progress=100,
            diagnostics=final_values["diagnostics"],
            result_path=final_values["result_path"],
            end_time=final_values["end_time"],
            heartbeat_time=final_values["heartbeat_time"],
            error_message=None,
            last_execution_token=execution_token,
            active_execution_token=None,
        )
        .execution_options(synchronize_session=False)
    )
    if finalized.rowcount != 1:
        session.rollback()
        raise StaleExecutionError(
            "legacy final success rejected for stale/cancelled attempt"
        )
    session.commit()
    session.expire_all()


def seal_successful_attempt(
    session: Session, task_id: int, *, execution_token: str
) -> None:
    """清除已成功 attempt 的 active token，同时保留最后租约身份。"""

    result = session.execute(
        update(SimulationTask)
        .where(
            SimulationTask.id == task_id,
            SimulationTask.status == "success",
            SimulationTask.active_execution_token == execution_token,
        )
        .values(
            last_execution_token=execution_token,
            active_execution_token=None,
        )
    )
    if result.rowcount != 1:
        session.rollback()
        raise StaleExecutionError("successful task lease could not be sealed")
    session.commit()


def handle_infrastructure_failure(
    session: Session,
    task_id: int,
    *,
    execution_token: str,
    message: str,
    maximum_retries: int = MAX_INFRASTRUCTURE_RETRIES,
) -> str:
    """把基础设施失败确定地转为 requeue、failed 或 reconciliation。"""

    session.expire_all()
    task = session.get(SimulationTask, task_id)
    if task is None or task.active_execution_token != execution_token:
        session.rollback()
        return "stale"
    if task.status == "cancel_requested" or task.cancel_requested:
        if transition_attempt_terminal(
            session,
            task_id,
            execution_token=execution_token,
            status="cancelled",
            message=message,
        ):
            return "cancelled"
        return "stale"
    risky_finalization = (
        task.execution_phase in FINALIZATION_PHASES
        or task.artifact_status in FINALIZATION_ARTIFACT_STATES
    )
    if risky_finalization:
        result = session.execute(
            update(SimulationTask)
            .where(
                SimulationTask.id == task_id,
                SimulationTask.status == "running",
                SimulationTask.cancel_requested.is_(False),
                SimulationTask.active_execution_token == execution_token,
            )
            .values(
                status="failed",
                progress=100,
                artifact_status="reconciliation_required",
                error_message=(
                    "infrastructure failure during result/artifact finalization; "
                    "reconciliation required"
                ),
                last_infrastructure_error=message[:4000],
                infrastructure_retry_count=SimulationTask.infrastructure_retry_count + 1,
                last_execution_token=execution_token,
                active_execution_token=None,
                end_time=datetime.now(UTC),
                heartbeat_time=datetime.now(UTC),
            )
        )
        if result.rowcount != 1:
            session.rollback()
            return "stale"
        session.execute(
            update(HydraulicTaskArtifact)
            .where(
                HydraulicTaskArtifact.task_id == task_id,
                HydraulicTaskArtifact.status.in_(("prepared", "publishing")),
            )
            .values(status="reconciliation_required")
        )
        session.commit()
        return "reconciliation_required"
    if task.infrastructure_retry_count < maximum_retries:
        now = datetime.now(UTC)
        result = session.execute(
            update(SimulationTask)
            .where(
                SimulationTask.id == task_id,
                SimulationTask.status == "running",
                SimulationTask.cancel_requested.is_(False),
                SimulationTask.active_execution_token == execution_token,
                SimulationTask.infrastructure_retry_count
                == task.infrastructure_retry_count,
            )
            .values(
                status="queued",
                progress=0,
                queue_job_id=None,
                delivery_attempt_count=0,
                last_delivery_time=None,
                queued_time=now,
                start_time=None,
                end_time=None,
                heartbeat_time=None,
                worker_id=None,
                execution_phase=None,
                accepted_step_count=0,
                numerical_retry_count=0,
                cfl_reduction_count=0,
                positivity_retry_count=0,
                event_refinement_count=0,
                gate_solver_retry_count=0,
                pump_solver_retry_count=0,
                minimum_dt_failure_count=0,
                current_simulation_time=None,
                current_cfl=None,
                last_event=None,
                diagnostics=None,
                result_path=None,
                artifact_status=(
                    "none"
                    if task.input_schema_version == "dayu.model-input.v4"
                    else task.artifact_status
                ),
                retry_reason=message[:4000],
                error_message=None,
                last_infrastructure_error=message[:4000],
                infrastructure_retry_count=SimulationTask.infrastructure_retry_count + 1,
                last_execution_token=execution_token,
                active_execution_token=None,
            )
        )
        if result.rowcount != 1:
            session.rollback()
            return "stale"
        session.commit()
        return "requeued"
    if transition_attempt_terminal(
        session,
        task_id,
        execution_token=execution_token,
        status="failed",
        message=f"infrastructure retry limit reached: {message}",
        commit=False,
    ):
        session.execute(
            update(SimulationTask)
            .where(SimulationTask.id == task_id)
            .values(
                last_infrastructure_error=message[:4000],
                infrastructure_retry_count=SimulationTask.infrastructure_retry_count + 1,
            )
        )
        session.commit()
        return "failed"
    session.rollback()
    return "stale"


def recover_stale_tasks(session: Session, stale_seconds: int = 120) -> list[int]:
    """用 token/heartbeat CAS 恢复僵尸 attempt，并隔离发布窗口。"""

    cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
    candidates = session.execute(
        select(
            SimulationTask.id,
            SimulationTask.status,
            SimulationTask.execution_phase,
            SimulationTask.artifact_status,
            SimulationTask.active_execution_token,
            SimulationTask.heartbeat_time,
            SimulationTask.infrastructure_retry_count,
            SimulationTask.input_schema_version,
        ).where(
            SimulationTask.status.in_(("running", "cancel_requested")),
            SimulationTask.heartbeat_time < cutoff,
        )
    ).all()
    recovered: list[int] = []
    for candidate in candidates:
        phase = candidate.execution_phase or "unknown"
        message = f"worker heartbeat stale during {phase}"
        reconciliation = (
            phase in FINALIZATION_PHASES
            or candidate.artifact_status in FINALIZATION_ARTIFACT_STATES
        )
        token_predicate = (
            SimulationTask.active_execution_token == candidate.active_execution_token
            if candidate.active_execution_token is not None
            else SimulationTask.active_execution_token.is_(None)
        )
        common_predicates = (
            SimulationTask.id == candidate.id,
            SimulationTask.status == candidate.status,
            token_predicate,
            SimulationTask.heartbeat_time == candidate.heartbeat_time,
            SimulationTask.heartbeat_time < cutoff,
            SimulationTask.infrastructure_retry_count
            == candidate.infrastructure_retry_count,
        )

        if (
            candidate.status == "running"
            and not reconciliation
            and candidate.infrastructure_retry_count < MAX_INFRASTRUCTURE_RETRIES
        ):
            now = datetime.now(UTC)
            result = session.execute(
                update(SimulationTask)
                .where(*common_predicates)
                .values(
                    status="queued",
                    progress=0,
                    queue_job_id=None,
                    delivery_attempt_count=0,
                    last_delivery_time=None,
                    queued_time=now,
                    start_time=None,
                    end_time=None,
                    heartbeat_time=None,
                    worker_id=None,
                    execution_phase=None,
                    accepted_step_count=0,
                    numerical_retry_count=0,
                    cfl_reduction_count=0,
                    positivity_retry_count=0,
                    event_refinement_count=0,
                    gate_solver_retry_count=0,
                    pump_solver_retry_count=0,
                    minimum_dt_failure_count=0,
                    current_simulation_time=None,
                    current_cfl=None,
                    last_event=None,
                    diagnostics=None,
                    result_path=None,
                    artifact_status=(
                        "none"
                        if candidate.input_schema_version == "dayu.model-input.v4"
                        else candidate.artifact_status
                    ),
                    retry_reason=message,
                    error_message=None,
                    last_infrastructure_error=message,
                    infrastructure_retry_count=(
                        SimulationTask.infrastructure_retry_count + 1
                    ),
                    last_execution_token=candidate.active_execution_token,
                    active_execution_token=None,
                )
            )
            if result.rowcount == 1:
                recovered.append(candidate.id)
            continue

        cancelled = candidate.status == "cancel_requested"
        target_status = "cancelled" if cancelled else "failed"
        if reconciliation:
            error_message = (
                f"{message}; result/artifact reconciliation required before retry"
            )
        elif cancelled:
            error_message = f"{message}; cancellation completed"
        else:
            error_message = f"infrastructure retry limit reached: {message}"
        result = session.execute(
            update(SimulationTask)
            .where(*common_predicates)
            .values(
                status=target_status,
                progress=100,
                artifact_status=(
                    "reconciliation_required"
                    if reconciliation
                    else candidate.artifact_status
                ),
                error_message=error_message,
                last_infrastructure_error=(None if cancelled else message),
                infrastructure_retry_count=(
                    SimulationTask.infrastructure_retry_count
                    if cancelled
                    else SimulationTask.infrastructure_retry_count + 1
                ),
                last_execution_token=candidate.active_execution_token,
                active_execution_token=None,
                worker_id=None,
                queue_job_id=None,
                end_time=datetime.now(UTC),
            )
        )
        if result.rowcount != 1:
            continue
        if reconciliation:
            session.execute(
                update(HydraulicTaskArtifact)
                .where(
                    HydraulicTaskArtifact.task_id == candidate.id,
                    HydraulicTaskArtifact.status.in_(("prepared", "publishing")),
                )
                .values(status="reconciliation_required")
            )
        recovered.append(candidate.id)
    session.commit()
    return recovered


__all__ = [
    "DuplicateClaimError",
    "FINALIZATION_ARTIFACT_STATES",
    "FINALIZATION_PHASES",
    "InvalidTaskRouteError",
    "MAX_INFRASTRUCTURE_RETRIES",
    "StaleExecutionError",
    "cancellation_requested",
    "claim_task",
    "claim_v4_task",
    "handle_infrastructure_failure",
    "heartbeat",
    "lock_attempt_for_finalization",
    "persist_legacy_result_with_attempt_cas",
    "recover_stale_tasks",
    "request_cancel",
    "seal_successful_attempt",
    "transition_attempt_terminal",
]
