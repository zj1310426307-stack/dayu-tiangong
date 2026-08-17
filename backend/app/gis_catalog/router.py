"""HTTP boundary for the PostGIS Catalog and allow-listed GeoServer Gateway."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app.gis_catalog import service
from app.gis_catalog.schemas import CatalogLayer, GISCatalogResponse, GISFeatureInfoResponse
from app.gis_governance.errors import GovernanceError


router = APIRouter(prefix="/api/v1/gis", tags=["gis-catalog"])
SessionDependency = Annotated[Session, Depends(get_database_session)]


def _raise(exc: GovernanceError) -> None:
    """Map structured service failures to the shared HTTP error envelope."""

    raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc


@router.get("/catalog", response_model=GISCatalogResponse)
def read_catalog(
    dataset_version_id: Annotated[int, Query(gt=0)],
    response: Response,
    session: SessionDependency,
) -> GISCatalogResponse:
    """Return the only browser-facing business layer directory."""

    try:
        catalog, etag = service.build_catalog(session, dataset_version_id)
    except GovernanceError as exc:
        _raise(exc)
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=30"
    return catalog


@router.get("/layers", response_model=list[CatalogLayer])
def read_layers(
    dataset_version_id: Annotated[int, Query(gt=0)],
    session: SessionDependency,
) -> list[CatalogLayer]:
    """Return the minimal layer directory requested by the WebGIS contract."""

    try:
        return service.list_catalog_layers(session, dataset_version_id)
    except GovernanceError as exc:
        _raise(exc)


@router.get("/ogc/wms", responses={200: {"content": {"image/png": {}, "image/jpeg": {}}}})
def read_wms_map(
    session: SessionDependency,
    dataset_version_id: Annotated[int, Query(gt=0)],
    layer_key: Annotated[str, Query(min_length=2, max_length=63)],
    bbox: str = Query(alias="BBOX"),
    width: int = Query(alias="WIDTH", ge=1, le=2048),
    height: int = Query(alias="HEIGHT", ge=1, le=2048),
    image_format: str = Query(default="image/png", alias="FORMAT"),
    transparent: bool = Query(default=True, alias="TRANSPARENT"),
) -> Response:
    """Proxy one safe GetMap request; browser-supplied layer names are ignored."""

    try:
        content, content_type = service.render_wms_map(
            session,
            dataset_version_id=dataset_version_id,
            layer_key=layer_key,
            bbox=bbox,
            width=width,
            height=height,
            image_format=image_format,
            transparent=transparent,
        )
    except GovernanceError as exc:
        _raise(exc)
    return Response(content=content, media_type=content_type, headers={"Cache-Control": "private, max-age=60", "X-Content-Type-Options": "nosniff"})


@router.get("/feature-info", response_model=GISFeatureInfoResponse)
def read_feature_info(
    session: SessionDependency,
    dataset_version_id: Annotated[int, Query(gt=0)],
    layer_key: Annotated[str, Query(min_length=2, max_length=63)],
    bbox: str,
    width: Annotated[int, Query(ge=1, le=2048)],
    height: Annotated[int, Query(ge=1, le=2048)],
    x: Annotated[int, Query(ge=0)],
    y: Annotated[int, Query(ge=0)],
) -> GISFeatureInfoResponse:
    """Query attributes through FastAPI so OpenLayers never talks to GeoServer directly."""

    try:
        return service.feature_info(
            session,
            dataset_version_id=dataset_version_id,
            layer_key=layer_key,
            bbox=bbox,
            width=width,
            height=height,
            x=x,
            y=y,
        )
    except GovernanceError as exc:
        _raise(exc)
