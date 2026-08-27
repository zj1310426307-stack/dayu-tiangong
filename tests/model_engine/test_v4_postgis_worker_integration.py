"""Hosted D2 integration against real PostGIS, Redis, and Celery workers."""

from __future__ import annotations

from datetime import UTC, datetime
from os import getenv
from time import monotonic, sleep

import pytest
from redis import Redis
from sqlalchemy import func, select

from app.database.session import SessionLocal
from app.gis.models import (
    BoundaryCondition,
    DatasetVersion,
    Gate,
    HydraulicTaskArtifact,
    HydraulicTaskControlEvent,
    HydraulicTaskGateResult,
    HydraulicTaskPumpResult,
    HydraulicTaskSectionResult,
    Pump,
    River,
    SimulationCase,
    SimulationTask,
)
from app.hydraulic.models import (
    HydraulicBranch,
    HydraulicCrossSection,
    HydraulicNetwork,
    HydraulicNode,
)
from app.worker.celery_app import celery_app
from app.worker.lifecycle import claim_task
from app.worker.tasks import V4_QUEUE, run_hydraulic_v4_task
from model.adapters import project_v4_to_v4_lite
from model.provenance import snapshot_hash
from model.solver.registry import (
    D1_CAPABILITY_ID,
    D1_RUNTIME_ADAPTER_ID,
    D1_SOLVER_ID,
)
from tests.model_engine.helpers import native_v4_payload


pytestmark = pytest.mark.skipif(
    getenv("RUN_D2_INTEGRATION") != "1",
    reason="requires migrated PostGIS, Redis, and both Celery workers",
)


def _point(longitude: float, latitude: float):
    return func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4490)


def _seed_authoritative_identities() -> int:
    """Seed only the platform identities required by frozen D1 v4 evidence."""

    with SessionLocal() as session:
        version = DatasetVersion(
            id=1,
            version="D2-CI-1",
            name="D2 hosted integration",
            creator="github-actions",
            status="approved",
            content_hash="a" * 64,
        )
        session.add(version)
        session.flush()

        boundary = BoundaryCondition(
            id=41,
            dataset_version_id=version.id,
            name="D2 CI upstream",
            boundary_type="upstream_flow",
            values={"value": 0.0},
            unit="m3/s",
        )
        session.add(boundary)
        session.flush()
        simulation_case = SimulationCase(
            id=71,
            name="D2 hosted Worker integration",
            dataset_version_id=version.id,
            boundary_condition_id=boundary.id,
        )
        river = River(
            id=1,
            dataset_version_id=version.id,
            name="D2 CI river",
            code="D2-CI-RIVER",
            length=7600.0,
            level="validation",
            status="active",
            geometry=func.ST_GeomFromText(
                "LINESTRING(113.10 23.10, 113.20 23.20)", 4490
            ),
        )
        network = HydraulicNetwork(
            id=11,
            dataset_version_id=version.id,
            code="NW-D1",
            name="D2 CI network",
            engineering_crs="EPSG:4547",
            vertical_datum="1985 National Height Datum",
        )
        session.add_all([simulation_case, river, network])
        session.flush()

        upstream = HydraulicNode(
            id=31,
            dataset_version_id=version.id,
            network_id=network.id,
            node_code="D2-UP",
            node_type="boundary",
            geometry=_point(113.10, 23.10),
        )
        downstream = HydraulicNode(
            id=32,
            dataset_version_id=version.id,
            network_id=network.id,
            node_code="D2-DOWN",
            node_type="boundary",
            geometry=_point(113.20, 23.20),
        )
        session.add_all([upstream, downstream])
        session.flush()
        branch = HydraulicBranch(
            id=21,
            dataset_version_id=version.id,
            network_id=network.id,
            branch_code="B-001",
            river_name=river.name,
            branch_name="D2 CI branch",
            upstream_node_id=upstream.id,
            downstream_node_id=downstream.id,
            start_chainage=0.0,
            end_chainage=7600.0,
            length_m=7600.0,
            direction_status="confirmed",
            geometry=func.ST_GeomFromText(
                "LINESTRING(113.10 23.10, 113.20 23.20)", 4490
            ),
        )
        session.add(branch)
        session.flush()

        for section_id in range(1, 21):
            session.add(
                HydraulicCrossSection(
                    id=section_id,
                    dataset_version_id=version.id,
                    branch_id=branch.id,
                    section_code=f"CS{section_id:02d}",
                    section_name=f"D2 CI section {section_id}",
                    chainage=400.0 * (section_id - 1),
                    chainage_source="imported",
                    location_geometry=_point(
                        113.10 + section_id / 1000.0,
                        23.10 + section_id / 1000.0,
                    ),
                    orientation_status="confirmed",
                )
            )
        session.flush()

        gate = Gate(
            id=51,
            dataset_version_id=version.id,
            name="D2 CI gate",
            gate_code="D2-CI-GATE",
            river_id=river.id,
            gate_type="sluice",
            opening_direction="vertical",
            control_mode="automatic",
            width=4.0,
            height=2.0,
            max_flow=10.0,
            bottom_elevation=9.0,
            hydraulic_upstream_section_id=8,
            hydraulic_downstream_section_id=9,
            discharge_coefficient=0.62,
            status="online",
            geometry=_point(113.14, 23.14),
        )
        pump = Pump(
            id=61,
            dataset_version_id=version.id,
            name="D2 CI pump",
            pump_code="D2-CI-PUMP",
            river_id=river.id,
            design_flow=0.01,
            head=2.2,
            power=1.0,
            efficiency_curve={"points": [[0.0001, 0.55], [0.003, 0.82], [0.01, 0.70]]},
            head_curve={"points": [[0.0001, 2.2], [0.003, 1.8], [0.01, 1.0]]},
            hydraulic_section_id=16,
            unit_count=1,
            minimum_running_units=1,
            maximum_running_units=1,
            control_mode="automatic",
            status="online",
            geometry=_point(113.18, 23.18),
        )
        session.add_all([gate, pump])
        session.flush()

        projection = project_v4_to_v4_lite(native_v4_payload())
        snapshot = projection.source_snapshot
        task = SimulationTask(
            case_id=simulation_case.id,
            status="queued",
            progress=0,
            config={"storage_level": "full"},
            input_schema_version="dayu.model-input.v4",
            input_snapshot=snapshot,
            input_snapshot_hash=snapshot_hash(snapshot),
            engine_version="dayu-hydraulic-mvp",
            engine_commit="cc6936d9d48d64c46a78ba85bed77c473e20cff3",
            solver_id=D1_SOLVER_ID,
            capability_id=D1_CAPABILITY_ID,
            runtime_adapter_id=D1_RUNTIME_ADAPTER_ID,
            runtime_projection_hash=projection.manifest["runtime_projection_hash"],
            mesh_hash=projection.manifest["mesh_hash"],
            solver_policy_hash=projection.manifest["solver_policy_hash"],
            validation_policy_hash=projection.manifest["validation_policy_hash"],
            registry_hash=projection.manifest["registry_hash"],
            artifact_status="none",
            queued_time=datetime.now(UTC),
        )
        session.add(task)
        session.commit()
        return task.id


