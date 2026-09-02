"""Solver-neutral execution-lease operations used by backend workers."""

from __future__ import annotations

from model.hydraulic_1d.mascaret.config import MascaretRuntimeConfig
from model.hydraulic_1d.mascaret.runtime_recovery import (
    AttemptRecoveryOutcome as Hydraulic1DAttemptRecoveryOutcome,
)
from model.hydraulic_1d.mascaret.runtime_recovery import recover_abandoned_attempt
from model.hydraulic_1d.mascaret.workspace import mascaret_attempt_job_id
from model.hydraulic_1d.dflow_fm.config import DFlowRuntimeConfig
from model.hydraulic_1d.dflow_fm.runtime import ContainerDFlowRuntime, create_dflow_runtime
from model.hydraulic_1d.dflow_fm.workspace import DFlowJobWorkspace


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
    task_kind: str = "standard_1d",
) -> Hydraulic1DAttemptRecoveryOutcome:
    """Recover the configured engine's external resources behind a neutral seam."""

    if task_kind == "controlled_hydraulic_preview":
        config = DFlowRuntimeConfig.from_environment()
        matches: list[DFlowJobWorkspace] = []
        root = config.workspace_root.resolve()
        if root.is_dir():
            for simulation_dir in root.iterdir():
                candidate = simulation_dir / job_id
                if candidate.is_dir():
                    matches.append(DFlowJobWorkspace.open(candidate))
        if not matches:
            return Hydraulic1DAttemptRecoveryOutcome(
                allow_missing,
                "controlled D-Flow workspace is absent",
            )
        if len(matches) != 1:
            return Hydraulic1DAttemptRecoveryOutcome(
                False,
                "controlled D-Flow job id is not unique",
            )
        runtime = create_dflow_runtime(config)
        if not isinstance(runtime, ContainerDFlowRuntime):
            return Hydraulic1DAttemptRecoveryOutcome(
                False,
                "controlled orphan recovery currently requires container runtime",
            )
        try:
            runtime._after_forced_stop(matches[0])
        except Exception as exc:
            # Docker --rm may already have removed the container after the
            # worker died.  A failed owned cleanup remains unconfirmed unless
            # the lifecycle phase explicitly permits a missing runtime.
            return Hydraulic1DAttemptRecoveryOutcome(
                allow_missing,
                f"controlled D-Flow cleanup: {type(exc).__name__}: {exc}",
            )
        return Hydraulic1DAttemptRecoveryOutcome(
            True,
            "owned controlled D-Flow container removed",
        )
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
