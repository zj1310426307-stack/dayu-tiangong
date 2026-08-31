"""DGIS business logic for state, replay, catalog, raster proxy, and health."""

from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dgis.schemas import (
    DGISCatalogResponse,
    DGISComponent,
    DGISHealthResponse,
    FeatureStateCollection,
    FeatureStateCreate,
    FeatureStateRecord,
    SimulationLayerRecord,
    ThreeDTilesAsset,
)
from app.gis.models import DatasetVersion, FeatureState, SimulationLayer, SimulationTask


VECTOR_TILE_SOURCES = [
    "tiles.river", "tiles.road", "tiles.administrative_area",
    "tiles.place_name", "tiles.engineering_facility",
]


class DGISError(RuntimeError):
    """Represent a safe domain or upstream service failure at the API boundary."""


def _assert_version(session: Session, dataset_version_id: int) -> None:
    """Prevent state and catalog queries from silently crossing data versions."""

    if session.get(DatasetVersion, dataset_version_id) is None:
        raise DGISError(f"dataset version {dataset_version_id} does not exist")


def _serialize_state(session: Session, row: FeatureState) -> FeatureStateRecord:
    """Convert a PostGIS state row into the public CGCS2000 contract."""

    # Query the mapped geometry column by the hypertable's composite key. Rows
    # loaded through ``from_statement`` may carry EWKB as a Python value; using
    # that value directly in ST_X/ST_Y would bind it as varchar on psycopg 3.
    longitude, latitude = session.execute(
        select(func.ST_X(FeatureState.geometry), func.ST_Y(FeatureState.geometry)).where(
            FeatureState.id == row.id,
            FeatureState.timestamp == row.timestamp,
        )
    ).one()
    return FeatureStateRecord(
        id=row.id,
        dataset_version_id=row.dataset_version_id,
        feature_type=row.feature_type,
        feature_id=row.feature_id,
        timestamp=row.timestamp,
        state_json=row.state_json,
        geometry={"type": "Point", "coordinates": [longitude, latitude]},
        source=row.source,
        task_id=row.task_id,
    )


def create_feature_state(session: Session, payload: FeatureStateCreate) -> FeatureStateRecord:
    """Persist one immutable state sample with version and task provenance checks."""

    _assert_version(session, payload.dataset_version_id)
    if payload.task_id is not None:
        task = session.get(SimulationTask, payload.task_id)
        if task is None or task.dataset_version_id != payload.dataset_version_id:
            raise DGISError("task does not belong to the selected dataset version")
    longitude, latitude = payload.geometry.coordinates
    row = FeatureState(
        dataset_version_id=payload.dataset_version_id,
        feature_type=payload.feature_type,
        feature_id=payload.feature_id,
        timestamp=payload.timestamp,
        state_json=payload.state_json,
        geometry=func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4490),
        source=payload.source,
        task_id=payload.task_id,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DGISError("feature state already exists or violates provenance constraints") from exc
    session.refresh(row)
    return _serialize_state(session, row)


def list_feature_states(
    session: Session,
    dataset_version_id: int,
    feature_type: str | None,
    feature_id: int | None,
    time_start: datetime | None,
    time_end: datetime | None,
    bbox: tuple[float, float, float, float] | None,
    task_id: int | None,
    limit: int,
    offset: int,
) -> FeatureStateCollection:
    """Query the TimescaleDB hypertable by version, time, feature, and map extent."""

    _assert_version(session, dataset_version_id)
    conditions: list[Any] = [FeatureState.dataset_version_id == dataset_version_id]
    if feature_type:
        conditions.append(FeatureState.feature_type == feature_type)
    if feature_id:
        conditions.append(FeatureState.feature_id == feature_id)
    if time_start:
        conditions.append(FeatureState.timestamp >= time_start)
    if time_end:
        conditions.append(FeatureState.timestamp <= time_end)
    if task_id:
        conditions.append(FeatureState.task_id == task_id)
    if bbox:
        west, south, east, north = bbox
        conditions.append(
            func.ST_Intersects(
                FeatureState.geometry, func.ST_MakeEnvelope(west, south, east, north, 4490)
            )
        )
    total = session.scalar(select(func.count()).select_from(FeatureState).where(*conditions)) or 0
    rows = session.scalars(
        select(FeatureState).where(*conditions)
        .order_by(FeatureState.timestamp, FeatureState.feature_type, FeatureState.feature_id)
        .limit(limit).offset(offset)
    ).all()
    return FeatureStateCollection(
        items=[_serialize_state(session, row) for row in rows],
        total=total,
        dataset_version_id=dataset_version_id,
    )


