"""调度计划、动作、规则、运行、对比和审计的薄 HTTP 路由。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app.dispatch import service
from app.dispatch.schemas import (
    DispatchActionCreate, DispatchActionRecord, DispatchActionUpdate,
    DispatchComparison, DispatchPlanCreate, DispatchPlanRecord, DispatchPlanUpdate,
    DispatchRuleCreate, DispatchRuleRecord, DispatchRuleUpdate, DispatchRunRecord,
    Page, ValidationReport,
)
from app.gis.models import DispatchRun, SimulationTask
from app.worker.lifecycle import request_cancel


router = APIRouter(prefix="/api/v1/dispatch", tags=["dispatch"])
SessionDependency = Annotated[Session, Depends(get_database_session)]


def _error(exc: Exception) -> HTTPException:
    """把调度领域错误映射为稳定 404/409/503 语义。"""

    if isinstance(exc, service.DispatchNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, service.DispatchQueueError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/plans", response_model=Page)
def list_plans(
    session: SessionDependency,
    dataset_version_id: int | None = Query(default=None, gt=0),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page:
    """分页筛选调度计划。"""

    items, total = service.list_plans(
        session, dataset_version_id=dataset_version_id, status=status_filter,
        limit=limit, offset=offset,
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/plans", response_model=DispatchPlanRecord, status_code=status.HTTP_201_CREATED)
def create_plan(payload: DispatchPlanCreate, session: SessionDependency) -> DispatchPlanRecord:
    """创建计划草稿。"""

    try:
        return service.create_plan(session, payload)
    except (service.DispatchStateError, IntegrityError) as exc:
        session.rollback()
        raise _error(exc) from exc


@router.get("/plans/{plan_id}", response_model=DispatchPlanRecord)
def get_plan(plan_id: int, session: SessionDependency) -> DispatchPlanRecord:
    """读取单个计划。"""

    try:
        return service.get_plan_record(session, plan_id)
    except service.DispatchNotFoundError as exc:
        raise _error(exc) from exc


@router.patch("/plans/{plan_id}", response_model=DispatchPlanRecord)
def update_plan(plan_id: int, payload: DispatchPlanUpdate, session: SessionDependency) -> DispatchPlanRecord:
    """更新可编辑计划。"""

    try:
        return service.update_plan(session, plan_id, payload)
    except (service.DispatchNotFoundError, service.DispatchStateError) as exc:
        raise _error(exc) from exc


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(plan_id: int, session: SessionDependency) -> Response:
    """删除没有运行记录的未冻结计划。"""

    try:
        service.delete_plan(session, plan_id)
        return Response(status_code=204)
    except (service.DispatchNotFoundError, service.DispatchStateError) as exc:
        raise _error(exc) from exc


@router.post("/plans/{plan_id}/clone", response_model=DispatchPlanRecord)
def clone_plan(plan_id: int, session: SessionDependency) -> DispatchPlanRecord:
    """克隆为递增版本草稿。"""

    try:
        return service.clone_plan(session, plan_id)
    except service.DispatchNotFoundError as exc:
        raise _error(exc) from exc


@router.post("/plans/{plan_id}/validate", response_model=ValidationReport)
def validate_plan(plan_id: int, session: SessionDependency) -> ValidationReport:
    """校验计划及跨版本引用。"""

    try:
        return service.validate_and_mark(session, plan_id)
    except (service.DispatchNotFoundError, service.DispatchStateError) as exc:
        raise _error(exc) from exc


@router.post("/plans/{plan_id}/freeze", response_model=DispatchPlanRecord)
def freeze_plan(plan_id: int, session: SessionDependency) -> DispatchPlanRecord:
    """冻结已校验计划。"""

    try:
        return service.freeze_plan(session, plan_id)
    except (service.DispatchNotFoundError, service.DispatchStateError) as exc:
        raise _error(exc) from exc


@router.get("/plans/{plan_id}/actions", response_model=list[DispatchActionRecord])
def list_actions(plan_id: int, session: SessionDependency) -> list[DispatchActionRecord]:
    """读取人工计划动作。"""

    try:
        return service.list_actions(session, plan_id)
    except service.DispatchNotFoundError as exc:
        raise _error(exc) from exc


@router.post("/plans/{plan_id}/actions", response_model=DispatchActionRecord, status_code=201)
def create_action(plan_id: int, payload: DispatchActionCreate, session: SessionDependency) -> DispatchActionRecord:
    """新增人工计划动作。"""

    try:
        return service.create_action(session, plan_id, payload)
    except (service.DispatchNotFoundError, service.DispatchStateError, IntegrityError) as exc:
        session.rollback()
        raise _error(exc) from exc


@router.patch("/actions/{action_id}", response_model=DispatchActionRecord)
def update_action(action_id: int, payload: DispatchActionUpdate, session: SessionDependency) -> DispatchActionRecord:
    """更新人工计划动作。"""

    try:
        return service.update_action(session, action_id, payload)
    except (service.DispatchNotFoundError, service.DispatchStateError) as exc:
        raise _error(exc) from exc


@router.delete("/actions/{action_id}", status_code=204)
def delete_action(action_id: int, session: SessionDependency) -> Response:
    """删除人工计划动作。"""

    try:
        service.delete_action(session, action_id)
        return Response(status_code=204)
    except (service.DispatchNotFoundError, service.DispatchStateError) as exc:
        raise _error(exc) from exc


@router.get("/plans/{plan_id}/rules", response_model=list[DispatchRuleRecord])
def list_rules(plan_id: int, session: SessionDependency) -> list[DispatchRuleRecord]:
    """读取阈值规则。"""

    try:
        return service.list_rules(session, plan_id)
    except service.DispatchNotFoundError as exc:
        raise _error(exc) from exc


@router.post("/plans/{plan_id}/rules", response_model=DispatchRuleRecord, status_code=201)
def create_rule(plan_id: int, payload: DispatchRuleCreate, session: SessionDependency) -> DispatchRuleRecord:
    """新增受控阈值规则。"""

    try:
        return service.create_rule(session, plan_id, payload)
    except (service.DispatchNotFoundError, service.DispatchStateError) as exc:
        raise _error(exc) from exc


@router.patch("/rules/{rule_id}", response_model=DispatchRuleRecord)
def update_rule(rule_id: int, payload: DispatchRuleUpdate, session: SessionDependency) -> DispatchRuleRecord:
    """更新受控阈值规则。"""

    try:
        return service.update_rule(session, rule_id, payload)
    except (service.DispatchNotFoundError, service.DispatchStateError) as exc:
        raise _error(exc) from exc


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, session: SessionDependency) -> Response:
    """删除受控阈值规则。"""

    try:
        service.delete_rule(session, rule_id)
        return Response(status_code=204)
    except (service.DispatchNotFoundError, service.DispatchStateError) as exc:
        raise _error(exc) from exc


@router.post("/plans/{plan_id}/runs", response_model=DispatchRunRecord, status_code=202)
def create_run(plan_id: int, session: SessionDependency) -> DispatchRunRecord:
    """创建并异步投递基准/受控计算。"""

    try:
        return service.create_run(session, plan_id)
    except (
        service.DispatchNotFoundError,
        service.DispatchStateError,
        service.DispatchQueueError,
    ) as exc:
        raise _error(exc) from exc


@router.get("/runs", response_model=Page)
def list_runs(
    session: SessionDependency,
    dataset_version_id: int | None = Query(default=None, gt=0),
    plan_id: int | None = Query(default=None, gt=0),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
) -> Page:
    """分页筛选调度运行。"""

    items, total = service.list_runs(
        session, dataset_version_id=dataset_version_id, plan_id=plan_id,
        status=status_filter, limit=limit, offset=offset,
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=DispatchRunRecord)
def get_run(run_id: int, session: SessionDependency) -> DispatchRunRecord:
    """读取调度运行和派生进度。"""

    try:
        return service.get_run(session, run_id)
    except service.DispatchNotFoundError as exc:
        raise _error(exc) from exc


@router.post("/runs/{run_id}/cancel", response_model=DispatchRunRecord)
def cancel_run(run_id: int, session: SessionDependency) -> DispatchRunRecord:
    """对基准和受控任务同时请求协作式取消。"""

    run = session.get(DispatchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="dispatch run does not exist")
    for task_id in (run.baseline_task_id, run.controlled_task_id):
        task = session.get(SimulationTask, task_id)
        if task is not None and task.status in {"queued", "running"}:
            request_cancel(session, task)
    run.status = "cancel_requested"
    session.commit()
    return service.get_run(session, run_id)


@router.post("/runs/{run_id}/retry", response_model=DispatchRunRecord, status_code=202)
def retry_run(run_id: int, session: SessionDependency) -> DispatchRunRecord:
    """以原冻结计划创建新的可审计运行，不覆写历史运行。"""

    run = session.get(DispatchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="dispatch run does not exist")
    if run.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="only failed or cancelled runs can be retried")
    try:
        return service.create_run(session, run.plan_id)
    except (
        service.DispatchNotFoundError,
        service.DispatchStateError,
        service.DispatchQueueError,
        ValueError,
    ) as exc:
        session.rollback()
        raise _error(exc) from exc


@router.get("/runs/{run_id}/comparison", response_model=DispatchComparison)
def comparison(run_id: int, session: SessionDependency) -> DispatchComparison:
    """返回基准与调度曲线、差值和指标。"""

    try:
        return service.comparison(session, run_id)
    except service.DispatchNotFoundError as exc:
        raise _error(exc) from exc


@router.get("/runs/{run_id}/{kind}", response_model=list[dict[str, Any]])
def related_rows(run_id: int, kind: str, session: SessionDependency) -> list[dict[str, Any]]:
    """读取 events/structures/nodes 结果；其他 kind 返回 404。"""

    if kind not in {"events", "structures", "nodes"}:
        raise HTTPException(status_code=404, detail="unsupported dispatch result kind")
    try:
        return service.related_rows(session, run_id, kind)
    except service.DispatchNotFoundError as exc:
        raise _error(exc) from exc
