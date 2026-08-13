"""Phase 1D business logic for basemap search, spatial analysis, comparison and cartography."""

from __future__ import annotations

from collections import defaultdict, deque
from io import BytesIO
import json
import re
from typing import Any

from geoalchemy2 import Geography, Geometry
from sqlalchemy import cast, func, select, text
from sqlalchemy.orm import Session

from app.gis import service as gis_service
from app.gis.models import (
    CrossSection, DatasetVersion, Gate, MapAnnotation, Pump, River, RiverConnection,
    SimulationCase, SimulationTask,
)
from app.gis_analysis.schemas import (
    AnnotationCreate, AnnotationRecord, AnnotationUpdate, BufferAnalysisRequest,
    BufferAnalysisResponse, ComparisonStructureSample, ComparisonWaterSample,
    GISComparisonFrame, LayerCatalogItem, NearestFacilityRequest,
    NearestFacilityResponse, LocationSearchItem, LocationSearchResponse, SpatialFeature,
    SpatialSelectRequest, SpatialSelectResponse, ThematicMapRequest, TraceResponse,
)


class GISAnalysisError(ValueError):
    """Represent a stable domain validation failure for the HTTP boundary."""


MODEL_BY_TYPE = {
    "river": River, "gate": Gate, "pump": Pump, "cross_section": CrossSection,
}

VECTOR_TILE_LAYER_SQL = {
    "river": ("river", "name"),
    "gate": ("gate", "name"),
    "pump": ("pump", "name"),
    "cross_section": ("cross_section", "COALESCE(NULLIF(section_name, ''), section_code)"),
    "map_annotation": ("map_annotation", "text"),
}


def layer_catalog() -> list[LayerCatalogItem]:
    """Return the professional layer directory shared by the map and PDF workflows."""

    rows = [
        ("basemap", "卫星影像/经纬网", "base", "WMTS", "raster", True, False),
        ("administrative_area", "行政区", "base", "WMS", "polygon", True, False),
        ("road", "道路", "base", "WMTS", "line", True, False),
        ("place_name", "地名", "base", "WMTS", "point", True, False),
        ("water_name", "水名", "base", "WMTS", "point", True, False),
        ("poi", "公共设施 / POI", "base", "WMS", "point", False, False),
        ("river", "河道", "engineering", "WMTS", "line", True, False),
        ("river_segment", "河段", "engineering", "WMS", "line", False, False),
        ("river_node", "河网节点", "engineering", "WMS", "point", False, False),
        ("cross_section", "横断面", "engineering", "WMS", "point", True, False),
        ("gate", "闸门", "engineering", "WMTS", "point", True, False),
        ("pump", "泵站", "engineering", "WMTS", "point", True, False),
        ("annotation", "地点注记", "annotation", "FastAPI", "point", True, True),
        ("water_result", "水位风险", "model", "FastAPI", "point", True, True),
        ("velocity_result", "流速与流向", "model", "FastAPI", "mixed", True, True),
        ("risk_result", "风险分级", "analysis", "FastAPI", "point", True, True),
        ("flood_evolution", "洪水演进", "model", "FastAPI", "mixed", False, True),
        ("gate_status", "闸门调度", "dispatch", "FastAPI", "point", True, True),
        ("pump_status", "泵站调度", "dispatch", "FastAPI", "point", True, True),
        ("comparison", "方案差异", "analysis", "PostGIS analysis", "mixed", False, True),
        ("selection", "空间分析结果", "analysis", "PostGIS analysis", "mixed", False, True),
        ("vector_tile", "PostGIS 矢量瓦片", "engineering", "MVT", "mixed", False, True),
    ]
    return [
        LayerCatalogItem(
            key=key, title=title, group=group, source=source, geometry=geometry,
            default_visible=visible, dynamic=dynamic,
        )
        for key, title, group, source, geometry, visible, dynamic in rows
    ]


