"""调度模块数据库查询与分页存取。"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.gis.models import DispatchAction, DispatchPlan, DispatchRule, DispatchRun


def dump(entity: Any) -> dict[str, Any]:
    """提取 ORM 实体可公开列，排除 SQLAlchemy 内部状态。"""

    return {column.name: getattr(entity, column.name) for column in entity.__table__.columns}


def list_plans(
    session: Session, *, dataset_version_id: int | None, status: str | None,
    limit: int, offset: int,
) -> tuple[list[DispatchPlan], int]:
    """按版本/状态筛选调度计划并返回分页总数。"""

    statement = select(DispatchPlan)
    if dataset_version_id is not None:
        statement = statement.where(DispatchPlan.dataset_version_id == dataset_version_id)
    if status is not None:
        statement = statement.where(DispatchPlan.status == status)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = list(
        session.scalars(
            statement.order_by(DispatchPlan.id.desc()).limit(limit).offset(offset)
        ).all()
    )
    return items, int(total)


def list_runs(
    session: Session, *, plan_id: int | None, status: str | None,
    limit: int, offset: int,
) -> tuple[list[DispatchRun], int]:
    """按计划/状态筛选调度运行并返回分页总数。"""

    statement = select(DispatchRun)
    if plan_id is not None:
        statement = statement.where(DispatchRun.plan_id == plan_id)
    if status is not None:
        statement = statement.where(DispatchRun.status == status)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = list(
        session.scalars(
            statement.order_by(DispatchRun.id.desc()).limit(limit).offset(offset)
        ).all()
    )
    return items, int(total)


def counts(session: Session, plan_id: int) -> tuple[int, int]:
    """返回计划动作数和规则数。"""

    action_count = session.scalar(
        select(func.count(DispatchAction.id)).where(DispatchAction.plan_id == plan_id)
    ) or 0
    rule_count = session.scalar(
        select(func.count(DispatchRule.id)).where(DispatchRule.plan_id == plan_id)
    ) or 0
    return int(action_count), int(rule_count)
