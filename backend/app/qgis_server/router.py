"""HTTP boundary for QGIS health and the safe same-origin WMS gateway."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app.gis_governance.errors import GovernanceError
from app.qgis_server.schemas import QgisServerHealthResponse
from app.qgis_server import service


router = APIRouter(tags=["qgis-server"])
SessionDependency = Annotated[Session, Depends(get_database_session)]


def _raise(exc: GovernanceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc


@router.get("/api/v1/gis/qgis-server/health", response_model=QgisServerHealthResponse)
def qgis_server_health(session: SessionDependency) -> QgisServerHealthResponse:
    """Return granular evidence for the private renderer."""

    return service.health(session)


@router.get("/qgis-server/wms")
def qgis_wms_gateway(request: Request, session: SessionDependency) -> Response:
    """Accept only platform parameters and never forward a raw browser query."""

    public = {key.lower(): value for key, value in request.query_params.multi_items()}
    try:
        content, content_type, status_code = service.proxy_wms(session, public)
    except GovernanceError as exc:
        _raise(exc)
    return Response(content=content, media_type=content_type, status_code=status_code, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
