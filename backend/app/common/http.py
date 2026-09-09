"""业务写接口共用的数据库异常映射。"""

from collections.abc import Callable
from typing import TypeVar

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


T = TypeVar("T")


def _integrity_conflict_detail(exc: IntegrityError) -> str:
    """Expose stable constraint context without leaking the full SQL statement."""

    diagnostic = getattr(exc.orig, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    table_name = getattr(diagnostic, "table_name", None)
    if constraint_name:
        location = f"表 {table_name} " if table_name else ""
        return (
            f"数据操作被关联或唯一性约束阻止：{location}约束 {constraint_name}；"
            "请先处理引用记录后重试"
        )
    return "数据违反唯一性、关联或数值约束；请先处理引用记录后重试"


def commit_or_conflict(session: Session, action: Callable[[], T]) -> T:
    """提交单次业务事务，并将约束冲突稳定映射为 HTTP 409。"""

    try:
        result = action()
        session.commit()
        return result
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_integrity_conflict_detail(exc),
        ) from exc


def not_found(resource: str) -> HTTPException:
    """构造统一的业务对象不存在响应。"""

    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource}不存在")
