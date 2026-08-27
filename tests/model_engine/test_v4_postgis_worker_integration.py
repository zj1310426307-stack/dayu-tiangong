"""Hosted D2 integration against real PostGIS, Redis, and Celery workers."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from os import getenv
from time import monotonic, sleep

import httpx
import pytest
from redis import Redis
from sqlalchemy import func, select

from app.database.session import SessionLocal
from app.gis.models import (
    BoundaryCondition,
    DatasetVersion,
    DispatchPlan,
    Gate,
    HydraulicTaskArtifact,
    HydraulicTaskControlEvent,
    HydraulicTaskGateResult,
    HydraulicTaskPumpResult,
    HydraulicTaskSectionResult,
    Pump,
    River,
    SimulationCase,
    SimulationCaseBoundary,
    SimulationTask,
)
from app.hydraulic.models import (
    HydraulicBranch,
    HydraulicCrossSection,
    HydraulicCrossSectionPoint,
    HydraulicCrossSectionProfile,
    HydraulicNetwork,
    HydraulicNode,
    HydraulicReach,
)
from app.worker.celery_app import celery_app
from app.worker.lifecycle import claim_task
from app.worker.tasks import V4_QUEUE
from model.provenance import snapshot_hash
from model.solver.registry import D1_SOLVER_ID
from tests.model_engine.helpers import native_v4_payload


pytestmark = pytest.mark.skipif(
    getenv("RUN_D2_INTEGRATION") != "1",
    reason="requires migrated PostGIS, Redis, and both Celery workers",
)

DATASET_ID = 9001
RIVER_ID = 9002
NETWORK_ID = 9011
BRANCH_ID = 9021
UPSTREAM_NODE_ID = 9031
DOWNSTREAM_NODE_ID = 9032
UPSTREAM_BOUNDARY_ID = 9041
DOWNSTREAM_BOUNDARY_ID = 9042
GATE_ID = 9051
PUMP_ID = 9061
CASE_ID = 9071
REACH_ID = 9081
PLAN_ID = 9091
SECTION_IDS = tuple(range(9101, 9121))
PROFILE_IDS = tuple(range(9201, 9221))


def _point(longitude: float, latitude: float):
    return func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4490)


def _seed_authoritative_case() -> int:
    """Seed the authoritative SimulationCase that must build the D1 v4 snapshot."""

    with SessionLocal() as session:
        source = native_v4_payload()
        source["dataset_version"]["id"] = DATASET_ID
        source["simulation_case"]["id"] = CASE_ID
        source["network"]["id"] = NETWORK_ID
        source["branches"][0].update(
            network_id=NETWORK_ID,
            branch_id=BRANCH_ID,
            upstream_node_id=UPSTREAM_NODE_ID,
            downstream_node_id=DOWNSTREAM_NODE_ID,
        )
        source["reaches"][0].update(id=REACH_ID, branch_id=BRANCH_ID)
        for ordinal, section in enumerate(source["cross_sections"]):
            section.update(
                section_id=SECTION_IDS[ordinal],
                branch_id=BRANCH_ID,
                profile_id=PROFILE_IDS[ordinal],
            )
        source["cross_section_profiles"] = [
            {
                "id": section["profile_id"],
                "cross_section_id": section["section_id"],
                "profile_hash": section["profile_hash"],
            }
            for section in source["cross_sections"]
        ]
        for ordinal, state in enumerate(source["initial_state"]["values"]):
            state["section_id"] = SECTION_IDS[ordinal]
        source["boundaries"]["upstream"]["identity"]["id"] = UPSTREAM_BOUNDARY_ID
        source["boundaries"]["upstream"]["target_node_id"] = UPSTREAM_NODE_ID
        source["boundaries"]["downstream"]["identity"]["id"] = DOWNSTREAM_BOUNDARY_ID
        source["boundaries"]["downstream"]["target_node_id"] = DOWNSTREAM_NODE_ID
        source["structures"]["gates"][0]["identity"]["id"] = GATE_ID
        source["structures"]["gates"][0]["branch_id"] = BRANCH_ID
        source["structures"]["gates"][0]["interface"] = {
            "upstream_section_id": SECTION_IDS[7],
            "downstream_section_id": SECTION_IDS[8],
        }
        source["structures"]["pumps"][0]["identity"]["id"] = PUMP_ID
        source["structures"]["pumps"][0]["branch_id"] = BRANCH_ID
        source["structures"]["pumps"][0]["section_id"] = SECTION_IDS[15]
        runtime = source["numerical_policy"]
        upstream_source = source["boundaries"]["upstream"]
        downstream_source = source["boundaries"]["downstream"]
        pump_source = source["structures"]["pumps"][0]
        gate_source = source["structures"]["gates"][0]
        version = DatasetVersion(
            id=DATASET_ID,
            version="D2-CI-1",
            name="D2 hosted integration",
            creator="github-actions",
            status="approved",
            content_hash="a" * 64,
        )
        session.add(version)
        session.flush()

        upstream_boundary = BoundaryCondition(
            id=UPSTREAM_BOUNDARY_ID,
            dataset_version_id=version.id,
            name="D2 CI upstream",
            boundary_type="upstream_flow",
            values={
                "time_seconds": upstream_source["time_seconds"],
                "flow_m3_s": upstream_source["flow_m3_s"],
            },
            unit="m3/s",
        )
        downstream_boundary = BoundaryCondition(
            id=DOWNSTREAM_BOUNDARY_ID,
            dataset_version_id=version.id,
            name="D2 CI downstream",
            boundary_type="downstream_water_level",
            values={
                "time_seconds": downstream_source["time_seconds"],
                "water_level_m": downstream_source["water_level_m"],
            },
            unit="m",
        )
        session.add_all([upstream_boundary, downstream_boundary])
        session.flush()
        simulation_case = SimulationCase(
            id=CASE_ID,
            name="D1 platform integration",
            dataset_version_id=version.id,
            boundary_condition_id=upstream_boundary.id,
            v4_configuration={
                "default_manning_n": 0.0,
                "initial_state": source["initial_state"],
                "numerical_policy": runtime,
                "known_limitations": source["known_limitations"],
            },
        )
        river = River(
            id=RIVER_ID,
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
            id=NETWORK_ID,
            dataset_version_id=version.id,
            code="NW-D1",
            name="D2 CI network",
            engineering_crs="EPSG:4547",
            vertical_datum="1985 National Height Datum",
        )
        session.add_all([simulation_case, river, network])
        session.flush()
        session.add_all(
            [
                SimulationCaseBoundary(
                    case_id=simulation_case.id,
                    boundary_condition_id=upstream_boundary.id,
                    role="upstream",
                ),
                SimulationCaseBoundary(
                    case_id=simulation_case.id,
                    boundary_condition_id=downstream_boundary.id,
                    role="downstream",
                ),
            ]
        )

        upstream = HydraulicNode(
            id=UPSTREAM_NODE_ID,
            dataset_version_id=version.id,
            network_id=network.id,
            node_code="D2-UP",
            node_type="boundary",
            geometry=_point(113.10, 23.10),
        )
        downstream = HydraulicNode(
            id=DOWNSTREAM_NODE_ID,
            dataset_version_id=version.id,
            network_id=network.id,
            node_code="D2-DOWN",
            node_type="boundary",
            geometry=_point(113.20, 23.20),
        )
        session.add_all([upstream, downstream])
        session.flush()
        upstream_boundary.hydraulic_node_id = upstream.id
        downstream_boundary.hydraulic_node_id = downstream.id
        session.flush()
        branch = HydraulicBranch(
            id=BRANCH_ID,
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

        session.add(
            HydraulicReach(
                id=REACH_ID,
                dataset_version_id=version.id,
                branch_id=branch.id,
                reach_code="R-D1",
                reach_type="channel",
                start_chainage_m=0.0,
                end_chainage_m=7600.0,
                upstream_node_id=upstream.id,
                downstream_node_id=downstream.id,
                length_m=7600.0,
                geometry=func.ST_GeomFromText(
                    "LINESTRING(113.10 23.10, 113.20 23.20)", 4490
                ),
            )
        )

        for ordinal, section_id in enumerate(SECTION_IDS, start=1):
            session.add(
                HydraulicCrossSection(
                    id=section_id,
                    dataset_version_id=version.id,
                    branch_id=branch.id,
                    section_code=f"CS{ordinal:02d}",
                    section_name=f"D2 CI section {ordinal}",
                    chainage=400.0 * (ordinal - 1),
                    chainage_source="imported",
                    location_geometry=_point(
                        113.10 + section_id / 1000.0,
                        23.10 + section_id / 1000.0,
                    ),
                    orientation_status="confirmed",
                )
            )
        session.flush()
        for ordinal, section_id in enumerate(SECTION_IDS):
            profile = HydraulicCrossSectionProfile(
                id=PROFILE_IDS[ordinal],
                dataset_version_id=version.id,
                cross_section_id=section_id,
                topography_id="D1-IDENTICAL",
                vertical_datum="1985 National Height Datum",
                default_manning_n=0.03,
                profile_hash=f"{ordinal + 1:064x}",
                is_active=True,
            )
            session.add(profile)
            session.flush()
            for sequence, (offset, elevation) in enumerate(
                ((0.0, 12.0), (10.0, 9.0), (20.0, 12.0))
            ):
                session.add(
                    HydraulicCrossSectionPoint(
                        dataset_version_id=version.id,
                        profile_id=profile.id,
                        sequence=sequence,
                        distance=offset,
                        elevation=elevation,
                    )
                )
        session.flush()

        gate = Gate(
            id=GATE_ID,
            dataset_version_id=version.id,
            name="D2 CI gate",
            gate_code="D2-CI-GATE",
            river_id=river.id,
            gate_type="sluice",
            opening_direction="vertical",
            control_mode="automatic",
            width=gate_source["width_m"],
            height=gate_source["height_m"],
            max_flow=10.0,
            bottom_elevation=gate_source["sill_elevation_m"],
            hydraulic_upstream_section_id=gate_source["interface"][
                "upstream_section_id"
            ],
            hydraulic_downstream_section_id=gate_source["interface"][
                "downstream_section_id"
            ],
            discharge_coefficient=gate_source["discharge_coefficient"],
            status="online",
            geometry=_point(113.14, 23.14),
        )
        pump = Pump(
            id=PUMP_ID,
            dataset_version_id=version.id,
            name="D2 CI pump",
            pump_code="D2-CI-PUMP",
            river_id=river.id,
            design_flow=0.01,
            head=2.2,
            power=1.0,
            efficiency_curve=pump_source["efficiency_curve"],
            head_curve=pump_source["head_curve"],
            hydraulic_section_id=pump_source["section_id"],
            curve_policy_id="d1-piecewise-linear-qh-qeta-si-v1",
            curve_unit="SI",
            curve_source_revision="D1-RC1",
            system_loss=pump_source["system_loss"],
            outlet_stage=pump_source["outlet_stage"],
            unit_count=1,
            minimum_running_units=1,
            maximum_running_units=1,
            control_mode="automatic",
            status="online",
            geometry=_point(113.18, 23.18),
        )
        normalized_curve = {
            "policy_id": pump.curve_policy_id,
            "unit": pump.curve_unit,
            "head_curve": pump_source["head_curve"],
            "efficiency_curve": pump_source["efficiency_curve"],
            "source_revision": pump.curve_source_revision,
        }
        pump.curve_hash = snapshot_hash(normalized_curve)
        session.add_all([gate, pump])
        session.flush()

        native_controls = {
            "gate_control": {
                "opening_m": gate_source["opening_m"],
                "threshold_water_level_m": gate_source["control"][
                    "threshold_water_level_m"
                ],
            },
            "pump_control": {
                key: value
                for key, value in pump_source["control"].items()
                if key != "type"
            },
        }
        frozen_snapshot = {
            "schema_version": "dayu.dispatch-plan.v1",
            "plan": {"evaluation_config": {"native_v4": native_controls}},
            "actions": [],
            "rules": [],
        }
        plan = DispatchPlan(
            id=PLAN_ID,
            dataset_version_id=version.id,
            simulation_case_id=simulation_case.id,
            name="D2 hosted D1 controls",
            version=1,
            status="frozen",
            duration_seconds=runtime["duration_seconds"],
            evaluation_config={"native_v4": native_controls},
            storage_level="full",
            created_by="github-actions",
            frozen_time=datetime.now(UTC),
            frozen_snapshot=frozen_snapshot,
            frozen_snapshot_hash=snapshot_hash(frozen_snapshot),
        )
        session.add(plan)
        session.commit()
        return plan.id


@pytest.fixture(scope="module")
def authoritative_plan_id() -> int:
    return _seed_authoritative_case()


def test_v4_task_runs_through_api_broker_worker_postgis_and_artifact(
    authoritative_plan_id: int,
) -> None:
    """Run readiness, API create/queue, Worker, PostGIS, and API reads end to end."""

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

    plan_id = authoritative_plan_id
    base_url = getenv("D2_BACKEND_URL", "http://127.0.0.1:8001")
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        readiness_response = client.get(
            f"/api/v1/model-data/simulation-cases/{CASE_ID}/input-v4/readiness",
            params={"dispatch_plan_id": plan_id},
        )
        assert readiness_response.status_code == 200, readiness_response.text
        readiness = readiness_response.json()
        assert readiness["ready"] is True, readiness
        assert readiness["errors"] == []
        assert readiness["snapshot_summary"]["section_count"] == 20

        preview_response = client.get(
            f"/api/v1/model-data/simulation-cases/{CASE_ID}/input-v4/preview",
            params={"dispatch_plan_id": plan_id},
        )
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()
        assert preview["readiness"]["ready"] is True
        assert preview["section_count"] == 20

        create_response = client.post(
            "/api/v1/model/tasks",
            json={
                "case_id": CASE_ID,
                "input_schema_version": "dayu.model-input.v4",
                "solver_id": D1_SOLVER_ID,
                "dispatch_plan_id": plan_id,
                "execution_mode": "validation",
                "storage_level": "full",
            },
        )
        assert create_response.status_code == 201, create_response.text
        created = create_response.json()
        task_id = int(created["id"])
        assert created["status"] == "pending"
        assert created["input_schema_version"] == "dayu.model-input.v4"

        enqueue_response = client.post(f"/api/v1/model/tasks/{task_id}/enqueue")
        assert enqueue_response.status_code == 200, enqueue_response.text
        assert enqueue_response.json()["status"] == "queued"

        deadline = monotonic() + 300.0
        status_payload = {}
        observed_progress: list[int] = []
        while monotonic() < deadline:
            status_response = client.get(f"/api/v1/model/tasks/{task_id}")
            assert status_response.status_code == 200, status_response.text
            status_payload = status_response.json()
            observed_progress.append(int(status_payload["progress"]))
            if status_payload["status"] in {"success", "failed", "cancelled"}:
                break
            sleep(0.5)
        assert status_payload["status"] == "success", status_payload
        assert observed_progress == sorted(observed_progress)

        summary_response = client.get(f"/api/v1/model/v4/tasks/{task_id}/summary")
        assert summary_response.status_code == 200, summary_response.text
        summary = summary_response.json()
        assert summary["result_schema_version"] == "dayu.hydraulic-result.v3"
        assert summary["section_count"] == 20
        assert summary["gate_row_count"] == 25
        assert summary["pump_row_count"] == 25
        assert summary["event_count"] == 3

        section_options = client.get(
            f"/api/v1/model/v4/tasks/{task_id}/sections"
        ).json()
        assert len(section_options) == 20
        section_result = client.get(
            f"/api/v1/model/v4/tasks/{task_id}/sections/{SECTION_IDS[0]}"
        ).json()
        assert len(section_result["time_seconds"]) == 25
        assert len(section_result["water_level_m"]) == 25
        assert len(client.get(f"/api/v1/model/v4/tasks/{task_id}/gates").json()) == 25
        assert len(client.get(f"/api/v1/model/v4/tasks/{task_id}/pumps").json()) == 25
        api_events = client.get(f"/api/v1/model/v4/tasks/{task_id}/events").json()
        assert [row["time_seconds"] for row in api_events] == [
            2940.0,
            7740.0,
            12540.0,
        ]
        artifact_rows = client.get(
            f"/api/v1/model/v4/tasks/{task_id}/artifacts"
        ).json()
        assert len(artifact_rows) == 1
        artifact_manifest = artifact_rows[0]
        download = client.get(
            f"/api/v1/model/v4/tasks/{task_id}/artifacts/"
            f"{artifact_manifest['id']}/download"
        )
        assert download.status_code == 200, download.text
        assert sha256(download.content).hexdigest() == artifact_manifest["sha256"]

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


def test_legacy_claim_accepts_pre_schema_null_tasks(
    authoritative_plan_id: int,
) -> None:
    """Preserve tasks created before input_schema_version became mandatory."""

    with SessionLocal() as session:
        legacy = SimulationTask(
            case_id=CASE_ID,
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
