"""系统接口使用的响应数据契约。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class SystemInfoResponse(BaseModel):
    """描述平台基础身份与运行状态。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    description: str
    status: Literal["running"]


class HealthResponse(BaseModel):
    """描述可供部署探针消费的应用健康信息。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["healthy"]
    service: str
    version: str