def replay_feature_states(
    session: Session,
    dataset_version_id: int,
    at: datetime,
    feature_type: str | None,
    task_id: int | None,
) -> FeatureStateCollection:
    """Restore the latest state per feature at or before an absolute replay instant."""

    _assert_version(session, dataset_version_id)
    sql = """
        SELECT DISTINCT ON (feature_type, feature_id) *
        FROM feature_state
        WHERE dataset_version_id = :dataset_version_id AND timestamp <= :at
          AND (CAST(:feature_type AS varchar) IS NULL OR feature_type = :feature_type)
          AND (CAST(:task_id AS integer) IS NULL OR task_id = :task_id)
        ORDER BY feature_type, feature_id, timestamp DESC
    """
    rows = session.scalars(
        select(FeatureState).from_statement(text(sql)),
        params={
            "dataset_version_id": dataset_version_id,
            "at": at,
            "feature_type": feature_type,
            "task_id": task_id,
        },
    ).all()
    return FeatureStateCollection(
        items=[_serialize_state(session, row) for row in rows],
        total=len(rows),
        dataset_version_id=dataset_version_id,
    )


def _serialize_layer(row: SimulationLayer) -> SimulationLayerRecord:
    """Render stored layer URLs while preserving an explicit service ownership boundary."""

    service_url = row.service_url.replace("{layer_id}", str(row.id))
    return SimulationLayerRecord(
        id=row.id,
        dataset_version_id=row.dataset_version_id,
        task_id=row.task_id,
        name=row.name,
        layer_type=row.layer_type,
        time_start=row.time_start,
        time_end=row.time_end,
        service_type=row.service_type,
        service_url=service_url,
        style=row.style,
        version=row.version,
        created_time=row.created_time,
    )


def list_simulation_layers(
    session: Session, dataset_version_id: int, layer_type: str | None, task_id: int | None
) -> list[SimulationLayerRecord]:
    """List versioned model result services without exposing local filesystem paths."""

    _assert_version(session, dataset_version_id)
    conditions: list[Any] = [SimulationLayer.dataset_version_id == dataset_version_id]
    if layer_type:
        conditions.append(SimulationLayer.layer_type == layer_type)
    if task_id:
        conditions.append(SimulationLayer.task_id == task_id)
    rows = session.scalars(
        select(SimulationLayer).where(*conditions).order_by(SimulationLayer.layer_type, SimulationLayer.id)
    ).all()
    return [_serialize_layer(row) for row in rows]


def list_3d_assets(session: Session, dataset_version_id: int) -> list[ThreeDTilesAsset]:
    """Return only registered 3D Tiles services for the selected data version."""

    layers = list_simulation_layers(session, dataset_version_id, "facility_3d", None)
    return [
        ThreeDTilesAsset(
            layer_id=layer.id,
            name=layer.name,
            tileset_url=layer.service_url,
            version=layer.version,
            maximum_screen_space_error=float(layer.style.get("maximum_screen_space_error", 16)),
        )
        for layer in layers if layer.service_type == "3D_TILES"
    ]


