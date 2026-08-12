"""GIS 业务服务：空间筛选、分页、GeoJSON 序列化与真实健康查询。"""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeAlias

from sqlalchemy import Select, func, select, text
from sqlalchemy.orm import Session

from app.gis.models import (
    CrossSection,
    DatasetVersion,
    DispatchPlan,
    DispatchRun,
    Gate,
    Pump,
    River,
    SimulationCase,
    SimulationResult,
    SimulationTask,
    StructureResult,
)
from app.gis.schemas import (
    GISHealthResponse,
    GISInteractionFrame,
    GISStatisticsResponse,
    GISStructureSample,
    GISWaterSample,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    PaginationMeta,
)


BBox: TypeAlias = tuple[float, float, float, float]


class GISVersionError(ValueError):
    """Reject a request that would mix static assets and dynamic results across versions."""


def parse_bbox(raw_bbox: str | None) -> BBox | None:
    """解析并校验 `minx,miny,maxx,maxy` 格式的 CGCS2000 空间范围。"""

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
        raise ValueError("bbox 超出 CGCS2000 / EPSG:4490 范围或最小值不小于最大值")
    return min_x, min_y, max_x, max_y


def _spatial_filter(geometry_column: Any, bbox: BBox | None) -> list[Any]:
    """根据可选 bbox 创建 PostGIS ST_Intersects 查询条件。"""

    if bbox is None:
        return []
    return [func.ST_Intersects(geometry_column, func.ST_MakeEnvelope(*bbox, 4490))]


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
    dataset_version_id: int,
    bbox: BBox | None,
) -> GeoJSONFeatureCollection:
    """集中构造 FeatureCollection 与分页元数据。"""

    return GeoJSONFeatureCollection(
        features=features,
        meta=PaginationMeta(
            total=total,
            limit=limit,
            offset=offset,
            dataset_version_id=dataset_version_id,
            bbox=list(bbox) if bbox else None,
        ),
    )


