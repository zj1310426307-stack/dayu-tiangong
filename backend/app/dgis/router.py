"""HTTP boundary for DGIS health, state, replay, catalog, raster, and 3D assets."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app.dgis import service
from app.dgis.schemas import (
    DGISCatalogResponse,
    DGISHealthResponse,
    FeatureStateCollection,
    FeatureStateCreate,
    FeatureStateRecord,
    SimulationLayerRecord,
    ThreeDTilesAsset,
)
from app.gis.service import parse_bbox


router = APIRouter(prefix="/api/v1/dgis", tags=["dgis-foundation"])
SessionDependency = Annotated[Session, Depends(get_database_session)]


def _domain_call(session: Session, action):
    """Translate DGIS domain errors into stable conflict or availability responses."""

    try:
        return action()
    except service.DGISError as exc:
        session.rollback()
        message = str(exc)
        code = status.HTTP_503_SERVICE_UNAVAILABLE if "unavailable" in message else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=message) from exc


@router.get("/health", response_model=DGISHealthResponse, summary="检查 DGIS 开源组件与时空底座")
def read_health(session: SessionDependency) -> DGISHealthResponse:
    """Expose component boundaries and real TimescaleDB hypertable status."""

    return _domain_call(session, lambda: service.get_health(session))


@router.get("/catalog", response_model=DGISCatalogResponse, summary="读取 DGIS 资产与服务目录")
def read_catalog(
    session: SessionDependency, dataset_version_id: int = Query(gt=0)
) -> DGISCatalogResponse:
    """Return one version-owned catalog for the React/Cesium workspace."""

    return _domain_call(session, lambda: service.get_catalog(session, dataset_version_id))


@router.post("/feature-states", response_model=FeatureStateRecord, status_code=201, summary="写入时空状态")
def create_state(payload: FeatureStateCreate, session: SessionDependency) -> FeatureStateRecord:
    """Append one immutable observation, simulation, dispatch, or import state."""

    return _domain_call(session, lambda: service.create_feature_state(session, payload))


@router.get("/feature-states", response_model=FeatureStateCollection, summary="按时间和空间查询状态")
def read_states(
    session: SessionDependency,
    dataset_version_id: int = Query(gt=0),
    feature_type: str | None = Query(default=None),
    feature_id: int | None = Query(default=None, gt=0),
    time_start: datetime | None = None,
    time_end: datetime | None = None,
    bbox: str | None = None,
    task_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=1000, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> FeatureStateCollection:
    """Read a bounded slice of the TimescaleDB/PostGIS state hypertable."""

    try:
        parsed_bbox = parse_bbox(bbox)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _domain_call(session, lambda: service.list_feature_states(
        session, dataset_version_id, feature_type, feature_id, time_start, time_end,
        parsed_bbox, task_id, limit, offset,
    ))


@router.get("/feature-states/replay", response_model=FeatureStateCollection, summary="恢复指定时刻状态")
def replay_states(
    session: SessionDependency,
    dataset_version_id: int = Query(gt=0),
    at: datetime = Query(),
    feature_type: str | None = Query(default=None),
    task_id: int | None = Query(default=None, gt=0),
) -> FeatureStateCollection:
    """Restore the newest sample per feature at or before the replay instant."""

    return _domain_call(session, lambda: service.replay_feature_states(
        session, dataset_version_id, at, feature_type, task_id
    ))


@router.get("/simulation-layers", response_model=list[SimulationLayerRecord], summary="读取模型结果空间图层")
def read_simulation_layers(
    session: SessionDependency,
    dataset_version_id: int = Query(gt=0),
    layer_type: str | None = Query(default=None),
    task_id: int | None = Query(default=None, gt=0),
) -> list[SimulationLayerRecord]:
    """Filter water level, velocity, risk, terrain, and 3D layer registrations."""

    return _domain_call(session, lambda: service.list_simulation_layers(
        session, dataset_version_id, layer_type, task_id
    ))


@router.get("/3d-tiles", response_model=list[ThreeDTilesAsset], summary="读取 3D Tiles 资产清单")
def read_3d_assets(
    session: SessionDependency, dataset_version_id: int = Query(gt=0)
) -> list[ThreeDTilesAsset]:
    """Expose registered Cesium 3D Tiles assets without implementing a custom converter."""

    return _domain_call(session, lambda: service.list_3d_assets(session, dataset_version_id))


@router.get("/raster/{layer_id}/{z}/{x}/{y}.png", summary="读取受控 TiTiler COG 瓦片")
def read_raster_tile(
    layer_id: int, z: int, x: int, y: int, session: SessionDependency
) -> Response:
    """Proxy only registered local COGs, preventing arbitrary TiTiler URL access."""

    if z < 0 or z > 22 or x < 0 or y < 0 or x >= 2 ** z or y >= 2 ** z:
        raise HTTPException(status_code=422, detail="invalid WebMercator tile coordinate")
    payload = _domain_call(session, lambda: service.read_raster_tile(session, layer_id, z, x, y))
    return Response(content=payload, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})
