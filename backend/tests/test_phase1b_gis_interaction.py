"""PostGIS-backed acceptance tests for Phase 1B GIS interaction frames."""

from __future__ import annotations

from datetime import UTC, datetime
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database.session import SessionLocal
from app.gis.models import (
    CrossSection,
    DatasetVersion,
    DispatchPlan,
    DispatchRun,
    Gate,
    SimulationCase,
    SimulationResult,
    SimulationTask,
    StructureResult,
)
from app.main import app


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGIS_TESTS") != "1",
    reason="requires the migrated local PostGIS service",
)
client = TestClient(app)


def _build_interaction_fixture() -> tuple[int, int, int, int]:
    """Create a minimal dynamic frame with two times and one simulated gate."""

    with SessionLocal() as session:
        case = session.scalar(select(SimulationCase).order_by(SimulationCase.id))
        assert case is not None
        section = session.scalar(
            select(CrossSection)
            .where(CrossSection.dataset_version_id == case.dataset_version_id)
            .order_by(CrossSection.id)
        )
        gate = session.scalar(
            select(Gate)
            .where(Gate.dataset_version_id == case.dataset_version_id)
            .order_by(Gate.id)
        )
        assert section is not None and gate is not None
        task = SimulationTask(
            case_id=case.id,
            dataset_version_id=case.dataset_version_id,
            status="success",
            progress=100,
            config={},
            end_time=datetime.now(UTC),
        )
        session.add(task)
        session.flush()
        session.add_all(
            [
                SimulationResult(
                    task_id=task.id,
                    section_id=section.id,
                    river_id=section.river_id,
                    section_code=section.section_code,
                    station=section.station,
                    time_seconds=time_seconds,
                    water_level=water_level,
                    flow=42.0,
                    velocity=velocity,
                )
                for time_seconds, water_level, velocity in (
                    (0.0, 11.0, 0.2),
                    (3600.0, 12.4, -1.8),
                )
            ]
        )
        plan = DispatchPlan(
            dataset_version_id=case.dataset_version_id,
            simulation_case_id=case.id,
            name=f"PHASE1B {datetime.now(UTC).timestamp()}",
            version=1,
            status="frozen",
            duration_seconds=3600,
            evaluation_config={"warning_level": 11.5, "danger_level": 12.0},
            storage_level="full",
            created_by="phase1b-test",
        )
        session.add(plan)
        session.flush()
        run = DispatchRun(
            plan_id=plan.id,
            controlled_task_id=task.id,
            status="success",
            progress=100,
        )
        session.add(run)
        session.flush()
        session.add(
            StructureResult(
                task_id=task.id,
                dispatch_run_id=run.id,
                time_seconds=3600,
                structure_type="gate",
                structure_id=gate.id,
                requested_value=1.2,
                actual_value=1.0,
                flow=15.0,
                power_kw=None,
                constraint_flags=["opening_rate_limited"],
            )
        )
        session.commit()
        return case.dataset_version_id, task.id, run.id, plan.id


def _delete_interaction_fixture(task_id: int, run_id: int, plan_id: int) -> None:
    """Delete acceptance rows in foreign-key-safe order."""

    with SessionLocal() as session:
        session.query(StructureResult).filter(
            StructureResult.dispatch_run_id == run_id
        ).delete()
        run = session.get(DispatchRun, run_id)
        if run is not None:
            session.delete(run)
        session.flush()
        task = session.get(SimulationTask, task_id)
        if task is not None:
            session.delete(task)
        session.flush()
        plan = session.get(DispatchPlan, plan_id)
        if plan is not None:
            session.delete(plan)
        session.commit()


def test_interaction_frame_aligns_time_and_simulated_structure_state() -> None:
    """One response must align hydraulic and dispatch overlays to one version/time."""

    version_id, task_id, run_id, plan_id = _build_interaction_fixture()
    try:
        response = client.get(
            "/api/v1/gis/interaction-frame",
            params={
                "dataset_version_id": version_id,
                "task_id": task_id,
                "dispatch_run_id": run_id,
                "time_seconds": 3500,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["dataset_version_id"] == version_id
        assert payload["timeline"] == [0.0, 3600.0]
        assert payload["selected_time_seconds"] == 3600.0
        assert payload["threshold_source"] == "dispatch_plan"
        assert payload["water_samples"][0]["risk_level"] == "danger"
        assert payload["water_samples"][0]["velocity_level"] == "high"
        assert payload["water_samples"][0]["flow_direction"] == "upstream"
        assert 0 <= payload["water_samples"][0]["flow_bearing_degrees"] < 360
        assert payload["structure_samples"][0]["state"] == "open"
        assert payload["structure_samples"][0]["constraint_flags"] == [
            "opening_rate_limited"
        ]
    finally:
        _delete_interaction_fixture(task_id, run_id, plan_id)


def test_interaction_frame_rejects_cross_version_and_cross_run_mixing() -> None:
    """A task cannot be paired with another version or another run."""

    version_id, task_id, run_id, plan_id = _build_interaction_fixture()
    other_task_id = 0
    other_version_id = 0
    try:
        with SessionLocal() as session:
            case = session.scalar(
                select(SimulationCase).where(
                    SimulationCase.dataset_version_id == version_id
                )
            )
            assert case is not None
            other_task = SimulationTask(
                case_id=case.id,
                dataset_version_id=case.dataset_version_id,
                status="success",
                progress=100,
                config={},
            )
            other_version = DatasetVersion(
                version=f"phase1b-{datetime.now(UTC).timestamp()}",
                name="Phase 1B isolation test",
                creator="phase1b-test",
            )
            session.add_all((other_task, other_version))
            session.commit()
            other_task_id = other_task.id
            other_version_id = other_version.id

        mismatched_task = client.get(
            "/api/v1/gis/interaction-frame",
            params={
                "dataset_version_id": version_id,
                "task_id": other_task_id,
                "dispatch_run_id": run_id,
            },
        )
        assert mismatched_task.status_code == 409
        assert "受控任务" in mismatched_task.json()["detail"]

        mismatched_version = client.get(
            "/api/v1/gis/interaction-frame",
            params={
                "dataset_version_id": other_version_id,
                "task_id": task_id,
            },
        )
        assert mismatched_version.status_code == 409
        assert "数据版本" in mismatched_version.json()["detail"]
    finally:
        with SessionLocal() as session:
            other_task = session.get(SimulationTask, other_task_id)
            if other_task is not None:
                session.delete(other_task)
            other_version = session.get(DatasetVersion, other_version_id)
            if other_version is not None:
                session.delete(other_version)
            session.commit()
        _delete_interaction_fixture(task_id, run_id, plan_id)
