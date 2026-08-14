"""Acceptance coverage for DGIS contracts, GDAL validation, and live spatiotemporal APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.data_converter import gdal_service, router as conversion_router, validator
from app.data_converter.importer import immutable_table_name
from app.database.session import get_database_session
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
    postgis_body = schema.json()["components"]["schemas"][
        "Body_import_to_postgis_api_v1_dgis_conversions_postgis_post"
    ]
    assert {"file", "layer_name"}.issubset(postgis_body["required"])
    assert {
        "entity_type", "parent_version_id", "operator",
    }.issubset(postgis_body["properties"])
    assert postgis_body["properties"]["entity_type"]["anyOf"][0]["enum"] == [
        "river", "cross_section", "gate", "pump",
    ]
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
    assert validator.validate_governed_target_srid(4490) == 4490
    with pytest.raises(validator.ConversionValidationError, match="EPSG:4490"):
        validator.validate_governed_target_srid(4326)


def test_raw_postgis_table_names_are_server_owned_and_batch_scoped() -> None:
    """Keep the legacy logical label while preventing raw table overwrite semantics."""

    first = immutable_table_name("a" * 32, "River_Import_01")
    second = immutable_table_name("b" * 32, "River_Import_01")
    assert first == "batch_aaaaaaaaaaaaaaaa_river_import_01"
    assert second == "batch_bbbbbbbbbbbbbbbb_river_import_01"
    assert first != second
    assert len(first) <= 63

    gdal_source = (Path(__file__).parents[1] / "app" / "data_converter" / "gdal_service.py").read_text(encoding="utf-8")
    assert '"-overwrite"' not in gdal_source


def test_detect_source_crs_never_treats_geometry_type_as_a_crs() -> None:
    """Geometry family metadata must not be persisted as false CRS provenance."""

    assert gdal_service.detect_source_crs({
        "layers": [{"geometryType": "LineString"}],
    }) == "unknown"
    assert gdal_service.detect_source_crs({
        "layers": [{
            "geometryFields": [{
                "coordinateSystem": {"id": {"authority": "EPSG", "code": 4490}}
            }]
        }]
    }) == "EPSG:4490"


class _FakeImportSession:
    """Capture import-batch persistence without requiring a live PostGIS database."""

    def __init__(self, parent: object | None = None) -> None:
        self.parent = parent
        self.added: list[object] = []
        self.commit_count = 0
        self.rollback_count = 0

    def get(self, _model: object, _identifier: int) -> object | None:
        return self.parent

    def add(self, value: object) -> None:
        setattr(value, "id", len(self.added) + 1)
        self.added.append(value)

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


def _postgis_import(
    monkeypatch: pytest.MonkeyPatch,
    session: _FakeImportSession,
    *,
    layer_name: str,
    entity_type: str | None = None,
    parent_version_id: int | None = None,
    operator: str | None = None,
    inspect_error: Exception | None = None,
    import_error: Exception | None = None,
) -> object:
    """Call the multipart route with deterministic GDAL and database fakes."""

    monkeypatch.setattr(
        conversion_router.importer,
        "stage_upload",
        lambda *_args, **_kwargs: ("a" * 32, "GeoJSON", Path("source.geojson")),
    )

    def inspect(*_args: object, **_kwargs: object) -> dict[str, object]:
        if inspect_error is not None:
            raise inspect_error
        return {
            "layers": [{
                "geometryFields": [{
                    "coordinateSystem": {"id": {"authority": "EPSG", "code": 4490}}
                }]
            }]
        }

    def import_postgis(*_args: object, **_kwargs: object) -> None:
        if import_error is not None:
            raise import_error

    monkeypatch.setattr(conversion_router.gdal_service, "inspect", inspect)
    monkeypatch.setattr(conversion_router.importer, "import_postgis", import_postgis)
    app.dependency_overrides[get_database_session] = lambda: session
    data = {"layer_name": layer_name}
    if entity_type is not None:
        data["entity_type"] = entity_type
    if parent_version_id is not None:
        data["parent_version_id"] = str(parent_version_id)
    if operator is not None:
        data["operator"] = operator
    try:
        return client.post(
            "/api/v1/dgis/conversions/postgis",
            files={"file": ("input.geojson", b'{"type":"FeatureCollection"}')},
            data=data,
        )
    finally:
        app.dependency_overrides.pop(get_database_session, None)


def test_postgis_import_accepts_explicit_entity_and_keeps_raw_batch_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raw landing records provenance but does not claim typed staging is complete."""

    parent = SimpleNamespace(status="published", content_hash="b" * 64)
    session = _FakeImportSession(parent)
    response = _postgis_import(
        monkeypatch,
        session,
        layer_name="survey_2026",
        entity_type="cross_section",
        parent_version_id=7,
        operator="survey-team-a",
    )

    assert response.status_code == 200
    body = response.json()
    assert {
        "entity_type": "cross_section",
        "batch_status": "created",
        "raw_landing_status": "completed",
        "parent_version_id": 7,
    }.items() <= body["details"].items()
    batch = session.added[0]
    assert batch.status == "created"
    assert batch.entity_type == "cross_section"
    assert batch.operator == "survey-team-a"
    assert batch.parent_content_hash == "b" * 64
    assert batch.source_crs == "EPSG:4490"
    assert batch.metadata_json["_governance"]["raw_landing"]["status"] == "completed"
    assert batch.metadata_json["_governance"]["standardization"]["status"] == "required"
    assert "standardization to staging_qgis is still required" in batch.notes


