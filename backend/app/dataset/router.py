"""数据版本、模型参数、边界条件和计算方案 HTTP 路由。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.common.http import commit_or_conflict, not_found
from app.database.session import get_database_session
from app.dataset import service
from app.dataset.schemas import (
    BoundaryRatingCurveGenerateRequest,
    BoundaryRatingCurveGenerateResponse,
    BoundaryConditionCreate,
    BoundaryConditionRecord,
    BoundaryConditionUpdate,
    DatasetVersionCreate,
    DatasetVersionCloneRequest,
    DatasetVersionApprovalRequest,
    DatasetVersionRecord,
    DatasetVersionUpdate,
    ModelParameterCreate,
    ModelParameterRecord,
    ModelParameterUpdate,
    SimulationCaseCreate,
    SimulationCaseRecord,
    SimulationCaseUpdate,
)
from app.gis.models import BoundaryCondition, DatasetVersion, ModelParameter, SimulationCase


router = APIRouter(prefix="/api/v1/model-data", tags=["model-data"])
SessionDependency = Annotated[Session, Depends(get_database_session)]


def _commit_value_error(session: Session, action: Any) -> Any:
    """提交版本配置事务，并把跨版本业务错误映射为 422。"""

    try:
        return commit_or_conflict(session, action)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/dataset-versions", response_model=list[DatasetVersionRecord], summary="查询数据集版本")
def read_dataset_versions(session: SessionDependency) -> list[DatasetVersionRecord]:
    """返回全部版本。"""

    return service.list_dataset_versions(session)


@router.post("/dataset-versions", response_model=DatasetVersionRecord, status_code=201, summary="新增数据集版本")
def create_dataset_version(payload: DatasetVersionCreate, session: SessionDependency) -> DatasetVersionRecord:
    """新增数据集版本。"""

    return commit_or_conflict(session, lambda: service.create_dataset_version(session, payload))


@router.post(
    "/dataset-versions/{version_id}/clone",
    response_model=DatasetVersionRecord,
    status_code=201,
    summary="基于数据版本创建新的草稿版本",
)
def clone_dataset_version(
    version_id: int,
    payload: DatasetVersionCloneRequest,
    session: SessionDependency,
) -> DatasetVersionRecord:
    """Create a new Draft lineage node instead of modifying a certified source."""

    source = session.get(DatasetVersion, version_id)
    if source is None:
        raise not_found("数据集版本")
    return _commit_value_error(
        session, lambda: service.clone_dataset_version(session, source, payload)
    )


@router.put("/dataset-versions/{version_id}", response_model=DatasetVersionRecord, summary="修改数据集版本")
def update_dataset_version(version_id: int, payload: DatasetVersionUpdate, session: SessionDependency) -> DatasetVersionRecord:
    """修改唯一可编辑草稿的名称、说明或人工只读锁。"""

    entity = session.get(DatasetVersion, version_id)
    if entity is None:
        raise not_found("数据集版本")
    return commit_or_conflict(session, lambda: service.update_dataset_version(session, entity, payload))


@router.post(
    "/dataset-versions/{version_id}/approve-for-calculation",
    response_model=DatasetVersionRecord,
    summary="校核并批准 Standard 1D 计算数据版本",
)
def approve_dataset_version_for_calculation(
    version_id: int,
    payload: DatasetVersionApprovalRequest,
    session: SessionDependency,
) -> DatasetVersionRecord:
    """批准通过校核的数据；编辑权限由独立只读开关控制。"""

    entity = session.get(DatasetVersion, version_id)
    if entity is None:
        raise not_found("数据集版本")
    return _commit_value_error(
        session,
        lambda: service.approve_dataset_version_for_calculation(session, entity, payload),
    )


@router.delete("/dataset-versions/{version_id}", status_code=204, summary="删除数据版本")
def delete_dataset_version(version_id: int, session: SessionDependency) -> Response:
    """只删除未锁定、未派生且未被执行证据引用的草稿版本。"""

    entity = session.get(DatasetVersion, version_id)
    if entity is None:
        raise not_found("数据集版本")
    commit_or_conflict(session, lambda: service.delete_entity(session, entity))
    return Response(status_code=204)
@router.get("/parameters", response_model=list[ModelParameterRecord], summary="查询模型参数")
def read_parameters(session: SessionDependency, dataset_version_id: int | None = Query(default=None, gt=0)) -> list[ModelParameterRecord]:
    """按版本查询模型参数。"""

    return service.list_parameters(session, dataset_version_id)


@router.post("/parameters", response_model=ModelParameterRecord, status_code=201, summary="新增模型参数")
def create_parameter(payload: ModelParameterCreate, session: SessionDependency) -> ModelParameterRecord:
    """新增模型参数。"""

    return commit_or_conflict(session, lambda: service.create_parameter(session, payload))


@router.put("/parameters/{parameter_id}", response_model=ModelParameterRecord, summary="修改模型参数")
def update_parameter(parameter_id: int, payload: ModelParameterUpdate, session: SessionDependency) -> ModelParameterRecord:
    """修改模型参数。"""

    entity = session.get(ModelParameter, parameter_id)
    if entity is None:
        raise not_found("模型参数")
    return commit_or_conflict(session, lambda: service.update_parameter(session, entity, payload))


@router.delete("/parameters/{parameter_id}", status_code=204, summary="删除模型参数")
def delete_parameter(parameter_id: int, session: SessionDependency) -> Response:
    """删除模型参数。"""

    entity = session.get(ModelParameter, parameter_id)
    if entity is None:
        raise not_found("模型参数")
    commit_or_conflict(session, lambda: service.delete_entity(session, entity))
    return Response(status_code=204)


@router.get("/boundary-conditions", response_model=list[BoundaryConditionRecord], summary="查询边界条件")
def read_boundaries(session: SessionDependency, dataset_version_id: int | None = Query(default=None, gt=0)) -> list[BoundaryConditionRecord]:
    """按版本查询边界条件。"""

    return service.list_boundaries(session, dataset_version_id)


@router.post(
    "/boundary-conditions/rating-curve/generate",
    response_model=BoundaryRatingCurveGenerateResponse,
    summary="根据下游断面自动生成水位流量关系曲线",
)
def generate_boundary_rating_curve(
    payload: BoundaryRatingCurveGenerateRequest,
    session: SessionDependency,
) -> BoundaryRatingCurveGenerateResponse:
    """Generate a read-only Manning Q-H preview for a downstream boundary."""

    try:
        return service.generate_boundary_rating_curve(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/boundary-conditions", response_model=BoundaryConditionRecord, status_code=201, summary="新增边界条件")
def create_boundary(payload: BoundaryConditionCreate, session: SessionDependency) -> BoundaryConditionRecord:
    """新增边界条件。"""

    return commit_or_conflict(session, lambda: service.create_boundary(session, payload))


@router.put("/boundary-conditions/{boundary_id}", response_model=BoundaryConditionRecord, summary="修改边界条件")
def update_boundary(boundary_id: int, payload: BoundaryConditionUpdate, session: SessionDependency) -> BoundaryConditionRecord:
    """修改边界条件。"""

    entity = session.get(BoundaryCondition, boundary_id)
    if entity is None:
        raise not_found("边界条件")
    return commit_or_conflict(session, lambda: service.update_boundary(session, entity, payload))


@router.delete("/boundary-conditions/{boundary_id}", status_code=204, summary="删除边界条件")
def delete_boundary(boundary_id: int, session: SessionDependency) -> Response:
    """删除未被方案引用的边界条件。"""

    entity = session.get(BoundaryCondition, boundary_id)
    if entity is None:
        raise not_found("边界条件")
    commit_or_conflict(session, lambda: service.delete_entity(session, entity))
    return Response(status_code=204)


@router.get("/simulation-cases", response_model=list[SimulationCaseRecord], summary="查询计算方案")
def read_cases(session: SessionDependency, dataset_version_id: int | None = Query(default=None, gt=0)) -> list[SimulationCaseRecord]:
    """按版本查询计算方案。"""

    return service.list_cases(session, dataset_version_id)


@router.post("/simulation-cases", response_model=SimulationCaseRecord, status_code=201, summary="新增计算方案")
def create_case(payload: SimulationCaseCreate, session: SessionDependency) -> SimulationCaseRecord:
    """新增计算方案并校验跨版本引用。"""

    return _commit_value_error(session, lambda: service.create_case(session, payload))


@router.put("/simulation-cases/{case_id}", response_model=SimulationCaseRecord, summary="修改计算方案")
def update_case(case_id: int, payload: SimulationCaseUpdate, session: SessionDependency) -> SimulationCaseRecord:
    """修改计算方案。"""

    entity = session.get(SimulationCase, case_id)
    if entity is None:
        raise not_found("计算方案")
    return _commit_value_error(session, lambda: service.update_case(session, entity, payload))


@router.delete("/simulation-cases/{case_id}", status_code=204, summary="删除计算方案")
def delete_case(case_id: int, session: SessionDependency) -> Response:
    """删除计算方案。"""

    entity = session.get(SimulationCase, case_id)
    if entity is None:
        raise not_found("计算方案")
    commit_or_conflict(session, lambda: service.delete_entity(session, entity))
    return Response(status_code=204)


__all__ = ["router"]
