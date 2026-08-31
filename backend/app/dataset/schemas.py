"""版本化模型数据与 Phase 3 输入快照 HTTP 契约。"""

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


BoundaryType = Literal[
    "upstream_discharge",
    "downstream_water_level",
    "lateral_inflow",
]


class DatasetVersionCreate(BaseModel):
    """新增不可混用的数据集版本。"""

    model_config = ConfigDict(extra="forbid")
    version: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    creator: str = Field(min_length=1, max_length=64)


class DatasetVersionUpdate(BaseModel):
    """允许修改数据集版本说明性字段。"""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None


class DatasetVersionRecord(DatasetVersionCreate):
    """返回带主键与创建时间的数据集版本。"""

    id: int
    status: str = "draft"
    parent_version_id: int | None = None
    source_batch_id: int | None = None
    content_hash: str | None = None
    change_summary: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    published_at: datetime | None = None
    retired_at: datetime | None = None
    created_time: datetime


class ModelParameterCreate(BaseModel):
    """新增版本化模型参数。"""

    model_config = ConfigDict(extra="forbid")
    dataset_version_id: int = Field(gt=0)
    parameter_type: str = Field(min_length=1, max_length=64)
    parameter_name: str = Field(min_length=1, max_length=128)
    value: float
    unit: str = Field(min_length=1, max_length=32)
    description: str | None = None


class ModelParameterUpdate(BaseModel):
    """允许修改模型参数值与说明。"""

    model_config = ConfigDict(extra="forbid")
    value: float | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    description: str | None = None


class ModelParameterRecord(ModelParameterCreate):
    """返回模型参数记录。"""

    id: int


class BoundaryConditionCreate(BaseModel):
    """Create one Standard 1D endpoint or lateral boundary."""

    model_config = ConfigDict(extra="forbid")
    dataset_version_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=128)
    boundary_type: BoundaryType
    target_node_id: int | None = Field(
        default=None,
        gt=0,
        deprecated=True,
        description=(
            "Historical river_node compatibility reference only. Standard 1D never "
            "uses this field for hydraulic binding."
        ),
    )
    hydraulic_node_id: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Authoritative hydraulic.node endpoint. Required for upstream_discharge "
            "and downstream_water_level."
        ),
    )
    branch_id: int | None = Field(
        default=None,
        gt=0,
        description="Authoritative hydraulic.branch identity for lateral_inflow.",
    )
    chainage_m: float | None = Field(
        default=None,
        ge=0,
        description="Directed metre chainage on branch_id for lateral_inflow.",
    )
    values: dict[str, Any]
    unit: str = Field(min_length=1, max_length=32)
    description: str | None = None

    @model_validator(mode="after")
    def validate_hydraulic_binding(self) -> Self:
        """Require one unambiguous authoritative hydraulic location."""

        if self.boundary_type in {"upstream_discharge", "downstream_water_level"}:
            if self.hydraulic_node_id is None:
                raise ValueError(f"{self.boundary_type} requires hydraulic_node_id")
            if self.branch_id is not None or self.chainage_m is not None:
                raise ValueError(
                    "endpoint boundaries use hydraulic_node_id and must not define "
                    "branch_id or chainage_m"
                )
        elif self.branch_id is None or self.chainage_m is None:
            raise ValueError("lateral_inflow requires branch_id and chainage_m")
        elif self.hydraulic_node_id is not None:
            raise ValueError("lateral_inflow must not define hydraulic_node_id")
        return self


class BoundaryConditionUpdate(BaseModel):
    """允许修改边界条件业务字段。"""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    boundary_type: BoundaryType | None = None
    target_node_id: int | None = Field(
        default=None,
        gt=0,
        deprecated=True,
        description=(
            "Historical river_node compatibility reference only. Standard 1D never "
            "uses this field for hydraulic binding."
        ),
    )
    hydraulic_node_id: int | None = Field(default=None, gt=0)
    branch_id: int | None = Field(default=None, gt=0)
    chainage_m: float | None = Field(default=None, ge=0)
    values: dict[str, Any] | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    description: str | None = None


class BoundaryConditionRecord(BaseModel):
    """Return the persisted boundary, including its authoritative location."""

    model_config = ConfigDict(extra="forbid")
    dataset_version_id: int
    name: str
    boundary_type: BoundaryType
    target_node_id: int | None = Field(
        default=None,
        deprecated=True,
        description=(
            "Historical river_node compatibility reference only. Standard 1D never "
            "uses this field for hydraulic binding."
        ),
    )
    hydraulic_node_id: int | None = None
    branch_id: int | None = None
    chainage_m: float | None = None
    values: dict[str, Any]
    unit: str
    description: str | None = None
    id: int


class SimulationCaseCreate(BaseModel):
    """新增引用数据版本和边界条件的计算方案。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    dataset_version_id: int = Field(gt=0)
    boundary_condition_id: int = Field(gt=0)
    boundary_condition_ids: list[int] = Field(default_factory=list)
    hydraulic_1d_configuration: dict[str, Any] | None = None


class SimulationCaseUpdate(BaseModel):
    """允许修改计算方案名称、说明和边界条件。"""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    boundary_condition_id: int | None = Field(default=None, gt=0)
    boundary_condition_ids: list[int] | None = None
    hydraulic_1d_configuration: dict[str, Any] | None = None


class SimulationCaseRecord(SimulationCaseCreate):
    """返回完整计算方案记录。"""

    id: int
    created_time: datetime
