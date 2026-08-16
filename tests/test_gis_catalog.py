"""Browser-safe Catalog status, revision, and merge contracts."""

from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.gis_governance.errors import GovernanceError


ROOT = Path(__file__).resolve().parents[1]


class ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows


class CatalogSession:
    def __init__(self, version: object | None, registry: list[object] | None = None, basemaps: list[object] | None = None) -> None:
        self.version = version
        self.results = iter((registry or [], basemaps or []))

    def get(self, model: object, identity: int) -> object | None:
        return self.version

    def scalars(self, statement: object) -> ScalarRows:
        return ScalarRows(next(self.results))


def _version(status: str = "published", content_hash: str | None = "a" * 64) -> SimpleNamespace:
    return SimpleNamespace(id=7, version="V7", name="Version 7", status=status, content_hash=content_hash, published_at=datetime(2026, 8, 15, tzinfo=UTC), change_summary="reviewed")


def test_catalog_version_status_matrix() -> None:
    from app.gis_catalog import service

    with pytest.raises(GovernanceError) as unknown:
        service._public_version(CatalogSession(None), 99)
    assert (unknown.value.status_code, unknown.value.code) == (404, "DATASET_VERSION_NOT_FOUND")
    for status in ("draft", "approved", "rejected"):
        with pytest.raises(GovernanceError) as blocked:
            service._public_version(CatalogSession(_version(status)), 7)
        assert (blocked.value.status_code, blocked.value.code) == (409, "DATASET_VERSION_NOT_PUBLIC")
    with pytest.raises(GovernanceError) as retired:
        service._public_version(CatalogSession(_version("retired")), 7)
    assert (retired.value.status_code, retired.value.code) == (410, "DATASET_VERSION_RETIRED")


def test_catalog_is_deterministic_and_does_not_leak_internal_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.gis_catalog import service

    manifest = json.loads((ROOT / "qgis/server/generated/dayu_tiangong_server.manifest.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(service, "_manifest", lambda: manifest)
    monkeypatch.setattr(service.qgis_service, "health", lambda session: SimpleNamespace(process=SimpleNamespace(passed=True), project_valid=SimpleNamespace(passed=True), database_read=SimpleNamespace(passed=True), wms_capabilities=SimpleNamespace(passed=True)))
    monkeypatch.setattr(service, "_runtime_health", lambda modes, qgis_healthy: {mode: True for mode in modes})
    registry = [SimpleNamespace(
        layer_key="river", title="河道", group_key="01_HYDROGRAPHY",
        service_mode="QGIS_WMS", render_mode="RASTER_WMS", source_relation="river",
        geometry_type="LINESTRING", dataset_filter_field="dataset_version_id",
        identify_enabled=True, legend_enabled=True, search_enabled=True,
        default_visible=True, default_opacity=1.0, qgis_short_name="river",
        model_entity_type="river", identify_mode="FEATURE_INFO",
        detail_route_key="river_detail", cache_mode="CLIENT_PRIVATE", display_order=10,
    )]
    basemaps = [SimpleNamespace(basemap_key="world_imagery", title="影像底图", basemap_type="ARCGIS_REST", endpoint_key="world_imagery_proxy", credit="controlled", native_crs="EPSG:3857", default_visible=True, default_opacity=1.0)]
    first, etag1 = service.build_catalog(CatalogSession(_version(), registry, basemaps), 7)
    second, etag2 = service.build_catalog(CatalogSession(_version(), registry, basemaps), 7)
    assert etag1 == etag2 and first.catalog_revision == second.catalog_revision
    value = first.model_dump_json()
    for forbidden in ("source_schema", "source_relation", "internal_url", "dsn", "MAP", "FILTER", "password", "project_path"):
        assert forbidden not in value
    assert first.layers[0].service["endpoint"] == "/qgis-server/wms"
    assert first.basemaps[0].endpoint.startswith("/api/v1/gis/basemaps/")


def test_catalog_openapi_path_and_structured_errors() -> None:
    from app.main import create_app

    schema = create_app().openapi()
    assert "/api/v1/gis/catalog" in schema["paths"]
    assert "/api/v1/gis/qgis-server/health" in schema["paths"]
    assert "/qgis-server/wms" in schema["paths"]
