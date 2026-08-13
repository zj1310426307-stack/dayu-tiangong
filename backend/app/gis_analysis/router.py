"""HTTP boundary for Phase 1D search, GIS analysis, comparison and map export."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app.gis import service as gis_service
from app.gis_analysis import annotation, service
from app.gis_analysis.schemas import (
    AnnotationCollection, AnnotationCreate, AnnotationRecord, AnnotationType,
    AnnotationUpdate, BufferAnalysisRequest, BufferAnalysisResponse, GISComparisonFrame,
    LayerCatalogItem, LocationSearchResponse, NearestFacilityRequest, NearestFacilityResponse,
    SpatialSelectRequest, SpatialSelectResponse, ThematicMapRequest, TraceResponse,
)


router = APIRouter(prefix="/api/v1/gis-analysis", tags=["gis-analysis"])
SessionDependency = Annotated[Session, Depends(get_database_session)]


def _domain_call(session: Session, action):
    """Map service validation and constraint failures to stable HTTP responses."""

    try:
        return action()
    except (service.GISAnalysisError, gis_service.GISVersionError) as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="注记违反版本、关联或唯一性约束") from exc


@router.get("/layers", response_model=list[LayerCatalogItem], summary="获取 Phase 1D 专业图层目录")
def read_layer_catalog() -> list[LayerCatalogItem]:
    """Return the static, dynamic and analysis layer ownership catalog."""

    return service.layer_catalog()


@router.get("/search", response_model=LocationSearchResponse, summary="坐标或本地地名道路 POI 定位")
def search_map_locations(
    session: SessionDependency,
    dataset_version_id: int = Query(gt=0),
    q: str = Query(min_length=1, max_length=128),
    limit: int = Query(default=12, ge=1, le=50),
) -> LocationSearchResponse:
    """Expose the read-only Phase 1D location search boundary."""

    return _domain_call(
        session, lambda: service.search_locations(session, dataset_version_id, q, limit)
    )


@router.get("/vector-tiles/{layer}/{z}/{x}/{y}.mvt", summary="读取版本隔离的 PostGIS 矢量瓦片")
def read_vector_tile(
    layer: Literal["river", "gate", "pump", "cross_section", "map_annotation"],
    z: int, x: int, y: int, dataset_version_id: int,
    session: SessionDependency,
) -> Response:
    """Return one Mapbox vector tile without exposing a second GIS database."""

    content = _domain_call(
        session,
        lambda: service.build_vector_tile(session, dataset_version_id, layer, z, x, y),
    )
    return Response(
        content=content,
        media_type="application/vnd.mapbox-vector-tile",
        headers={"Cache-Control": "private, max-age=300", "X-Dataset-Version": str(dataset_version_id)},
    )


@router.get("/annotations", response_model=AnnotationCollection, summary="读取比例尺与时刻相关注记")
def read_annotations(
    session: SessionDependency,
    dataset_version_id: int = Query(gt=0),
    scale_denominator: float = Query(default=50000, ge=0),
    bbox: str | None = Query(default=None),
    annotation_type: list[AnnotationType] | None = Query(default=None),
    limit: int = Query(default=2000, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    time_seconds: float = Query(default=0, ge=0),
    task_id: int | None = Query(default=None, gt=0),
    dispatch_run_id: int | None = Query(default=None, gt=0),
) -> AnnotationCollection:
    """Return static and dynamic labels without persisting runtime simulation state."""

    try:
        parsed_bbox = gis_service.parse_bbox(bbox)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _domain_call(session, lambda: annotation.list_annotations(
        session, dataset_version_id, scale_denominator, parsed_bbox,
        list(annotation_type) if annotation_type else None, limit, offset,
        time_seconds, task_id, dispatch_run_id,
    ))


@router.post("/annotations", response_model=AnnotationRecord, status_code=201, summary="创建工程注记")
def create_annotation(payload: AnnotationCreate, session: SessionDependency) -> AnnotationRecord:
    """Create one label in the sole authoritative PostGIS database."""

    return _domain_call(session, lambda: service.create_annotation(session, payload))


@router.put("/annotations/{annotation_id}", response_model=AnnotationRecord, summary="更新工程注记")
def update_annotation(
    annotation_id: int, payload: AnnotationUpdate, session: SessionDependency,
    dataset_version_id: int = Query(gt=0),
) -> AnnotationRecord:
    """Update one annotation without crossing its selected data version."""

    return _domain_call(session, lambda: service.update_annotation(
        session, annotation_id, dataset_version_id, payload
    ))


@router.delete("/annotations/{annotation_id}", status_code=204, summary="删除工程注记")
def delete_annotation(
    annotation_id: int, session: SessionDependency, dataset_version_id: int = Query(gt=0)
) -> Response:
    """Delete a label only; related engineering features remain untouched."""

    _domain_call(session, lambda: service.delete_annotation(session, annotation_id, dataset_version_id))
    return Response(status_code=204)


@router.get("/trace", response_model=TraceResponse, summary="沿河追踪上下游和控制设施")
def trace_river(
    session: SessionDependency, dataset_version_id: int = Query(gt=0), river_id: int = Query(gt=0)
) -> TraceResponse:
    """Traverse directed river topology for the selected data version."""

    return _domain_call(session, lambda: service.trace_river(session, dataset_version_id, river_id))


@router.post("/select", response_model=SpatialSelectResponse, summary="空间框选工程对象")
def select_features(payload: SpatialSelectRequest, session: SessionDependency) -> SpatialSelectResponse:
    """Intersect a user rectangle with versioned PostGIS engineering layers."""

    return _domain_call(session, lambda: service.select_features(session, payload))


@router.post("/buffer", response_model=BufferAnalysisResponse, summary="设施影响范围缓冲分析")
def buffer_analysis(payload: BufferAnalysisRequest, session: SessionDependency) -> BufferAnalysisResponse:
    """Calculate a metre-based impact area and affected facilities."""

    return _domain_call(session, lambda: service.buffer_analysis(session, payload))


@router.post("/nearest", response_model=NearestFacilityResponse, summary="查询最近设施")
def nearest_facilities(payload: NearestFacilityRequest, session: SessionDependency) -> NearestFacilityResponse:
    """Return nearest facilities using exact PostGIS geography distance."""

    return _domain_call(session, lambda: service.nearest_facilities(session, payload))


@router.get("/comparison-frame", response_model=GISComparisonFrame, summary="读取同版本多方案空间差异帧")
def comparison_frame(
    session: SessionDependency, dataset_version_id: int = Query(gt=0),
    baseline_task_id: int = Query(gt=0), comparison_task_id: int = Query(gt=0),
    time_seconds: float = Query(default=0, ge=0),
    baseline_dispatch_run_id: int | None = Query(default=None, gt=0),
    comparison_dispatch_run_id: int | None = Query(default=None, gt=0),
) -> GISComparisonFrame:
    """Align A/B model and dispatch results on stable spatial identifiers."""

    return _domain_call(session, lambda: service.comparison_frame(
        session, dataset_version_id, baseline_task_id, comparison_task_id,
        time_seconds, baseline_dispatch_run_id, comparison_dispatch_run_id,
    ))


@router.post("/thematic-map.pdf", summary="输出专业 GIS 专题图 PDF")
def thematic_map_pdf(payload: ThematicMapRequest, session: SessionDependency) -> Response:
    """Return a visually complete map with legend, scale, north arrow and provenance."""

    content = _domain_call(session, lambda: service.build_thematic_pdf(session, payload))
    return Response(
        content=content, media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="dayu-phase1d-thematic-map.pdf"'},
    )
