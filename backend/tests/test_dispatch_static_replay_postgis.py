"""Disposable PostGIS/API integration for synthetic static Gate/Pump scheduling."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from queue import Queue
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from geoalchemy2.elements import WKTElement
import pytest
from sqlalchemy import func, select, text

from app.database.session import SessionLocal
from app.dispatch import service as dispatch_service
from app.gis.models import (
    BoundaryCondition,
    DatasetVersion,
    DispatchPlan,
    DispatchRun,
    Gate,
    Pump,
    River,
    RiverNode,
    RiverSegment,
    SimulationCase,
    SimulationTask,
)
from app.hydraulic.models import (
    HydraulicBranch,
    HydraulicNetwork,
    HydraulicNode,
    HydraulicStructure,
)
from app.main import app
from model.control.replay import (
    SYNTHETIC_INITIAL_STATE_BASIS,
    SYNTHETIC_SCHEDULE_EVALUATOR_ID,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DISPATCH_STATIC_REPLAY_POSTGIS") != "1",
    reason="requires a disposable migrated PostGIS database",
)


def _nested_keys(value: object) -> set[str]:
    """Collect response field names without matching safety-notice prose."""

    if isinstance(value, dict):
        return {str(key).lower() for key in value} | set().union(
            *(_nested_keys(item) for item in value.values()), set()
        )
    if isinstance(value, list):
        return set().union(*(_nested_keys(item) for item in value), set())
    return set()


def _fixture() -> tuple[int, int]:
    """Create one disposable legacy/unified Gate/Pump scheduling model."""

    suffix = uuid4().hex[:10]
    with SessionLocal() as session:
        version = DatasetVersion(
            version=f"DISPATCH-DEV-05-{suffix}",
            name="Dispatch synthetic replay integration",
            creator="pytest",
            status="draft",
        )
        session.add(version)
        session.flush()
        river = River(
            dataset_version_id=version.id,
            name="Synthetic dispatch river",
            code=f"DDR-{suffix}",
            length=1000.0,
            level="test",
            status="active",
            geometry=WKTElement("LINESTRING(120 30,120.01 30)", srid=4490),
        )
        session.add(river)
        session.flush()
        legacy_up = RiverNode(
            dataset_version_id=version.id,
            node_code=f"LUP-{suffix}",
            node_type="start",
            longitude=120.0,
            latitude=30.0,
            geometry=WKTElement("POINT(120 30)", srid=4490),
        )
        legacy_down = RiverNode(
            dataset_version_id=version.id,
            node_code=f"LDN-{suffix}",
            node_type="end",
            longitude=120.01,
            latitude=30.0,
            geometry=WKTElement("POINT(120.01 30)", srid=4490),
        )
        session.add_all([legacy_up, legacy_down])
        session.flush()
        segment = RiverSegment(
            dataset_version_id=version.id,
            river_id=river.id,
            segment_code=f"SEG-{suffix}",
            upstream_node_id=legacy_up.id,
            downstream_node_id=legacy_down.id,
            length=1000.0,
            geometry=WKTElement("LINESTRING(120 30,120.01 30)", srid=4490),
        )
        session.add(segment)
        session.flush()
        gate = Gate(
            dataset_version_id=version.id,
            name="Synthetic Gate",
            gate_code=f"G-{suffix}",
            river_id=river.id,
            gate_type="sluice",
            opening_direction="vertical",
            control_mode="dispatch",
            width=5.0,
            height=2.0,
            max_flow=100.0,
            bottom_elevation=0.0,
            river_segment_id=segment.id,
            station=400.0,
            upstream_node_id=legacy_up.id,
            downstream_node_id=legacy_down.id,
            minimum_opening=0.0,
            maximum_opening=2.0,
            opening_rate_limit=0.1,
            minimum_hold_seconds=0.0,
            status="online",
            geometry=WKTElement("POINT(120.004 30)", srid=4490),
        )
        pump = Pump(
            dataset_version_id=version.id,
            name="Synthetic Pump",
            pump_code=f"P-{suffix}",
            river_id=river.id,
            design_flow=2.0,
            head=3.0,
            power=50.0,
            efficiency_curve={"points": [[0.0, 0.7], [1.0, 0.8]]},
            intake_node_id=legacy_up.id,
            transfer_type="external_outflow",
            unit_count=2,
            minimum_running_units=1,
            maximum_running_units=2,
            minimum_run_seconds=60.0,
            minimum_stop_seconds=60.0,
            maximum_starts_per_run=2,
            control_mode="dispatch",
            status="online",
            geometry=WKTElement("POINT(120.006 30)", srid=4490),
        )
        session.add_all([gate, pump])
        session.flush()
        network = HydraulicNetwork(
            dataset_version_id=version.id,
            code=f"NET-{suffix}",
            name="Synthetic dispatch network",
            display_crs="EPSG:4490",
            engineering_crs="EPSG:32651",
            horizontal_unit="m",
            vertical_datum="synthetic",
            vertical_unit="m",
            source_kind="api",
            metadata_json={},
        )
        session.add(network)
        session.flush()
        unified_up = HydraulicNode(
            dataset_version_id=version.id,
            network_id=network.id,
            node_code=f"UP-{suffix}",
            node_name="Upstream",
            node_type="boundary",
            geometry=WKTElement("POINT(120 30)", srid=4490),
            metadata_json={},
        )
        unified_down = HydraulicNode(
            dataset_version_id=version.id,
            network_id=network.id,
            node_code=f"DN-{suffix}",
            node_name="Downstream",
            node_type="boundary",
            geometry=WKTElement("POINT(120.01 30)", srid=4490),
            metadata_json={},
        )
        session.add_all([unified_up, unified_down])
        session.flush()
        branch = HydraulicBranch(
            dataset_version_id=version.id,
            network_id=network.id,
            legacy_river_id=river.id,
            branch_code=f"BR-{suffix}",
            river_name=river.name,
            branch_name="Synthetic branch",
            upstream_node_id=unified_up.id,
            downstream_node_id=unified_down.id,
            start_chainage=0.0,
            end_chainage=1000.0,
            length_m=1000.0,
            direction_status="confirmed",
            geometry=WKTElement("LINESTRING(120 30,120.01 30)", srid=4490),
            metadata_json={},
        )
        session.add(branch)
        session.flush()
        session.add_all(
            [
                HydraulicStructure(
                    dataset_version_id=version.id,
                    network_id=network.id,
                    branch_id=branch.id,
                    structure_code=f"HG-{suffix}",
                    structure_name="Unified synthetic Gate",
                    structure_type="gate",
                    chainage_m=400.0,
                    location=WKTElement("POINT(120.004 30)", srid=4490),
                    width_m=5.0,
                    height_m=2.0,
                    hydraulic_law_type="none",
                    hydraulic_parameters={},
                    operation_rule_type="time_series",
                    operation_parameters={},
                    status="active",
                    metadata_json={},
                    legacy_gate_id=gate.id,
                ),
                HydraulicStructure(
                    dataset_version_id=version.id,
                    network_id=network.id,
                    branch_id=branch.id,
                    structure_code=f"HP-{suffix}",
                    structure_name="Unified synthetic Pump",
                    structure_type="pump",
                    chainage_m=600.0,
                    location=WKTElement("POINT(120.006 30)", srid=4490),
                    hydraulic_law_type="none",
                    hydraulic_parameters={},
                    operation_rule_type="time_series",
                    operation_parameters={},
                    status="active",
                    metadata_json={},
                    legacy_pump_id=pump.id,
                ),
            ]
        )
        boundary = BoundaryCondition(
            dataset_version_id=version.id,
            name=f"BC-{suffix}",
            boundary_type="upstream_discharge",
            values={"mode": "constant", "value": 1.0},
            unit="m3/s",
        )
        session.add(boundary)
        session.flush()
        case = SimulationCase(
            name=f"CASE-{suffix}",
            dataset_version_id=version.id,
            boundary_condition_id=boundary.id,
            hydraulic_1d_configuration={},
        )
        session.add(case)
        session.commit()
        return version.id, case.id


def test_frozen_v2_readiness_replay_and_runtime_fail_closed() -> None:
    """Close the API loop without creating any hydraulic task or dispatch run."""

    version_id, case_id = _fixture()
    client = TestClient(app)
    created = client.post(
        "/api/v1/dispatch/plans",
        json={
            "dataset_version_id": version_id,
            "simulation_case_id": case_id,
            "name": f"Synthetic replay {uuid4().hex[:8]}",
            "duration_seconds": 600,
            "evaluation_config": {"warning_level": 10.0},
            "storage_level": "key_sections",
            "created_by": "pytest",
        },
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    # Hold the source row so two clone statements take their initial snapshot
    # before either can allocate a version.  After release, each allocation
    # must use a fresh statement snapshot and produce a distinct version.
    with SessionLocal() as blocker:
        assert blocker.scalar(
            select(DispatchPlan)
            .where(DispatchPlan.id == plan_id)
            .with_for_update()
        ) is not None
        clone_pids: Queue[int] = Queue()

        def clone_version() -> int:
            with SessionLocal() as concurrent_session:
                pid = concurrent_session.scalar(text("SELECT pg_backend_pid()"))
                assert pid is not None
                clone_pids.put(int(pid))
                return dispatch_service.clone_plan(
                    concurrent_session, plan_id
                ).version

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(clone_version) for _ in range(2)]
            try:
                worker_pids = [clone_pids.get(timeout=10) for _ in futures]
                deadline = time.monotonic() + 10.0
                waiting = 0
                while time.monotonic() < deadline:
                    # pg_blocking_pids reads the live lock manager rather than
                    # the transaction-cached pg_stat_activity snapshot.
                    waiting = sum(
                        int(
                            blocker.scalar(
                                text(
                                    "SELECT cardinality(pg_blocking_pids(:pid))"
                                ),
                                {"pid": pid},
                            )
                            or 0
                        )
                        > 0
                        for pid in worker_pids
                    )
                    if waiting == 2:
                        break
                    time.sleep(0.05)
                both_clones_blocked = waiting == 2
            finally:
                blocker.commit()
            clone_versions = [future.result(timeout=15) for future in futures]
    assert both_clones_blocked, "both clone sessions did not reach a row-lock wait"
    assert sorted(clone_versions) == [2, 3]
    with SessionLocal() as session:
        gate = session.scalar(
            select(Gate).where(Gate.dataset_version_id == version_id)
        )
        pump = session.scalar(
            select(Pump).where(Pump.dataset_version_id == version_id)
        )
        assert gate is not None and pump is not None
        gate_id, pump_id = gate.id, pump.id
        task_count = session.scalar(select(func.count(SimulationTask.id))) or 0
        run_count = session.scalar(select(func.count(DispatchRun.id))) or 0
    action_ids: list[int] = []
    for payload in (
        {
            "sequence": 1,
            "time_seconds": 0,
            "structure_type": "gate",
            "gate_id": gate_id,
            "command_type": "gate_opening_m",
            "target_value": 0.5,
            "interpolation": "step",
            "priority": 1,
        },
        {
            "sequence": 2,
            "time_seconds": 0,
            "structure_type": "pump",
            "pump_id": pump_id,
            "command_type": "pump_enabled",
            "target_value": 1,
            "interpolation": "step",
            "priority": 1,
        },
        {
            "sequence": 3,
            "time_seconds": 100,
            "structure_type": "gate",
            "gate_id": gate_id,
            "command_type": "gate_opening_m",
            "target_value": 0.6,
            "interpolation": "step",
            "priority": 1,
        },
    ):
        response = client.post(
            f"/api/v1/dispatch/plans/{plan_id}/actions", json=payload
        )
        assert response.status_code == 201, response.text
        action_ids.append(response.json()["id"])
    conflict = client.patch(
        f"/api/v1/dispatch/actions/{action_ids[2]}",
        json={"time_seconds": 0},
    )
    assert conflict.status_code == 409, conflict.text
    action_rows = client.get(
        f"/api/v1/dispatch/plans/{plan_id}/actions"
    ).json()
    assert next(item for item in action_rows if item["id"] == action_ids[2])[
        "time_seconds"
    ] == 100
    rule = client.post(
        f"/api/v1/dispatch/plans/{plan_id}/rules",
        json={
            "name": "Synthetic elapsed-time override",
            "enabled": True,
            "observation_type": "elapsed_time",
            "operator": ">=",
            "threshold": 300,
            "hysteresis": 0,
            "minimum_hold_seconds": 0,
            "cooldown_seconds": 0,
            "action_template": {
                "structure_type": "gate",
                "structure_id": gate_id,
                "command_type": "gate_opening_m",
                "target_value": 1.0,
            },
            "priority": 10,
        },
    )
    assert rule.status_code == 201, rule.text
    validated = client.post(f"/api/v1/dispatch/plans/{plan_id}/validate")
    assert validated.status_code == 200, validated.text
    assert validated.json()["valid"] is True
    frozen = client.post(f"/api/v1/dispatch/plans/{plan_id}/freeze")
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["frozen_snapshot_hash"]
    readiness = client.get(f"/api/v1/dispatch/plans/{plan_id}/readiness")
    assert readiness.status_code == 200, readiness.text
    readiness_payload = readiness.json()
    assert readiness_payload["planning_valid"] is True
    assert readiness_payload["frozen_snapshot_valid"] is True
    assert readiness_payload["static_preview_allowed"] is True
    assert readiness_payload["hydraulic_runtime_supported"] is False
    assert readiness_payload["real_validation_status"] == "SKIPPED_BY_USER"
    assert readiness_payload["run_allowed"] is False
    assert {item["feature"] for item in readiness_payload["capabilities"]} == {
        "GATE",
        "PUMP",
    }
    assert all(
        item["status"] == "UNSUPPORTED"
        for item in readiness_payload["capabilities"]
    )
    preview = client.post(
        f"/api/v1/dispatch/plans/{plan_id}/schedule-preview",
        json={
            "evidence_class": "SYNTHETIC_DEVELOPMENT_ONLY",
            "observations": [
                {"time_seconds": 0, "values": []},
                {"time_seconds": 100, "values": []},
                {"time_seconds": 300, "values": []},
                {"time_seconds": 600, "values": []},
            ],
        },
    )
    assert preview.status_code == 200, preview.text
    preview_payload = preview.json()
    assert preview_payload["evaluator_id"] == SYNTHETIC_SCHEDULE_EVALUATOR_ID
    assert preview_payload["initial_state_basis"] == SYNTHETIC_INITIAL_STATE_BASIS
    assert preview_payload["hydraulic_execution_supported"] is False
    assert preview_payload["no_hydraulic_feedback"] is True
    assert preview_payload["rule_trigger_count"] == 1
    assert len(preview_payload["result_hash"]) == 64
    forbidden = {"water_level", "flow", "power_kw", "energy_kwh", "mass_balance"}
    assert forbidden.isdisjoint(_nested_keys(preview_payload))
    blocked = client.post(f"/api/v1/dispatch/plans/{plan_id}/runs")
    assert blocked.status_code == 409
    assert "UNSUPPORTED_BY_MASCARET_ADAPTER" in blocked.text
    with SessionLocal() as session:
        assert (session.scalar(select(func.count(SimulationTask.id))) or 0) == task_count
        assert (session.scalar(select(func.count(DispatchRun.id))) or 0) == run_count
        plan = session.get(DispatchPlan, plan_id)
        assert plan is not None
        session.delete(plan)
        session.commit()
