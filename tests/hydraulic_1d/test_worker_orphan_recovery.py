"""Verify stale DB leases cannot bypass MASCARET resource recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from app.worker import lifecycle
from model.hydraulic_1d.contracts import HYDRAULIC_1D_INPUT_SCHEMA
from model.hydraulic_1d.execution_lease import Hydraulic1DAttemptRecoveryOutcome


class _Rows:
    """Expose the narrow SQLAlchemy result surface used by stale recovery."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        """Return the prebuilt candidate rows."""

        return self._rows


class _Updated:
    """Report a successful one-row compare-and-swap update."""

    rowcount = 1


class _RecoverySession:
    """Capture the terminal update while emulating a locked candidate row."""

    def __init__(self, task: SimpleNamespace) -> None:
        self.task = task
        self.update_statement: Any | None = None
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement: Any) -> Any:
        """Return candidates for SELECT and capture the final UPDATE."""

        if statement.is_select:
            return _Rows([self.task])
        self.update_statement = statement
        return _Updated()

    def scalar(self, statement: Any) -> SimpleNamespace:
        """Represent SELECT FOR UPDATE finding the unchanged exact lease."""

        assert statement.is_select
        return self.task

    def commit(self) -> None:
        """Count the transaction boundary that releases the row lock."""

        self.commits += 1

    def rollback(self) -> None:
        """Count rejected compare-and-swap attempts."""

        self.rollbacks += 1


def _running_task() -> SimpleNamespace:
    """Create one current-schema stale task with a complete execution identity."""

    return SimpleNamespace(
        id=42,
        status="running",
        active_execution_token="lease-token",
        heartbeat_time=datetime.now(UTC) - timedelta(minutes=10),
        infrastructure_retry_count=0,
        input_schema_version=HYDRAULIC_1D_INPUT_SCHEMA,
        execution_attempt_count=3,
        execution_phase="executing",
    )


def _compiled_values(session: _RecoverySession) -> dict[str, Any]:
    """Return literal update parameters captured from the lifecycle statement."""

    assert session.update_statement is not None
    return session.update_statement.compile().params


def test_stale_attempt_requeues_only_after_exact_workspace_recovery(
    monkeypatch,
) -> None:
    """A safe process/workspace outcome is a hard prerequisite for requeue."""

    task = _running_task()
    session = _RecoverySession(task)
    observed: dict[str, Any] = {}

    def recover(*, job_id: str, allow_missing: bool) -> Hydraulic1DAttemptRecoveryOutcome:
        """Record the exact lease identity and approve resource cleanup."""

        observed.update(job_id=job_id, allow_missing=allow_missing)
        return Hydraulic1DAttemptRecoveryOutcome(
            True,
            "owned process stopped; workspace removed",
        )

    monkeypatch.setattr(lifecycle, "recover_configured_hydraulic_1d_attempt", recover)

    assert lifecycle.recover_stale_tasks(session, stale_seconds=120) == [42]

    values = _compiled_values(session)
    assert values["status"] == "queued"
    assert observed == {
        "job_id": "task-42-token-lease-token-attempt-3",
        "allow_missing": False,
    }
    assert session.commits == 1
    assert session.rollbacks == 0


def test_unconfirmed_orphan_fails_closed_instead_of_requeueing(
    monkeypatch,
) -> None:
    """An ambiguous PID/container identity becomes terminal and preserves evidence."""

    task = _running_task()
    session = _RecoverySession(task)

    monkeypatch.setattr(
        lifecycle,
        "recover_configured_hydraulic_1d_attempt",
        lambda **_kwargs: Hydraulic1DAttemptRecoveryOutcome(
            False,
            "launcher PID was reused; nothing was killed",
        ),
    )

    assert lifecycle.recover_stale_tasks(session, stale_seconds=120) == [42]

    values = _compiled_values(session)
    assert values["status"] == "failed"
    assert values["execution_phase"] == "orphan_recovery_failed"
    assert lifecycle.ORPHAN_RECOVERY_FAILURE_CODE in values["error_message"]
    assert session.commits == 1
    assert session.rollbacks == 0
