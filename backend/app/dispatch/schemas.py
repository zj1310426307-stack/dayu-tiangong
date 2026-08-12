"""调度计划、动作、规则、运行、事件和对比 HTTP 契约。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PlanStatus = Literal["draft", "validated", "frozen", "archived"]
RunStatus = Literal[
    "pending", "queued", "running", "cancel_requested", "cancelled", "success", "failed"
]


def _validate_action_template(template: dict[str, Any]) -> dict[str, Any]:
    """Validate the complete, non-executable action payload used by a rule."""

    required = {"structure_type", "structure_id", "command_type", "target_value"}
    if set(template) != required:
        raise ValueError(
            "action_template must contain only structure_type, structure_id, "
            "command_type and target_value"
        )
    structure_type = template.get("structure_type")
    structure_id = template.get("structure_id")
    command_type = template.get("command_type")
    target_value = template.get("target_value")
    if structure_type not in {"gate", "pump"}:
        raise ValueError("unsupported action_template structure_type")
    if isinstance(structure_id, bool) or not isinstance(structure_id, int) or structure_id <= 0:
        raise ValueError("action_template structure_id must be a positive integer")
    if not isinstance(command_type, str):
        raise ValueError("action_template command_type must be a string")
    if isinstance(target_value, bool) or not isinstance(target_value, (int, float)):
        raise ValueError("action_template target_value must be numeric")
    from model.control.constraints import command_matches_structure, validate_command_value
    if not command_matches_structure(structure_type, command_type):
        raise ValueError("action_template command does not match its structure_type")
    valid, reason = validate_command_value(command_type, float(target_value))
    if not valid:
        raise ValueError(reason or "invalid action_template target_value")
    return template


class DispatchPlanCreate(BaseModel):
    """创建一个可编辑的调度计划草稿。"""

    model_config = ConfigDict(extra="forbid")
    dataset_version_id: int = Field(gt=0)
    simulation_case_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    duration_seconds: float = Field(gt=0)
    evaluation_config: dict[str, Any] = Field(default_factory=dict)
    storage_level: Literal["summary", "key_sections", "full"] = "key_sections"
    created_by: str = Field(default="local-user", min_length=1, max_length=64)


class DispatchPlanUpdate(BaseModel):
    """仅草稿/已校验计划允许修改的字段。"""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    duration_seconds: float | None = Field(default=None, gt=0)
    evaluation_config: dict[str, Any] | None = None
    storage_level: Literal["summary", "key_sections", "full"] | None = None
    status: Literal["archived"] | None = None


class DispatchPlanRecord(BaseModel):
    """返回计划版本、状态、计数和冻结来源。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    dataset_version_id: int
    simulation_case_id: int
    name: str
    version: int
    status: PlanStatus
    description: str | None
    duration_seconds: float
    evaluation_config: dict[str, Any]
    storage_level: str
    created_by: str
    created_time: datetime
    updated_time: datetime
    frozen_time: datetime | None
    frozen_snapshot_hash: str | None
    action_count: int = 0
    rule_count: int = 0


class DispatchActionCreate(BaseModel):
    """新增一个具有明确单位语义的人工计划动作。"""

    model_config = ConfigDict(extra="forbid")
    sequence: int = Field(ge=0)
    time_seconds: float = Field(ge=0)
    structure_type: Literal["gate", "pump"]
    gate_id: int | None = Field(default=None, gt=0)
    pump_id: int | None = Field(default=None, gt=0)
    command_type: Literal[
        "gate_opening_m", "gate_opening_ratio", "pump_enabled",
        "pump_unit_count", "pump_target_flow",
    ]
    target_value: float
    interpolation: Literal["step", "linear"] = "step"
    priority: int = 0
    note: str | None = None

    @model_validator(mode="after")
    def validate_asset(self) -> "DispatchActionCreate":
        """确保结构物类型与唯一非空外键一致。"""

        valid = (
            self.structure_type == "gate" and self.gate_id is not None and self.pump_id is None
        ) or (
            self.structure_type == "pump" and self.pump_id is not None and self.gate_id is None
        )
        if not valid:
            raise ValueError("structure_type 与 gate_id/pump_id 必须唯一对应")
        from model.control.constraints import command_matches_structure, validate_command_value
        if not command_matches_structure(self.structure_type, self.command_type):
            raise ValueError("command_type does not match structure_type")
        value_valid, reason = validate_command_value(self.command_type, self.target_value)
        if not value_valid:
            raise ValueError(reason or "控制目标值无效")
        return self


