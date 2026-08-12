"""河道 CRUD 与河网拓扑 HTTP 契约。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.spatial import validate_geometry


class RiverBase(BaseModel):
    """定义河道新增和修改共用字段。"""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64)
    length: float = Field(ge=0)
    level: str = Field(min_length=1, max_length=32)
    status: Literal["active", "inactive", "planned"] = "active"
    description: str | None = None
    geometry: dict[str, Any]

    @field_validator("geometry")
    @classmethod
    def check_geometry(cls, value: dict[str, Any]) -> dict[str, Any]:
        """要求河道几何为有效 CGCS2000 / EPSG:4490 LineString。"""

        validate_geometry(value, "LineString")
        return value


class RiverCreate(RiverBase):
    """新增河道请求。"""


class RiverUpdate(BaseModel):
    """允许局部更新河道业务字段。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    code: str | None = Field(default=None, min_length=1, max_length=64)
    length: float | None = Field(default=None, ge=0)
    level: str | None = Field(default=None, min_length=1, max_length=32)
    status: Literal["active", "inactive", "planned"] | None = None
    description: str | None = None
    geometry: dict[str, Any] | None = None

    @field_validator("geometry")
    @classmethod
    def check_geometry(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        """更新几何存在时必须是有效 LineString。"""

        if value is not None:
            validate_geometry(value, "LineString")
        return value


class RiverRecord(RiverBase):
    """返回带主键和创建时间的河道记录。"""

    id: int
    created_time: datetime


class RiverListResponse(BaseModel):
    """返回河道分页列表。"""

    items: list[RiverRecord]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class TopologyGenerateRequest(BaseModel):
    """指定需要重新生成拓扑的数据版本。"""

    dataset_version_id: int = Field(gt=0)
    tolerance: float = Field(default=0.00001, gt=0, le=0.01)


class RiverNodeRecord(BaseModel):
    """返回河网节点及其空间位置。"""

    id: int
    dataset_version_id: int
    node_code: str
    node_type: str
    longitude: float
    latitude: float
    geometry: dict[str, Any]


class RiverSegmentRecord(BaseModel):
    """返回计算河段及其上下游节点。"""

    id: int
    dataset_version_id: int
    river_id: int
    segment_code: str
    upstream_node_id: int
    downstream_node_id: int
    length: float
    geometry: dict[str, Any]


class RiverConnectionRecord(BaseModel):
    """返回河网有向连接边。"""

    id: int
    dataset_version_id: int
    from_node_id: int
    to_node_id: int
    river_id: int


class TopologyResponse(BaseModel):
    """返回一个数据版本的完整河网拓扑。"""

    dataset_version_id: int
    nodes: list[RiverNodeRecord]
    segments: list[RiverSegmentRecord]
    connections: list[RiverConnectionRecord]
