"""GIS 业务服务：空间筛选、分页、GeoJSON 序列化与真实健康查询。"""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeAlias

from sqlalchemy import Select, func, select, text
from sqlalchemy.orm import Session

from app.gis.models import CrossSection, Gate, Pump, River
from app.gis.schemas import (
    GISHealthResponse,
    GISStatisticsResponse,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    PaginationMeta,
)


BBox: TypeAlias = tuple[float, float, float, float]


def parse_bbox(raw_bbox: str | None) -> BBox | None:
    """解析并校验 `minx,miny,maxx,maxy` 格式的 WGS 84 空间范围。"""

    if raw_bbox is None:
        return None

    try:
        values = tuple(float(value.strip()) for value in raw_bbox.split(","))
    except ValueError as exc:
        raise ValueError("bbox 必须包含四个数值") from exc

    if len(values) != 4:
        raise ValueError("bbox 必须使用 minx,miny,maxx,maxy 格式")

    min_x, min_y, max_x, max_y = values
    if not (-180 <= min_x < max_x <= 180 and -90 <= min_y < max_y <= 90):
        raise ValueError("bbox 超出 EPSG:4326 范围或最小值不小于最大值")
    return min_x, min_y, max_x, max_y


def _spatial_filter(geometry_column: Any, bbox: BBox | None) -> list[Any]:
    """根据可选 bbox 创建 PostGIS ST_Intersects 查询条件。"""

    if bbox is None:
        return []
    return [func.ST_Intersects(geometry_column, func.ST_MakeEnvelope(*bbox, 4326))]


def _decode_geometry(raw_geometry: str) -> dict[str, Any]:
    """将 PostGIS `ST_AsGeoJSON` 文本解码为响应对象。"""

    geometry = json.loads(raw_geometry)
    if not isinstance(geometry, dict):
        raise ValueError("数据库返回了无效 GeoJSON 几何")
    return geometry


def _iso(value: datetime) -> str:
    """输出带时区的 ISO 8601 时间文本。"""

    return value.isoformat()


def _collection(
    features: list[GeoJSONFeature],
    total: int,
    limit: int,
    offset: int,
    bbox: BBox | None,
) -> GeoJSONFeatureCollection:
    """集中构造 FeatureCollection 与分页元数据。"""

    return GeoJSONFeatureCollection(
        features=features,
        meta=PaginationMeta(
            total=total,
            limit=limit,
            offset=offset,
            bbox=list(bbox) if bbox else None,
        ),
    )


def list_rivers(
    session: Session,
    bbox: BBox | None,
    limit: int,
    offset: int,
) -> GeoJSONFeatureCollection:
    """查询河道并附带每条河道的横断面数量。"""

    conditions = _spatial_filter(River.geometry, bbox)
    total = session.scalar(select(func.count(River.id)).where(*conditions)) or 0
    section_count = (
        select(func.count(CrossSection.id))
        .where(CrossSection.river_id == River.id)
        .correlate(River)
        .scalar_subquery()
    )
    statement = (
        select(
            River,
            func.ST_AsGeoJSON(River.geometry, 8).label("geometry_json"),
            section_count.label("section_count"),
        )
        .where(*conditions)
        .order_by(River.id)
        .limit(limit)
        .offset(offset)
    )
    features = [
        GeoJSONFeature(
            id=river.id,
            geometry=_decode_geometry(geometry_json),
            properties={
                "feature_type": "river",
                "name": river.name,
                "code": river.code,
                "length": river.length,
                "level": river.level,
                "status": river.status,
                "dataset_version_id": river.dataset_version_id,
                "description": river.description,
                "cross_section_count": cross_section_total,
                "created_time": _iso(river.created_time),
                "demo_data": True,
            },
        )
        for river, geometry_json, cross_section_total in session.execute(statement).all()
    ]
    return _collection(features, total, limit, offset, bbox)