def build_vector_tile(
    session: Session, dataset_version_id: int, layer: str, z: int, x: int, y: int
) -> bytes:
    """Encode one version-filtered PostGIS layer as a Web Mercator Mapbox vector tile."""

    _require_version(session, dataset_version_id)
    if layer not in VECTOR_TILE_LAYER_SQL:
        raise GISAnalysisError("不支持的矢量瓦片图层")
    if z < 0 or z > 22 or x < 0 or y < 0 or x >= 2 ** z or y >= 2 ** z:
        raise GISAnalysisError("矢量瓦片坐标超出有效范围")
    table_name, label_expression = VECTOR_TILE_LAYER_SQL[layer]
    # Table and label expressions come only from the closed mapping above; all user values stay bound.
    statement = text(f"""
        WITH bounds AS (
            SELECT ST_TileEnvelope(:z, :x, :y) AS geometry
        ), tile_rows AS (
            SELECT source.id, source.dataset_version_id,
                   {label_expression} AS label,
                   ST_AsMVTGeom(
                       ST_Transform(source.geometry, 3857), bounds.geometry,
                       4096, 64, true
                   ) AS geometry
            FROM {table_name} AS source
            CROSS JOIN bounds
            WHERE source.dataset_version_id = :dataset_version_id
              AND ST_Intersects(ST_Transform(source.geometry, 3857), bounds.geometry)
        )
        SELECT ST_AsMVT(tile_rows, :layer, 4096, 'geometry') FROM tile_rows
    """)
    payload = session.scalar(statement, {
        "z": z, "x": x, "y": y,
        "dataset_version_id": dataset_version_id, "layer": layer,
    })
    return bytes(payload or b"")


COORDINATE_PATTERN = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*[,，]\s*"
    r"([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*$"
)


def search_locations(
    session: Session, dataset_version_id: int, query: str, limit: int
) -> LocationSearchResponse:
    """Parse coordinates or search the versioned offline PostGIS gazetteer."""

    _require_version(session, dataset_version_id)
    token = query.strip()
    coordinate = COORDINATE_PATTERN.fullmatch(token)
    if coordinate:
        longitude, latitude = (float(coordinate.group(1)), float(coordinate.group(2)))
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            raise GISAnalysisError("坐标超出 EPSG:4490 经度/纬度范围")
        return LocationSearchResponse(
            query=token, mode="coordinate", dataset_version_id=dataset_version_id,
            items=[LocationSearchItem(
                result_type="coordinate", name=f"坐标 {longitude:.6f}, {latitude:.6f}",
                longitude=longitude, latitude=latitude, source="coordinate-parser",
            )],
        )

    pattern = f"%{token}%"
    prefix = f"{token}%"
    rows = session.execute(text("""
        WITH candidates AS (
            SELECT 'administrative_area' AS result_type, id AS object_id, name, address,
                   ST_X(ST_PointOnSurface(geometry)) AS longitude,
                   ST_Y(ST_PointOnSurface(geometry)) AS latitude,
                   CASE WHEN name = :query THEN 0 WHEN name ILIKE :prefix THEN 1 ELSE 2 END AS rank
            FROM administrative_area
            WHERE dataset_version_id = :version_id
              AND (name ILIKE :pattern OR COALESCE(address, '') ILIKE :pattern)
            UNION ALL
            SELECT 'road', id, name, address,
                   ST_X(ST_LineInterpolatePoint(geometry, 0.5)),
                   ST_Y(ST_LineInterpolatePoint(geometry, 0.5)),
                   CASE WHEN name = :query THEN 0 WHEN name ILIKE :prefix THEN 1 ELSE 2 END
            FROM road
            WHERE dataset_version_id = :version_id
              AND (name ILIKE :pattern OR COALESCE(address, '') ILIKE :pattern)
            UNION ALL
            SELECT 'place_name', id, name, address, ST_X(geometry), ST_Y(geometry),
                   CASE WHEN name = :query THEN 0 WHEN name ILIKE :prefix THEN 1 ELSE 2 END
            FROM place_name
            WHERE dataset_version_id = :version_id
              AND (name ILIKE :pattern OR COALESCE(address, '') ILIKE :pattern)
            UNION ALL
            SELECT 'water_name', id, name, address, ST_X(geometry), ST_Y(geometry),
                   CASE WHEN name = :query THEN 0 WHEN name ILIKE :prefix THEN 1 ELSE 2 END
            FROM water_name
            WHERE dataset_version_id = :version_id
              AND (name ILIKE :pattern OR COALESCE(address, '') ILIKE :pattern)
            UNION ALL
            SELECT 'poi', id, name, address, ST_X(geometry), ST_Y(geometry),
                   CASE WHEN name = :query THEN 0 WHEN name ILIKE :prefix THEN 1 ELSE 2 END
            FROM poi
            WHERE dataset_version_id = :version_id
              AND (name ILIKE :pattern OR COALESCE(address, '') ILIKE :pattern)
        )
        SELECT result_type, object_id, name, address, longitude, latitude
        FROM candidates ORDER BY rank, result_type, name, object_id LIMIT :limit
    """), {
        "query": token, "prefix": prefix, "pattern": pattern,
        "version_id": dataset_version_id, "limit": limit,
    }).mappings().all()
    return LocationSearchResponse(
        query=token, mode="text", dataset_version_id=dataset_version_id,
        items=[LocationSearchItem(
            result_type=row["result_type"], object_id=row["object_id"], name=row["name"],
            address=row["address"], longitude=float(row["longitude"]),
            latitude=float(row["latitude"]), source="PostGIS dayu_basemap",
        ) for row in rows],
    )


