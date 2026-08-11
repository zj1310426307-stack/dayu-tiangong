"""批量导入响应契约。"""

from typing import Literal

from pydantic import BaseModel, Field


class ImportIssue(BaseModel):
    """描述一条可定位到行号的导入问题。"""

    row: int = Field(ge=1)
    message: str


class ImportResponse(BaseModel):
    """返回导入资源、原文件存档、数量和问题列表。"""

    status: Literal["success", "failed"]
    resource: str
    imported_count: int = Field(ge=0)
    stored_filename: str
    errors: list[ImportIssue]
    warnings: list[ImportIssue]
