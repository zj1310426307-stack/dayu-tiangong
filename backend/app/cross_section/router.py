"""横断面 CRUD HTTP 路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.common.http import commit_or_conflict, not_found
from app.cross_section import service
from app.cross_section.schemas import (
    CrossSectionCreate,
    CrossSectionListResponse,
    CrossSectionRecord,
    CrossSectionUpdate,
)
from app.database.session import get_database_session
from app.gis.models import CrossSection


router = APIRouter(prefix="/api/v1/cross-sections", tags=["cross-section-database"])
SessionDependency = Annotated[Session, Depends(get_database_session)]


@router.get("", response_model=CrossSectionListResponse, summary="分页查询横断面")
def read_cross_sections(
    session: SessionDependency,
    dataset_version_id: int | None = Query(default=None, gt=0),
    river_id: int | None = Query(default=None, gt=0),
    search: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> CrossSectionListResponse:
    """返回支持版本、河道和关键词筛选的断面列表。"""

    return service.list_cross_sections(
        session, dataset_version_id, river_id, search, limit, offset
    )


@router.post(
    "", response_model=CrossSectionRecord, status_code=status.HTTP_201_CREATED, summary="新增横断面"
)
def create_cross_section(
    payload: CrossSectionCreate, session: SessionDependency
) -> CrossSectionRecord:
    """新增并提交横断面。"""

    return commit_or_conflict(
        session, lambda: service.create_cross_section(session, payload)
    )


@router.get("/{section_id}", response_model=CrossSectionRecord, summary="读取横断面详情")
def read_cross_section(section_id: int, session: SessionDependency) -> CrossSectionRecord:
    """按主键读取完整断面数据。"""

    record = service.get_cross_section(session, section_id)
    if record is None:
        raise not_found("横断面")
    return record


@router.put("/{section_id}", response_model=CrossSectionRecord, summary="修改横断面")
def update_cross_section(
    section_id: int, payload: CrossSectionUpdate, session: SessionDependency
) -> CrossSectionRecord:
    """局部修改并提交横断面。"""

    section = session.get(CrossSection, section_id)
    if section is None:
        raise not_found("横断面")
    return commit_or_conflict(
        session, lambda: service.update_cross_section(session, section, payload)
    )


@router.delete("/{section_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除横断面")
def delete_cross_section(section_id: int, session: SessionDependency) -> Response:
    """删除指定横断面。"""

    section = session.get(CrossSection, section_id)
    if section is None:
        raise not_found("横断面")
    commit_or_conflict(session, lambda: service.delete_cross_section(session, section))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
