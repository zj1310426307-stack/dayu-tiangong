"""GIS HTTP 路由：健康、统计、GeoJSON 列表和属性详情。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app.gis import service
from app.gis.schemas import (
    GISHealthResponse,
    GISInteractionFrame,
    GISStatisticsResponse,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
)


router = APIRouter(prefix="/api/v1/gis", tags=["gis"])
SessionDependency = Annotated[Session, Depends(get_database_session)]
LimitQuery = Annotated[int, Query(ge=1, le=1000, description="单页最多返回 1000 个对象")]
OffsetQuery = Annotated[int, Query(ge=0, description="从零开始的分页偏移量")]
DatasetVersionQuery = Annotated[int, Query(gt=0, description="强制隔离的业务数据版本 ID")]
BBoxQuery = Annotated[
    str | None,
    Query(alias="bbox", description="CGCS2000 / EPSG:4490 范围：minx,miny,maxx,maxy"),
]


def _parse_bbox_or_422(raw_bbox: str | None) -> service.BBox | None:
    """把 bbox 解析错误稳定映射为 HTTP 422。"""

    try:
        return service.parse_bbox(raw_bbox)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


def _not_found(feature_name: str) -> HTTPException:
    """构造一致的空间对象不存在响应。"""

    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{feature_name}不存在")


@router.get("/health", response_model=GISHealthResponse, summary="检查 PostGIS 真实连接")
def read_gis_health(session: SessionDependency) -> GISHealthResponse:
    """执行真实 PostGIS SQL；连接或扩展异常时返回 503。"""

    try:
        return service.get_gis_health(session)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostGIS 不可用",
        ) from exc


@router.get("/stats", response_model=GISStatisticsResponse, summary="获取指定版本 GIS DEMO DATA 统计")
def read_gis_statistics(dataset_version_id: DatasetVersionQuery, session: SessionDependency) -> GISStatisticsResponse:
    """返回数据库中四类空间对象的实时计数。"""

    return service.get_statistics(session, dataset_version_id)


@router.get("/rivers", response_model=GeoJSONFeatureCollection, summary="获取河道 GeoJSON")
def read_rivers(
    session: SessionDependency,
    dataset_version_id: DatasetVersionQuery,
    bbox: BBoxQuery = None,
    limit: LimitQuery = 500,
    offset: OffsetQuery = 0,
) -> GeoJSONFeatureCollection:
    """按 bbox 和分页参数读取河道。"""

    return service.list_rivers(session, dataset_version_id, _parse_bbox_or_422(bbox), limit, offset)


@router.get("/rivers/{river_id}", response_model=GeoJSONFeature, summary="获取单条河道")
def read_river(river_id: int, dataset_version_id: DatasetVersionQuery, session: SessionDependency) -> GeoJSONFeature:
    """返回河道属性、空间信息和断面数量。"""

    feature = service.get_river(session, river_id, dataset_version_id)
    if feature is None:
        raise _not_found("河道")
    return feature


@router.get("/gates", response_model=GeoJSONFeatureCollection, summary="获取闸门 GeoJSON")
def read_gates(
    session: SessionDependency,
    dataset_version_id: DatasetVersionQuery,
    bbox: BBoxQuery = None,
    limit: LimitQuery = 500,
    offset: OffsetQuery = 0,
) -> GeoJSONFeatureCollection:
    """按 bbox 和分页参数读取闸门。"""

    return service.list_gates(session, dataset_version_id, _parse_bbox_or_422(bbox), limit, offset)


@router.get("/gates/{gate_id}", response_model=GeoJSONFeature, summary="获取单个闸门")
def read_gate(gate_id: int, dataset_version_id: DatasetVersionQuery, session: SessionDependency) -> GeoJSONFeature:
    """返回闸门属性与空间位置。"""

    feature = service.get_gate(session, gate_id, dataset_version_id)
    if feature is None:
        raise _not_found("闸门")
    return feature


@router.get("/pumps", response_model=GeoJSONFeatureCollection, summary="获取泵站 GeoJSON")
def read_pumps(
    session: SessionDependency,
    dataset_version_id: DatasetVersionQuery,
    bbox: BBoxQuery = None,
    limit: LimitQuery = 500,
    offset: OffsetQuery = 0,
) -> GeoJSONFeatureCollection:
    """按 bbox 和分页参数读取泵站。"""

    return service.list_pumps(session, dataset_version_id, _parse_bbox_or_422(bbox), limit, offset)


@router.get("/pumps/{pump_id}", response_model=GeoJSONFeature, summary="获取单个泵站")
def read_pump(pump_id: int, dataset_version_id: DatasetVersionQuery, session: SessionDependency) -> GeoJSONFeature:
    """返回泵站属性与空间位置。"""

    feature = service.get_pump(session, pump_id, dataset_version_id)
    if feature is None:
        raise _not_found("泵站")
    return feature


@router.get(
    "/cross_sections",
    response_model=GeoJSONFeatureCollection,
    summary="获取横断面 GeoJSON",
)
def read_cross_sections(
    session: SessionDependency,
    dataset_version_id: DatasetVersionQuery,
    bbox: BBoxQuery = None,
    limit: LimitQuery = 500,
    offset: OffsetQuery = 0,
) -> GeoJSONFeatureCollection:
    """按 bbox 和分页参数读取横断面定位点。"""

    return service.list_cross_sections(session, dataset_version_id, _parse_bbox_or_422(bbox), limit, offset)


@router.get(
    "/cross_sections/{section_id}",
    response_model=GeoJSONFeature,
    summary="获取单个横断面",
)
def read_cross_section(section_id: int, dataset_version_id: DatasetVersionQuery, session: SessionDependency) -> GeoJSONFeature:
    """返回横断面属性、高程数组与空间位置。"""

    feature = service.get_cross_section(session, section_id, dataset_version_id)
    if feature is None:
        raise _not_found("横断面")
    return feature


@router.get(
    "/interaction-frame",
    response_model=GISInteractionFrame,
    summary="读取版本隔离的 GIS 动态结果帧",
)
def read_interaction_frame(
    dataset_version_id: DatasetVersionQuery,
    session: SessionDependency,
    time_seconds: float = Query(default=0, ge=0),
    task_id: int | None = Query(default=None, gt=0),
    dispatch_run_id: int | None = Query(default=None, gt=0),
) -> GISInteractionFrame:
    """Atomically return hydraulic and dispatch overlays for one dataset version/time."""

    try:
        return service.get_interaction_frame(
            session, dataset_version_id, time_seconds, task_id, dispatch_run_id
        )
    except service.GISVersionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