def test_v4_task_runs_through_real_broker_worker_and_postgis() -> None:
    """Require both queues, broker delivery, durable results, and published evidence."""

    broker = getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    assert Redis.from_url(broker).ping() is True
    active_queues = {}
    deadline = monotonic() + 60.0
    while monotonic() < deadline:
        active_queues = celery_app.control.inspect(timeout=5).active_queues() or {}
        if len(active_queues) >= 2:
            break
        sleep(1.0)
    queue_sets = {
        worker: {item["name"] for item in queues}
        for worker, queues in active_queues.items()
    }
    assert any(V4_QUEUE in queues for queues in queue_sets.values()), queue_sets
    assert any("celery" in queues and V4_QUEUE not in queues for queues in queue_sets.values()), queue_sets

    task_id = _seed_authoritative_identities()
    async_result = run_hydraulic_v4_task.apply_async(args=[task_id], queue=V4_QUEUE)
    assert async_result.get(timeout=300) == {"task_id": task_id, "status": "success"}

    with SessionLocal() as session:
        task = session.get(SimulationTask, task_id)
        assert task is not None
        assert task.status == "success"
        assert task.progress == 100
        assert task.result_schema_version == "dayu.hydraulic-result.v3"
        assert task.artifact_status == "published"
        assert task.accepted_step_count == 381
        assert session.scalar(
            select(func.count(HydraulicTaskSectionResult.id)).where(
                HydraulicTaskSectionResult.task_id == task_id
            )
        ) == 500
        assert session.scalar(
            select(func.count(HydraulicTaskGateResult.id)).where(
                HydraulicTaskGateResult.task_id == task_id
            )
        ) == 25
        assert session.scalar(
            select(func.count(HydraulicTaskPumpResult.id)).where(
                HydraulicTaskPumpResult.task_id == task_id
            )
        ) == 25
        events = list(
            session.scalars(
                select(HydraulicTaskControlEvent)
                .where(HydraulicTaskControlEvent.task_id == task_id)
                .order_by(HydraulicTaskControlEvent.time_seconds)
            ).all()
        )
        assert [row.time_seconds for row in events] == [2940.0, 7740.0, 12540.0]
        artifact = session.scalar(
            select(HydraulicTaskArtifact).where(HydraulicTaskArtifact.task_id == task_id)
        )
        assert artifact is not None
        assert artifact.status == "published"
        assert artifact.record_count == 1530
        assert len(artifact.sha256) == 64


def test_legacy_claim_accepts_pre_schema_null_tasks() -> None:
    """Preserve tasks created before input_schema_version became mandatory."""

    with SessionLocal() as session:
        legacy = SimulationTask(
            case_id=71,
            status="queued",
            progress=0,
            config={},
            input_schema_version=None,
        )
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id
    with SessionLocal() as session:
        claimed = claim_task(session, legacy_id, "d2-integration-legacy")
        assert claimed.status == "running"
