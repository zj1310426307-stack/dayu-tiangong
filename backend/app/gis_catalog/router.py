"""Public Catalog and fixed basemap proxy endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app.gis_catalog.schemas import GISCatalogResponse
from app.gis_catalog import service
from app.gis_governance.errors import GovernanceError


router = APIRouter(prefix="/api/v1/gis", tags=["gis-catalog"])
SessionDependency = Annotated[Session, Depends(get_database_session)]


def _raise(exc: GovernanceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc


@router.get("/catalog", response_model=GISCatalogResponse)
def read_catalog(dataset_version_id: Annotated[int, Query(gt=0)], response: Response, session: SessionDependency) -> GISCatalogResponse:
    """Return the only browser-facing business layer directory."""

    try:
        catalog, etag = service.build_catalog(session, dataset_version_id)
    except GovernanceError as exc:
        _raise(exc)
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=30"
    return catalog


@router.get("/basemaps/world_imagery/{z}/{y}/{x}")
def world_imagery_tile(z: int, y: int, x: int) -> Response:
    """Expose only the deployment-owned imagery source through a bounded proxy."""

    try:
        content, content_type = service.proxy_world_imagery(z, y, x)
    except GovernanceError as exc:
        _raise(exc)
    return Response(content=content, media_type=content_type, headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"})