def create_annotation(session: Session, payload: AnnotationCreate) -> AnnotationRecord:
    """Persist a versioned label and derive its point geometry from validated coordinates."""

    _require_version(session, payload.dataset_version_id)
    _validate_relation(session, payload.dataset_version_id, payload.related_type, payload.related_id)
    row = MapAnnotation(**payload.model_dump(), geometry=func.ST_SetSRID(
        func.ST_MakePoint(payload.longitude, payload.latitude), 4490
    ))
    session.add(row)
    session.commit()
    session.refresh(row)
    return _annotation_record(row)


def update_annotation(
    session: Session, annotation_id: int, dataset_version_id: int, payload: AnnotationUpdate
) -> AnnotationRecord:
    """Update one label within its original data-version boundary."""

    row = session.scalar(select(MapAnnotation).where(
        MapAnnotation.id == annotation_id,
        MapAnnotation.dataset_version_id == dataset_version_id,
    ))
    if row is None:
        raise GISAnalysisError("注记不存在")
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(row, key, value)
    if (payload.longitude is not None) != (payload.latitude is not None):
        raise GISAnalysisError("移动注记时必须同时提供 longitude 和 latitude")
    if payload.longitude is not None and payload.latitude is not None:
        row.geometry = func.ST_SetSRID(func.ST_MakePoint(payload.longitude, payload.latitude), 4490)
    if row.visible_scale_max < row.visible_scale_min:
        raise GISAnalysisError("visible_scale_max 必须不小于 visible_scale_min")
    if (row.related_type is None) != (row.related_id is None):
        raise GISAnalysisError("related_type 和 related_id 必须同时存在或同时为空")
    _validate_relation(session, dataset_version_id, row.related_type, row.related_id)
    session.commit()
    session.refresh(row)
    return _annotation_record(row)


def delete_annotation(session: Session, annotation_id: int, dataset_version_id: int) -> None:
    """Delete one annotation without touching its related engineering object."""

    row = session.scalar(select(MapAnnotation).where(
        MapAnnotation.id == annotation_id,
        MapAnnotation.dataset_version_id == dataset_version_id,
    ))
    if row is None:
        raise GISAnalysisError("注记不存在")
    session.delete(row)
    session.commit()


def _annotation_record(row: MapAnnotation) -> AnnotationRecord:
    """Serialize one static annotation for CRUD responses."""

    return AnnotationRecord(
        id=row.id, dataset_version_id=row.dataset_version_id,
        annotation_type=row.annotation_type, name=row.name, text=row.text,
        description=row.description, longitude=row.longitude, latitude=row.latitude,
        rotation=row.rotation, font_size=row.font_size, color=row.color,
        visible_scale_min=row.visible_scale_min, visible_scale_max=row.visible_scale_max,
        related_type=row.related_type, related_id=row.related_id,
        display_text=row.text, dynamic_lines=[], dynamic_source="static",
        created_time=row.created_time,
    )


def trace_river(session: Session, dataset_version_id: int, river_id: int) -> TraceResponse:
    """Traverse the versioned directed river graph and return related engineering assets."""

    selected = session.scalar(select(River).where(
        River.id == river_id, River.dataset_version_id == dataset_version_id
    ))
    if selected is None:
        raise GISAnalysisError("河道不存在")
    connections = session.scalars(select(RiverConnection).where(
        RiverConnection.dataset_version_id == dataset_version_id
    )).all()
    river_from: dict[int, set[int]] = defaultdict(set)
    river_to: dict[int, set[int]] = defaultdict(set)
    for edge in connections:
        river_from[edge.river_id].add(edge.from_node_id)
        river_to[edge.river_id].add(edge.to_node_id)
    upstream_graph: dict[int, set[int]] = defaultdict(set)
    downstream_graph: dict[int, set[int]] = defaultdict(set)
    river_ids = set(river_from) | set(river_to)
    for left in river_ids:
        for right in river_ids:
            if left != right and river_to[left] & river_from[right]:
                downstream_graph[left].add(right)
                upstream_graph[right].add(left)
    upstream_ids = _walk_graph(upstream_graph, river_id)
    downstream_ids = _walk_graph(downstream_graph, river_id)
    return TraceResponse(
        dataset_version_id=dataset_version_id,
        selected_river=_feature(session, "river", selected),
        upstream_rivers=_features_by_ids(session, "river", upstream_ids, dataset_version_id),
        downstream_rivers=_features_by_ids(session, "river", downstream_ids, dataset_version_id),
        gates=_features_for_rivers(session, "gate", {river_id, *upstream_ids, *downstream_ids}, dataset_version_id),
        pumps=_features_for_rivers(session, "pump", {river_id, *upstream_ids, *downstream_ids}, dataset_version_id),
        cross_sections=_features_for_rivers(
            session, "cross_section", {river_id, *upstream_ids, *downstream_ids}, dataset_version_id
        ),
    )


