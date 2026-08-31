"""闸门与泵站 CRUD HTTP 路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.common.http import commit_or_conflict, not_found
from app.database.session import get_database_session
from app.gis.models import Gate, Pump
from app.structure import service
from app.structure.schemas import (
    GateCreate,
    GateListResponse,
    GateRecord,
    GateUpdate,
    PumpCreate,
    PumpListResponse,
    PumpRecord,
    PumpUpdate,
)


router = APIRouter(tags=["structure-database"])
SessionDependency = Annotated[Session, Depends(get_database_session)]


@router.get("/api/v1/gates", response_model=GateListResponse, summary="分页查询闸门")
def read_gates(session: SessionDependency, dataset_version_id: int | None = Query(default=None, gt=0), river_id: int | None = Query(default=None, gt=0), search: str | None = None, limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0)) -> GateListResponse:
    """返回可筛选的闸门列表。"""

    return service.list_gates(session, dataset_version_id, river_id, search, limit, offset)


@router.post("/api/v1/gates", response_model=GateRecord, status_code=status.HTTP_201_CREATED, summary="新增闸门")
def create_gate(payload: GateCreate, session: SessionDependency) -> GateRecord:
    """新增并提交闸门。"""

    return commit_or_conflict(session, lambda: service.create_gate(session, payload))


@router.get("/api/v1/gates/{gate_id}", response_model=GateRecord, summary="读取闸门详情")
def read_gate(gate_id: int, session: SessionDependency) -> GateRecord:
    """按主键读取闸门。"""

    record = service.get_gate(session, gate_id)
    if record is None:
        raise not_found("闸门")
    return record


@router.put("/api/v1/gates/{gate_id}", response_model=GateRecord, summary="修改闸门")
def update_gate(gate_id: int, payload: GateUpdate, session: SessionDependency) -> GateRecord:
    """局部修改并提交闸门。"""

    entity = session.get(Gate, gate_id)
    if entity is None:
        raise not_found("闸门")
    return commit_or_conflict(session, lambda: service.update_gate(session, entity, payload))


@router.delete("/api/v1/gates/{gate_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除闸门")
def delete_gate(gate_id: int, session: SessionDependency) -> Response:
    """删除指定闸门。"""

    entity = session.get(Gate, gate_id)
    if entity is None:
        raise not_found("闸门")
    commit_or_conflict(session, lambda: service.delete_structure(session, entity))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/v1/pumps", response_model=PumpListResponse, summary="分页查询泵站")
def read_pumps(session: SessionDependency, dataset_version_id: int | None = Query(default=None, gt=0), river_id: int | None = Query(default=None, gt=0), search: str | None = None, limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0)) -> PumpListResponse:
    """返回可筛选的泵站列表。"""

    return service.list_pumps(session, dataset_version_id, river_id, search, limit, offset)


@router.post("/api/v1/pumps", response_model=PumpRecord, status_code=status.HTTP_201_CREATED, summary="新增泵站")
def create_pump(payload: PumpCreate, session: SessionDependency) -> PumpRecord:
    """新增并提交泵站。"""

    return commit_or_conflict(session, lambda: service.create_pump(session, payload))


@router.get("/api/v1/pumps/{pump_id}", response_model=PumpRecord, summary="读取泵站详情")
def read_pump(pump_id: int, session: SessionDependency) -> PumpRecord:
    """按主键读取泵站。"""

    record = service.get_pump(session, pump_id)
    if record is None:
        raise not_found("泵站")
    return record


@router.put("/api/v1/pumps/{pump_id}", response_model=PumpRecord, summary="修改泵站")
def update_pump(pump_id: int, payload: PumpUpdate, session: SessionDependency) -> PumpRecord:
    """局部修改并提交泵站。"""

    entity = session.get(Pump, pump_id)
    if entity is None:
        raise not_found("泵站")
    return commit_or_conflict(session, lambda: service.update_pump(session, entity, payload))


@router.delete("/api/v1/pumps/{pump_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除泵站")
def delete_pump(pump_id: int, session: SessionDependency) -> Response:
    """删除指定泵站。"""

    entity = session.get(Pump, pump_id)
    if entity is None:
        raise not_found("泵站")
    commit_or_conflict(session, lambda: service.delete_structure(session, entity))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
