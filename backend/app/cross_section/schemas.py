"""横断面 CRUD HTTP 契约与剖面点校验。"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.spatial import validate_geometry


def _validate_profile(value: dict[str, list[list[float]]]) -> dict[str, list[list[float]]]:
    """要求剖面至少三个点，且横向距离严格递增。"""

    points = value.get("points")
    if not isinstance(points, list) or len(points) < 3:
        raise ValueError("points.points 至少包含三个 [distance, elevation] 点")
    previous: float | None = None
    for point in points:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError("每个断面点必须是 [distance, elevation]")
        distance, elevation = point
        if not isinstance(distance, (int, float)) or not isinstance(elevation, (int, float)):
            raise ValueError("断面距离和高程必须是数值")
        if previous is not None and distance <= previous:
            raise ValueError("断面横向距离必须严格递增")
        previous = float(distance)
    return value


class CrossSectionBase(BaseModel):
    """定义横断面新增与响应共用字段。"""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    river_id: int = Field(gt=0)
    section_code: str = Field(min_length=1, max_length=64)
    section_name: str = Field(min_length=1, max_length=128)
    station: float = Field(ge=0)
    points: dict[str, list[list[float]]]
    roughness: float = Field(gt=0, le=1)
    elevation_min: float
    survey_date: date | None = None
    geometry: dict[str, Any]

    @field_validator("points")
    @classmethod
    def check_profile(cls, value: dict[str, list[list[float]]]) -> dict[str, list[list[float]]]:
        """校验剖面点数组。"""

        return _validate_profile(value)

    @field_validator("geometry")
    @classmethod
    def check_geometry(cls, value: dict[str, Any]) -> dict[str, Any]:
        """要求断面定位几何为 WGS 84 Point。"""

        validate_geometry(value, "Point")
        return value


class CrossSectionCreate(CrossSectionBase):
    """新增横断面请求。"""


class CrossSectionUpdate(BaseModel):
    """允许局部修改横断面业务字段。"""

    model_config = ConfigDict(extra="forbid")

    river_id: int | None = Field(default=None, gt=0)
    section_code: str | None = Field(default=None, min_length=1, max_length=64)
    section_name: str | None = Field(default=None, min_length=1, max_length=128)
    station: float | None = Field(default=None, ge=0)
    points: dict[str, list[list[float]]] | None = None
    roughness: float | None = Field(default=None, gt=0, le=1)
    elevation_min: float | None = None
    survey_date: date | None = None
    geometry: dict[str, Any] | None = None

    @field_validator("points")
    @classmethod
    def check_profile(
        cls, value: dict[str, list[list[float]]] | None
    ) -> dict[str, list[list[float]]] | None:
        """更新剖面存在时校验其点序。"""

        return _validate_profile(value) if value is not None else value

    @field_validator("geometry")
    @classmethod
    def check_geometry(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        """更新几何存在时要求为 Point。"""

        if value is not None:
            validate_geometry(value, "Point")
        return value


class CrossSectionRecord(CrossSectionBase):
    """返回完整横断面记录。"""

    id: int
    created_time: datetime


class CrossSectionListResponse(BaseModel):
    """返回横断面分页列表。"""

    items: list[CrossSectionRecord]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