def _probe(url: str) -> bool:
    """Perform one bounded internal HTTP health request."""

    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def _component_rows(session: Session) -> tuple[list[DGISComponent], bool]:
    """Build component status from database facts and internal health endpoints."""

    extension_version = session.scalar(
        text("SELECT extversion FROM pg_extension WHERE extname='timescaledb'")
    )
    hypertable = bool(session.scalar(text("""
        SELECT EXISTS (
            SELECT 1 FROM timescaledb_information.hypertables
            WHERE hypertable_schema='public' AND hypertable_name='feature_state'
        )
    """))) if extension_version else False
    martin_internal = os.getenv("MARTIN_INTERNAL_URL", "http://127.0.0.1:3000")
    titiler_internal = os.getenv("TITILER_INTERNAL_URL", "http://127.0.0.1:8002")
    geonode_internal = os.getenv("GEONODE_INTERNAL_URL")
    geonode_public = os.getenv("GEONODE_PUBLIC_URL", "/geonode/")
    rows = [
        DGISComponent(key="postgis", name="PostGIS", responsibility="single spatial fact store", status="online"),
        DGISComponent(key="timescaledb", name="TimescaleDB", responsibility="feature state time-series hypertable", status="online" if hypertable else "offline", version=extension_version),
        DGISComponent(key="geoserver", name="GeoServer", responsibility="WMS / WFS / WMTS", status="configured", endpoint="/geoserver/"),
        DGISComponent(
            key="geonode", name="GeoNode",
            responsibility="catalog / metadata / permission management",
            status=("online" if geonode_internal and _probe(geonode_internal) else "optional"),
            endpoint=geonode_public,
        ),
        DGISComponent(key="gdal", name="GDAL / OGR", responsibility="format validation and conversion", status="configured", endpoint="/api/v1/dgis/conversions/capabilities"),
        DGISComponent(key="martin", name="Martin", responsibility="PostGIS vector tiles", status="online" if _probe(f"{martin_internal}/health") else "offline", endpoint="/vector/"),
        DGISComponent(key="titiler", name="TiTiler", responsibility="COG raster tiles", status="online" if _probe(f"{titiler_internal}/healthz") else "offline", endpoint="/api/v1/dgis/raster/"),
        DGISComponent(key="cesium", name="CesiumJS", responsibility="2D / 3D client visualization", status="configured"),
    ]
    return rows, hypertable


def get_health(session: Session) -> DGISHealthResponse:
    """Return the real database, tile, raster, and optional catalog health state."""

    components, hypertable = _component_rows(session)
    layer_count = session.scalar(select(func.count()).select_from(SimulationLayer)) or 0
    required = {"postgis", "timescaledb", "martin", "titiler"}
    healthy = all(row.status in {"online", "configured"} for row in components if row.key in required)
    return DGISHealthResponse(
        status="healthy" if healthy else "degraded",
        timescale_hypertable=hypertable,
        components=components,
        vector_tile_sources=VECTOR_TILE_SOURCES,
        simulation_layer_count=layer_count,
    )


def get_catalog(session: Session, dataset_version_id: int) -> DGISCatalogResponse:
    """Aggregate frontend-safe catalog data from the same authoritative database."""

    components, _ = _component_rows(session)
    return DGISCatalogResponse(
        components=components,
        simulation_layers=list_simulation_layers(session, dataset_version_id, None, None),
        vector_tile_template="/vector/{source}/{z}/{x}/{y}?dataset_version_id={dataset_version_id}",
        vector_tile_sources=VECTOR_TILE_SOURCES,
        geonode_url=os.getenv("GEONODE_PUBLIC_URL", "/geonode/"),
        conversion_formats={
            "inputs": ["Shapefile ZIP", "GeoJSON", "GeoTIFF", "DXF", "KML"],
            "outputs": ["PostGIS", "GeoJSON", "COG"],
        },
    )


def read_raster_tile(session: Session, layer_id: int, z: int, x: int, y: int) -> bytes:
    """Proxy a registered local COG through TiTiler without exposing arbitrary URL fetching."""

    layer = session.get(SimulationLayer, layer_id)
    if layer is None or layer.service_type != "TITILER":
        raise DGISError("registered TiTiler layer does not exist")
    asset_path = str(layer.style.get("asset_path", ""))
    if not asset_path.startswith("/data/") or ".." in asset_path:
        raise DGISError("raster asset is outside the controlled TiTiler data directory")
    params = {"url": f"file://{asset_path}"}
    for key in ("rescale", "colormap_name"):
        value = layer.style.get(key)
        if isinstance(value, str) and value:
            params[key] = value
    base_url = os.getenv("TITILER_INTERNAL_URL", "http://127.0.0.1:8002").rstrip("/")
    url = f"{base_url}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            payload = response.read()
            if response.headers.get_content_type() != "image/png":
                raise DGISError("TiTiler returned a non-PNG response")
            return payload
    except (OSError, urllib.error.URLError) as exc:
        raise DGISError("TiTiler raster service is unavailable") from exc
