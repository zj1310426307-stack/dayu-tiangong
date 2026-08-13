"""Verify the Phase 1A GeoServer API boundary without requiring a live container."""

import urllib.error

from fastapi.testclient import TestClient

from app.geoserver import service
from app.main import app


client = TestClient(app)


WMS_CAPABILITIES = b"""<?xml version="1.0"?><WMS_Capabilities><Capability><Layer>
<Layer><Name>dayu:river</Name></Layer><Layer><Name>dayu:river_segment</Name></Layer>
<Layer><Name>dayu:river_node</Name></Layer><Layer><Name>dayu:cross_section</Name></Layer>
<Layer><Name>dayu:gate</Name></Layer><Layer><Name>dayu:pump</Name></Layer>
<Layer><Name>dayu:map_annotation</Name></Layer>
<Layer><Name>dayu:administrative_area</Name></Layer><Layer><Name>dayu:road</Name></Layer>
<Layer><Name>dayu:place_name</Name></Layer><Layer><Name>dayu:water_name</Name></Layer>
<Layer><Name>dayu:poi</Name></Layer><Layer><Name>dayu:dayu_basemap</Name></Layer>
</Layer></Capability></WMS_Capabilities>"""
WMTS_CAPABILITIES = b"""<?xml version="1.0"?><Capabilities><Contents>
<Layer><Identifier>dayu:river</Identifier></Layer><Layer><Identifier>dayu:river_segment</Identifier></Layer>
<Layer><Identifier>dayu:gate</Identifier></Layer><Layer><Identifier>dayu:pump</Identifier></Layer>
<Layer><Identifier>dayu:road</Identifier></Layer><Layer><Identifier>dayu:place_name</Identifier></Layer>
<Layer><Identifier>dayu:water_name</Identifier></Layer>
</Contents></Capabilities>"""
WFS_CAPABILITIES = b"""<?xml version="1.0"?><WFS_Capabilities><OperationsMetadata>
<Operation name="GetCapabilities"/><Operation name="DescribeFeatureType"/><Operation name="GetFeature"/>
</OperationsMetadata></WFS_Capabilities>"""


class _Headers:
    """Provide the media-type method consumed by urllib response headers."""

    @staticmethod
    def get_content_type() -> str:
        return "application/xml"


class _Response:
    """Act as a minimal context-managed capabilities response."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.headers = _Headers()

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_health_layers_and_config(monkeypatch) -> None:
    """Health must validate both capabilities while other APIs stay credential-free."""

    def fake_urlopen(url: str, timeout: int) -> _Response:
        assert timeout == 5
        if "WMTS" in url:
            return _Response(WMTS_CAPABILITIES)
        if "WFS" in url:
            return _Response(WFS_CAPABILITIES)
        return _Response(WMS_CAPABILITIES)

    monkeypatch.setattr(service.urllib.request, "urlopen", fake_urlopen)
    health = client.get("/api/v1/gis/geoserver/health")
    assert health.status_code == 200
    assert health.json() == {
        "status": "healthy",
        "workspace": "dayu",
        "layers": 12,
        "cached_layers": 7,
        "basemap_group": "dayu_basemap",
        "wms": "online",
        "wmts": "online",
        "wfs_mode": "basic-read-only",
        "source": "PostGIS / CGCS2000",
    }

    layers = client.get("/api/v1/gis/geoserver/layers").json()
    assert [layer["name"] for layer in layers] == [
        "river", "river_segment", "river_node", "cross_section", "gate", "pump",
        "map_annotation", "administrative_area", "road", "place_name", "water_name", "poi",
    ]
    assert sum(layer["wmts_cached"] for layer in layers) == 7
    assert all(layer["srid"] == 4490 for layer in layers)

    config = client.get("/api/v1/gis/geoserver/config").json()
    assert config["wms_url"] == "/geoserver/dayu/wms"
    assert config["wmts_url"] == "/geoserver/gwc/service/wmts"
    assert config["interaction_source"] == "FastAPI /api/v1/gis/*"
    assert "rest" not in " ".join(config.values()).lower()


def test_health_maps_upstream_failure_to_503(monkeypatch) -> None:
    """An unavailable GeoServer must not be reported as healthy or leak its URL."""

    def failing_urlopen(_url: str, timeout: int) -> _Response:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(service.urllib.request, "urlopen", failing_urlopen)
    response = client.get("/api/v1/gis/geoserver/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "GeoServer 空间服务不可用"}


def test_public_config_rejects_management_or_cross_origin_urls(monkeypatch) -> None:
    """Frontend configuration must never become a credentialed/admin endpoint escape hatch."""

    monkeypatch.setenv("GEOSERVER_PUBLIC_WMS_URL", "https://example.com/geoserver/dayu/wms")
    response = client.get("/api/v1/gis/geoserver/config")
    assert response.status_code == 500

    monkeypatch.setenv("GEOSERVER_PUBLIC_WMS_URL", "/geoserver/rest/workspaces")
    response = client.get("/api/v1/gis/geoserver/config")
    assert response.status_code == 500
