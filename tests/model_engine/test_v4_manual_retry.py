"""Manual retry eligibility and complete telemetry reset tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.model_engine import router
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
        "last_delivery_time",
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
        "delivery_attempt_count",
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


def test_initial_broker_failure_leaves_a_bounded_recovery_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = SimpleNamespace(
        id=9,
        status="pending",
        queued_time=None,
        delivery_attempt_count=0,
        last_delivery_time=None,
        queue_job_id="stale-marker",
        last_infrastructure_error=None,
    )
    commits = 0

    class Session:
        def get(self, _model: object, task_id: int) -> object:
            assert task_id == task.id
            return task

        def commit(self) -> None:
            nonlocal commits
            commits += 1

    def unavailable(_task: object) -> object:
        raise ConnectionError("injected broker failure")

    monkeypatch.setattr(router, "_deliver", unavailable)
    with pytest.raises(HTTPException) as error:
        router.enqueue_task(task.id, Session())  # type: ignore[arg-type]
    assert error.value.status_code == 503
    assert task.status == "queued"
    assert task.queue_job_id is None
    assert task.delivery_attempt_count == 1
    assert task.last_delivery_time == task.queued_time
    assert "recovery pending" in task.last_infrastructure_error
    assert commits == 2
