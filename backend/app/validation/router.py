"""水利数据库质量校验 HTTP 路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app.validation.schemas import ValidationReport, ValidationRequest
from app.validation.service import run_validation


router = APIRouter(prefix="/api/v1/validation", tags=["data-validation"])
SessionDependency = Annotated[Session, Depends(get_database_session)]


@router.post("/run", response_model=ValidationReport, summary="运行水利数据库自动校验")
def validate_dataset(payload: ValidationRequest, session: SessionDependency) -> ValidationReport:
    """返回空间、水力、建筑物、拓扑和模型完整性报告。"""

    try:
        return run_validation(session, payload.dataset_version_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
