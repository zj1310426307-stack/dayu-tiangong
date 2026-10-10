"""Disposable PostGIS acceptance for REAL-01-CLOSE clone/hash boundaries."""

from __future__ import annotations

import os
from uuid import uuid4

from geoalchemy2.elements import WKTElement
import pytest
from sqlalchemy import func, select

from app.database.session import SessionLocal
from app.dataset.schemas import DatasetVersionCloneRequest
from app.dataset.service import clone_dataset_version
from app.gis.models import BoundaryCondition, DatasetVersion, SimulationCase, SimulationCaseBoundary
from app.hydraulic.models import (
    HydraulicBranch,
    HydraulicExternalResult,
    HydraulicNetwork,
    HydraulicNode,
)
from app.hydraulic.snapshot import engineering_graph_content_hash


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_REAL01_CLOSE_POSTGIS") != "1",
    reason="requires a disposable database migrated to the current PostGIS head",
)


def test_clone_is_hash_equivalent_and_excludes_external_results() -> None:
    """Clone editable inputs only, remap FKs, and preserve the canonical graph hash."""

    token = uuid4().hex[:10]
    with SessionLocal() as session:
        try:
            source = DatasetVersion(
                version=f"R1C-SRC-{token}",
                name=f"REAL-01-CLOSE source {token}",
                description="Disposable transaction-owned clone acceptance fixture",
                creator="pytest",
                status="draft",
            )
            session.add(source)
            session.flush()
            network = HydraulicNetwork(
                dataset_version_id=source.id,
                code="R1C-NET",
                name="REAL-01-CLOSE network",
                display_crs="EPSG:4490",
                engineering_crs="EPSG:4547",
                horizontal_unit="m",
                vertical_datum="1985-national-height-datum",
                vertical_unit="m",
                source_kind="api",
                metadata_json={"source": "pytest"},
            )
            session.add(network)
            session.flush()
            upstream = HydraulicNode(
                dataset_version_id=source.id,
                network_id=network.id,
                node_code="UP",
                node_name="Upstream",
                node_type="boundary",
                geometry=WKTElement("POINT(112.8 22.9)", srid=4490),
                metadata_json={},
            )
            downstream = HydraulicNode(
                dataset_version_id=source.id,
                network_id=network.id,
                node_code="DOWN",
                node_name="Downstream",
                node_type="boundary",
                geometry=WKTElement("POINT(112.81 22.9)", srid=4490),
                metadata_json={},
            )
            session.add_all([upstream, downstream])
            session.flush()
            branch = HydraulicBranch(
                dataset_version_id=source.id,
                network_id=network.id,
                branch_code="R1C-BRANCH",
                river_name="Disposable river",
                branch_name="Disposable branch",
                upstream_node_id=upstream.id,
                downstream_node_id=downstream.id,
                start_chainage=0.0,
                end_chainage=1000.0,
                length_m=1000.0,
                direction_status="confirmed",
                geometry=WKTElement("LINESTRING(112.8 22.9,112.81 22.9)", srid=4490),
                source_revision="pytest",
                metadata_json={},
            )
            session.add(branch)
            session.flush()
            boundary = BoundaryCondition(
                dataset_version_id=source.id,
                name=f"R1C-Q-{token}",
                boundary_type="upstream_discharge",
                hydraulic_node_id=upstream.id,
                values={
                    "mode": "time_series",
                    "source": "pytest",
                    "time_basis": "UTC",
                    "timezone": "Asia/Shanghai",
                    "series": [
                        {"time": "2026-01-01T00:00:00+08:00", "value": 1.0},
                        {"time": "2026-01-01T01:00:00+08:00", "value": 2.0},
                    ],
                },
                unit="m3/s",
            )
            session.add(boundary)
            session.flush()
            case = SimulationCase(
                name=f"R1C-CASE-{token}",
                description="Disposable case",
                dataset_version_id=source.id,
                boundary_condition_id=boundary.id,
                hydraulic_1d_configuration={"initial_condition": {"source": "pytest"}},
            )
            session.add(case)
            session.flush()
            session.add(
                SimulationCaseBoundary(
                    case_id=case.id,
                    boundary_condition_id=boundary.id,
                    role="upstream",
                )
            )
            session.add(
                HydraulicExternalResult(
                    dataset_version_id=source.id,
                    result_code=f"R1C-EXT-{token}",
                    external_model_name="MIKE11",
                    external_model_version="test-evidence",
                    scenario="disposable",
                    vertical_datum="1985-national-height-datum",
                    source_filename="sanitized.csv",
                    source_sha256="a" * 64,
                    mapping_json={},
                    points_json=[],
                    provenance_json={"test": True},
                )
            )
            session.flush()
            source_hash = engineering_graph_content_hash(session, source.id)

            clone_record = clone_dataset_version(
                session,
                source,
                DatasetVersionCloneRequest(
                    version=f"R1C-CLONE-{token}",
                    name=f"REAL-01-CLOSE clone {token}",
                    creator="pytest",
                    description="Disposable clone",
                ),
            )
            session.flush()
            clone_hash = engineering_graph_content_hash(session, clone_record.id)

            assert clone_hash == source_hash
            assert session.scalar(
                select(func.count(HydraulicExternalResult.id)).where(
                    HydraulicExternalResult.dataset_version_id == clone_record.id
                )
            ) == 0
            cloned_boundary = session.scalar(
                select(BoundaryCondition).where(
                    BoundaryCondition.dataset_version_id == clone_record.id
                )
            )
            cloned_case = session.scalar(
                select(SimulationCase).where(SimulationCase.dataset_version_id == clone_record.id)
            )
            assert cloned_boundary is not None
            assert cloned_case is not None
            assert cloned_boundary.hydraulic_node_id != boundary.hydraulic_node_id
            assert cloned_case.boundary_condition_id == cloned_boundary.id
            assert cloned_case.name != case.name
        finally:
            # No fixture row may survive this test, even when an assertion fails.
            session.rollback()
