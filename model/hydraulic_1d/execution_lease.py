"""Solver-neutral execution-lease operations used by backend workers."""

from __future__ import annotations

from model.hydraulic_1d.mascaret.config import MascaretRuntimeConfig
from model.hydraulic_1d.mascaret.runtime_recovery import (
    AttemptRecoveryOutcome as Hydraulic1DAttemptRecoveryOutcome,
)
from model.hydraulic_1d.mascaret.runtime_recovery import recover_abandoned_attempt
from model.hydraulic_1d.mascaret.workspace import mascaret_attempt_job_id


def hydraulic_1d_attempt_job_id(
    *,
    task_id: int,
    execution_attempt_count: int,
    execution_token: str,
) -> str:
    """Bind a solver runtime job to one exact database execution lease."""

    return mascaret_attempt_job_id(
        task_id=task_id,
        execution_attempt_count=execution_attempt_count,
        execution_token=execution_token,
    )


def recover_configured_hydraulic_1d_attempt(
    *,
    job_id: str,
    allow_missing: bool = False,
) -> Hydraulic1DAttemptRecoveryOutcome:
    """Recover the configured engine's external resources behind a neutral seam."""

    workspace_root = MascaretRuntimeConfig.from_environment().workspace_root
    return recover_abandoned_attempt(
        workspace_root,
        job_id=job_id,
        allow_missing=allow_missing,
    )


__all__ = [
    "Hydraulic1DAttemptRecoveryOutcome",
    "hydraulic_1d_attempt_job_id",
    "recover_configured_hydraulic_1d_attempt",
]
