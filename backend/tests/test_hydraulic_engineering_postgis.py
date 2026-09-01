"""Real PostGIS/API round trip for Engineering-03 structures and network graph."""

from __future__ import annotations

import os
from uuid import uuid4

from fastapi.testclient import TestClient
from geoalchemy2.elements import WKTElement
import pytest

from app.database.session import SessionLocal
from app.gis.models import BoundaryCondition, DatasetVersion, SimulationCase
from app.hydraulic.models import HydraulicBranch, HydraulicNetwork, HydraulicNode
from app.main import app


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_HYDRAULIC_ENGINEERING_POSTGIS") != "1",
    reason="requires a disposable migrated PostGIS database",
)


def test_structure_crud_location_capability_and_network_graph_round_trip() -> None:
    """Exercise the real database constraints, spatial mapping, API, and graph surface."""

    version_label = f"ENGINEERING-03-{uuid4().hex[:10]}"
    with SessionLocal() as session:
        version = DatasetVersion(
            version=version_label,
            name="Engineering-03 disposable integration version",
            creator="pytest",
            status="draft",
        )
        session.add(version)
        session.flush()
        network = HydraulicNetwork(
            dataset_version_id=version.id,
            code="E03-NET",
            name="Engineering-03 API network",
            display_crs="EPSG:4490",
            engineering_crs="EPSG:32651",
            horizontal_unit="m",
            vertical_datum="1985-national-height-datum",
            vertical_unit="m",
            source_kind="api",
            metadata_json={},
        )
        session.add(network)
        session.flush()
        upstream = HydraulicNode(
            dataset_version_id=version.id,
            network_id=network.id,
            node_code="E03-UP",
            node_name="Upstream",
            node_type="boundary",
            geometry=WKTElement("POINT(120 30)", srid=4490),
            metadata_json={},
        )
        downstream = HydraulicNode(
            dataset_version_id=version.id,
            network_id=network.id,
            node_code="E03-DOWN",
            node_name="Downstream",
            node_type="boundary",
            geometry=WKTElement("POINT(120.01 30)", srid=4490),
            metadata_json={},
        )
        session.add_all([upstream, downstream])
        session.flush()
        branch = HydraulicBranch(
            dataset_version_id=version.id,
            network_id=network.id,
            branch_code="E03-BRANCH",
            river_name="Engineering-03 river",
            branch_name="Engineering-03 branch",
            upstream_node_id=upstream.id,
            downstream_node_id=downstream.id,
            start_chainage=0.0,
            end_chainage=1000.0,
            length_m=1000.0,
            direction_status="confirmed",
            geometry=WKTElement("LINESTRING(120 30,120.01 30)", srid=4490),
            metadata_json={},
        )
        session.add(branch)
        session.flush()
        boundary = BoundaryCondition(
            dataset_version_id=version.id,
            name=f"{version_label}-upstream",
            boundary_type="upstream_discharge",
            hydraulic_node_id=upstream.id,
            values={"mode": "constant", "value": 8.0},
            unit="m3/s",
        )
        session.add(boundary)
        session.flush()
        case = SimulationCase(
            name=f"{version_label}-case",
            dataset_version_id=version.id,
            boundary_condition_id=boundary.id,
            hydraulic_1d_configuration={},
        )
        session.add(case)
        session.commit()
        version_id, network_id, branch_id = version.id, network.id, branch.id
        boundary_id, case_id = boundary.id, case.id

    client = TestClient(app)
    payload = {
        "dataset_version_id": version_id,
        "network_id": network_id,
        "branch_id": branch_id,
        "structure_code": "E03-WEIR",
        "structure_name": "Engineering-03 test weir",
        "structure_type": "weir",
        "chainage_m": 500.0,
        "x": 120.005,
        "y": 30.0,
        "crest_elevation_m": 2.45,
        "width_m": 12.0,
        "hydraulic_law_type": "broad_crested_geometric",
        "hydraulic_parameters": {"discharge_coefficient": 0.435},
        "operation_rule_type": "fixed",
        "operation_parameters": {},
        "status": "active",
        "metadata": {"test": "engineering-03"},
    }
    try:
        created = client.post("/api/v1/hydraulic/structures", json=payload)
        assert created.status_code == 201, created.text
        structure = created.json()
        structure_id = structure["id"]
        assert structure["solver_status"] == "VERIFIED_NATIVE"

        invalid = client.post(
            "/api/v1/hydraulic/structures",
            json=payload
            | {
                "structure_code": "E03-FLOATING",
                "x": 121.0,
                "y": 31.0,
            },
        )
        assert invalid.status_code == 422
        assert "STRUCTURE_LOCATION_INVALID" in invalid.text

        updated = client.put(
            f"/api/v1/hydraulic/structures/{structure_id}",
            json={"width_m": 13.0},
        )
        assert updated.status_code == 200
        assert updated.json()["width_m"] == 13.0

        scenario = client.put(
            f"/api/v1/hydraulic/structures/{structure_id}/scenarios/{case_id}",
            json={
                "status_override": "inactive",
                "hydraulic_parameters_override": {"discharge_coefficient": 0.4},
                "operation_rule_type_override": "scenario_specific",
                "operation_parameters_override": {"reviewed": True},
                "metadata": {"case": "integration"},
            },
        )
        assert scenario.status_code == 200, scenario.text
        assert scenario.json()["status_override"] == "inactive"

        graph = client.get(f"/api/v1/hydraulic/networks/{network_id}/graph")
        assert graph.status_code == 200, graph.text
        graph_payload = graph.json()
        assert len(graph_payload["nodes"]) == 2
        assert graph_payload["cross_sections"] == []
        assert [item["id"] for item in graph_payload["structures"]] == [structure_id]
        assert [item["id"] for item in graph_payload["boundaries"]] == [boundary_id]
        assert graph_payload["branches"][0]["upstream_node_id"] is not None

        deleted = client.delete(f"/api/v1/hydraulic/structures/{structure_id}")
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/hydraulic/structures/{structure_id}").status_code == 404
    finally:
        with SessionLocal() as session:
            stored_case = session.get(SimulationCase, case_id)
            if stored_case is not None:
                session.delete(stored_case)
                session.flush()
            stored_boundary = session.get(BoundaryCondition, boundary_id)
            if stored_boundary is not None:
                session.delete(stored_boundary)
                session.flush()
            stored = session.get(DatasetVersion, version_id)
            if stored is not None:
                session.delete(stored)
                session.commit()