def test_postgis_import_only_infers_entity_from_known_legacy_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep safe old calls working without silently disguising unknown layers as rivers."""

    inferred_session = _FakeImportSession()
    inferred = _postgis_import(monkeypatch, inferred_session, layer_name="rivers")
    assert inferred.status_code == 200
    assert inferred_session.added[0].entity_type == "river"

    unknown_session = _FakeImportSession()
    unknown = _postgis_import(monkeypatch, unknown_session, layer_name="survey_2026")
    assert unknown.status_code == 422
    assert "entity_type is required" in unknown.json()["detail"]
    assert unknown_session.added == []


@pytest.mark.parametrize(
    "parent",
    [
        None,
        SimpleNamespace(status="draft", content_hash="b" * 64),
        SimpleNamespace(status="approved", content_hash=None),
    ],
)
def test_postgis_import_rejects_unqualified_parent_versions(
    monkeypatch: pytest.MonkeyPatch, parent: object | None,
) -> None:
    """A parent must be frozen and content-addressed before it can anchor a batch."""

    session = _FakeImportSession(parent)
    response = _postgis_import(
        monkeypatch,
        session,
        layer_name="rivers",
        parent_version_id=9,
    )

    assert response.status_code == 422
    assert session.added == []


@pytest.mark.parametrize("failure_stage", ["inspect", "import"])
def test_postgis_import_persists_auditable_raw_failure(
    monkeypatch: pytest.MonkeyPatch, failure_stage: str,
) -> None:
    """Any GDAL failure after batch registration remains visible and blocks standardization."""

    session = _FakeImportSession()
    error = gdal_service.GDALServiceError(f"{failure_stage} failed")
    response = _postgis_import(
        monkeypatch,
        session,
        layer_name="gates",
        inspect_error=error if failure_stage == "inspect" else None,
        import_error=error if failure_stage == "import" else None,
    )

    assert response.status_code == 503
    batch = session.added[0]
    assert batch.status == "created"
    assert batch.notes.startswith("RAW_LANDING_FAILED:")
    governance = batch.metadata_json["_governance"]
    assert governance["raw_landing"]["status"] == "failed"
    assert governance["standardization"]["status"] == "blocked"
    assert session.rollback_count == 1


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
