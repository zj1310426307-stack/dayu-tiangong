"""Build the PostGIS Catalog and proxy only allow-listed GeoServer requests."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import math
import os
import re
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.geoserver import service as geoserver_service
from app.gis.models import DatasetVersion, GISCatalogLayer
from app.gis_catalog.schemas import (
    CatalogBasemap,
    CatalogCapabilities,
    CatalogDataset,
    CatalogFeature,
    CatalogGroup,
    CatalogLayer,
    CatalogProject,
    CatalogService,
    GISCatalogResponse,
    GISFeatureInfoResponse,
)
from app.gis_governance.errors import GovernanceError


GROUP_TITLES = {
    "01_HYDROGRAPHY": "水系",
    "02_HYDRAULIC_MODEL": "水动力模型",
    "03_ENGINEERING": "水工建筑物",
    "90_REFERENCE": "基础参考",
}
SAFE_PROPERTY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
WEB_MERCATOR_LIMIT = 20_037_508.35


def _error(code: str, message: str, *, status_code: int, **context: Any) -> GovernanceError:
    """Create one structured GIS boundary error."""

    return GovernanceError(code, message, status_code=status_code, context=context)


def _public_version(session: Session, version_id: int) -> DatasetVersion:
    """Require one immutable public dataset version before any map read."""

    version = session.get(DatasetVersion, version_id)
    if version is None:
        raise _error("DATASET_VERSION_NOT_FOUND", "Dataset version does not exist.", status_code=404, dataset_version_id=version_id)
    if version.status == "retired":
        raise _error("DATASET_VERSION_RETIRED", "Dataset version is retired.", status_code=410, dataset_version_id=version_id)
    if version.status != "published" or version.content_hash is None or version.published_at is None:
        raise _error("DATASET_VERSION_NOT_PUBLIC", "Dataset version is not publicly available.", status_code=409, dataset_version_id=version_id, status=version.status)
    return version


def _catalog_rows(session: Session) -> list[GISCatalogLayer]:
    """Read active GeoServer rows from the only PostGIS Catalog."""

    return list(
        session.scalars(
            select(GISCatalogLayer)
            .where(GISCatalogLayer.active.is_(True))
            .order_by(GISCatalogLayer.display_order, GISCatalogLayer.layer_key)
        ).all()
    )


def _geoserver_healthy() -> bool:
    """Keep external health evidence separate from Catalog existence."""

    try:
        return geoserver_service.get_health().status == "healthy"
    except Exception:
        return False


def build_catalog(session: Session, dataset_version_id: int) -> tuple[GISCatalogResponse, str]:
    """Build a deterministic GeoServer-only Catalog with no internal URL or SQL leakage."""

    version = _public_version(session, dataset_version_id)
    rows = _catalog_rows(session)
    healthy = _geoserver_healthy()
    groups: dict[str, CatalogGroup] = {}
    layers: list[CatalogLayer] = []
    for row in rows:
        group = groups.setdefault(
            row.group_key,
            CatalogGroup(
                group_key=row.group_key,
                title=GROUP_TITLES.get(row.group_key, row.group_key),
                order=row.display_order,
                collapsed=row.group_key == "90_REFERENCE",
            ),
        )
        layers.append(
            CatalogLayer(
                key=row.layer_key,
                title=row.title,
                group_key=row.group_key,
                group_title=group.title,
                order=row.display_order,
                z_index=row.display_order,
                geometry_type=row.geometry_type,
                layer_name=f"dayu:{row.source_relation}",
                dataset_version_id=version.id,
                default_visible=row.default_visible,
                default_opacity=row.default_opacity,
                identify_enabled=bool(row.identify_enabled and healthy),
                legend_enabled=bool(row.legend_enabled and healthy),
                search_enabled=bool(row.search_enabled and healthy),
                detail_route_key=row.detail_route_key,
                model_entity_type=row.model_entity_type,
                cache_mode=row.cache_mode,
                capabilities={
                    "render": healthy,
                    "identify": bool(row.identify_enabled and healthy),
                    "legend": bool(row.legend_enabled and healthy),
                    "print": False,
                },
            )
        )

    payload = GISCatalogResponse(
        catalog_revision="pending",
        generated_at=datetime.now(UTC),
        project=CatalogProject(project_key="dayu_tiangong", title="大禹·天工"),
        dataset=CatalogDataset(
            dataset_version_id=version.id,
            version=version.version,
            name=version.name,
            status="published",
            content_hash=version.content_hash,
            published_at=version.published_at,
            change_summary=version.change_summary,
        ),
        capabilities=CatalogCapabilities(
            identify=any(layer.identify_enabled for layer in layers),
            legend=any(layer.legend_enabled for layer in layers),
            measure=True,
            version_switch=True,
        ),
        services=[CatalogService(healthy=healthy)],
        groups=sorted(groups.values(), key=lambda item: (item.order, item.group_key)),
        layers=layers,
        basemaps=[CatalogBasemap()],
    )
    revision_input = payload.model_dump(mode="json", exclude={"catalog_revision", "generated_at"})
    digest = hashlib.sha256(json.dumps(revision_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    payload.catalog_revision = f"sha256:{digest}"
    return payload, f'"{digest}"'


def list_catalog_layers(session: Session, dataset_version_id: int) -> list[CatalogLayer]:
    """Expose the layer portion as the stable minimal `/layers` API."""

    catalog, _ = build_catalog(session, dataset_version_id)
    return catalog.layers


def _catalog_layer(session: Session, layer_key: str) -> GISCatalogLayer:
    """Resolve one active layer key without accepting arbitrary GeoServer names."""

    if not re.fullmatch(r"[a-z][a-z0-9_]{1,62}", layer_key):
        raise _error("GIS_LAYER_INVALID", "Layer key is invalid.", status_code=422)
    layer = session.scalar(select(GISCatalogLayer).where(GISCatalogLayer.layer_key == layer_key, GISCatalogLayer.active.is_(True)))
    if layer is None:
        raise _error("GIS_LAYER_NOT_FOUND", "Layer is not in the active Catalog.", status_code=404, layer_key=layer_key)
    return layer


def _bbox(raw: str) -> tuple[float, float, float, float]:
    """Validate an EPSG:3857 map extent before forwarding it to GeoServer."""

    try:
        values = tuple(float(value.strip()) for value in raw.split(","))
    except ValueError as exc:
        raise _error("GIS_BBOX_INVALID", "BBOX must contain four numbers.", status_code=422) from exc
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        raise _error("GIS_BBOX_INVALID", "BBOX must contain four finite numbers.", status_code=422)
    min_x, min_y, max_x, max_y = values
    if not (-WEB_MERCATOR_LIMIT <= min_x < max_x <= WEB_MERCATOR_LIMIT and -WEB_MERCATOR_LIMIT <= min_y < max_y <= WEB_MERCATOR_LIMIT):
        raise _error("GIS_BBOX_INVALID", "BBOX is outside EPSG:3857 or has invalid ordering.", status_code=422)
    return values


def _upstream_get(params: dict[str, str], *, expected: set[str], limit: int) -> httpx.Response:
    """Call private GeoServer with bounded time, status, media type, and size."""

    base = os.getenv("GEOSERVER_INTERNAL_URL", "http://geoserver:8080/geoserver").rstrip("/")
    try:
        response = httpx.get(f"{base}/dayu/wms", params=params, timeout=10.0, follow_redirects=False)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise _error("GEOSERVER_UNAVAILABLE", "GeoServer map service is unavailable.", status_code=503) from exc
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in expected or len(response.content) > limit:
        raise _error("GEOSERVER_RESPONSE_BLOCKED", "GeoServer response failed content validation.", status_code=502)
    return response


def render_wms_map(
    session: Session,
    *,
    dataset_version_id: int,
    layer_key: str,
    bbox: str,
    width: int,
    height: int,
    image_format: str,
    transparent: bool,
) -> tuple[bytes, str]:
    """Render one allow-listed, version-filtered WMS image through GeoServer."""

    _public_version(session, dataset_version_id)
    layer = _catalog_layer(session, layer_key)
    extent = _bbox(bbox)
    if not 1 <= width <= 2048 or not 1 <= height <= 2048:
        raise _error("GIS_IMAGE_SIZE_INVALID", "Map dimensions must be between 1 and 2048.", status_code=422)
    media_type = image_format.lower()
    if media_type not in {"image/png", "image/jpeg"}:
        raise _error("GIS_IMAGE_FORMAT_INVALID", "Only PNG and JPEG map images are supported.", status_code=422)
    response = _upstream_get(
        {
            "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap",
            "LAYERS": f"dayu:{layer.source_relation}", "STYLES": "", "SRS": "EPSG:3857",
            "BBOX": ",".join(str(value) for value in extent), "WIDTH": str(width), "HEIGHT": str(height),
            "FORMAT": media_type, "TRANSPARENT": "TRUE" if transparent else "FALSE",
            "CQL_FILTER": f"dataset_version_id={dataset_version_id}",
        },
        expected={"image/png", "image/jpeg"},
        limit=10_000_000,
    )
    return response.content, response.headers.get("content-type", media_type).split(";", 1)[0]


def feature_info(
    session: Session,
    *,
    dataset_version_id: int,
    layer_key: str,
    bbox: str,
    width: int,
    height: int,
    x: int,
    y: int,
) -> GISFeatureInfoResponse:
    """Return sanitized attributes for one OpenLayers map click."""

    _public_version(session, dataset_version_id)
    layer = _catalog_layer(session, layer_key)
    extent = _bbox(bbox)
    if not 1 <= width <= 2048 or not 1 <= height <= 2048 or not 0 <= x < width or not 0 <= y < height:
        raise _error("GIS_FEATURE_INFO_PIXEL_INVALID", "FeatureInfo pixel is outside the map image.", status_code=422)
    response = _upstream_get(
        {
            "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetFeatureInfo",
            "LAYERS": f"dayu:{layer.source_relation}", "QUERY_LAYERS": f"dayu:{layer.source_relation}",
            "STYLES": "", "SRS": "EPSG:3857", "BBOX": ",".join(str(value) for value in extent),
            "WIDTH": str(width), "HEIGHT": str(height), "X": str(x), "Y": str(y),
            "INFO_FORMAT": "application/json", "FEATURE_COUNT": "10",
            "CQL_FILTER": f"dataset_version_id={dataset_version_id}",
        },
        expected={"application/json"},
        limit=2_000_000,
    )
    try:
        raw = response.json()
    except ValueError as exc:
        raise _error("GEOSERVER_RESPONSE_INVALID", "GeoServer FeatureInfo is not valid JSON.", status_code=502) from exc
    items = raw.get("features", []) if isinstance(raw, dict) else []
    features: list[CatalogFeature] = []
    for item in items[:10] if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        safe_properties = {
            str(key): value
            for key, value in list(properties.items())[:50]
            if SAFE_PROPERTY.fullmatch(str(key)) and isinstance(value, (str, int, float, bool, type(None), list, dict))
        }
        raw_geometry = item.get("geometry")
        features.append(
            CatalogFeature(
                id=str(item.get("id") or safe_properties.get("id") or "unknown"),
                geometry=raw_geometry if isinstance(raw_geometry, dict) else None,
                properties=safe_properties,
            )
        )
    return GISFeatureInfoResponse(layer_key=layer_key, dataset_version_id=dataset_version_id, features=features)
