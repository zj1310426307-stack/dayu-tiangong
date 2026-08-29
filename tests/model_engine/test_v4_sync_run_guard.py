"""Native-v4 tasks never enter the compatibility synchronous execution path."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.model_engine import router, service
from model.solver.registry import MODEL_INPUT_V4


class _V4TaskSession:
    def __init__(self) -> None:
        self.task = SimpleNamespace(
            id=41,
            input_schema_version=MODEL_INPUT_V4,
            status="pending",
            progress=0,
        )

    def get(self, _model, task_id: int):
        assert task_id == self.task.id
        return self.task


def test_service_rejects_native_v4_before_any_sync_state_change() -> None:
    session = _V4TaskSession()

    with pytest.raises(service.TaskStateError, match="dedicated asynchronous Worker"):
        service.run_task(session, session.task.id)  # type: ignore[arg-type]

    assert session.task.status == "pending"
    assert session.task.progress == 0


def test_api_rejects_native_v4_even_when_sync_compatibility_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _V4TaskSession()
    monkeypatch.setenv("ENABLE_SYNC_MODEL_RUN", "1")

    with pytest.raises(HTTPException) as captured:
        router.run_task(session.task.id, session)  # type: ignore[arg-type]

    assert captured.value.status_code == 409
    assert "dedicated asynchronous Worker" in str(captured.value.detail)
    assert session.task.status == "pending"
