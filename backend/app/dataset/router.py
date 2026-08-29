"""数据版本、模型参数、边界条件和计算方案 HTTP 路由。"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.common.http import commit_or_conflict, not_found
from app.database.session import get_database_session
from app.dataset import service
from app.hydraulic.model_input import build_model_input_v3
from app.model_engine.v4_schemas import V4PreviewResponse, V4ReadinessResponse
from app.model_engine.v4_service import assess_database_case, preview_from_assessment
from app.dataset.schemas import (
    BoundaryConditionCreate,
    BoundaryConditionRecord,
    BoundaryConditionUpdate,
    DatasetVersionCreate,
    DatasetVersionRecord,
    DatasetVersionUpdate,
    ModelInputSnapshot,
    ModelParameterCreate,
    ModelParameterRecord,
    ModelParameterUpdate,
    SimulationCaseCreate,
    SimulationCaseRecord,
    SimulationCaseUpdate,
)
from app.gis.models import BoundaryCondition, DatasetVersion, ModelParameter, SimulationCase
from model.solver.registry import D1_CAPABILITY_ID, D3A_1_CAPABILITY_ID


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


@router.put("/dataset-versions/{version_id}", response_model=DatasetVersionRecord, summary="修改数据集版本")
def update_dataset_version(version_id: int, payload: DatasetVersionUpdate, session: SessionDependency) -> DatasetVersionRecord:
    """修改版本名称或说明。"""

    entity = session.get(DatasetVersion, version_id)
    if entity is None:
        raise not_found("数据集版本")
    return commit_or_conflict(session, lambda: service.update_dataset_version(session, entity, payload))


@router.delete("/dataset-versions/{version_id}", status_code=204, summary="删除空数据集版本")
def delete_dataset_version(version_id: int, session: SessionDependency) -> Response:
    """删除无关联资产的数据集版本。"""

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


@router.get("/simulation-cases/{case_id}/input", response_model=ModelInputSnapshot, summary="生成 Phase 3 模型输入快照")
def read_model_input(case_id: int, session: SessionDependency) -> ModelInputSnapshot:
    """返回只读、可追溯、无计算结果的模型输入。"""

    snapshot = service.build_model_input(session, case_id)
    if snapshot is None:
        raise not_found("计算方案")
    return snapshot


@router.get(
    "/simulation-cases/{case_id}/input-v3",
    response_model=dict[str, object],
    summary="生成正式河网与断面模型输入 v3",
)
def read_model_input_v3(case_id: int, session: SessionDependency) -> dict[str, object]:
    """Return a solver-ready snapshot or a clear hydraulic readiness error."""

    try:
        snapshot = build_model_input_v3(session, case_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if snapshot is None:
        raise not_found("计算方案")
    return snapshot


@router.get(
    "/simulation-cases/{case_id}/input-v4/readiness",
    response_model=V4ReadinessResponse,
    summary="Check restricted native-v4 D1 readiness",
)
def read_model_input_v4_readiness(
    case_id: int,
    session: SessionDependency,
    dispatch_plan_id: int = Query(gt=0),
    capability_id: Literal[D1_CAPABILITY_ID, D3A_1_CAPABILITY_ID] = Query(
        default=D1_CAPABILITY_ID
    ),
) -> V4ReadinessResponse:
    """Return structured fail-closed findings without creating or freezing a task."""

    return assess_database_case(
        session,
        case_id,
        dispatch_plan_id,
        capability_id=capability_id,
    ).readiness


@router.get(
    "/simulation-cases/{case_id}/input-v4/preview",
    response_model=V4PreviewResponse,
    summary="Preview restricted native-v4 D1 input identities and hashes",
)
def read_model_input_v4_preview(
    case_id: int,
    session: SessionDependency,
    dispatch_plan_id: int = Query(gt=0),
    capability_id: Literal[D1_CAPABILITY_ID, D3A_1_CAPABILITY_ID] = Query(
        default=D1_CAPABILITY_ID
    ),
) -> V4PreviewResponse:
    """Return a bounded summary; the complete snapshot remains on the task audit route."""

    return preview_from_assessment(
        assess_database_case(
            session,
            case_id,
            dispatch_plan_id,
            capability_id=capability_id,
        )
    )
