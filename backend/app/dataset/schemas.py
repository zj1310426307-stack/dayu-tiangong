"""版本化模型数据与 Phase 3 输入快照 HTTP 契约。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    """新增边界定值或时间序列。"""

    model_config = ConfigDict(extra="forbid")
    dataset_version_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=128)
    boundary_type: str = Field(min_length=1, max_length=64)
    target_node_id: int | None = Field(default=None, gt=0)
    values: dict[str, Any]
    unit: str = Field(min_length=1, max_length=32)
    description: str | None = None


class BoundaryConditionUpdate(BaseModel):
    """允许修改边界条件业务字段。"""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    boundary_type: str | None = Field(default=None, min_length=1, max_length=64)
    target_node_id: int | None = Field(default=None, gt=0)
    values: dict[str, Any] | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    description: str | None = None


class BoundaryConditionRecord(BoundaryConditionCreate):
    """返回边界条件记录。"""

    id: int


class SimulationCaseCreate(BaseModel):
    """新增引用数据版本和边界条件的计算方案。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    dataset_version_id: int = Field(gt=0)
    boundary_condition_id: int = Field(gt=0)
    boundary_condition_ids: list[int] = Field(default_factory=list)


class SimulationCaseUpdate(BaseModel):
    """允许修改计算方案名称、说明和边界条件。"""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    boundary_condition_id: int | None = Field(default=None, gt=0)
    boundary_condition_ids: list[int] | None = None


class SimulationCaseRecord(SimulationCaseCreate):
    """返回完整计算方案记录。"""

    id: int
    created_time: datetime


class ModelInputSnapshot(BaseModel):
    """返回可直接交给 Phase 3 适配器的只读输入快照。"""

    schema_version: str = "dayu.model-input.v1"
    generated_time: datetime
    simulation_case: SimulationCaseRecord
    dataset_version: DatasetVersionRecord
    rivers: list[dict[str, Any]]
    nodes: list[dict[str, Any]]
    segments: list[dict[str, Any]]
    connections: list[dict[str, Any]]
    cross_sections: list[dict[str, Any]]
    gates: list[dict[str, Any]]
    pumps: list[dict[str, Any]]
    parameters: list[ModelParameterRecord]
    boundary_conditions: list[BoundaryConditionRecord]
