"""Phase 5 OpenAPI contract tests that do not require a live database."""

from fastapi.testclient import TestClient

from app.main import app


def test_phase5_routes_are_registered_in_openapi() -> None:
    """All required optimization endpoints stay visible to client generation."""

    paths = app.openapi()["paths"]
    required = {
        "/api/v1/optimization/tasks",
        "/api/v1/optimization/tasks/{task_id}",
        "/api/v1/optimization/tasks/{task_id}/run",
        "/api/v1/optimization/tasks/{task_id}/candidates",
        "/api/v1/optimization/tasks/{task_id}/pareto",
        "/api/v1/optimization/tasks/{task_id}/recommendation",
    }
    assert required <= paths.keys()


def test_phase5_create_rejects_unknown_fields_before_database_access() -> None:
    """Strict configuration schemas prevent silently ignored optimizer settings."""

    response = TestClient(app).post(
        "/api/v1/optimization/tasks",
        json={
            "name": "invalid",
            "dataset_version_id": 1,
            "simulation_case_id": 1,
            "algorithm_config": {"particle_count": 3, "unknown_knob": 1},
        },
    )
    assert response.status_code == 422