class DispatchActionUpdate(BaseModel):
    """更新动作时复用完整受控字段，避免局部更新产生不一致。"""

    model_config = ConfigDict(extra="forbid")
    sequence: int | None = Field(default=None, ge=0)
    time_seconds: float | None = Field(default=None, ge=0)
    command_type: Literal[
        "gate_opening_m", "gate_opening_ratio", "pump_enabled",
        "pump_unit_count", "pump_target_flow",
    ] | None = None
    target_value: float | None = None
    interpolation: Literal["step", "linear"] | None = None
    priority: int | None = None
    note: str | None = None


class DispatchActionRecord(DispatchActionCreate):
    """返回动作主键和所属计划。"""

    id: int
    plan_id: int


class DispatchRuleCreate(BaseModel):
    """新增白名单观测与操作符组成的阈值规则。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    observation_type: Literal[
        "elapsed_time", "node_water_level", "section_water_level",
        "gate_head_difference", "pump_intake_level",
    ]
    observation_object_id: int | None = Field(default=None, gt=0)
    operator: Literal[">", ">=", "<", "<="]
    threshold: float
    hysteresis: float = Field(default=0, ge=0)
    minimum_hold_seconds: float = Field(default=0, ge=0)
    cooldown_seconds: float = Field(default=0, ge=0)
    action_template: dict[str, Any]
    priority: int = 0

    @model_validator(mode="after")
    def validate_rule_contract(self) -> "DispatchRuleCreate":
        """Keep observations and actions inside the documented rule DSL."""

        if self.observation_type == "elapsed_time" and self.observation_object_id is not None:
            raise ValueError("elapsed_time must not declare observation_object_id")
        if self.observation_type != "elapsed_time" and self.observation_object_id is None:
            raise ValueError("asset observations require observation_object_id")
        _validate_action_template(self.action_template)
        return self


class DispatchRuleUpdate(BaseModel):
    """局部更新规则的受控字段。"""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None
    threshold: float | None = None
    hysteresis: float | None = Field(default=None, ge=0)
    minimum_hold_seconds: float | None = Field(default=None, ge=0)
    cooldown_seconds: float | None = Field(default=None, ge=0)
    action_template: dict[str, Any] | None = None
    priority: int | None = None

    @model_validator(mode="after")
    def validate_action(self) -> "DispatchRuleUpdate":
        """Reject malformed replacement actions before they reach persistence."""

        if self.action_template is not None:
            _validate_action_template(self.action_template)
        return self


class DispatchRuleRecord(DispatchRuleCreate):
    """返回规则主键和所属计划。"""

    id: int
    plan_id: int


class ValidationReport(BaseModel):
    """返回计划是否可冻结及可操作错误/警告。"""

    plan_id: int
    valid: bool
    errors: list[str]
    warnings: list[str]


class DispatchRunRecord(BaseModel):
    """返回基准/受控任务、队列和评价状态。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    plan_id: int
    baseline_task_id: int | None
    controlled_task_id: int | None
    status: RunStatus
    progress: int
    metrics: dict[str, Any] | None
    queue_job_id: str | None
    error_message: str | None
    created_time: datetime
    start_time: datetime | None
    end_time: datetime | None


class Page(BaseModel):
    """统一分页容器。"""

    items: list[Any]
    total: int
    limit: int
    offset: int


class DispatchComparison(BaseModel):
    """返回基准/调度关键断面曲线、差值和指标。"""

    run_id: int
    status: RunStatus
    baseline_task_id: int | None
    controlled_task_id: int | None
    section_code: str | None
    time: list[float]
    baseline_water_level: list[float]
    controlled_water_level: list[float]
    difference: list[float]
    metrics: dict[str, Any]
    diagnostics: dict[str, Any]