def _list_point_features(
    session: Session,
    model: Any,
    bbox: BBox | None,
    limit: int,
    offset: int,
    property_builder: Callable[[Any], dict[str, Any]],
) -> GeoJSONFeatureCollection:
    """复用点要素的有界查询与 GeoJSON 序列化流程。"""

    conditions = _spatial_filter(model.geometry, bbox)
    total = session.scalar(select(func.count(model.id)).where(*conditions)) or 0
    statement: Select[Any] = (
        select(model, func.ST_AsGeoJSON(model.geometry, 8).label("geometry_json"))
        .where(*conditions)
        .order_by(model.id)
        .limit(limit)
        .offset(offset)
    )
    features = [
        GeoJSONFeature(
            id=entity.id,
            geometry=_decode_geometry(geometry_json),
            properties=property_builder(entity),
        )
        for entity, geometry_json in session.execute(statement).all()
    ]
    return _collection(features, total, limit, offset, bbox)


def list_gates(
    session: Session, bbox: BBox | None, limit: int, offset: int
) -> GeoJSONFeatureCollection:
    """查询闸门点要素。"""

    return _list_point_features(
        session,
        Gate,
        bbox,
        limit,
        offset,
        lambda gate: {
            "feature_type": "gate",
            "name": gate.name,
            "river_id": gate.river_id,
            "gate_type": gate.gate_type,
            "gate_code": gate.gate_code,
            "dataset_version_id": gate.dataset_version_id,
            "opening_direction": gate.opening_direction,
            "control_mode": gate.control_mode,
            "width": gate.width,
            "height": gate.height,
            "max_flow": gate.max_flow,
            "bottom_elevation": gate.bottom_elevation,
            "status": gate.status,
            "created_time": _iso(gate.created_time),
            "demo_data": True,
        },
    )


def list_pumps(
    session: Session, bbox: BBox | None, limit: int, offset: int
) -> GeoJSONFeatureCollection:
    """查询泵站点要素。"""

    return _list_point_features(
        session,
        Pump,
        bbox,
        limit,
        offset,
        lambda pump: {
            "feature_type": "pump",
            "name": pump.name,
            "river_id": pump.river_id,
            "pump_code": pump.pump_code,
            "dataset_version_id": pump.dataset_version_id,
            "capacity": pump.design_flow,
            "design_flow": pump.design_flow,
            "head": pump.head,
            "power": pump.power,
            "efficiency_curve": pump.efficiency_curve,
            "control_mode": pump.control_mode,
            "status": pump.status,
            "created_time": _iso(pump.created_time),
            "demo_data": True,
        },
    )


def list_cross_sections(
    session: Session, bbox: BBox | None, limit: int, offset: int
) -> GeoJSONFeatureCollection:
    """查询横断面定位点和高程数组。"""

    return _list_point_features(
        session,
        CrossSection,
        bbox,
        limit,
        offset,
        lambda section: {
            "feature_type": "cross_section",
            "river_id": section.river_id,
            "dataset_version_id": section.dataset_version_id,
            "section_code": section.section_code,
            "section_name": section.section_name,
            "station": section.station,
            "elevation_points": section.points,
            "points": section.points,
            "roughness": section.roughness,
            "elevation_min": section.elevation_min,
            "survey_date": section.survey_date.isoformat() if section.survey_date else None,
            "created_time": _iso(section.created_time),
            "demo_data": True,
        },
    )


def _get_feature(
    session: Session,
    model: Any,
    feature_id: int,
    property_builder: Callable[[Any], dict[str, Any]],
) -> GeoJSONFeature | None:
    """按主键查询单个空间对象并序列化。"""

    statement = select(
        model,
        func.ST_AsGeoJSON(model.geometry, 8).label("geometry_json"),
    ).where(model.id == feature_id)
    row = session.execute(statement).one_or_none()
    if row is None:
        return None
    entity, geometry_json = row
    return GeoJSONFeature(
        id=entity.id,
        geometry=_decode_geometry(geometry_json),
        properties=property_builder(entity),
    )


