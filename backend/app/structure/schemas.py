"""闸门、泵站 CRUD HTTP 契约。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.spatial import validate_geometry


StructureStatus = Literal["online", "offline", "maintenance", "fault"]


class SpatialStructure(BaseModel):
    """定义建筑物共用的数据版本、河道、状态和位置。"""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=128)
    river_id: int = Field(gt=0)
    control_mode: str = Field(min_length=1, max_length=32)
    status: StructureStatus = "offline"
    geometry: dict[str, Any]

    @field_validator("geometry")
    @classmethod
    def check_geometry(cls, value: dict[str, Any]) -> dict[str, Any]:
        """要求水工建筑物定位为 CGCS2000 / EPSG:4490 Point。"""

        validate_geometry(value, "Point")
        return value


class GateCreate(SpatialStructure):
    """新增闸门请求。"""

    gate_code: str = Field(min_length=1, max_length=64)
    gate_type: str = Field(min_length=1, max_length=32)
    opening_direction: str = Field(min_length=1, max_length=32)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    max_flow: float = Field(ge=0)
    bottom_elevation: float
    river_segment_id: int | None = Field(default=None, gt=0)
    station: float | None = Field(default=None, ge=0)
    upstream_node_id: int | None = Field(default=None, gt=0)
    downstream_node_id: int | None = Field(default=None, gt=0)
    crest_elevation: float | None = None
    discharge_coefficient: float | None = Field(default=None, gt=0)
    minimum_opening: float | None = Field(default=None, ge=0)
    maximum_opening: float | None = Field(default=None, ge=0)
    opening_rate_limit: float | None = Field(default=None, ge=0)
    minimum_hold_seconds: float | None = Field(default=None, ge=0)
    allow_reverse_flow: bool = False


class GateUpdate(BaseModel):
    """允许局部修改闸门字段。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    river_id: int | None = Field(default=None, gt=0)
    gate_code: str | None = Field(default=None, min_length=1, max_length=64)
    gate_type: str | None = Field(default=None, min_length=1, max_length=32)
    opening_direction: str | None = Field(default=None, min_length=1, max_length=32)
    control_mode: str | None = Field(default=None, min_length=1, max_length=32)
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    max_flow: float | None = Field(default=None, ge=0)
    bottom_elevation: float | None = None
    river_segment_id: int | None = Field(default=None, gt=0)
    station: float | None = Field(default=None, ge=0)
    upstream_node_id: int | None = Field(default=None, gt=0)
    downstream_node_id: int | None = Field(default=None, gt=0)
    crest_elevation: float | None = None
    discharge_coefficient: float | None = Field(default=None, gt=0)
    minimum_opening: float | None = Field(default=None, ge=0)
    maximum_opening: float | None = Field(default=None, ge=0)
    opening_rate_limit: float | None = Field(default=None, ge=0)
    minimum_hold_seconds: float | None = Field(default=None, ge=0)
    allow_reverse_flow: bool | None = None
    status: StructureStatus | None = None
    geometry: dict[str, Any] | None = None

    @field_validator("geometry")
    @classmethod
    def check_geometry(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        """更新几何存在时必须是 Point。"""

        if value is not None:
            validate_geometry(value, "Point")
        return value


class GateRecord(GateCreate):
    """返回完整闸门记录。"""

    id: int
    created_time: datetime


class GateListResponse(BaseModel):
    """返回闸门分页列表。"""

    items: list[GateRecord]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class PumpCreate(SpatialStructure):
    """新增泵站请求。"""

    pump_code: str = Field(min_length=1, max_length=64)
    design_flow: float = Field(ge=0)
    head: float = Field(ge=0)
    power: float = Field(ge=0)
    efficiency_curve: dict[str, list[list[float]]]
    head_curve: dict[str, list[list[float]]] | None = None
    intake_node_id: int | None = Field(default=None, gt=0)
    outlet_node_id: int | None = Field(default=None, gt=0)
    transfer_type: Literal["internal_transfer", "external_outflow", "external_inflow"] | None = None
    unit_count: int | None = Field(default=None, ge=1)
    minimum_running_units: int | None = Field(default=None, ge=0)
    maximum_running_units: int | None = Field(default=None, ge=0)
    minimum_run_seconds: float | None = Field(default=None, ge=0)
    minimum_stop_seconds: float | None = Field(default=None, ge=0)
    maximum_starts_per_run: int | None = Field(default=None, ge=0)
    minimum_operating_head: float | None = Field(default=None, ge=0)
    maximum_operating_head: float | None = Field(default=None, ge=0)
    reverse_flow_protection: bool = True

    @field_validator("efficiency_curve")
    @classmethod
    def check_efficiency_curve(
        cls, value: dict[str, list[list[float]]]
    ) -> dict[str, list[list[float]]]:
        """要求效率曲线至少含两个二维点。"""

        points = value.get("points")
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError("efficiency_curve.points 至少包含两个点")
        if any(not isinstance(point, list) or len(point) != 2 for point in points):
            raise ValueError("效率曲线点必须是 [flow_ratio, efficiency]")
        return value


class PumpUpdate(BaseModel):
    """允许局部修改泵站字段。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    river_id: int | None = Field(default=None, gt=0)
    pump_code: str | None = Field(default=None, min_length=1, max_length=64)
    design_flow: float | None = Field(default=None, ge=0)
    head: float | None = Field(default=None, ge=0)
    power: float | None = Field(default=None, ge=0)
    efficiency_curve: dict[str, list[list[float]]] | None = None
    head_curve: dict[str, list[list[float]]] | None = None
    intake_node_id: int | None = Field(default=None, gt=0)
    outlet_node_id: int | None = Field(default=None, gt=0)
    transfer_type: Literal["internal_transfer", "external_outflow", "external_inflow"] | None = None
    unit_count: int | None = Field(default=None, ge=1)
    minimum_running_units: int | None = Field(default=None, ge=0)
    maximum_running_units: int | None = Field(default=None, ge=0)
    minimum_run_seconds: float | None = Field(default=None, ge=0)
    minimum_stop_seconds: float | None = Field(default=None, ge=0)
    maximum_starts_per_run: int | None = Field(default=None, ge=0)
    minimum_operating_head: float | None = Field(default=None, ge=0)
    maximum_operating_head: float | None = Field(default=None, ge=0)
    reverse_flow_protection: bool | None = None
    control_mode: str | None = Field(default=None, min_length=1, max_length=32)
    status: StructureStatus | None = None
    geometry: dict[str, Any] | None = None

    @field_validator("efficiency_curve")
    @classmethod
    def check_efficiency_curve(
        cls, value: dict[str, list[list[float]]] | None
    ) -> dict[str, list[list[float]]] | None:
        """更新效率曲线存在时检查结构。"""

        if value is None:
            return value
        points = value.get("points")
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError("efficiency_curve.points 至少包含两个点")
        return value

    @field_validator("geometry")
    @classmethod
    def check_geometry(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        """更新几何存在时必须是 Point。"""

        if value is not None:
            validate_geometry(value, "Point")
        return value


class PumpRecord(PumpCreate):
    """返回完整泵站记录。"""

    id: int
    created_time: datetime


class PumpListResponse(BaseModel):
    """返回泵站分页列表。"""

    items: list[PumpRecord]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
