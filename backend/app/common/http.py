"""业务写接口共用的数据库异常映射。"""

from collections.abc import Callable
from typing import TypeVar

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


T = TypeVar("T")


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
            detail="数据违反唯一性、关联或数值约束",
        ) from exc


def not_found(resource: str) -> HTTPException:
    """构造统一的业务对象不存在响应。"""

    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource}不存在")
