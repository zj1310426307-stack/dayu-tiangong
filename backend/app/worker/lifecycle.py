"""Database-owned leases, cancellation, retry, and CAS finalization."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from app.gis.models import SimulationTask
from model.hydraulic_1d.contracts import HYDRAULIC_1D_INPUT_SCHEMA
from model.hydraulic_1d.execution_lease import (
    Hydraulic1DAttemptRecoveryOutcome,
    hydraulic_1d_attempt_job_id,
    recover_configured_hydraulic_1d_attempt,
)
from model.hydraulic_1d.registry import task_engine_provenance


MAX_INFRASTRUCTURE_RETRIES = 2
ORPHAN_RECOVERY_FAILURE_CODE = "MASCARET_ORPHAN_RECOVERY_UNCONFIRMED"
_MISSING_WORKSPACE_SAFE_PHASES = frozenset(
    {
        "validating_snapshot",
        "validated",
        "parsing",
        "complete",
        "finalizing",
        "persisting",
    }
)


class DuplicateClaimError(RuntimeError):
    """The queued task was already claimed or is no longer executable."""


class InvalidTaskRouteError(RuntimeError):
    """The frozen task does not match the registered Standard 1D adapter route."""


class StaleExecutionError(RuntimeError):
    """The current worker no longer owns the active execution token."""


class _DeferredCommitSession:
    """Convert persistence commit into a flush so the attempt CAS owns success."""

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
            "execution_phase": task.execution_phase,
        }
        self.final_values: dict[str, object] | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    def commit(self) -> None:
        """Capture intended terminal values without publishing success early."""

        if self.final_values is not None:
            raise RuntimeError("result persistence attempted multiple commits")
        self.final_values = {
            "status": self._task.status,
            "progress": self._task.progress,
            "diagnostics": self._task.diagnostics,
            "result_path": self._task.result_path,
            "end_time": self._task.end_time,
            "heartbeat_time": self._task.heartbeat_time,
            "execution_phase": self._task.execution_phase,
        }
        for key, value in self._initial.items():
            setattr(self._task, key, value)
        self._session.flush()

    def refresh(self, _instance: object, *args: object, **kwargs: object) -> None:
        """Delay refresh until after the real transaction commit."""

        return None


def _claim_values(worker_id: str) -> dict[str, object]:
    """Build the atomic values for one new external-engine attempt."""

    now = datetime.now(UTC)
    return {
        "status": "running",
        "progress": 5,
        "worker_id": worker_id,
        "start_time": now,
        "end_time": None,
        "heartbeat_time": now,
        "execution_phase": "validating_snapshot",
        "error_message": None,
        "cancel_requested": False,
        "execution_attempt_count": SimulationTask.execution_attempt_count + 1,
        "active_execution_token": uuid4().hex,
    }


def _reject_bad_route(
    session: Session,
    task: SimulationTask,
    message: str,
) -> None:
    """Make an obsolete or tampered queued task terminal instead of redelivering it."""

    result = session.execute(
        update(SimulationTask)
        .where(
            SimulationTask.id == task.id,
            SimulationTask.status == "queued",
            SimulationTask.active_execution_token.is_(None),
        )
        .values(
            status="failed",
            progress=100,
            queue_job_id=None,
            execution_phase="validating_snapshot",
            error_message=message[:4000],
            end_time=datetime.now(UTC),
            heartbeat_time=datetime.now(UTC),
        )
    )
    if result.rowcount == 1:
        session.commit()
        raise InvalidTaskRouteError(message)
    session.rollback()
    raise DuplicateClaimError("task route changed while it was being rejected")


def claim_task(session: Session, task_id: int, worker_id: str) -> SimulationTask:
    """Claim exactly one registered Standard 1D task and issue an execution token."""

    observed = session.get(SimulationTask, task_id)
    if observed is None or observed.status != "queued":
        raise DuplicateClaimError("task is not queued or was already claimed")
    if observed.input_schema_version != HYDRAULIC_1D_INPUT_SCHEMA:
        _reject_bad_route(
            session,
            observed,
            "LEGACY_ENGINE_RETIRED: historical custom-solver tasks cannot execute",
        )
    expected = task_engine_provenance()
    route_fields = tuple(expected)
    mismatches = [
        f"{field}: task={getattr(observed, field)!r}, registered={expected[field]!r}"
        for field in route_fields
        if getattr(observed, field) != expected[field]
    ]
    if mismatches:
        _reject_bad_route(
            session,
            observed,
            "STANDARD_1D_ROUTE_MISMATCH: " + "; ".join(mismatches),
        )
    result = session.execute(
        update(SimulationTask)
        .where(
            SimulationTask.id == task_id,
            SimulationTask.status == "queued",
            SimulationTask.input_schema_version == HYDRAULIC_1D_INPUT_SCHEMA,
            *(getattr(SimulationTask, field) == expected[field] for field in route_fields),
        )
        .values(**_claim_values(worker_id))
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


def heartbeat(
    session: Session,
    task_id: int,
    *,
    execution_token: str,
    progress: int,
    execution_phase: str | None = None,
) -> None:
    """Allow only the active, non-cancelled attempt to update generic progress."""

    bounded_progress = max(0, min(progress, 99))
    values: dict[str, object] = {
        "heartbeat_time": datetime.now(UTC),
        "progress": case(
            (SimulationTask.progress > bounded_progress, SimulationTask.progress),
            else_=bounded_progress,
        ),
    }
    if execution_phase is not None:
        values["execution_phase"] = execution_phase[:32]
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
    session: Session,
    task_id: int,
    *,
    execution_token: str,
) -> bool:
    """Treat cancellation, terminal state, disappearance, or token drift as stop."""

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
    return bool(row.cancel_requested or row.status != "running")


def request_cancel(session: Session, task: SimulationTask) -> SimulationTask:
    """CAS-cancel queued work or signal one running external process."""

    task_id = task.id
    now = datetime.now(UTC)
    result = session.execute(
        update(SimulationTask)
        .where(SimulationTask.id == task_id, SimulationTask.status == "queued")
        .values(
            status="cancelled",
            progress=100,
            cancel_requested=True,
            execution_phase="finalizing",
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
    commit: bool = True,
) -> bool:
    """Complete a failed/cancelled attempt with token-and-status CAS."""

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
        predicates.append(SimulationTask.status.in_(("running", "cancel_requested")))
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
    result = session.execute(update(SimulationTask).where(*predicates).values(**values))
    if result.rowcount != 1:
        if commit:
            session.rollback()
        return False
    if commit:
        session.commit()
    return True


def lock_attempt_for_finalization(
    session: Session,
    task_id: int,
    *,
    execution_token: str,
) -> SimulationTask:
    """Serialize success publication against cancel and stale-worker recovery."""

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


def persist_result_with_attempt_cas(
    session: Session,
    task: SimulationTask,
    engine_result: Any,
    *,
    execution_token: str,
    persist: Callable[[Any, SimulationTask, Any], object],
) -> None:
    """Persist result rows and publish success in one attempt-owned transaction."""

    if (
        task.status != "running"
        or task.cancel_requested
        or task.active_execution_token != execution_token
    ):
        session.rollback()
        raise StaleExecutionError("attempt is no longer eligible for success")
    deferred = _DeferredCommitSession(session, task)
    persist(deferred, task, engine_result)
    if deferred.final_values is None:
        session.rollback()
        raise RuntimeError("result persistence did not reach its commit boundary")
    final_values = deferred.final_values
    if final_values["status"] != "success" or final_values["progress"] != 100:
        session.rollback()
        raise RuntimeError("result persistence produced an invalid success state")
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
            execution_phase=final_values["execution_phase"],
            error_message=None,
            last_execution_token=execution_token,
            active_execution_token=None,
        )
        .execution_options(synchronize_session=False)
    )
    if finalized.rowcount != 1:
        session.rollback()
        raise StaleExecutionError("final success rejected for stale/cancelled attempt")
    session.commit()
    session.expire_all()


def handle_infrastructure_failure(
    session: Session,
    task_id: int,
    *,
    execution_token: str,
    message: str,
    maximum_retries: int = MAX_INFRASTRUCTURE_RETRIES,
) -> str:
    """Requeue bounded infrastructure failures without retrying model/runtime errors."""

    session.expire_all()
    task = session.get(SimulationTask, task_id)
    if task is None or task.active_execution_token != execution_token:
        session.rollback()
        return "stale"
    if task.status == "cancel_requested" or task.cancel_requested:
        return (
            "cancelled"
            if transition_attempt_terminal(
                session,
                task_id,
                execution_token=execution_token,
                status="cancelled",
                message=message,
            )
            else "stale"
        )
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
                diagnostics=None,
                result_path=None,
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
    """Recover exact external resources before invalidating a stale DB lease."""

    cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
    candidates = session.execute(
        select(
            SimulationTask.id,
            SimulationTask.status,
            SimulationTask.active_execution_token,
            SimulationTask.heartbeat_time,
            SimulationTask.infrastructure_retry_count,
            SimulationTask.input_schema_version,
            SimulationTask.execution_attempt_count,
            SimulationTask.execution_phase,
        ).where(
            SimulationTask.status.in_(("running", "cancel_requested")),
            SimulationTask.heartbeat_time < cutoff,
        )
    ).all()
    recovered: list[int] = []
    for candidate in candidates:
        token_predicate = (
            SimulationTask.active_execution_token == candidate.active_execution_token
            if candidate.active_execution_token is not None
            else SimulationTask.active_execution_token.is_(None)
        )
        predicates = (
            SimulationTask.id == candidate.id,
            SimulationTask.status == candidate.status,
            token_predicate,
            SimulationTask.heartbeat_time == candidate.heartbeat_time,
            SimulationTask.heartbeat_time < cutoff,
            SimulationTask.infrastructure_retry_count
            == candidate.infrastructure_retry_count,
        )
        locked = session.scalar(
            select(SimulationTask).where(*predicates).with_for_update()
        )
        if locked is None:
            session.rollback()
            continue
        current_schema = locked.input_schema_version == HYDRAULIC_1D_INPUT_SCHEMA
        recovery = Hydraulic1DAttemptRecoveryOutcome(
            True,
            "legacy task has no MASCARET runtime",
        )
        if current_schema:
            token = locked.active_execution_token
            if not token or locked.execution_attempt_count < 1:
                recovery = Hydraulic1DAttemptRecoveryOutcome(
                    False,
                    "stale task lacks an exact execution lease identity",
                )
            else:
                try:
                    recovery = recover_configured_hydraulic_1d_attempt(
                        job_id=hydraulic_1d_attempt_job_id(
                            task_id=locked.id,
                            execution_attempt_count=locked.execution_attempt_count,
                            execution_token=token,
                        ),
                        allow_missing=(
                            locked.execution_phase in _MISSING_WORKSPACE_SAFE_PHASES
                        ),
                    )
                except Exception as exc:
                    recovery = Hydraulic1DAttemptRecoveryOutcome(
                        False,
                        f"orphan recovery raised {type(exc).__name__}: {exc}",
                    )
        if current_schema and not recovery.safe:
            message = f"{ORPHAN_RECOVERY_FAILURE_CODE}: {recovery.detail}"[:4000]
            result = session.execute(
                update(SimulationTask)
                .where(*predicates)
                .values(
                    status="failed",
                    progress=100,
                    execution_phase="orphan_recovery_failed",
                    error_message=message,
                    last_infrastructure_error=message,
                    infrastructure_retry_count=(
                        SimulationTask.infrastructure_retry_count + 1
                    ),
                    last_execution_token=candidate.active_execution_token,
                    active_execution_token=None,
                    worker_id=None,
                    queue_job_id=None,
                    heartbeat_time=datetime.now(UTC),
                    end_time=datetime.now(UTC),
                )
            )
            if result.rowcount == 1:
                recovered.append(candidate.id)
                session.commit()
            else:
                session.rollback()
            continue
        can_requeue = (
            locked.status == "running"
            and current_schema
            and locked.infrastructure_retry_count < MAX_INFRASTRUCTURE_RETRIES
        )
        if can_requeue:
            now = datetime.now(UTC)
            result = session.execute(
                update(SimulationTask)
                .where(*predicates)
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
                    diagnostics=None,
                    result_path=None,
                    retry_reason=(
                        "worker heartbeat stale; " + recovery.detail
                    )[:4000],
                    error_message=None,
                    last_infrastructure_error=(
                        "worker heartbeat stale; " + recovery.detail
                    )[:4000],
                    infrastructure_retry_count=(
                        SimulationTask.infrastructure_retry_count + 1
                    ),
                    last_execution_token=candidate.active_execution_token,
                    active_execution_token=None,
                )
            )
        else:
            cancelled = locked.status == "cancel_requested"
            message = (
                "worker heartbeat stale; cancellation completed after runtime recovery"
                if cancelled
                else (
                    "LEGACY_ENGINE_RETIRED"
                    if not current_schema
                    else "infrastructure retry limit reached: worker heartbeat stale"
                )
            )
            result = session.execute(
                update(SimulationTask)
                .where(*predicates)
                .values(
                    status="cancelled" if cancelled else "failed",
                    progress=100,
                    error_message=message,
                    last_infrastructure_error=None if cancelled else message,
                    last_execution_token=candidate.active_execution_token,
                    active_execution_token=None,
                    worker_id=None,
                    queue_job_id=None,
                    end_time=datetime.now(UTC),
                )
            )
        if result.rowcount == 1:
            recovered.append(candidate.id)
            session.commit()
        else:
            session.rollback()
    return recovered


__all__ = [
    "DuplicateClaimError",
    "InvalidTaskRouteError",
    "MAX_INFRASTRUCTURE_RETRIES",
    "ORPHAN_RECOVERY_FAILURE_CODE",
    "StaleExecutionError",
    "cancellation_requested",
    "claim_task",
    "handle_infrastructure_failure",
    "heartbeat",
    "lock_attempt_for_finalization",
    "persist_result_with_attempt_cas",
    "recover_stale_tasks",
    "request_cancel",
    "transition_attempt_terminal",
]
