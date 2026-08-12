"""Run post-deployment Phase 1A checks against Compose-exposed services."""

from __future__ import annotations

import json
import os
import struct
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import psycopg


GEOSERVER_URL = os.getenv("GEOSERVER_VERIFY_URL", "http://127.0.0.1:8081/geoserver").rstrip("/")
BACKEND_URL = os.getenv("BACKEND_VERIFY_URL", "http://127.0.0.1:8001").rstrip("/")
LAYERS = ("river", "river_segment", "river_node", "cross_section", "gate", "pump", "map_annotation")
CACHED = ("river", "river_segment", "gate", "pump")
DATASET_VERSION_ID = int(os.getenv("GIS_VERIFY_DATASET_VERSION_ID", "1"))


def _get(url: str) -> tuple[str, bytes, dict[str, str]]:
    """Read one validation resource and normalize response metadata."""

    with urllib.request.urlopen(url, timeout=20) as response:
        return response.headers.get_content_type(), response.read(), dict(response.headers.items())


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    """Validate the PNG signature and read IHDR dimensions without image libraries."""

    if payload[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("response is not a PNG")
    return struct.unpack(">II", payload[16:24])


def _capabilities(service: str, path: str, version: str) -> str:
    """Return one public capabilities document as UTF-8 text."""

    query = urllib.parse.urlencode(
        {"service": service, "version": version, "request": "GetCapabilities"}
    )
    media_type, payload, _ = _get(f"{GEOSERVER_URL}{path}?{query}")
    assert "xml" in media_type
    return payload.decode("utf-8", errors="replace")


def _verify_catalog_and_images() -> None:
    """Check catalog contents, rendered WMS, cached WMTS, and Basic WFS."""

    wms = _capabilities("WMS", "/dayu/wms", "1.3.0")
    wmts = _capabilities("WMTS", "/gwc/service/wmts", "1.0.0")
    wfs = _capabilities("WFS", "/dayu/ows", "2.0.0")
    for layer in LAYERS:
        assert f"dayu:{layer}" in wms or f">{layer}<" in wms
    for layer in CACHED:
        assert f"dayu:{layer}" in wmts
    wfs_root = ET.fromstring(wfs)
    operations = {
        node.attrib.get("name")
        for node in wfs_root.iter()
        if node.tag.endswith("Operation") and node.attrib.get("name")
    }
    assert not ({"Transaction", "LockFeature"} & operations)

    wms_query = urllib.parse.urlencode(
        {
            "service": "WMS",
            "version": "1.1.1",
            "request": "GetMap",
            "layers": "dayu:river,dayu:gate,dayu:pump",
            "styles": "",
            "srs": "EPSG:4490",
            "bbox": "119.9,30.0,120.65,30.55",
            "width": 512,
            "height": 384,
            "format": "image/png",
            "transparent": "true",
            "CQL_FILTER": ";".join(
                [f"dataset_version_id={DATASET_VERSION_ID}"] * 3
            ),
        }
    )
    media_type, wms_png, _ = _get(f"{GEOSERVER_URL}/dayu/wms?{wms_query}")
    assert media_type == "image/png"
    assert _png_dimensions(wms_png) == (512, 384)

    wmts_query = urllib.parse.urlencode(
        {
            "service": "WMTS",
            "version": "1.0.0",
            "request": "GetTile",
            "layer": "dayu:river",
            "style": "",
            "tilematrixset": "EPSG:900913",
            "tilematrix": "EPSG:900913:8",
            "tilerow": 105,
            "tilecol": 213,
            "format": "image/png",
            "CQL_FILTER": f"dataset_version_id={DATASET_VERSION_ID}",
        }
    )
    media_type, wmts_png, headers = _get(f"{GEOSERVER_URL}/gwc/service/wmts?{wmts_query}")
    assert media_type == "image/png"
    assert _png_dimensions(wmts_png) == (256, 256)
    normalized_headers = {name.lower(): value for name, value in headers.items()}
    assert normalized_headers.get("geowebcache-gridset") == "EPSG:900913"


def _verify_read_only_role() -> None:
    """Audit role attributes/grants and prove that a DML statement is rejected."""

    role = os.getenv("GEOSERVER_DB_USER", "dayu_geoserver")
    with psycopg.connect(
        host=os.getenv("POSTGRES_VERIFY_HOST", "127.0.0.1"),
        port=int(os.getenv("POSTGRES_VERIFY_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "dayu_tiangong"),
        user=role,
        password=os.environ["GEOSERVER_DB_PASSWORD"],
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SHOW default_transaction_read_only")
            assert cursor.fetchone()[0] == "on"
            cursor.execute("SELECT count(*) FROM river")
            assert cursor.fetchone()[0] >= 0
            try:
                cursor.execute("DELETE FROM river WHERE false")
            except psycopg.errors.ReadOnlySqlTransaction:
                connection.rollback()
            else:
                raise AssertionError("read-only GeoServer role unexpectedly accepted DELETE")


def _verify_backend() -> None:
    """Confirm the backend health API reports the real catalog and public URLs."""

    _, payload, _ = _get(f"{BACKEND_URL}/api/v1/gis/geoserver/health")
    health = json.loads(payload)
    assert health["status"] == "healthy" and health["layers"] == 7
    _, payload, _ = _get(f"{BACKEND_URL}/api/v1/gis/geoserver/layers")
    assert len(json.loads(payload)) == 7
    rivers_query = urllib.parse.urlencode(
        {"dataset_version_id": DATASET_VERSION_ID, "limit": 1}
    )
    _, payload, _ = _get(f"{BACKEND_URL}/api/v1/gis/rivers?{rivers_query}")
    assert len(json.loads(payload)["features"]) == 1


def main() -> None:
    """Run all real-service acceptance gates and print a compact success record."""

    _verify_catalog_and_images()
    _verify_read_only_role()
    _verify_backend()
    print(
        "Phase 1B live verification passed: version-filtered WMS/WMTS, "
        "Basic WFS, read-only role, FastAPI"
    )


if __name__ == "__main__":
    main()
