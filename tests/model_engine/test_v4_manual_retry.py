"""Manual retry eligibility and complete telemetry reset tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.model_engine.service import (
    can_retry_task,
    manual_retry_reset_values,
    retry_block_reason,
)


def _task(**changes):
    values = {
        "status": "failed",
        "input_schema_version": "dayu.model-input.v4",
        "artifact_status": "failed",
        "active_execution_token": None,
        "manual_retry_count": 2,
        "retry_count": 17,
        "error_message": "previous attempt failed",
    }
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("changes", "eligible", "message"),
    [
        ({}, True, None),
        ({"status": "cancelled", "artifact_status": "none"}, True, None),
        ({"status": "success"}, False, "successful tasks are immutable"),
        ({"status": "running"}, False, "only failed or cancelled"),
        (
            {"active_execution_token": "active-lease"},
            False,
            "execution lease is still active",
        ),
        ({"artifact_status": "prepared"}, False, "must be reconciled"),
        ({"artifact_status": "publishing"}, False, "must be reconciled"),
        (
            {"artifact_status": "reconciliation_required"},
            False,
            "must be reconciled",
        ),
        ({"artifact_status": "orphaned"}, False, "must be reconciled"),
        ({"artifact_status": "published"}, False, "must be reconciled"),
    ],
)
def test_v4_retry_eligibility_is_fail_closed(
    changes: dict[str, object], eligible: bool, message: str | None
) -> None:
    """Allow only terminal tasks with a clean Artifact state and no active lease."""

    task = _task(**changes)
    assert can_retry_task(task) is eligible
    reason = retry_block_reason(task)
    if message is None:
        assert reason is None
    else:
        assert message in str(reason)


def test_v4_manual_retry_resets_all_runtime_telemetry_only() -> None:
    """Preserve frozen evidence while clearing every attempt-scoped value."""

    values = manual_retry_reset_values(_task())
    assert values["status"] == "queued"
    assert values["manual_retry_count"] == 3
    assert values["retry_reason"] == "previous attempt failed"
    assert values["artifact_status"] == "none"
    assert "retry_count" not in values
    for field in (
        "worker_id",
        "queue_job_id",
        "start_time",
        "end_time",
        "heartbeat_time",
        "current_simulation_time",
        "current_cfl",
        "last_event",
        "execution_phase",
        "active_execution_token",
        "error_message",
        "diagnostics",
        "result_path",
    ):
        assert values[field] is None
    for field in (
        "progress",
        "accepted_step_count",
        "numerical_retry_count",
        "cfl_reduction_count",
        "positivity_retry_count",
        "event_refinement_count",
        "gate_solver_retry_count",
        "pump_solver_retry_count",
        "minimum_dt_failure_count",
    ):
        assert values[field] == 0
    assert not {
        "input_snapshot",
        "input_snapshot_hash",
        "solver_id",
        "capability_id",
        "runtime_adapter_id",
        "runtime_projection_hash",
        "mesh_hash",
        "solver_policy_hash",
        "validation_policy_hash",
        "execution_mode",
        "comparison_group_id",
    }.intersection(values)


def test_legacy_retry_count_remains_a_compatibility_counter() -> None:
    """Keep legacy clients stable without reusing retry_count for native-v4 numerics."""

    values = manual_retry_reset_values(
        _task(input_schema_version="dayu.model-input.v3", artifact_status=None)
    )
    assert values["retry_count"] == 18
    assert values["manual_retry_count"] == 3
