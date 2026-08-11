"""数据库质量校验请求与报告契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ValidationRequest(BaseModel):
    """指定待校验数据版本。"""

    dataset_version_id: int = Field(gt=0)


class ValidationItem(BaseModel):
    """描述一项规则的严重级别、命中数量与样例主键。"""

    code: str
    category: Literal["spatial", "hydraulic", "structure", "topology", "model"]
    severity: Literal["error", "warning", "passed"]
    message: str
    count: int = Field(ge=0)
    sample_ids: list[int] = Field(default_factory=list)


class ValidationSummary(BaseModel):
    """聚合错误、警告和通过规则数量。"""

    errors: int = Field(ge=0)
    warnings: int = Field(ge=0)
    passed: int = Field(ge=0)
    is_model_ready: bool


class ValidationReport(BaseModel):
    """返回一次可追溯的数据版本质量报告。"""

    dataset_version_id: int
    checked_time: datetime
    summary: ValidationSummary
    items: list[ValidationItem]
