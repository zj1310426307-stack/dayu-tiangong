"""河道 CRUD 与河网拓扑 HTTP 路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.common.http import commit_or_conflict, not_found
from app.database.session import get_database_session
from app.gis.models import River
from app.river import service
from app.river.schemas import (
    RiverCreate,
    RiverListResponse,
    RiverRecord,
    RiverUpdate,
    TopologyGenerateRequest,
    TopologyResponse,
)


router = APIRouter(prefix="/api/v1/rivers", tags=["river-database"])
SessionDependency = Annotated[Session, Depends(get_database_session)]


@router.get("", response_model=RiverListResponse, summary="分页查询河道")
def read_rivers(
    session: SessionDependency,
    dataset_version_id: int | None = Query(default=None, gt=0),
    search: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> RiverListResponse:
    """返回可按版本和名称编码筛选的河道列表。"""

    return service.list_rivers(session, dataset_version_id, search, limit, offset)


@router.post("", response_model=RiverRecord, status_code=status.HTTP_201_CREATED, summary="新增河道")
def create_river(payload: RiverCreate, session: SessionDependency) -> RiverRecord:
    """创建河道并提交单一业务事务。"""

    return commit_or_conflict(session, lambda: service.create_river(session, payload))


@router.post("/topology/generate", response_model=TopologyResponse, summary="自动生成河网拓扑")
def generate_topology(
    payload: TopologyGenerateRequest, session: SessionDependency
) -> TopologyResponse:
    """按容差从河道端点幂等重建拓扑。"""

    return commit_or_conflict(
        session,
        lambda: service.generate_topology(
            session, payload.dataset_version_id, payload.tolerance
        ),
    )


@router.get("/topology", response_model=TopologyResponse, summary="读取河网拓扑")
def read_topology(
    session: SessionDependency,
    dataset_version_id: int = Query(gt=0),
) -> TopologyResponse:
    """返回指定数据版本的节点、河段与连接。"""

    return service.get_topology(session, dataset_version_id)


@router.get("/{river_id}", response_model=RiverRecord, summary="读取河道详情")
def read_river(river_id: int, session: SessionDependency) -> RiverRecord:
    """按主键返回单条河道。"""

    record = service.get_river(session, river_id)
    if record is None:
        raise not_found("河道")
    return record


@router.put("/{river_id}", response_model=RiverRecord, summary="修改河道")
def update_river(
    river_id: int, payload: RiverUpdate, session: SessionDependency
) -> RiverRecord:
    """局部更新河道并提交。"""

    river = session.get(River, river_id)
    if river is None:
        raise not_found("河道")
    return commit_or_conflict(session, lambda: service.update_river(session, river, payload))


@router.delete("/{river_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除河道")
def delete_river(river_id: int, session: SessionDependency) -> Response:
    """删除河道；有关联闸泵时数据库将拒绝并返回冲突。"""

    river = session.get(River, river_id)
    if river is None:
        raise not_found("河道")
    commit_or_conflict(session, lambda: service.delete_river(session, river))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
