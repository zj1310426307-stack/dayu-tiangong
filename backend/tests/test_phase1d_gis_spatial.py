"""PostGIS-backed acceptance coverage for Phase 1D basemap search and catalog ownership."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database.session import SessionLocal
from app.main import app


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGIS_TESTS") != "1",
    reason="requires the migrated local Phase 1D PostGIS service",
)
client = TestClient(app)


def test_layer_catalog_and_openapi_expose_phase1d_boundaries() -> None:
    """The generated-client source must have a stable search path and grouped catalog."""

    schema = client.get("/openapi.json").json()
    assert "/api/v1/gis-analysis/search" in schema["paths"]
    catalog = client.get("/api/v1/gis-analysis/layers")
    assert catalog.status_code == 200
    rows = catalog.json()
    assert len(rows) == 22
    assert {item["group"] for item in rows} >= {
        "base", "engineering", "annotation", "model", "dispatch", "analysis",
    }
    assert {item["key"] for item in rows if item["group"] == "base"} == {
        "basemap", "administrative_area", "road", "place_name", "water_name", "poi",
    }
    assert {item["key"] for item in rows if item["group"] == "dispatch"} == {
        "gate_status", "pump_status",
    }
    assert "risk_result" in {item["key"] for item in rows if item["group"] == "analysis"}


@pytest.mark.parametrize(
    ("query", "expected_type", "expected_name"),
    [
        ("广州市", "administrative_area", "广州市"),
        ("广州市天河区天寿路", "road", "天寿路"),
        ("广州东站", "poi", "广州东站"),
        ("沙河涌", "water_name", "沙河涌"),
    ],
)
def test_offline_text_search(query: str, expected_type: str, expected_name: str) -> None:
    """Administrative areas, roads, water names, and POIs resolve from local PostGIS."""

    response = client.get("/api/v1/gis-analysis/search", params={
        "dataset_version_id": 1, "q": query,
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "text"
    assert payload["crs"] == "EPSG:4490"
    assert any(
        item["result_type"] == expected_type and item["name"] == expected_name
        for item in payload["items"]
    )


def test_coordinate_search_is_strict_and_deterministic() -> None:
    """The documented coordinate example must parse directly without an external geocoder."""

    response = client.get("/api/v1/gis-analysis/search", params={
        "dataset_version_id": 1, "q": "113.3238,23.1356",
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "coordinate"
    assert payload["items"][0]["longitude"] == pytest.approx(113.3238)
    assert payload["items"][0]["latitude"] == pytest.approx(23.1356)
    assert payload["items"][0]["source"] == "coordinate-parser"

    invalid = client.get("/api/v1/gis-analysis/search", params={
        "dataset_version_id": 1, "q": "181,23",
    })
    assert invalid.status_code == 409


def test_phase1d_physical_tables_srid_rows_and_indexes() -> None:
    """Audit all five source tables instead of accepting only an ORM-level response."""

    expected_geometry = {
        ("administrative_area", "POLYGON", 4490),
        ("road", "LINESTRING", 4490),
        ("place_name", "POINT", 4490),
        ("water_name", "POINT", 4490),
        ("poi", "POINT", 4490),
    }
    expected_indexes = {f"ix_{name}_geometry_gist" for name, _, _ in expected_geometry}
    with SessionLocal() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "20260815_0014"
        geometries = set(session.execute(text("""
            SELECT f_table_name, type, srid FROM geometry_columns
            WHERE f_table_name IN ('administrative_area','road','place_name','water_name','poi')
        """)).all())
        indexes = set(session.execute(text("""
            SELECT indexname FROM pg_indexes WHERE schemaname = 'public'
              AND tablename IN ('administrative_area','road','place_name','water_name','poi')
              AND lower(indexdef) LIKE '%using gist%'
        """)).scalars())
        counts = dict(session.execute(text("""
            SELECT 'administrative_area', count(*) FROM administrative_area
            UNION ALL SELECT 'road', count(*) FROM road
            UNION ALL SELECT 'place_name', count(*) FROM place_name
            UNION ALL SELECT 'water_name', count(*) FROM water_name
            UNION ALL SELECT 'poi', count(*) FROM poi
        """)).all())
    assert geometries == expected_geometry
    assert indexes == expected_indexes
    assert counts == {
        "administrative_area": 3, "road": 4, "place_name": 3, "water_name": 3, "poi": 4,
    }