def _walk_graph(graph: dict[int, set[int]], start: int) -> list[int]:
    """Breadth-first traverse a river graph while preventing topology cycles."""

    result: list[int] = []
    queue = deque(sorted(graph.get(start, set())))
    seen = {start}
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        result.append(current)
        queue.extend(sorted(graph.get(current, set()) - seen))
    return result


def select_features(session: Session, payload: SpatialSelectRequest) -> SpatialSelectResponse:
    """Intersect four authoritative PostGIS tables with one user-drawn rectangle."""

    _require_version(session, payload.dataset_version_id)
    features: list[SpatialFeature] = []
    counts: dict[str, int] = {}
    envelope = func.ST_MakeEnvelope(*payload.bbox, 4490)
    for object_type in dict.fromkeys(payload.object_types):
        model = MODEL_BY_TYPE[object_type]
        rows = session.scalars(select(model).where(
            model.dataset_version_id == payload.dataset_version_id,
            func.ST_Intersects(model.geometry, envelope),
        ).order_by(model.id).limit(payload.limit_per_type)).all()
        counts[object_type] = len(rows)
        features.extend(_feature(session, object_type, row) for row in rows)
    return SpatialSelectResponse(
        dataset_version_id=payload.dataset_version_id, bbox=payload.bbox,
        features=features, counts=counts,
    )


def buffer_analysis(session: Session, payload: BufferAnalysisRequest) -> BufferAnalysisResponse:
    """Buffer one source object in metres and return all version-safe impacted assets."""

    source_model = MODEL_BY_TYPE[payload.object_type]
    source_row = session.scalar(select(source_model).where(
        source_model.id == payload.object_id,
        source_model.dataset_version_id == payload.dataset_version_id,
    ))
    if source_row is None:
        raise GISAnalysisError("缓冲分析源对象不存在")
    source_geometry = select(source_model.geometry).where(
        source_model.id == payload.object_id,
        source_model.dataset_version_id == payload.dataset_version_id,
    ).scalar_subquery()
    buffer_geometry = cast(
        func.ST_Buffer(cast(source_geometry, Geography(srid=4490)), payload.distance_m),
        Geometry(geometry_type="POLYGON", srid=4490),
    )
    buffer_json = session.scalar(select(func.ST_AsGeoJSON(buffer_geometry, 8)))
    impacted: list[SpatialFeature] = []
    for object_type in dict.fromkeys(payload.include_types):
        model = MODEL_BY_TYPE[object_type]
        rows = session.execute(select(
            model,
            func.ST_Distance(
                cast(model.geometry, Geography(srid=4490)),
                cast(source_geometry, Geography(srid=4490)),
            ).label("distance_m"),
        ).where(
            model.dataset_version_id == payload.dataset_version_id,
            func.ST_DWithin(
                cast(model.geometry, Geography(srid=4490)),
                cast(source_geometry, Geography(srid=4490)), payload.distance_m,
            ),
        ).order_by("distance_m").limit(1000)).all()
        impacted.extend(_feature(session, object_type, row, float(distance)) for row, distance in rows)
    return BufferAnalysisResponse(
        dataset_version_id=payload.dataset_version_id,
        source=_feature(session, payload.object_type, source_row),
        distance_m=payload.distance_m,
        buffer_geometry=json.loads(buffer_json), impacted=impacted,
    )