def get_river(session: Session, river_id: int) -> GeoJSONFeature | None:
    """按 ID 查询河道属性、几何和断面数量。"""

    section_total = session.scalar(
        select(func.count(CrossSection.id)).where(CrossSection.river_id == river_id)
    ) or 0
    return _get_feature(
        session,
        River,
        river_id,
        lambda river: {
            "feature_type": "river",
            "name": river.name,
            "code": river.code,
            "length": river.length,
            "level": river.level,
            "status": river.status,
            "dataset_version_id": river.dataset_version_id,
            "description": river.description,
            "cross_section_count": section_total,
            "created_time": _iso(river.created_time),
            "demo_data": True,
        },
    )


def get_gate(session: Session, gate_id: int) -> GeoJSONFeature | None:
    """按 ID 查询闸门属性与空间位置。"""

    return _get_feature(
        session,
        Gate,
        gate_id,
        lambda gate: {
            "feature_type": "gate",
            "name": gate.name,
            "river_id": gate.river_id,
            "gate_type": gate.gate_type,
            "gate_code": gate.gate_code,
            "dataset_version_id": gate.dataset_version_id,
            "opening_direction": gate.opening_direction,
            "control_mode": gate.control_mode,
            "width": gate.width,
            "height": gate.height,
            "max_flow": gate.max_flow,
            "bottom_elevation": gate.bottom_elevation,
            "status": gate.status,
            "created_time": _iso(gate.created_time),
            "demo_data": True,
        },
    )


def get_pump(session: Session, pump_id: int) -> GeoJSONFeature | None:
    """按 ID 查询泵站属性与空间位置。"""

    return _get_feature(
        session,
        Pump,
        pump_id,
        lambda pump: {
            "feature_type": "pump",
            "name": pump.name,
            "river_id": pump.river_id,
            "pump_code": pump.pump_code,
            "dataset_version_id": pump.dataset_version_id,
            "capacity": pump.design_flow,
            "design_flow": pump.design_flow,
            "head": pump.head,
            "power": pump.power,
            "efficiency_curve": pump.efficiency_curve,
            "control_mode": pump.control_mode,
            "status": pump.status,
            "created_time": _iso(pump.created_time),
            "demo_data": True,
        },
    )


def get_cross_section(session: Session, section_id: int) -> GeoJSONFeature | None:
    """按 ID 查询横断面属性与空间位置。"""

    return _get_feature(
        session,
        CrossSection,
        section_id,
        lambda section: {
            "feature_type": "cross_section",
            "river_id": section.river_id,
            "dataset_version_id": section.dataset_version_id,
            "section_code": section.section_code,
            "section_name": section.section_name,
            "station": section.station,
            "elevation_points": section.points,
            "points": section.points,
            "roughness": section.roughness,
            "elevation_min": section.elevation_min,
            "survey_date": section.survey_date.isoformat() if section.survey_date else None,
            "created_time": _iso(section.created_time),
            "demo_data": True,
        },
    )


def get_statistics(session: Session) -> GISStatisticsResponse:
    """从 PostGIS 实时聚合四类 DEMO DATA 记录数量。"""

    return GISStatisticsResponse(
        rivers=session.scalar(select(func.count(River.id))) or 0,
        gates=session.scalar(select(func.count(Gate.id))) or 0,
        pumps=session.scalar(select(func.count(Pump.id))) or 0,
        cross_sections=session.scalar(select(func.count(CrossSection.id))) or 0,
    )


def get_gis_health(session: Session) -> GISHealthResponse:
    """执行真实 SQL 并返回数据库名与 PostGIS 完整版本。"""

    database_name, postgis_version = session.execute(
        text("SELECT current_database(), postgis_full_version()")
    ).one()
    return GISHealthResponse(
        status="healthy",
        database=database_name,
        postgis_version=postgis_version,
    )
