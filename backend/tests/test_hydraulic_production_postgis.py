"""Disposable PostGIS round trip for Production-04 imported evidence and audit."""

from __future__ import annotations

import json
import os
from uuid import uuid4

from fastapi.testclient import TestClient
from geoalchemy2.elements import WKTElement
import pytest
from sqlalchemy import delete

from app.database.session import SessionLocal
from app.gis.models import DatasetVersion
from app.hydraulic.models import (
    HydraulicBranch,
    HydraulicExternalResult,
    HydraulicNetwork,
    HydraulicNode,
    HydraulicObservationSeries,
    HydraulicProductionAuditEvent,
)
from app.main import app


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_HYDRAULIC_PRODUCTION_POSTGIS") != "1",
    reason="requires a disposable migrated PostGIS database",
)


def test_imported_observation_external_result_and_audit_round_trip() -> None:
    """Prove file-derived lineage, dimensional fields, FKs, and append-only audit APIs."""

    label = f"PRODUCTION-04-{uuid4().hex[:10]}"
    with SessionLocal() as session:
        version = DatasetVersion(
            version=label,
            name="Production-04 disposable integration version",
            creator="pytest",
            status="draft",
        )
        session.add(version)
        session.flush()
        network = HydraulicNetwork(
            dataset_version_id=version.id,
            code="P04-NET",
            name="Production-04 integration network",
            display_crs="EPSG:4490",
            engineering_crs="EPSG:4547",
            horizontal_unit="m",
            vertical_datum="1985-national-height",
            vertical_unit="m",
            source_kind="api",
            metadata_json={},
        )
        session.add(network)
        session.flush()
        upstream = HydraulicNode(
            dataset_version_id=version.id,
            network_id=network.id,
            node_code="P04-UP",
            node_type="boundary",
            geometry=WKTElement("POINT(120 30)", srid=4490),
            metadata_json={},
        )
        downstream = HydraulicNode(
            dataset_version_id=version.id,
            network_id=network.id,
            node_code="P04-DOWN",
            node_type="boundary",
            geometry=WKTElement("POINT(120.01 30)", srid=4490),
            metadata_json={},
        )
        session.add_all([upstream, downstream])
        session.flush()
        branch = HydraulicBranch(
            dataset_version_id=version.id,
            network_id=network.id,
            branch_code="P04-BRANCH",
            river_name="Production river",
            branch_name="Production branch",
            upstream_node_id=upstream.id,
            downstream_node_id=downstream.id,
            start_chainage=0,
            end_chainage=1000,
            length_m=1000,
            direction_status="confirmed",
            geometry=WKTElement("LINESTRING(120 30,120.01 30)", srid=4490),
            metadata_json={},
        )
        session.add(branch)
        session.commit()
        version_id, branch_id = version.id, branch.id

    client = TestClient(app)
    observation_options = {
        "series_kind": "observation",
        "series_id": "P04-OBS-H",
        "variable": "water_level",
        "unit": "m",
        "source": "integration-survey",
        "branch_id": str(branch_id),
        "chainage_m": 500,
        "station_id": "P04-STA",
        "vertical_datum": "1985-national-height",
        "time_basis": "relative",
        "column_mapping": {"time": "t", "value": "H", "quality_flag": "quality"},
    }
    external_options = {
        "external_model_name": "MIKE11",
        "external_model_version": "UNKNOWN",
        "scenario": "P04-reference",
        "vertical_datum": "1985-national-height",
        "time_basis": "relative",
        "column_mapping": {
            "branch": "reach",
            "chainage": "station",
            "time": "t",
            "water_level": "H",
            "discharge": "Q",
        },
        "branch_mappings": [
            {"external_branch": "MIKE-A", "dayu_branch": str(branch_id)}
        ],
    }
    try:
        observation = client.post(
            "/api/v1/hydraulic/production/observations/import",
            data={
                "dataset_version_id": str(version_id),
                "actor": "pytest-reviewer",
                "options_json": json.dumps(observation_options),
            },
            files={
                "file": (
                    "observed-H.csv",
                    b"t,H,quality\n0,3.1,GOOD\n60,,MISSING\n120,3.3,GOOD\n",
                    "text/csv",
                )
            },
        )
        assert observation.status_code == 201, observation.text
        assert observation.json()["branch_id"] == branch_id
        assert len(observation.json()["source_sha256"]) == 64

        external = client.post(
            "/api/v1/hydraulic/production/external-results/import",
            data={
                "dataset_version_id": str(version_id),
                "result_code": "P04-MIKE-REF",
                "actor": "pytest-reviewer",
                "options_json": json.dumps(external_options),
            },
            files={
                "file": (
                    "mike11-export.csv",
                    b"reach,station,t,H,Q\nMIKE-A,500,0,3.0,10\nMIKE-A,500,60,3.2,12\n",
                    "text/csv",
                )
            },
        )
        assert external.status_code == 201, external.text
        assert external.json()["external_model_version"] == "UNKNOWN"

        audit = client.get(
            "/api/v1/hydraulic/production/audit",
            params={"dataset_version_id": version_id},
        )
        assert audit.status_code == 200, audit.text
        assert [item["action"] for item in audit.json()] == ["IMPORT", "IMPORT"]
        assert all(len(item["content_hash"]) == 64 for item in audit.json())

        with SessionLocal() as session:
            stored = session.get(HydraulicObservationSeries, observation.json()["id"])
            assert stored is not None
            assert stored.samples_json[1]["quality_flag"] == "MISSING"
            assert stored.samples_json[1]["value"] is None
            reference = session.get(HydraulicExternalResult, external.json()["id"])
            assert reference is not None
            assert reference.mapping_json["branch_mappings"][0]["dayu_branch"] == str(
                branch_id
            )
    finally:
        with SessionLocal() as session:
            session.execute(
                delete(HydraulicProductionAuditEvent).where(
                    HydraulicProductionAuditEvent.dataset_version_id == version_id
                )
            )
            session.execute(
                delete(HydraulicExternalResult).where(
                    HydraulicExternalResult.dataset_version_id == version_id
                )
            )
            session.execute(
                delete(HydraulicObservationSeries).where(
                    HydraulicObservationSeries.dataset_version_id == version_id
                )
            )
            version = session.get(DatasetVersion, version_id)
            if version is not None:
                session.delete(version)
            session.commit()