def nearest_facilities(session: Session, payload: NearestFacilityRequest) -> NearestFacilityResponse:
    """Order facilities by exact PostGIS geography distance from one user point."""

    _require_version(session, payload.dataset_version_id)
    origin = func.ST_SetSRID(func.ST_MakePoint(payload.longitude, payload.latitude), 4490)
    candidates: list[SpatialFeature] = []
    for object_type in dict.fromkeys(payload.facility_types):
        if object_type == "hydrology_station":
            model = MapAnnotation
            conditions = [
                model.dataset_version_id == payload.dataset_version_id,
                model.annotation_type == "hydrology_station",
            ]
        else:
            model = MODEL_BY_TYPE[object_type]
            conditions = [model.dataset_version_id == payload.dataset_version_id]
        distance = func.ST_Distance(
            cast(model.geometry, Geography(srid=4490)), cast(origin, Geography(srid=4490))
        )
        if payload.max_distance_m is not None:
            conditions.append(func.ST_DWithin(
                cast(model.geometry, Geography(srid=4490)), cast(origin, Geography(srid=4490)),
                payload.max_distance_m,
            ))
        rows = session.execute(select(model, distance.label("distance_m")).where(
            *conditions
        ).order_by(distance).limit(payload.limit)).all()
        for row, distance_m in rows:
            feature = _annotation_feature(session, row, float(distance_m)) if object_type == "hydrology_station" else _feature(
                session, object_type, row, float(distance_m)
            )
            feature.properties["facility_type"] = object_type
            candidates.append(feature)
    candidates.sort(key=lambda item: item.distance_m or 0)
    return NearestFacilityResponse(
        dataset_version_id=payload.dataset_version_id,
        origin={"type": "Point", "coordinates": [payload.longitude, payload.latitude]},
        facilities=candidates[:payload.limit],
    )


def comparison_frame(
    session: Session, dataset_version_id: int, baseline_task_id: int,
    comparison_task_id: int, time_seconds: float,
    baseline_dispatch_run_id: int | None, comparison_dispatch_run_id: int | None,
) -> GISComparisonFrame:
    """Compare two same-version atomic frames by stable section and structure identifiers."""

    baseline = gis_service.get_interaction_frame(
        session, dataset_version_id, time_seconds, baseline_task_id, baseline_dispatch_run_id
    )
    comparison = gis_service.get_interaction_frame(
        session, dataset_version_id, time_seconds, comparison_task_id, comparison_dispatch_run_id
    )
    baseline_water = {item.section_id: item for item in baseline.water_samples}
    comparison_water = {item.section_id: item for item in comparison.water_samples}
    water = []
    for section_id in sorted(baseline_water.keys() & comparison_water.keys()):
        left, right = baseline_water[section_id], comparison_water[section_id]
        water.append(ComparisonWaterSample(
            section_id=section_id, section_code=right.section_code, river_id=right.river_id,
            longitude=right.longitude, latitude=right.latitude,
            baseline_water_level=left.water_level, comparison_water_level=right.water_level,
            water_level_difference=right.water_level - left.water_level,
            baseline_velocity=left.velocity, comparison_velocity=right.velocity,
            velocity_difference=right.velocity - left.velocity,
            baseline_flow=left.flow, comparison_flow=right.flow,
            flow_difference=right.flow - left.flow,
        ))
    baseline_structures = {(x.structure_type, x.structure_id): x for x in baseline.structure_samples}
    comparison_structures = {(x.structure_type, x.structure_id): x for x in comparison.structure_samples}
    structures = []
    for key in sorted(baseline_structures.keys() | comparison_structures.keys()):
        left, right = baseline_structures.get(key), comparison_structures.get(key)
        sample = right or left
        assert sample is not None
        structures.append(ComparisonStructureSample(
            structure_type=sample.structure_type, structure_id=sample.structure_id,
            name=sample.name, longitude=sample.longitude, latitude=sample.latitude,
            baseline_value=left.actual_value if left else None,
            comparison_value=right.actual_value if right else None,
            value_difference=_difference(right.actual_value if right else None, left.actual_value if left else None),
            baseline_flow=left.flow if left else None, comparison_flow=right.flow if right else None,
            flow_difference=_difference(right.flow if right else None, left.flow if left else None),
        ))
    return GISComparisonFrame(
        dataset_version_id=dataset_version_id, baseline_task_id=baseline_task_id,
        comparison_task_id=comparison_task_id,
        baseline_dispatch_run_id=baseline_dispatch_run_id,
        comparison_dispatch_run_id=comparison_dispatch_run_id,
        requested_time_seconds=time_seconds,
        baseline_time_seconds=baseline.selected_time_seconds,
        comparison_time_seconds=comparison.selected_time_seconds,
        water_samples=water, structure_samples=structures,
    )


