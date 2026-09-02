"""Celery execution boundary for registered standard and controlled 1D routes."""

from __future__ import annotations

import socket
from collections.abc import Mapping
from hmac import compare_digest
from typing import Any

from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from app.database.session import SessionLocal
from app.hydraulic.production.gate import assert_production_gate
from app.model_engine.service import parse_frozen_task_model, persist_hydraulic_1d_result
from app.worker.celery_app import celery_app
from app.worker.lifecycle import (
    DuplicateClaimError,
    InvalidTaskRouteError,
    StaleExecutionError,
    cancellation_requested,
    claim_task,
    handle_infrastructure_failure,
    heartbeat,
    lock_attempt_for_finalization,
    persist_result_with_attempt_cas,
    transition_attempt_terminal,
)
from model.build_identity import BuildIdentityError, assert_runtime_build_matches
from model.hydraulic_1d.engine import Hydraulic1DExecutionContext
from model.hydraulic_1d.controlled import ControlledHydraulic1DRun
from model.hydraulic_1d.errors import Hydraulic1DCancelled, Hydraulic1DError
from model.hydraulic_1d.execution_lease import hydraulic_1d_attempt_job_id
from model.hydraulic_1d.factory import create_hydraulic_1d_engine
from model.hydraulic_1d.registry import DFLOW_FM_ENGINE_ID
from model.provenance import snapshot_hash


HYDRAULIC_1D_QUEUE = "hydraulic-1d"
INFRASTRUCTURE_ERRORS = (OperationalError, InterfaceError, DBAPIError)


def _finish(
    session: Any,
    task_id: int,
    *,
    execution_token: str,
    status: str,
    message: str,
) -> str:
    """Persist one terminal outcome while respecting attempt ownership."""

    session.rollback()
    changed = transition_attempt_terminal(
        session,
        task_id,
        execution_token=execution_token,
        status=status,
        message=message,
    )
    return status if changed else "stale"


@celery_app.task(
    bind=True,
    name="dayu.run_hydraulic_task",
    queue=HYDRAULIC_1D_QUEUE,
    max_retries=None,
)
def run_hydraulic_task(self, task_id: int) -> dict[str, str | int]:
    """Execute the frozen registered route and atomically persist unified results."""

    worker_id = f"{socket.gethostname()}:{self.request.id or 'eager'}:hydraulic-1d"
    with SessionLocal() as session:
        try:
            task = claim_task(session, task_id, worker_id)
        except InvalidTaskRouteError:
            return {"task_id": task_id, "status": "failed"}
        except DuplicateClaimError:
            return {"task_id": task_id, "status": "duplicate"}
        execution_token = str(task.active_execution_token or "")
        if not execution_token:
            raise StaleExecutionError("claimed task has no execution token")

        def cancelled() -> bool:
            return cancellation_requested(
                session,
                task_id,
                execution_token=execution_token,
            )

        def progress(value: float, details: dict[str, Any]) -> None:
            phase = str(details.get("phase", "running"))
            heartbeat(
                session,
                task_id,
                execution_token=execution_token,
                progress=int(value),
                execution_phase=phase,
            )

        try:
            if task.task_kind == "controlled_hydraulic_preview":
                if not isinstance(task.input_snapshot, Mapping) or not isinstance(
                    task.input_snapshot_hash, str
                ):
                    raise ValueError("controlled task snapshot or digest is missing")
                observed_hash = snapshot_hash(task.input_snapshot)
                if not compare_digest(observed_hash, task.input_snapshot_hash):
                    raise ValueError("controlled task snapshot digest mismatch")
                run = ControlledHydraulic1DRun.model_validate(task.input_snapshot)
                engine = create_hydraulic_1d_engine(DFLOW_FM_ENGINE_ID)
                run_controlled = getattr(engine, "run_controlled", None)
                if run_controlled is None:
                    raise ValueError("selected D-Flow engine lacks controlled execution")
                result = run_controlled(
                    run,
                    Hydraulic1DExecutionContext(
                        job_id=hydraulic_1d_attempt_job_id(
                            task_id=task_id,
                            execution_attempt_count=task.execution_attempt_count,
                            execution_token=execution_token,
                        ),
                        cancel_check=cancelled,
                        progress_callback=progress,
                    ),
                )
                task = lock_attempt_for_finalization(
                    session,
                    task_id,
                    execution_token=execution_token,
                )
                task.execution_phase = "persisting"
                session.flush()
                from app.dispatch.hydraulic_service import persist_controlled_result

                persist_result_with_attempt_cas(
                    session,
                    task,
                    result,
                    execution_token=execution_token,
                    persist=persist_controlled_result,
                )
                return {"task_id": task_id, "status": "success"}
            executed_build_identity = assert_runtime_build_matches(
                expected_engine_version=task.engine_version,
                expected_engine_commit=task.engine_commit,
                expected_solver_build_id=task.solver_build_id,
                expected_build_mode=task.build_mode,
                expected_verified=task.build_verified,
                expected_registry_hash=task.registry_hash,
            )
            model = parse_frozen_task_model(task)
            assert_production_gate(task.config, model, str(task.input_snapshot_hash or ""))
            result = create_hydraulic_1d_engine().run(
                model,
                Hydraulic1DExecutionContext(
                    job_id=hydraulic_1d_attempt_job_id(
                        task_id=task_id,
                        execution_attempt_count=task.execution_attempt_count,
                        execution_token=execution_token,
                    ),
                    cancel_check=cancelled,
                    progress_callback=progress,
                ),
            )
            task = lock_attempt_for_finalization(
                session,
                task_id,
                execution_token=execution_token,
            )
            task.execution_phase = "persisting"
            session.flush()
            persist_result_with_attempt_cas(
                session,
                task,
                result,
                execution_token=execution_token,
                persist=lambda active_session, active_task, active_result: (
                    persist_hydraulic_1d_result(
                        active_session,
                        active_task,
                        active_result,
                        executed_build_identity=executed_build_identity,
                    )
                ),
            )
            return {"task_id": task_id, "status": "success"}
        except Hydraulic1DCancelled as exc:
            outcome = _finish(
                session,
                task_id,
                execution_token=execution_token,
                status="cancelled",
                message=str(exc),
            )
            return {"task_id": task_id, "status": outcome}
        except StaleExecutionError as exc:
            outcome = _finish(
                session,
                task_id,
                execution_token=execution_token,
                status="cancelled",
                message=str(exc),
            )
            return {"task_id": task_id, "status": outcome}
        except (Hydraulic1DError, BuildIdentityError, ValueError) as exc:
            outcome = _finish(
                session,
                task_id,
                execution_token=execution_token,
                status="failed",
                message=str(exc),
            )
            return {"task_id": task_id, "status": outcome}
        except INFRASTRUCTURE_ERRORS as exc:
            session.rollback()
            outcome = handle_infrastructure_failure(
                session,
                task_id,
                execution_token=execution_token,
                message=f"{type(exc).__name__}: {exc}",
            )
            if outcome == "requeued":
                raise self.retry(exc=exc, countdown=5)
            return {"task_id": task_id, "status": outcome}
        except Exception as exc:
            outcome = _finish(
                session,
                task_id,
                execution_token=execution_token,
                status="failed",
                message=f"{type(exc).__name__}: {exc}",
            )
            return {"task_id": task_id, "status": outcome}


__all__ = ["HYDRAULIC_1D_QUEUE", "run_hydraulic_task"]
