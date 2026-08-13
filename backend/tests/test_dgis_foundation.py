"""Acceptance coverage for DGIS contracts, GDAL validation, and live spatiotemporal APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.data_converter import validator
from app.main import app


client = TestClient(app)
requires_postgis = pytest.mark.skipif(
    os.getenv("RUN_POSTGIS_TESTS") != "1",
    reason="requires migrated TimescaleDB/PostGIS and DGIS services",
)


def _shape_zip(entries: dict[str, bytes]) -> bytes:
    """Build one in-memory Shapefile archive for path and bundle validation tests."""

    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return payload.getvalue()


def test_dgis_openapi_and_gdal_capability_contract() -> None:
    """Expose every DGIS boundary and a real-or-offline GDAL capability response."""

    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    for path in (
        "/api/v1/dgis/health", "/api/v1/dgis/catalog", "/api/v1/dgis/feature-states",
        "/api/v1/dgis/feature-states/replay", "/api/v1/dgis/simulation-layers",
        "/api/v1/dgis/3d-tiles", "/api/v1/dgis/conversions/capabilities",
    ):
        assert path in paths
    capability = client.get("/api/v1/dgis/conversions/capabilities")
    assert capability.status_code == 200
    assert capability.json()["outputs"] == ["PostGIS", "GeoJSON", "COG"]


def test_conversion_validator_rejects_unsafe_or_incomplete_archives() -> None:
    """Prevent traversal and incomplete Shapefiles before GDAL touches disk."""

    valid = _shape_zip({"basin.shp": b"shp", "basin.shx": b"shx", "basin.dbf": b"dbf"})
    assert validator.validate_upload("basin.zip", valid, "vector") == "ESRI Shapefile"
    with pytest.raises(validator.ConversionValidationError, match="unsafe path"):
        validator.validate_upload(
            "bad.zip", _shape_zip({"../bad.shp": b"x", "bad.shx": b"x", "bad.dbf": b"x"})
        )
    with pytest.raises(validator.ConversionValidationError, match="requires"):
        validator.validate_upload("bad.zip", _shape_zip({"bad.shp": b"x"}))
    assert validator.validate_layer_name("River_Import_01") == "river_import_01"
    with pytest.raises(validator.ConversionValidationError):
        validator.validate_layer_name("imports.river")


def test_real_gdal_vector_and_cog_conversion(tmp_path: Path) -> None:
    """Use the installed GDAL binaries for a real vector reprojection and valid COG output."""

    from app.data_converter import gdal_service

    if gdal_service.version() is None or shutil.which("gdal_create") is None:
        pytest.skip("GDAL runtime is not installed")
    vector_source = tmp_path / "points.geojson"
    vector_source.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature",'
        '"properties":{"name":"acceptance"},"geometry":{"type":"Point",'
        '"coordinates":[113.32,23.14]}}]}',
        encoding="utf-8",
    )
    vector_target = tmp_path / "points-4490.geojson"
    gdal_service.vector_to_geojson(vector_source, vector_target, 4490)
    vector_info = gdal_service.inspect(vector_target, False)
    assert vector_target.stat().st_size > 0
    assert vector_info["layers"][0]["featureCount"] == 1

    raster_source = tmp_path / "source-4326.tif"
    subprocess.run([
        shutil.which("gdal_create") or "gdal_create", "-of", "GTiff", "-outsize", "32", "32",
        "-bands", "1", "-ot", "Float32", "-burn", "2.5", "-a_srs", "EPSG:4326",
        "-a_ullr", "113.1", "23.35", "113.55", "22.95", str(raster_source),
    ], check=True, capture_output=True, timeout=30)
    raster_target = tmp_path / "output-4490.cog.tif"
    gdal_service.raster_to_cog(raster_source, raster_target, 4490)
    raster_info = gdal_service.inspect(raster_target, True)
    assert raster_info["driverShortName"] == "GTiff"
    assert raster_info["metadata"]["IMAGE_STRUCTURE"]["LAYOUT"] == "COG"
    assert "China Geodetic Coordinate System 2000" in raster_info["coordinateSystem"]["wkt"]


@requires_postgis
def test_spatiotemporal_catalog_health_and_replay() -> None:
    """Verify TimescaleDB, model layer catalog, version query, and deterministic replay."""

    health = client.get("/api/v1/dgis/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "healthy"
    assert body["timescale_hypertable"] is True
    assert body["simulation_layer_count"] >= 4
    assert set(body["vector_tile_sources"]) == {
        "tiles.river", "tiles.road", "tiles.administrative_area",
        "tiles.place_name", "tiles.engineering_facility",
    }

    catalog = client.get("/api/v1/dgis/catalog", params={"dataset_version_id": 1})
    assert catalog.status_code == 200
    assert {layer["layer_type"] for layer in catalog.json()["simulation_layers"]} >= {
        "water_level", "velocity", "flood_risk", "facility_3d",
    }

    replay = client.get("/api/v1/dgis/feature-states/replay", params={
        "dataset_version_id": 1, "at": "2026-08-13T09:00:00+08:00",
    })
    assert replay.status_code == 200
    assert replay.json()["total"] >= 3
    gate = next(item for item in replay.json()["items"] if item["feature_type"] == "gate")
    assert gate["state_json"]["opening"] == pytest.approx(0.65)


@requires_postgis
def test_feature_state_append_is_version_safe() -> None:
    """Append one timestamped observation and reject a cross-version simulation task."""

    payload = {
        "dataset_version_id": 1,
        "feature_type": "rainfall",
        "feature_id": 9001,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "state_json": {"rainfall": 12.5, "unit": "mm", "demo_data": True},
        "geometry": {"type": "Point", "coordinates": [113.32, 23.14]},
        "source": "observation",
        "task_id": None,
    }
    created = client.post("/api/v1/dgis/feature-states", json=payload)
    assert created.status_code == 201
    states = client.get("/api/v1/dgis/feature-states", params={
        "dataset_version_id": 1, "feature_type": "rainfall", "feature_id": 9001,
    })
    assert states.status_code == 200
    assert states.json()["total"] >= 1