def build_thematic_pdf(session: Session, payload: ThematicMapRequest) -> bytes:
    """Render a deterministic A4 landscape map with mandatory professional map furniture."""

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise GISAnalysisError("专题图 PDF 依赖 reportlab 未安装") from exc
    frame = gis_service.get_interaction_frame(
        session, payload.dataset_version_id, payload.time_seconds,
        payload.task_id, payload.dispatch_run_id,
    )
    river_geometries = [
        json.loads(value) for value in session.scalars(
            select(func.ST_AsGeoJSON(River.geometry, 8)).where(
                River.dataset_version_id == payload.dataset_version_id
            ).order_by(River.id)
        ).all()
    ]
    points = [(x.longitude, x.latitude) for x in frame.water_samples] + [
        (x.longitude, x.latitude) for x in frame.structure_samples
    ]
    for geometry in river_geometries:
        points.extend((float(x), float(y)) for x, y in geometry["coordinates"])
    bbox = tuple(payload.bbox) if payload.bbox else _extent(points)
    stream = BytesIO()
    width, height = landscape(A4)
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    pdf = canvas.Canvas(stream, pagesize=(width, height), pageCompression=1)
    pdf.setTitle(payload.title)
    pdf.setAuthor(payload.author)
    pdf.setFillColor(colors.HexColor("#F4F8FA"))
    pdf.rect(0, 0, width, height, fill=1, stroke=0)
    pdf.setFillColor(colors.HexColor("#12313A"))
    pdf.setFont("STSong-Light", 18)
    pdf.drawString(36, height - 42, payload.title)
    pdf.setFont("STSong-Light", 9)
    pdf.setFillColor(colors.HexColor("#49646C"))
    pdf.drawRightString(width - 36, height - 38, "DAYU TIANGONG · PHASE 1D · DEMO DATA")
    map_x, map_y, map_w, map_h = 36, 78, width - 260, height - 140
    pdf.setFillColor(colors.HexColor("#071923"))
    pdf.setStrokeColor(colors.HexColor("#3B7C86"))
    pdf.rect(map_x, map_y, map_w, map_h, fill=1, stroke=1)
    pdf.setLineWidth(2.2)
    pdf.setStrokeColor(colors.HexColor("#2E91A0"))
    for geometry in river_geometries:
        coordinates = geometry["coordinates"]
        if len(coordinates) < 2:
            continue
        path = pdf.beginPath()
        first_x, first_y = _project(*coordinates[0], bbox, map_x, map_y, map_w, map_h)
        path.moveTo(first_x, first_y)
        for longitude, latitude in coordinates[1:]:
            x, y = _project(longitude, latitude, bbox, map_x, map_y, map_w, map_h)
            path.lineTo(x, y)
        pdf.drawPath(path, stroke=1, fill=0)
    for sample in frame.water_samples:
        x, y = _project(sample.longitude, sample.latitude, bbox, map_x, map_y, map_w, map_h)
        color = {"normal": "#38D9C6", "warning": "#FFC85C", "danger": "#FF5F6D"}[sample.risk_level]
        pdf.setFillColor(colors.HexColor(color))
        pdf.circle(x, y, 4.5 if sample.risk_level == "danger" else 3.3, fill=1, stroke=0)
    for sample in frame.structure_samples:
        x, y = _project(sample.longitude, sample.latitude, bbox, map_x, map_y, map_w, map_h)
        pdf.setFillColor(colors.HexColor("#77E59B" if sample.state in ("open", "running") else "#8596A3"))
        pdf.rect(x - 3, y - 3, 6, 6, fill=1, stroke=0)
    _draw_grid(pdf, bbox, map_x, map_y, map_w, map_h, colors)
    _draw_north_arrow(pdf, map_x + map_w - 34, map_y + map_h - 24, colors)
    _draw_scale(pdf, bbox, map_x + 20, map_y + 18, map_w, colors)
    panel_x = map_x + map_w + 20
    pdf.setFillColor(colors.HexColor("#12313A"))
    pdf.setFont("STSong-Light", 12)
    pdf.drawString(panel_x, height - 92, "图例与制图信息")
    legend = [
        ("#2E91A0", "河网"),
        ("#38D9C6", "正常水位"), ("#FFC85C", "警戒水位"),
        ("#FF5F6D", "危险水位"), ("#77E59B", "闸泵运行/开启"),
        ("#8596A3", "闸泵停止/关闭"),
    ]
    y = height - 118
    pdf.setFont("STSong-Light", 9)
    for color, label in legend:
        pdf.setFillColor(colors.HexColor(color)); pdf.rect(panel_x, y - 3, 10, 10, fill=1, stroke=0)
        pdf.setFillColor(colors.HexColor("#294A53")); pdf.drawString(panel_x + 16, y, label); y -= 20
    selected_time = frame.selected_time_seconds if frame.selected_time_seconds is not None else payload.time_seconds
    task = session.get(SimulationTask, frame.task_id) if frame.task_id else None
    model_version = task.engine_version if task and task.engine_version else "DEMO simplified hydraulic engine"
    if task and task.engine_commit:
        model_version = f"{model_version} / {task.engine_commit}"
    metadata = [
        f"坐标系：CGCS2000 / EPSG:4490", f"数据版本：#{payload.dataset_version_id}",
        f"模型版本：{model_version}",
        f"模型任务：#{frame.task_id or '无'}", f"调度运行：#{frame.dispatch_run_id or '无'}",
        f"模拟时刻：{selected_time:.0f} s", f"水动力点：{len(frame.water_samples)}",
        f"闸泵状态：{len(frame.structure_samples)}", f"制图人：{payload.author}",
    ]
    y -= 12
    for line in metadata:
        pdf.drawString(panel_x, y, line); y -= 17
    pdf.setFillColor(colors.HexColor("#9B3C45"))
    pdf.setFont("STSong-Light", 8.5)
    for line in ("本图为 DEMO 模拟专题图，仅供人工分析。", "不代表实时遥测，不具有设备执行权限。"):
        pdf.drawString(panel_x, y, line); y -= 14
    pdf.setFillColor(colors.HexColor("#49646C"))
    pdf.drawString(36, 44, f"范围：{bbox[0]:.5f}, {bbox[1]:.5f} - {bbox[2]:.5f}, {bbox[3]:.5f}")
    pdf.drawRightString(width - 36, 44, "图例 · 比例尺 · 指北针 · 坐标 · 时间 · 数据/模型版本")
    pdf.showPage(); pdf.save()
    return stream.getvalue()


