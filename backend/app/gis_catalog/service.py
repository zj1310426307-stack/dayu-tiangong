"""Merge Registry, QGIS manifest, runtime evidence, and Dataset Version safely."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.gis.models import BasemapRegistry, DatasetVersion, GISLayerRegistry
from app.geoserver import service as geoserver_service
from app.gis_catalog.schemas import (
    CatalogBasemap,
    CatalogCapabilities,
    CatalogDataset,
    CatalogGroup,
    CatalogLayer,
    CatalogProject,
    CatalogService,
    GISCatalogResponse,
)
from app.gis_governance.errors import GovernanceError
from app.qgis_server import service as qgis_service


GROUP_TITLES = {
    "01_HYDROGRAPHY": "水系",
    "02_HYDRAULIC_MODEL": "水动力模型",
    "03_ENGINEERING": "水工建筑物",
    "05_SIMULATION": "仿真与调度结果",
    "90_REFERENCE": "基础参考",
}
SERVICE_KEYS = {
    "QGIS_WMS": "qgis_wms_primary",
    "GEOSERVER_WMS_LEGACY": "geoserver_wms_legacy",
    "MARTIN_MVT": "martin_mvt",
    "TITILER": "titiler",
    "FASTAPI": "fastapi_gis",
    "CESIUM_DYNAMIC": "cesium_dynamic",
    "THREE_D_TILES": "three_d_tiles",
}
PUBLIC_ENDPOINTS = {
    "QGIS_WMS": "/qgis-server/wms",
    "GEOSERVER_WMS_LEGACY": "/geoserver/dayu/wms",
    "MARTIN_MVT": "/vector",
    "TITILER": "/api/v1/dgis/raster",
    "FASTAPI": "/api/v1/gis",
    "CESIUM_DYNAMIC": "/api/v1/gis/interaction-frame",
    "THREE_D_TILES": "/3d",
}
BASEMAP_ENDPOINTS = {
    "world_imagery_proxy": "/api/v1/gis/basemaps/world_imagery/{z}/{y}/{x}",
}


def _error(code: str, message: str, *, status_code: int, **context: Any) -> GovernanceError:
    return GovernanceError(code, message, status_code=status_code, context=context)


def _public_version(session: Session, version_id: int) -> DatasetVersion:
    version = session.get(DatasetVersion, version_id)
    if version is None:
        raise _error("DATASET_VERSION_NOT_FOUND", "Dataset version does not exist.", status_code=404, dataset_version_id=version_id)
    if version.status == "retired":
        raise _error("DATASET_VERSION_RETIRED", "Dataset version is retired.", status_code=410, dataset_version_id=version_id)
    if version.status != "published" or version.content_hash is None or version.published_at is None:
        raise _error("DATASET_VERSION_NOT_PUBLIC", "Dataset version is not publicly available.", status_code=409, dataset_version_id=version_id, status=version.status)
    return version


def _manifest() -> dict[str, Any]:
    try:
        return qgis_service.read_manifest()
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _runtime_health(modes: set[str], *, qgis_healthy: bool) -> dict[str, bool]:
    """Probe external renderers and keep in-process adapters explicit."""

    evidence = {
        "QGIS_WMS": qgis_healthy,
        "FASTAPI": True,
        "CESIUM_DYNAMIC": True,
        "THREE_D_TILES": True,
        "TITILER": False,
        "GEOSERVER_WMS_LEGACY": False,
        "MARTIN_MVT": False,
    }
    if "GEOSERVER_WMS_LEGACY" in modes:
        try:
            evidence["GEOSERVER_WMS_LEGACY"] = (
                geoserver_service.get_health().status == "healthy"
            )
        except Exception:
            evidence["GEOSERVER_WMS_LEGACY"] = False
    for mode, url in (
        ("MARTIN_MVT", f"{os.getenv('MARTIN_INTERNAL_URL', 'http://martin:3000').rstrip('/')}/health"),
        ("TITILER", f"{os.getenv('TITILER_INTERNAL_URL', 'http://titiler:8000').rstrip('/')}/healthz"),
    ):
        if mode not in modes:
            continue
        try:
            response = httpx.get(url, timeout=2.0, follow_redirects=False)
            evidence[mode] = 200 <= response.status_code < 300
        except httpx.HTTPError:
            evidence[mode] = False
    return evidence


def _services(
    modes: set[str], *, runtime_health: dict[str, bool], project_revision: str | None
) -> list[CatalogService]:
    rows: list[CatalogService] = []
    for mode in sorted(modes):
        endpoint = PUBLIC_ENDPOINTS[mode]
        values: dict[str, Any] = {
            "service_key": SERVICE_KEYS[mode], "service_mode": mode,
            "endpoint": endpoint, "healthy": runtime_health.get(mode, False),
            "revision": project_revision if mode == "QGIS_WMS" else None,
        }
        if mode == "QGIS_WMS":
            values.update(wms_version="1.3.0", gateway_contract_version="qgis-wms-gateway/v1alpha1")
        elif mode == "GEOSERVER_WMS_LEGACY":
            values.update(wms_version="1.1.1", wmts_endpoint="/geoserver/gwc/service/wmts")
        elif mode == "MARTIN_MVT":
            values.update(tile_template="/vector/{source}/{z}/{x}/{y}?dataset_version_id={dataset_version_id}", min_zoom=0, max_zoom=18)
        elif mode in {"FASTAPI", "CESIUM_DYNAMIC"}:
            values.update(endpoint_key=SERVICE_KEYS[mode])
        rows.append(CatalogService(**values))
    return rows


def build_catalog(session: Session, dataset_version_id: int) -> tuple[GISCatalogResponse, str]:
    """Build a deterministic safe DTO; internal relations never enter the response."""

    version = _public_version(session, dataset_version_id)
    registry = list(session.scalars(select(GISLayerRegistry).where(GISLayerRegistry.active.is_(True)).order_by(GISLayerRegistry.display_order, GISLayerRegistry.layer_key)).all())
    manifest = _manifest()
    manifest_layers = {str(item.get("layer_key")): item for item in manifest.get("layers", []) if item.get("layer_key")}
    qgis_short_names = [item.get("qgis_short_name") for item in manifest.get("layers", [])]
    manifest_safe = bool(manifest and qgis_short_names and len(qgis_short_names) == len(set(qgis_short_names)))
    try:
        health = qgis_service.health(session)
        qgis_healthy = health.process.passed and health.project_valid.passed and health.database_read.passed and health.wms_capabilities.passed
    except Exception:
        qgis_healthy = False
    runtime_health = _runtime_health(
        {str(row.service_mode) for row in registry}, qgis_healthy=qgis_healthy
    )
    project_revision = str(manifest.get("project_revision") or "legacy-catalog")

    groups_by_key: dict[str, CatalogGroup] = {}
    layers: list[CatalogLayer] = []
    for row in registry:
        group = groups_by_key.setdefault(
            row.group_key,
            CatalogGroup(group_key=row.group_key, title=GROUP_TITLES.get(row.group_key, row.group_key), order=row.display_order, collapsed=row.group_key == "90_REFERENCE"),
        )
        entry = manifest_layers.get(row.layer_key) if row.service_mode == "QGIS_WMS" else None
        qgis_contract_ok = row.service_mode != "QGIS_WMS" or bool(
            manifest_safe and entry and entry.get("qgis_short_name") == row.qgis_short_name and entry.get("dataset_filter_field") == "dataset_version_id"
        )
        render_enabled = qgis_contract_ok and runtime_health.get(row.service_mode, False)
        identify_enabled = bool(row.identify_enabled and render_enabled)
        legend_enabled = bool(row.legend_enabled and render_enabled)
        service: dict[str, Any] = {"kind": row.service_mode, "endpoint": PUBLIC_ENDPOINTS[row.service_mode], "layer_key": row.layer_key}
        if row.service_mode == "MARTIN_MVT":
            service["source"] = row.source_relation
        legend = {"mode": "WMS_LEGEND", "endpoint": PUBLIC_ENDPOINTS[row.service_mode], "layer_key": row.layer_key} if legend_enabled and row.render_mode == "RASTER_WMS" else None
        identify = {"mode": row.identify_mode, "identity_fields": ["feature_id", "dataset_version_id"], "detail_route_key": row.detail_route_key}
        layers.append(CatalogLayer(
            key=row.layer_key, title=row.title,
            display_title=str(entry.get("display_title") if entry else row.title),
            group_key=row.group_key, group_title=group.title,
            order=int(entry.get("order") if entry else row.display_order),
            z_index=int(entry.get("order") if entry else row.display_order),
            geometry_type=row.geometry_type, service_key=SERVICE_KEYS[row.service_mode],
            service_mode=row.service_mode, render_mode=row.render_mode,
            dataset_version_id=version.id, dataset_filter_field=row.dataset_filter_field,
            default_visible=row.default_visible, default_opacity=row.default_opacity,
            min_scale=float(entry["min_scale"]) if entry and entry.get("min_scale") else None,
            max_scale=float(entry["max_scale"]) if entry and entry.get("max_scale") else None,
            identify_enabled=identify_enabled, legend_enabled=legend_enabled,
            search_enabled=bool(row.search_enabled and render_enabled),
            qgis_short_name=row.qgis_short_name, model_entity_type=row.model_entity_type,
            service=service, legend=legend, identify=identify, cache_mode=row.cache_mode,
            capabilities={"render": render_enabled, "identify": identify_enabled, "legend": legend_enabled, "print": False},
        ))

    basemaps = [
        CatalogBasemap(
            basemap_key=row.basemap_key, title=row.title, type=row.basemap_type,
            endpoint=BASEMAP_ENDPOINTS[row.endpoint_key], credit=row.credit,
            crs=row.native_crs, visible=row.default_visible, opacity=row.default_opacity,
        )
        for row in session.scalars(select(BasemapRegistry).where(BasemapRegistry.active.is_(True), BasemapRegistry.endpoint_key.in_(BASEMAP_ENDPOINTS)).order_by(BasemapRegistry.display_order)).all()
    ]
    services = _services(
        {row.service_mode for row in registry},
        runtime_health=runtime_health,
        project_revision=project_revision,
    )
    payload = GISCatalogResponse(
        catalog_revision="pending", generated_at=datetime.now(UTC),
        project=CatalogProject(project_key="dayu_tiangong", title="大禹·天工", crs=str(manifest.get("project_crs") or "EPSG:4490"), project_revision=project_revision, qgis_project_hash=manifest.get("qgis_project_hash"), qgis_version=manifest.get("qgis_version"), extent=None),
        dataset=CatalogDataset(dataset_version_id=version.id, version=version.version, name=version.name, status="published", content_hash=version.content_hash, published_at=version.published_at, change_summary=version.change_summary),
        capabilities=CatalogCapabilities(identify=any(layer.identify_enabled for layer in layers), legend=any(layer.legend_enabled for layer in layers), print=False, measure=True, version_switch=True, external_basemap_registration=False, editing=False),
        services=services, groups=sorted(groups_by_key.values(), key=lambda item: (item.order, item.group_key)), layers=layers, basemaps=basemaps,
    )
    revision_input = payload.model_dump(mode="json", exclude={"catalog_revision", "generated_at"})
    digest = hashlib.sha256(json.dumps(revision_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    payload.catalog_revision = f"sha256:{digest}"
    return payload, f'"{digest}"'


def proxy_world_imagery(z: int, y: int, x: int) -> tuple[bytes, str]:
    """Proxy one tile from a deployment-fixed HTTPS host with strict bounds."""

    if not 0 <= z <= 22 or not 0 <= x < 2**z or not 0 <= y < 2**z:
        raise _error("BASEMAP_TILE_INVALID", "Tile coordinate is outside the supported range.", status_code=422)
    base = os.getenv("BASEMAP_WORLD_IMAGERY_URL", "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer").rstrip("/")
    parsed = urlparse(base)
    allowed_hosts = {host.strip().lower() for host in os.getenv("BASEMAP_ALLOWED_HOSTS", "server.arcgisonline.com").split(",") if host.strip()}
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise _error("BASEMAP_ENDPOINT_BLOCKED", "Configured basemap endpoint is outside the deployment allow-list.", status_code=503)
    try:
        response = httpx.get(f"{base}/tile/{z}/{y}/{x}", timeout=8.0, follow_redirects=False)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise _error("BASEMAP_UNAVAILABLE", "Configured basemap service is unavailable.", status_code=503) from exc
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in {"image/jpeg", "image/png"} or len(response.content) > 5_000_000:
        raise _error("BASEMAP_RESPONSE_BLOCKED", "Basemap response failed content validation.", status_code=502)
    return response.content, content_type
