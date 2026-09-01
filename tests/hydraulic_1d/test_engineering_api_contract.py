"""Engineering-03 API, persistence, and migration contract checks."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.hydraulic.models import HydraulicBranch, HydraulicStructureScenario
from app.main import app


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "versions"
    / "20260901_0025_hydraulic_engineering_core.py"
)


def test_engine_capability_endpoint_exposes_evidence_without_runtime_details() -> None:
    """Give the frontend a stable pre-submit matrix while keeping execution internals private."""

    response = TestClient(app).get("/api/v1/hydraulic/engine-capabilities")

    assert response.status_code == 200
    rows = {item["feature"]: item for item in response.json()}
    assert rows["BRANCHED_NETWORK"]["status"] == "VERIFIED_NATIVE"
    assert rows["WEIR"]["benchmark_ids"] == ["S01"]
    assert rows["GATE"]["status"] == "UNSUPPORTED"
    assert rows["PUMP"]["status"] == "UNSUPPORTED"
    assert all("executable" not in item for item in rows.values())


def test_openapi_exposes_network_graph_structure_crud_and_scenario_override() -> None:
    """Keep every Engineering-03 management operation in the generated contract."""

    openapi = TestClient(app).get("/openapi.json").json()
    paths = openapi["paths"]

    assert {
        "/api/v1/hydraulic/engine-capabilities",
        "/api/v1/hydraulic/networks/{network_id}/graph",
        "/api/v1/hydraulic/structures",
        "/api/v1/hydraulic/structures/{structure_id}",
        "/api/v1/hydraulic/structures/{structure_id}/scenarios/{case_id}",
    } <= paths.keys()
    assert set(paths["/api/v1/hydraulic/structures"]) == {"get", "post"}
    assert set(paths["/api/v1/hydraulic/structures/{structure_id}"]) == {
        "get",
        "put",
        "delete",
    }
    graph_fields = openapi["components"]["schemas"]["HydraulicNetworkGraphRecord"][
        "properties"
    ]
    assert "cross_sections" in graph_fields


def test_persistence_metadata_enforces_network_and_scenario_version_ownership() -> None:
    """Do not rely only on service code to prevent cross-network or cross-version links."""

    branch_unique = {
        constraint.name
        for constraint in HydraulicBranch.__table__.constraints
        if constraint.name is not None
    }
    scenario_constraints = {
        constraint.name
        for constraint in HydraulicStructureScenario.__table__.constraints
        if constraint.name is not None
    }

    assert "uq_hydraulic_branch_id_network_version" in branch_unique
    assert "fk_hydraulic_structure_scenario_structure_version" in scenario_constraints
    assert "fk_hydraulic_structure_scenario_case_version" in scenario_constraints


def test_latest_migration_is_additive_round_trip_safe_and_preserves_legacy_assets() -> (
    None
):
    """Require copied Gate/Pump rows, snapped locations, and a downgrade without source loss."""

    source = MIGRATION.read_text(encoding="utf-8")
    downgrade = source.split("def downgrade", 1)[1]

    assert 'revision: str = "20260901_0025"' in source
    assert 'down_revision: str | None = "20260831_0024"' in source
    assert "FROM public.gate AS gate" in source
    assert "FROM public.pump AS pump" in source
    assert source.count("ST_ClosestPoint(branch.centerline") == 2
    assert 'drop_table("structure_scenario", schema="hydraulic")' in downgrade
    assert 'drop_table("structure", schema="hydraulic")' in downgrade
    assert 'drop_table("gate"' not in downgrade
    assert 'drop_table("pump"' not in downgrade
    assert "storage_connection" in downgrade