def _require_version(session: Session, dataset_version_id: int) -> None:
    """Fail before spatial work when the selected data version does not exist."""

    if session.get(DatasetVersion, dataset_version_id) is None:
        raise GISAnalysisError("数据版本不存在")


def _validate_relation(
    session: Session, dataset_version_id: int, related_type: str | None, related_id: int | None
) -> None:
    """Prove a related engineering object exists in the same selected data version."""

    if related_type is None or related_id is None or related_type == "dispatch_event":
        return
    if related_type == "hydrology_station":
        return
    model = MODEL_BY_TYPE.get(related_type)
    if model is None or session.scalar(select(model.id).where(
        model.id == related_id, model.dataset_version_id == dataset_version_id
    )) is None:
        raise GISAnalysisError("注记关联对象不存在或属于其他数据版本")


def _feature(
    session: Session, object_type: str, row: Any, distance_m: float | None = None
) -> SpatialFeature:
    """Serialize one supported ORM row into a compact, stable spatial-analysis feature."""

    geometry_json = session.scalar(select(func.ST_AsGeoJSON(row.geometry, 8)))
    name = row.name if hasattr(row, "name") else row.section_name
    properties = {"dataset_version_id": row.dataset_version_id}
    if object_type == "river": properties.update(code=row.code, length=row.length)
    elif object_type == "gate": properties.update(code=row.gate_code, river_id=row.river_id)
    elif object_type == "pump": properties.update(code=row.pump_code, river_id=row.river_id)
    else: properties.update(code=row.section_code, river_id=row.river_id, station=row.station)
    return SpatialFeature(
        object_type=object_type, object_id=row.id, name=name,
        geometry=json.loads(geometry_json), properties=properties, distance_m=distance_m,
    )


def _annotation_feature(session: Session, row: MapAnnotation, distance_m: float) -> SpatialFeature:
    """Represent an annotated hydrology station using the shared analysis feature contract."""

    geometry_json = session.scalar(select(func.ST_AsGeoJSON(row.geometry, 8)))
    return SpatialFeature(
        object_type="hydrology_station", object_id=row.id, name=row.text,
        geometry=json.loads(geometry_json), distance_m=distance_m,
        properties={"facility_type": "hydrology_station", "description": row.description},
    )


