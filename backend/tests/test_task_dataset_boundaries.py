"""Dataset Version query boundaries for all asynchronous task monitors."""

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.dispatch import repository as dispatch_repository
from app.dispatch.router import router as dispatch_router
from app.model_engine import service as model_service
from app.model_engine.router import router as model_router
from app.optimization import service as optimization_service
from app.optimization.router import router as optimization_router


class _Rows:
    """Return an empty SQLAlchemy-like scalar result for query construction tests."""

    def all(self) -> list[Any]:
        return []


class _CaptureSession:
    """Capture statements without requiring the optional live PostGIS test profile."""

    def __init__(self) -> None:
        self.scalar_statements: list[Any] = []
        self.scalars_statements: list[Any] = []

    def scalar(self, statement: Any) -> int:
        self.scalar_statements.append(statement)
        return 0

    def scalars(self, statement: Any) -> _Rows:
        self.scalars_statements.append(statement)
        return _Rows()


def _compiled(statement: Any) -> tuple[str, dict[str, Any]]:
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


def test_task_list_openapi_exposes_additive_dataset_version_filters() -> None:
    """Every task list accepts the shared version identity without removing old fields."""

    application = FastAPI()
    for router in (model_router, optimization_router, dispatch_router):
        application.include_router(router)
    paths = application.openapi()["paths"]
    expected = {
        "/api/v1/model/tasks": {"dataset_version_id"},
        "/api/v1/optimization/tasks": {"dataset_version_id"},
        "/api/v1/dispatch/runs": {
            "dataset_version_id", "plan_id", "status", "limit", "offset"
        },
    }
    for path, required in expected.items():
        parameters = {
            item["name"] for item in paths[path]["get"].get("parameters", [])
        }
        assert required <= parameters


def test_hydraulic_tasks_filter_through_simulation_case_dataset_version() -> None:
    """Hydraulic tasks derive version identity from their authoritative case relation."""

    session = _CaptureSession()
    assert model_service.list_tasks(
        cast(Session, session), dataset_version_id=17
    ) == []
    sql, params = _compiled(session.scalars_statements[-1])
    assert "JOIN simulation_case" in sql
    assert "simulation_case.dataset_version_id" in sql
    assert 17 in params.values()


def test_optimization_tasks_filter_on_persisted_dataset_version() -> None:
    """Optimization task monitoring must not query another Dataset Version."""

    session = _CaptureSession()
    assert optimization_service.list_tasks(
        cast(Session, session), dataset_version_id=23
    ) == []
    sql, params = _compiled(session.scalars_statements[-1])
    assert "optimization_task.dataset_version_id" in sql
    assert 23 in params.values()


def test_dispatch_runs_filter_through_dispatch_plan_dataset_version() -> None:
    """Dispatch runs inherit version identity from their authoritative plan."""

    session = _CaptureSession()
    items, total = dispatch_repository.list_runs(
        cast(Session, session), dataset_version_id=31, plan_id=None,
        status=None, limit=50, offset=0,
    )
    assert items == []
    assert total == 0
    sql, params = _compiled(session.scalars_statements[-1])
    assert "JOIN dispatch_plan" in sql
    assert "dispatch_plan.dataset_version_id" in sql
    assert 31 in params.values()


def test_omitted_dataset_filter_preserves_all_version_list_contracts() -> None:
    """Legacy callers without the additive query parameter keep all-version SQL."""

    model_session = _CaptureSession()
    assert model_service.list_tasks(cast(Session, model_session)) == []
    model_sql, _ = _compiled(model_session.scalars_statements[-1])
    assert "WHERE" not in model_sql

    optimization_session = _CaptureSession()
    assert optimization_service.list_tasks(cast(Session, optimization_session)) == []
    optimization_sql, _ = _compiled(optimization_session.scalars_statements[-1])
    assert "WHERE" not in optimization_sql

    dispatch_session = _CaptureSession()
    items, total = dispatch_repository.list_runs(
        cast(Session, dispatch_session), dataset_version_id=None, plan_id=None,
        status=None, limit=50, offset=0,
    )
    assert items == []
    assert total == 0
    dispatch_sql, _ = _compiled(dispatch_session.scalars_statements[-1])
    assert "JOIN dispatch_plan" not in dispatch_sql
