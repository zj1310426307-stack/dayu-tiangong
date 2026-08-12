"""Probe public GeoServer services and return source-controlled catalog metadata."""

from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from app.geoserver.schemas import (
    GeoServerConfigResponse,
    GeoServerHealthResponse,
    GeoServerLayerRecord,
)


WORKSPACE = "dayu"
EXPECTED_LAYERS: tuple[GeoServerLayerRecord, ...] = (
    GeoServerLayerRecord(name="river", qualified_name="dayu:river", title="河道", geometry_type="LineString", style="river", wmts_cached=True),
    GeoServerLayerRecord(name="river_segment", qualified_name="dayu:river_segment", title="河段", geometry_type="LineString", style="river_segment", wmts_cached=True),
    GeoServerLayerRecord(name="river_node", qualified_name="dayu:river_node", title="河网节点", geometry_type="Point", style="river_node", wmts_cached=False),
    GeoServerLayerRecord(name="cross_section", qualified_name="dayu:cross_section", title="横断面", geometry_type="Point", style="cross_section", wmts_cached=False),
    GeoServerLayerRecord(name="gate", qualified_name="dayu:gate", title="闸门", geometry_type="Point", style="gate", wmts_cached=True),
    GeoServerLayerRecord(name="pump", qualified_name="dayu:pump", title="泵站", geometry_type="Point", style="pump", wmts_cached=True),
    GeoServerLayerRecord(name="map_annotation", qualified_name="dayu:map_annotation", title="地点注记", geometry_type="Point", style="map_annotation", wmts_cached=False),
)


class GeoServerUnavailable(RuntimeError):
    """Indicate that real OGC service validation could not be completed."""


@dataclass(frozen=True)
class _EndpointConfig:
    """Keep internal probe URLs separate from public browser-facing URLs."""

    internal_base_url: str
    public_wms_url: str
    public_wmts_url: str
    public_wfs_url: str


def _public_ogc_path(value: str, label: str) -> str:
    """Restrict frontend configuration to same-origin public OGC paths."""

    parsed = urllib.parse.urlparse(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/geoserver/"):
        raise ValueError(f"{label} must be a same-origin /geoserver/* path")
    lowered = parsed.path.lower()
    if any(segment in lowered for segment in ("/rest", "/web")):
        raise ValueError(f"{label} must not expose a GeoServer management endpoint")
    return parsed.path


def _load_endpoints() -> _EndpointConfig:
    """Load GeoServer addresses without accepting frontend administrator URLs."""

    return _EndpointConfig(
        internal_base_url=os.getenv(
            "GEOSERVER_INTERNAL_URL", "http://127.0.0.1:8081/geoserver"
        ).rstrip("/"),
        public_wms_url=_public_ogc_path(
            os.getenv("GEOSERVER_PUBLIC_WMS_URL", "/geoserver/dayu/wms"), "WMS URL"
        ),
        public_wmts_url=_public_ogc_path(
            os.getenv("GEOSERVER_PUBLIC_WMTS_URL", "/geoserver/gwc/service/wmts"), "WMTS URL"
        ),
        public_wfs_url=_public_ogc_path(
            os.getenv("GEOSERVER_PUBLIC_WFS_URL", "/geoserver/dayu/ows"), "WFS URL"
        ),
    )


def _read_xml(url: str) -> ET.Element:
    """Fetch and parse one capabilities document with a bounded timeout."""

    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            media_type = response.headers.get_content_type()
            payload = response.read()
    except (OSError, urllib.error.URLError) as exc:
        raise GeoServerUnavailable(f"GeoServer connection failed: {url}") from exc
    if "xml" not in media_type:
        raise GeoServerUnavailable(f"GeoServer returned unexpected media type: {media_type}")
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise GeoServerUnavailable("GeoServer capabilities are not valid XML") from exc


def _capabilities_url(base_url: str, service: str, path: str) -> str:
    """Build a deterministic OGC GetCapabilities URL."""

    query = urllib.parse.urlencode(
        {"service": service, "version": "1.0.0" if service == "WMTS" else "1.3.0", "request": "GetCapabilities"}
    )
    return f"{base_url}{path}?{query}"


def _layer_names(root: ET.Element) -> set[str]:
    """Extract qualified and unqualified layer identifiers from capabilities XML."""

    names: set[str] = set()
    for node in root.iter():
        if not (node.tag.endswith("Name") or node.tag.endswith("Identifier")) or not node.text:
            continue
        value = node.text.strip()
        names.add(value)
        names.add(value.split(":")[-1])
    return names


def get_health() -> GeoServerHealthResponse:
    """Verify WMS/WMTS catalogs and confirm that WFS remains read-only."""

    endpoints = _load_endpoints()
    wms = _read_xml(
        _capabilities_url(endpoints.internal_base_url, "WMS", f"/{WORKSPACE}/wms")
    )
    wmts = _read_xml(
        _capabilities_url(endpoints.internal_base_url, "WMTS", "/gwc/service/wmts")
    )
    wfs_url = (
        f"{endpoints.internal_base_url}/{WORKSPACE}/ows?"
        + urllib.parse.urlencode(
            {"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"}
        )
    )
    wfs = _read_xml(wfs_url)
    wms_names = _layer_names(wms)
    wmts_names = _layer_names(wmts)
    missing_wms = {layer.name for layer in EXPECTED_LAYERS} - wms_names
    expected_cached = {layer.qualified_name for layer in EXPECTED_LAYERS if layer.wmts_cached}
    missing_wmts = expected_cached - wmts_names
    if missing_wms or missing_wmts:
        raise GeoServerUnavailable(
            f"GeoServer catalog incomplete: WMS={sorted(missing_wms)}, WMTS={sorted(missing_wmts)}"
        )
    operations = {
        node.attrib.get("name")
        for node in wfs.iter()
        if node.tag.endswith("Operation") and node.attrib.get("name")
    }
    if {"Transaction", "LockFeature"} & operations:
        raise GeoServerUnavailable("GeoServer WFS-T is enabled")
    return GeoServerHealthResponse(
        status="healthy",
        layers=len(EXPECTED_LAYERS),
        cached_layers=len(expected_cached),
    )


def list_layers() -> list[GeoServerLayerRecord]:
    """Return the immutable layer/style/cache contract used by bootstrap and frontend."""

    return list(EXPECTED_LAYERS)


def get_public_config() -> GeoServerConfigResponse:
    """Return only browser-safe OGC paths and the FastAPI interaction boundary."""

    endpoints = _load_endpoints()
    return GeoServerConfigResponse(
        wms_url=endpoints.public_wms_url,
        wmts_url=endpoints.public_wmts_url,
        wfs_url=endpoints.public_wfs_url,
    )
