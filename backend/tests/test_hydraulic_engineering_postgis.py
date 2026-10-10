"""Real PostGIS/API round trip for Engineering-03 structures and network graph."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from geoalchemy2.elements import WKTElement
import jwt
import pytest

from app.database.session import SessionLocal
from app.gis.models import BoundaryCondition, DatasetVersion, SimulationCase
from app.hydraulic.models import HydraulicBranch, HydraulicNetwork, HydraulicNode
from app.main import app
from app.security.models import IdentityPrincipal, IdentityRoleBinding


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_HYDRAULIC_ENGINEERING_POSTGIS") != "1",
    reason="requires a disposable migrated PostGIS database",
)


def test_structure_crud_location_capability_and_network_graph_round_trip(monkeypatch) -> None:
    """Exercise the real database constraints, spatial mapping, API, and graph surface."""

    version_label = f"ENGINEERING-03-{uuid4().hex[:10]}"
    issuer = f"https://engineering-03.pytest.invalid/{uuid4().hex}"
    subject = "integration-engineer"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("OIDC_ISSUER", issuer)
    monkeypatch.setenv("OIDC_AUDIENCE", "dayu-api")
    monkeypatch.setenv("OIDC_PUBLIC_KEY_FILE", "engineering-03-test-key.pem")
    monkeypatch.setenv("OIDC_ALLOWED_ALGORITHMS", "RS256")
    original_read_text = Path.read_text
    monkeypatch.setattr(
        "app.security.auth.Path.read_text",
        lambda path, *args, **kwargs: (
            public_pem.decode()
            if path.name == "engineering-03-test-key.pem"
            else original_read_text(path, *args, **kwargs)
        ),
    )
    now = datetime.now(UTC)
    access_token = jwt.encode(
        {
            "iss": issuer,
            "sub": subject,
            "aud": "dayu-api",
            "exp": now + timedelta(minutes=5),
            "iat": now,
            "name": "Engineering Integration User",
        },
        private_key,
        algorithm="RS256",
    )
    with SessionLocal() as session:
        principal = IdentityPrincipal(
            issuer=issuer,
            subject=subject,
            display_name="Engineering Integration User",
            authentication_method="oidc",
        )
        session.add(principal)
        session.flush()
        session.add(
            IdentityRoleBinding(
                principal_id=principal.id,
                role="engineer",
                active=True,
                created_by_principal_id=principal.id,
            )
        )
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
    client.headers["Authorization"] = f"Bearer {access_token}"
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
        automatic_location_payload = {
            key: value for key, value in payload.items() if key not in {"x", "y"}
        }
        created = client.post("/api/v1/hydraulic/structures", json=automatic_location_payload)
        assert created.status_code == 201, created.text
        structure = created.json()
        structure_id = structure["id"]
        assert structure["solver_status"] == "VERIFIED_NATIVE"
        assert structure["location_geometry"]["coordinates"] == pytest.approx([120.005, 30.0])

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
            json={"width_m": 13.0, "chainage_m": 250.0},
        )
        assert updated.status_code == 200
        assert updated.json()["width_m"] == 13.0
        assert updated.json()["location_geometry"]["coordinates"] == pytest.approx([120.0025, 30.0])

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

        database_view = client.get(
            "/api/v1/hydraulic/networks",
            params={"dataset_version_id": version_id},
        )
        assert database_view.status_code == 200, database_view.text
        branch_view = database_view.json()[0]["branches"][0]
        assert branch_view["branch_code"] == "E03-BRANCH"
        assert branch_view["flow_direction"] == "unknown"
        assert branch_view["source_revision"] is None
        assert branch_view["vertex_count"] == 0

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
