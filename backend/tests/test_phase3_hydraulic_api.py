"""Integration tests for the Phase 3 task lifecycle and persisted results."""

import os
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.database.session import SessionLocal
from app.gis.models import SimulationResult, SimulationTask
from app.main import app


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGIS_TESTS") != "1",
    reason="requires the migrated local PostGIS service",
)
client = TestClient(app)


def test_phase2_snapshot_contains_complete_phase3_inputs() -> None:
    """The immutable input snapshot must carry all solver-owned dependencies."""

    cases = client.get("/api/v1/model-data/simulation-cases").json()
    response = client.get(
        f"/api/v1/model-data/simulation-cases/{cases[0]['id']}/input"
    )

    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["schema_version"] == "dayu.model-input.v1"
    assert len(snapshot["rivers"]) == 3
    assert len(snapshot["segments"]) == 7
    assert len(snapshot["cross_sections"]) == 20
    assert {item["boundary_type"] for item in snapshot["boundary_conditions"]} >= {
        "upstream_flow",
        "downstream_water_level",
    }
    assert {item["parameter_name"] for item in snapshot["parameters"]} >= {
        "duration_seconds",
        "time_step",
        "output_interval",
        "cfl",
        "initial_water_level",
        "initial_flow",
        "minimum_depth",
    }


def test_task_api_runs_and_persists_section_results() -> None:
    """Create, run, inspect and clean up one real database-backed task."""

    cases = client.get("/api/v1/model-data/simulation-cases").json()
    created = client.post(
        "/api/v1/model/tasks",
        json={
            "case_id": cases[0]["id"],
            "duration_seconds": 600,
            "time_step_seconds": 60,
            "output_interval_seconds": 120,
            "cfl_number": 0.75,
            "initial_water_level": 10.8,
            "initial_flow": 60,
            "minimum_depth": 0.05,
        },
    )
    assert created.status_code == 201
    task_id = created.json()["id"]
    assert created.json()["status"] == "pending"
    assert created.json()["progress"] == 0

    started = time.perf_counter()
    completed = client.post(f"/api/v1/model/tasks/{task_id}/run")
    elapsed = time.perf_counter() - started
    assert completed.status_code == 200
    assert completed.json()["status"] == "success"
    assert completed.json()["progress"] == 100
    assert completed.json()["result_path"].endswith(f"task_id={task_id}")
    assert elapsed < 5.0

    task = client.get(f"/api/v1/model/tasks/{task_id}")
    assert task.status_code == 200
    assert task.json()["diagnostics"]["coordinate_system"] == "CGCS2000 (EPSG:4490)"

    result = client.get(f"/api/v1/model/results/{task_id}")
    assert result.status_code == 200
    payload = result.json()
    assert len(payload["available_sections"]) == 20
    assert len(payload["time"]) == 6
    assert len(payload["water_level"]) == 6
    assert len(payload["flow"]) == 6
    assert len(payload["velocity"]) == 6
    assert payload["time"] == sorted(payload["time"])

    selected = payload["available_sections"][-1]["section_id"]
    linked = client.get(
        f"/api/v1/model/results/{task_id}", params={"section_id": selected}
    )
    assert linked.status_code == 200
    assert linked.json()["section_id"] == selected

    with SessionLocal() as session:
        persisted = session.scalar(
            select(text("count(*)")).select_from(SimulationResult).where(
                SimulationResult.task_id == task_id
            )
        )
        assert persisted == 120
        entity = session.get(SimulationTask, task_id)
        assert entity is not None
        session.delete(entity)
        session.commit()


def test_phase3_tables_and_all_spatial_srids() -> None:
    """Audit task tables and all six spatial geometry typmods directly."""

    with SessionLocal() as session:
        tables = set(
            session.execute(
                text(
                    """
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = 'public'
                      AND tablename IN ('simulation_task', 'simulation_result')
                    """
                )
            ).scalars()
        )
        assert tables == {"simulation_task", "simulation_result"}

        srids = dict(
            session.execute(
                text(
                    """
                    SELECT f_table_name, srid FROM geometry_columns
                    WHERE f_table_name IN (
                      'river', 'river_node', 'river_segment',
                      'cross_section', 'gate', 'pump'
                    )
                    """
                )
            ).all()
        )
        assert srids == {
            "river": 4490,
            "river_node": 4490,
            "river_segment": 4490,
            "cross_section": 4490,
            "gate": 4490,
            "pump": 4490,
        }
