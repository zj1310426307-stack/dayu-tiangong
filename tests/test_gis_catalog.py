"""Browser-safe GeoServer Catalog and gateway contracts."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.gis_governance.errors import GovernanceError


class ScalarRows:
    """Mimic SQLAlchemy scalar rows for deterministic unit tests."""

    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows


class CatalogSession:
    """Provide the two read operations used by the Catalog service."""

    def __init__(self, version: object | None, rows: list[object] | None = None) -> None:
        self.version = version
        self.rows = rows or []

    def get(self, _model: object, _identity: int) -> object | None:
        return self.version

    def scalars(self, _statement: object) -> ScalarRows:
        return ScalarRows(self.rows)


def _version(status: str = "published", content_hash: str | None = "a" * 64) -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        version="V7",
        name="Version 7",
        status=status,
        content_hash=content_hash,
        published_at=datetime(2026, 8, 15, tzinfo=UTC),
        change_summary="reviewed",
    )


def _row() -> SimpleNamespace:
    return SimpleNamespace(
        layer_key="river",
        title="河道",
        group_key="01_HYDROGRAPHY",
        geometry_type="LINESTRING",
        source_relation="river",
        identify_enabled=True,
        legend_enabled=True,
        search_enabled=True,
        default_visible=True,
        default_opacity=1.0,
        detail_route_key="river_detail",
        model_entity_type="river",
        cache_mode="CLIENT_PRIVATE",
        display_order=10,
    )


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


def test_catalog_is_deterministic_and_geoserver_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.gis_catalog import service

    monkeypatch.setattr(service, "_geoserver_healthy", lambda: True)
    session = CatalogSession(_version(), [_row()])
    first, etag1 = service.build_catalog(session, 7)
    second, etag2 = service.build_catalog(session, 7)
    assert etag1 == etag2 and first.catalog_revision == second.catalog_revision
    assert [item.service_mode for item in first.services] == ["GEOSERVER_WMS"]
    assert first.layers[0].service_mode == "GEOSERVER_WMS"
    assert first.layers[0].layer_name == "dayu:river"
    assert first.project.native_crs == "EPSG:4490"
    assert first.project.web_crs == "EPSG:3857"
    value = first.model_dump_json()
    for forbidden in (
        "source_schema",
        "internal_url",
        "dsn",
        "password",
        "project_path",
        "QGIS_WMS",
        "MARTIN_MVT",
        "TITILER",
        "CESIUM_DYNAMIC",
    ):
        assert forbidden not in value


def test_catalog_openapi_exposes_only_safe_webgis_boundary() -> None:
    from app.main import create_app

    paths = create_app().openapi()["paths"]
    for path in (
        "/api/v1/gis/catalog",
        "/api/v1/gis/layers",
        "/api/v1/gis/ogc/wms",
        "/api/v1/gis/feature-info",
    ):
        assert path in paths
    assert "/api/v1/gis/qgis-server/health" not in paths
    assert "/qgis-server/wms" not in paths