def list_rivers(
    session: Session,
    dataset_version_id: int,
    bbox: BBox | None,
    limit: int,
    offset: int,
) -> GeoJSONFeatureCollection:
    """查询河道并附带每条河道的横断面数量。"""

    conditions = [River.dataset_version_id == dataset_version_id, *_spatial_filter(River.geometry, bbox)]
    total = session.scalar(select(func.count(River.id)).where(*conditions)) or 0
    section_count = (
        select(func.count(CrossSection.id))
        .where(
            CrossSection.river_id == River.id,
            CrossSection.dataset_version_id == dataset_version_id,
        )
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
    return _collection(features, total, limit, offset, dataset_version_id, bbox)


def _list_point_features(
    session: Session,
    model: Any,
    dataset_version_id: int,
    bbox: BBox | None,
    limit: int,
    offset: int,
    property_builder: Callable[[Any], dict[str, Any]],
) -> GeoJSONFeatureCollection:
    """复用点要素的有界查询与 GeoJSON 序列化流程。"""

    conditions = [model.dataset_version_id == dataset_version_id, *_spatial_filter(model.geometry, bbox)]
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
    return _collection(features, total, limit, offset, dataset_version_id, bbox)


def list_gates(
    session: Session, dataset_version_id: int, bbox: BBox | None, limit: int, offset: int
) -> GeoJSONFeatureCollection:
    """查询闸门点要素。"""

    return _list_point_features(
        session,
        Gate,
        dataset_version_id,
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
    session: Session, dataset_version_id: int, bbox: BBox | None, limit: int, offset: int
) -> GeoJSONFeatureCollection:
    """查询泵站点要素。"""

    return _list_point_features(
        session,
        Pump,
        dataset_version_id,
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
    session: Session, dataset_version_id: int, bbox: BBox | None, limit: int, offset: int
) -> GeoJSONFeatureCollection:
    """查询横断面定位点和高程数组。"""

    return _list_point_features(
        session,
        CrossSection,
        dataset_version_id,
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
    dataset_version_id: int,
    property_builder: Callable[[Any], dict[str, Any]],
) -> GeoJSONFeature | None:
    """按主键查询单个空间对象并序列化。"""

    statement = select(
        model,
        func.ST_AsGeoJSON(model.geometry, 8).label("geometry_json"),
    ).where(model.id == feature_id, model.dataset_version_id == dataset_version_id)
    row = session.execute(statement).one_or_none()
    if row is None:
        return None
    entity, geometry_json = row
    return GeoJSONFeature(
        id=entity.id,
        geometry=_decode_geometry(geometry_json),
        properties=property_builder(entity),
    )


def get_river(session: Session, river_id: int, dataset_version_id: int) -> GeoJSONFeature | None:
    """按 ID 查询河道属性、几何和断面数量。"""

    section_total = session.scalar(
        select(func.count(CrossSection.id)).where(
            CrossSection.river_id == river_id,
            CrossSection.dataset_version_id == dataset_version_id,
        )
    ) or 0
    return _get_feature(
        session,
        River,
        river_id,
        dataset_version_id,
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


def get_gate(session: Session, gate_id: int, dataset_version_id: int) -> GeoJSONFeature | None:
    """按 ID 查询闸门属性与空间位置。"""

    return _get_feature(
        session,
        Gate,
        gate_id,
        dataset_version_id,
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


def get_pump(session: Session, pump_id: int, dataset_version_id: int) -> GeoJSONFeature | None:
    """按 ID 查询泵站属性与空间位置。"""

    return _get_feature(
        session,
        Pump,
        pump_id,
        dataset_version_id,
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


def get_cross_section(session: Session, section_id: int, dataset_version_id: int) -> GeoJSONFeature | None:
    """按 ID 查询横断面属性与空间位置。"""

    return _get_feature(
        session,
        CrossSection,
        section_id,
        dataset_version_id,
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


def get_statistics(session: Session, dataset_version_id: int) -> GISStatisticsResponse:
    """从 PostGIS 实时聚合四类 DEMO DATA 记录数量。"""

    return GISStatisticsResponse(
        dataset_version_id=dataset_version_id,
        rivers=session.scalar(select(func.count(River.id)).where(River.dataset_version_id == dataset_version_id)) or 0,
        gates=session.scalar(select(func.count(Gate.id)).where(Gate.dataset_version_id == dataset_version_id)) or 0,
        pumps=session.scalar(select(func.count(Pump.id)).where(Pump.dataset_version_id == dataset_version_id)) or 0,
        cross_sections=session.scalar(select(func.count(CrossSection.id)).where(CrossSection.dataset_version_id == dataset_version_id)) or 0,
    )


def _risk_level(water_level: float, warning_level: float, danger_level: float) -> str:
    """Classify a simulated water level using explicit display thresholds."""

    if water_level >= danger_level:
        return "danger"
    if water_level >= warning_level:
        return "warning"
    return "normal"


def _velocity_level(velocity: float) -> str:
    """Classify absolute velocity for a compact engineering map legend."""

    speed = abs(velocity)
    if speed >= 1.5:
        return "high"
    if speed >= 0.5:
        return "medium"
    return "low"


def _resolve_task(
    session: Session,
    dataset_version_id: int,
    task_id: int | None,
    dispatch_run_id: int | None,
) -> tuple[SimulationTask | None, DispatchRun | None, DispatchPlan | None]:
    """Resolve one dynamic result source and prove it belongs to the selected dataset version."""

    dispatch_run = session.get(DispatchRun, dispatch_run_id) if dispatch_run_id else None
    dispatch_plan = session.get(DispatchPlan, dispatch_run.plan_id) if dispatch_run else None
    if dispatch_run_id and (dispatch_run is None or dispatch_plan is None):
        raise GISVersionError("调度运行不存在")
    if dispatch_plan and dispatch_plan.dataset_version_id != dataset_version_id:
        raise GISVersionError("调度运行与当前数据版本不一致")
    if (
        task_id is not None
        and dispatch_run is not None
        and dispatch_run.controlled_task_id != task_id
    ):
        raise GISVersionError("水动力任务不是该调度运行的受控任务")
    resolved_task_id = task_id or (dispatch_run.controlled_task_id if dispatch_run else None)
    task = session.get(SimulationTask, resolved_task_id) if resolved_task_id else None
    if resolved_task_id and task is None:
        raise GISVersionError("水动力任务不存在")
    if task is None:
        task = session.scalar(
            select(SimulationTask)
            .join(SimulationCase, SimulationCase.id == SimulationTask.case_id)
            .where(
                SimulationCase.dataset_version_id == dataset_version_id,
                SimulationTask.status == "success",
            )
            .order_by(SimulationTask.id.desc())
            .limit(1)
        )
    if task is not None:
        case_version_id = session.scalar(
            select(SimulationCase.dataset_version_id).where(SimulationCase.id == task.case_id)
        )
        if case_version_id != dataset_version_id:
            raise GISVersionError("水动力任务与当前数据版本不一致")
    return task, dispatch_run, dispatch_plan


def _display_thresholds(dispatch_plan: DispatchPlan | None) -> tuple[float, float, str]:
    """Resolve safe map thresholds without treating missing config as numeric data."""

    warning_level = 11.5
    danger_level = 12.0
    threshold_source = "demo_default"
    if dispatch_plan is not None:
        configured_warning = dispatch_plan.evaluation_config.get("warning_level")
        configured_danger = dispatch_plan.evaluation_config.get("danger_level")
        if configured_warning is not None:
            warning_level = float(configured_warning)
            threshold_source = "dispatch_plan"
        if configured_danger is not None:
            danger_level = float(configured_danger)
            threshold_source = "dispatch_plan"
        elif configured_warning is not None:
            danger_level = warning_level + 0.5
    if danger_level <= warning_level:
        danger_level = warning_level + 0.5
    return warning_level, danger_level, threshold_source


def get_interaction_frame(
    session: Session,
    dataset_version_id: int,
    time_seconds: float,
    task_id: int | None,
    dispatch_run_id: int | None,
) -> GISInteractionFrame:
    """Build an atomic, version-isolated hydraulic and structure map frame."""

    if session.get(DatasetVersion, dataset_version_id) is None:
        raise GISVersionError("数据版本不存在")
    task, dispatch_run, dispatch_plan = _resolve_task(
        session, dataset_version_id, task_id, dispatch_run_id
    )
    warning_level, danger_level, threshold_source = _display_thresholds(dispatch_plan)

    timeline: list[float] = []
    selected_time: float | None = None
    water_samples: list[GISWaterSample] = []
    structure_samples: list[GISStructureSample] = []
    if task:
        timeline = [
            float(value)
            for value in session.scalars(
                select(SimulationResult.time_seconds)
                .where(SimulationResult.task_id == task.id)
                .distinct()
                .order_by(SimulationResult.time_seconds)
            ).all()
        ]
        if timeline:
            selected_time = min(timeline, key=lambda value: abs(value - time_seconds))
            result_rows = session.execute(
                select(
                    SimulationResult,
                    func.ST_X(CrossSection.geometry),
                    func.ST_Y(CrossSection.geometry),
                    func.degrees(
                        func.ST_Azimuth(
                            func.ST_StartPoint(River.geometry),
                            func.ST_EndPoint(River.geometry),
                        )
                    ),
                )
                .join(CrossSection, CrossSection.id == SimulationResult.section_id)
                .join(River, River.id == SimulationResult.river_id)
                .where(
                    SimulationResult.task_id == task.id,
                    SimulationResult.time_seconds == selected_time,
                    CrossSection.dataset_version_id == dataset_version_id,
                )
                .order_by(SimulationResult.section_id)
            ).all()
            water_samples = [
                GISWaterSample(
                    section_id=result.section_id,
                    section_code=result.section_code,
                    river_id=result.river_id,
                    longitude=longitude,
                    latitude=latitude,
                    water_level=result.water_level,
                    flow=result.flow,
                    velocity=result.velocity,
                    risk_level=_risk_level(result.water_level, warning_level, danger_level),
                    velocity_level=_velocity_level(result.velocity),
                    flow_direction=(
                        "downstream" if result.velocity > 1.0e-6
                        else "upstream" if result.velocity < -1.0e-6
                        else "stationary"
                    ),
                    flow_bearing_degrees=(
                        (float(river_bearing or 0.0) + (180.0 if result.velocity < -1.0e-6 else 0.0))
                        % 360.0
                    ),
                )
                for result, longitude, latitude, river_bearing in result_rows
                if result.section_id is not None and result.river_id is not None
            ]

    if dispatch_run and selected_time is not None:
        structure_times = [
            float(value)
            for value in session.scalars(
                select(StructureResult.time_seconds)
                .where(StructureResult.dispatch_run_id == dispatch_run.id)
                .distinct()
            ).all()
        ]
        structure_time = min(structure_times, key=lambda value: abs(value - selected_time)) if structure_times else None
        rows = (
            session.scalars(
                select(StructureResult)
                .where(
                    StructureResult.dispatch_run_id == dispatch_run.id,
                    StructureResult.task_id == task.id,
                    StructureResult.time_seconds == structure_time,
                )
                .order_by(
                    StructureResult.structure_type,
                    StructureResult.structure_id,
                )
            ).all()
            if structure_time is not None and task is not None
            else []
        )
        for row in rows:
            model = Gate if row.structure_type == "gate" else Pump
            asset = session.get(model, row.structure_id)
            if asset is None or asset.dataset_version_id != dataset_version_id:
                continue
            longitude, latitude = session.execute(
                select(func.ST_X(model.geometry), func.ST_Y(model.geometry)).where(model.id == asset.id)
            ).one()
            actual = row.actual_value
            structure_samples.append(
                GISStructureSample(
                    structure_type=row.structure_type,
                    structure_id=row.structure_id,
                    code=asset.gate_code if row.structure_type == "gate" else asset.pump_code,
                    name=asset.name,
                    longitude=longitude,
                    latitude=latitude,
                    requested_value=row.requested_value,
                    actual_value=actual,
                    flow=row.flow,
                    power_kw=row.power_kw,
                    state=(
                        "open" if row.structure_type == "gate" and actual is not None and actual > 1.0e-6
                        else "closed" if row.structure_type == "gate" and actual is not None
                        else "running" if row.structure_type == "pump" and actual is not None and actual > 1.0e-6
                        else "stopped" if row.structure_type == "pump" and actual is not None
                        else "unknown"
                    ),
                    constraint_flags=row.constraint_flags,
                )
            )
    return GISInteractionFrame(
        dataset_version_id=dataset_version_id,
        task_id=task.id if task else None,
        dispatch_run_id=dispatch_run.id if dispatch_run else None,
        task_status=task.status if task else None,
        timeline=timeline,
        requested_time_seconds=time_seconds,
        selected_time_seconds=selected_time,
        warning_level=warning_level,
        danger_level=danger_level,
        threshold_source=threshold_source,
        water_samples=water_samples,
        structure_samples=structure_samples,
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
