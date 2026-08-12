"""HTTP routing for GeoServer status and browser-safe OGC configuration."""

from fastapi import APIRouter, HTTPException, status

from app.geoserver import service
from app.geoserver.schemas import (
    GeoServerConfigResponse,
    GeoServerHealthResponse,
    GeoServerLayerRecord,
)


router = APIRouter(prefix="/api/v1/gis/geoserver", tags=["geoserver"])


@router.get("/health", response_model=GeoServerHealthResponse, summary="检查 GeoServer WMS/WMTS")
def read_geoserver_health() -> GeoServerHealthResponse:
    """Map real capabilities failures to a stable HTTP 503 response."""

    try:
        return service.get_health()
    except service.GeoServerUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GeoServer 空间服务不可用",
        ) from exc


@router.get("/layers", response_model=list[GeoServerLayerRecord], summary="列出 GeoServer 图层")
def read_geoserver_layers() -> list[GeoServerLayerRecord]:
    """Return six source-controlled layers without querying administrator APIs."""

    return service.list_layers()


@router.get("/config", response_model=GeoServerConfigResponse, summary="获取公开 OGC 地址")
def read_geoserver_config() -> GeoServerConfigResponse:
    """Expose WMS/WMTS/WFS paths while keeping credentials and REST URLs private."""

    try:
        return service.get_public_config()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GeoServer 公开地址配置错误",
        ) from exc