def _features_by_ids(
    session: Session, object_type: str, ids: list[int], dataset_version_id: int
) -> list[SpatialFeature]:
    """Read a deterministic list of version-safe features by stable identifiers."""

    if not ids:
        return []
    model = MODEL_BY_TYPE[object_type]
    rows = session.scalars(select(model).where(
        model.id.in_(ids), model.dataset_version_id == dataset_version_id
    ).order_by(model.id)).all()
    return [_feature(session, object_type, row) for row in rows]


def _features_for_rivers(
    session: Session, object_type: str, river_ids: set[int], dataset_version_id: int
) -> list[SpatialFeature]:
    """Return assets attached to every river reached by topology traversal."""

    model = MODEL_BY_TYPE[object_type]
    rows = session.scalars(select(model).where(
        model.river_id.in_(river_ids), model.dataset_version_id == dataset_version_id
    ).order_by(model.id)).all()
    return [_feature(session, object_type, row) for row in rows]


def _difference(right: float | None, left: float | None) -> float | None:
    """Return a numeric B-A difference only when both plans contain the value."""

    return right - left if right is not None and left is not None else None


def _extent(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    """Build a padded deterministic map extent from result points or the DEMO region."""

    if not points:
        return (119.9, 30.0, 120.65, 30.55)
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    pad_x = max((max(xs) - min(xs)) * 0.08, 0.01)
    pad_y = max((max(ys) - min(ys)) * 0.08, 0.01)
    return min(xs) - pad_x, min(ys) - pad_y, max(xs) + pad_x, max(ys) + pad_y


def _project(
    longitude: float, latitude: float, bbox: tuple[float, float, float, float],
    x: float, y: float, width: float, height: float,
) -> tuple[float, float]:
    """Project CGCS2000 coordinates into the PDF map frame without changing data storage."""

    return (
        x + (longitude - bbox[0]) / (bbox[2] - bbox[0]) * width,
        y + (latitude - bbox[1]) / (bbox[3] - bbox[1]) * height,
    )


def _draw_grid(pdf: Any, bbox: tuple[float, float, float, float], x: float, y: float, width: float, height: float, colors: Any) -> None:
    """Draw coordinate ticks and labels around the thematic map frame."""

    pdf.setStrokeColor(colors.HexColor("#2C5964")); pdf.setFillColor(colors.HexColor("#B8D3D9"))
    pdf.setFont("Helvetica", 7)
    for index in range(5):
        ratio = index / 4
        gx, gy = x + ratio * width, y + ratio * height
        pdf.setDash(1, 4); pdf.line(gx, y, gx, y + height); pdf.line(x, gy, x + width, gy)
        pdf.drawCentredString(gx, y - 11, f"{bbox[0] + ratio * (bbox[2] - bbox[0]):.4f}E")
        pdf.drawRightString(x - 4, gy - 2, f"{bbox[1] + ratio * (bbox[3] - bbox[1]):.4f}N")
    pdf.setDash()


def _draw_north_arrow(pdf: Any, x: float, y: float, colors: Any) -> None:
    """Draw a compact north arrow with an unambiguous map orientation."""

    pdf.setFillColor(colors.HexColor("#F4F8FA")); pdf.setFont("Helvetica-Bold", 11)
    pdf.drawCentredString(x, y + 20, "N")
    path = pdf.beginPath(); path.moveTo(x, y + 15); path.lineTo(x - 7, y - 10); path.lineTo(x, y - 5); path.lineTo(x + 7, y - 10); path.close()
    pdf.drawPath(path, fill=1, stroke=0)


def _draw_scale(pdf: Any, bbox: tuple[float, float, float, float], x: float, y: float, map_width: float, colors: Any) -> None:
    """Draw an approximate latitude-aware kilometre bar for the current geographic extent."""

    middle_latitude = (bbox[1] + bbox[3]) / 2
    width_km = (bbox[2] - bbox[0]) * 111.32 * max(0.1, __import__("math").cos(__import__("math").radians(middle_latitude)))
    bar_km = max(1, round(width_km / 5))
    bar_width = min(map_width / 3, map_width * bar_km / max(width_km, 0.1))
    pdf.setStrokeColor(colors.white); pdf.setFillColor(colors.white); pdf.setFont("Helvetica", 7)
    pdf.line(x, y, x + bar_width, y); pdf.line(x, y - 3, x, y + 3); pdf.line(x + bar_width, y - 3, x + bar_width, y + 3)
    pdf.drawCentredString(x + bar_width / 2, y + 5, f"{bar_km} km")
