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

    def __init__(
        self,
        version: object | None,
        rows: list[object] | None = None,
        basemaps: list[object] | None = None,
    ) -> None:
        self.version = version
        self.rows = rows or []
        self.basemaps = basemaps or []
        self.scalar_calls = 0

    def get(self, _model: object, _identity: int) -> object | None:
        return self.version

    def scalars(self, _statement: object) -> ScalarRows:
        values = self.rows if self.scalar_calls % 2 == 0 else self.basemaps
        self.scalar_calls += 1
        return ScalarRows(values)

    def scalar(self, _statement: object) -> object | None:
        return self.basemaps[0] if self.basemaps else None


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
        dataset_filter_field="dataset_version_id",
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


def _basemap(
    *,
    basemap_key: str = "nasa_blue_marble",
    endpoint_key: str = "nasa_gibs_blue_marble",
    title: str = "NASA Blue Marble 真彩色影像",
    visible: bool = True,
    credit: str = "NASA Earth Observatory / GIBS",
) -> SimpleNamespace:
    """Build one registry-like basemap row for Catalog and proxy tests."""

    return SimpleNamespace(
        basemap_key=basemap_key,
        title=title,
        basemap_type="XYZ",
        endpoint_key=endpoint_key,
        default_visible=visible,
        default_opacity=1.0,
        credit=credit,
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
    session = CatalogSession(_version(), [_row()], [_basemap()])
    first, etag1 = service.build_catalog(session, 7)
    second, etag2 = service.build_catalog(session, 7)
    assert etag1 == etag2 and first.catalog_revision == second.catalog_revision
    assert [item.service_mode for item in first.services] == ["GEOSERVER_WMS"]
    assert first.layers[0].service_mode == "GEOSERVER_WMS"
    assert first.layers[0].layer_name == "dayu:river"
    assert first.project.native_crs == "EPSG:4490"
    assert first.project.web_crs == "EPSG:3857"
    assert first.basemaps[0].endpoint.startswith("/api/v1/gis/basemaps/")
    assert first.basemaps[0].max_zoom == 8
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
        "gibs.earthdata.nasa.gov",
        "services.arcgisonline.com",
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
        "/api/v1/gis/basemaps/{basemap_key}/tiles/{z}/{y}/{x}.jpeg",
    ):
        assert path in paths
    assert "/api/v1/gis/qgis-server/health" not in paths
    assert "/qgis-server/wms" not in paths


def test_basemap_tile_proxy_rejects_unknown_and_fetches_allowlisted_jpeg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.gis_catalog import service

    class Response:
        content = b"jpeg"
        headers = {"content-type": "image/jpeg"}

        def raise_for_status(self) -> None:
            return None

    session = CatalogSession(_version(), basemaps=[_basemap()])
    monkeypatch.setattr(service.httpx, "get", lambda url, **_kwargs: Response())
    content, media_type = service.fetch_basemap_tile(
        session, basemap_key="nasa_blue_marble", z=4, y=6, x=13
    )
    assert (content, media_type) == (b"jpeg", "image/jpeg")
    with pytest.raises(GovernanceError) as blocked:
        service.fetch_basemap_tile(
            CatalogSession(_version()), basemap_key="arbitrary", z=4, y=6, x=13
        )
    assert blocked.value.code == "BASEMAP_NOT_FOUND"


def test_high_resolution_basemap_uses_fixed_esri_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The building-scale layer must stay allow-listed and support Guangdong z18 tiles."""

    from app.gis_catalog import service

    class Response:
        content = b"high-resolution-jpeg"
        headers = {"content-type": "image/jpeg"}

        def raise_for_status(self) -> None:
            return None

    requested: list[str] = []

    def fake_get(url: str, **_kwargs: object) -> Response:
        requested.append(url)
        return Response()

    basemap = _basemap(
        basemap_key="esri_world_imagery",
        endpoint_key="esri_world_imagery",
        title="Esri World Imagery 高分辨率影像",
        credit="Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community",
    )
    monkeypatch.setattr(service.httpx, "get", fake_get)
    content, media_type = service.fetch_basemap_tile(
        CatalogSession(_version(), basemaps=[basemap]),
        basemap_key="esri_world_imagery",
        z=18,
        y=113752,
        x=213548,
    )
    assert (content, media_type) == (b"high-resolution-jpeg", "image/jpeg")
    assert requested == [
        "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/18/113752/213548"
    ]
