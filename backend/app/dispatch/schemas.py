"""调度计划、动作、规则、运行、事件和对比 HTTP 契约。"""

from datetime import datetime
import math
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    field_validator,
    model_validator,
)


PlanStatus = Literal["draft", "validated", "frozen", "archived"]
RunStatus = Literal[
    "pending", "queued", "running", "cancel_requested", "cancelled", "success", "failed"
]


def _evaluation_config_path(parent: str, key: object) -> str:
    """Render one deterministic nested path for an actionable validation error."""

    if isinstance(key, str) and key.isidentifier():
        return f"{parent}.{key}"
    return f"{parent}[{key!r}]"


def _validate_finite_evaluation_config(value: object, path: str) -> None:
    """Reject non-finite floats anywhere in the JSON-like evaluation config tree."""

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be finite, got {value!r}")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_finite_evaluation_config(
                item, _evaluation_config_path(path, key)
            )
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_finite_evaluation_config(item, f"{path}[{index}]")


def _validate_evaluation_config(value: dict[str, Any]) -> dict[str, Any]:
    """Validate generic JSON plus the numeric flood-risk settings we consume."""

    _validate_finite_evaluation_config(value, "evaluation_config")
    for field_name in ("warning_level", "guarantee_level"):
        if field_name not in value:
            continue
        setting = value[field_name]
        if (
            isinstance(setting, bool)
            or not isinstance(setting, (int, float))
            or not math.isfinite(float(setting))
        ):
            raise ValueError(f"evaluation_config.{field_name} must be a finite number")
    return value


def _reject_explicit_nulls(model: BaseModel, nullable_fields: set[str]) -> None:
    """Keep PATCH from turning non-null database columns into runtime 500s."""

    invalid = sorted(
        field_name
        for field_name in model.model_fields_set
        if field_name not in nullable_fields and getattr(model, field_name) is None
    )
    if invalid:
        raise ValueError(
            "explicit null is not allowed for: " + ", ".join(invalid)
        )


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
    if (
        isinstance(target_value, bool)
        or not isinstance(target_value, (int, float))
        or not math.isfinite(float(target_value))
    ):
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
    duration_seconds: FiniteFloat = Field(gt=0)
    evaluation_config: dict[str, Any] = Field(default_factory=dict)
    storage_level: Literal["summary", "key_sections", "full"] = "key_sections"
    created_by: str = Field(default="local-user", min_length=1, max_length=64)

    @field_validator("evaluation_config")
    @classmethod
    def validate_evaluation_config(
        cls, value: dict[str, Any]
    ) -> dict[str, Any]:
        """Keep every nested numeric evaluation setting JSON/hash safe."""

        return _validate_evaluation_config(value)


class DispatchPlanUpdate(BaseModel):
    """仅草稿/已校验计划允许修改的字段。"""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    duration_seconds: FiniteFloat | None = Field(default=None, gt=0)
    evaluation_config: dict[str, Any] | None = None
    storage_level: Literal["summary", "key_sections", "full"] | None = None
    status: Literal["archived"] | None = None

    @field_validator("evaluation_config")
    @classmethod
    def validate_evaluation_config(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Apply the same recursive finite-value gate to partial plan updates."""

        if value is not None:
            _validate_evaluation_config(value)
        return value

    @model_validator(mode="after")
    def reject_nonnullable_nulls(self) -> "DispatchPlanUpdate":
        """Only description is nullable in the persisted plan contract."""

        _reject_explicit_nulls(self, {"description"})
        return self


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
    snapshot_target: Literal["static_v2", "hydraulic_v3"] = "static_v2"
    cloned_from_plan_id: int | None = None
    action_count: int = 0
    rule_count: int = 0


class DispatchActionCreate(BaseModel):
    """新增一个具有明确单位语义的人工计划动作。"""

    model_config = ConfigDict(extra="forbid")
    sequence: int = Field(ge=0)
    time_seconds: FiniteFloat = Field(ge=0)
    structure_type: Literal["gate", "pump"]
    gate_id: int | None = Field(default=None, gt=0)
    pump_id: int | None = Field(default=None, gt=0)
    command_type: Literal[
        "gate_opening_m", "gate_opening_ratio", "pump_enabled",
        "pump_unit_count", "pump_target_flow",
    ]
    target_value: FiniteFloat
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
        from model.control.constraints import (
            command_matches_structure,
            validate_command_value,
            validate_interpolation,
        )
        if not command_matches_structure(self.structure_type, self.command_type):
            raise ValueError("command_type does not match structure_type")
        value_valid, reason = validate_command_value(self.command_type, self.target_value)
        if not value_valid:
            raise ValueError(reason or "控制目标值无效")
        interpolation_valid, reason = validate_interpolation(
            self.command_type, self.interpolation
        )
        if not interpolation_valid:
            raise ValueError(reason or "控制插值无效")
        return self


class DispatchActionUpdate(BaseModel):
    """更新动作时复用完整受控字段，避免局部更新产生不一致。"""

    model_config = ConfigDict(extra="forbid")
    sequence: int | None = Field(default=None, ge=0)
    time_seconds: FiniteFloat | None = Field(default=None, ge=0)
    command_type: Literal[
        "gate_opening_m", "gate_opening_ratio", "pump_enabled",
        "pump_unit_count", "pump_target_flow",
    ] | None = None
    target_value: FiniteFloat | None = None
    interpolation: Literal["step", "linear"] | None = None
    priority: int | None = None
    note: str | None = None

    @model_validator(mode="after")
    def reject_nonnullable_nulls(self) -> "DispatchActionUpdate":
        """Only note is nullable in the persisted action contract."""

        _reject_explicit_nulls(self, {"note"})
        return self


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
    threshold: FiniteFloat
    hysteresis: FiniteFloat = Field(default=0, ge=0)
    minimum_hold_seconds: FiniteFloat = Field(default=0, ge=0)
    cooldown_seconds: FiniteFloat = Field(default=0, ge=0)
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
    threshold: FiniteFloat | None = None
    hysteresis: FiniteFloat | None = Field(default=None, ge=0)
    minimum_hold_seconds: FiniteFloat | None = Field(default=None, ge=0)
    cooldown_seconds: FiniteFloat | None = Field(default=None, ge=0)
    action_template: dict[str, Any] | None = None
    priority: int | None = None

    @model_validator(mode="after")
    def validate_action(self) -> "DispatchRuleUpdate":
        """Reject malformed replacement actions before they reach persistence."""

        _reject_explicit_nulls(self, set())
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


class DispatchReadinessIssue(BaseModel):
    """Return one stable execution blocker or non-blocking warning."""

    code: str
    message: str
    feature: str | None = None
    status: str | None = None


class DispatchCapabilityFact(BaseModel):
    """Expose the exact version-bound capability fact used by readiness."""

    engine: str
    engine_version: str
    adapter_version: str
    feature: str
    status: str
    production_status: str | None = None
    synthetic_status: str | None = None
    production_eligible: bool | None = None
    reason: str
    benchmark_ids: list[str]
    accepted_cases: list[str] = Field(default_factory=list)
    evidence_class: str | None = None
    supported_subset: list[str] = Field(default_factory=list)
    unsupported_subset: list[str] = Field(default_factory=list)
    verified_at: str | None = None


class DispatchExecutionReadiness(BaseModel):
    """Separate plan validity, runtime availability, and Solver compatibility."""

    plan_id: int
    plan_status: PlanStatus
    planning_valid: bool
    frozen_snapshot_valid: bool
    static_preview_allowed: bool
    hydraulic_runtime_supported: Literal[False]
    run_allowed: bool
    evidence_class: Literal["SYNTHETIC_DEVELOPMENT_ONLY"]
    real_validation_status: Literal["SKIPPED_BY_USER"]
    engine: str
    engine_version: str
    adapter_version: str
    runtime_available: bool
    runtime_detail: str
    required_features: list[str]
    capabilities: list[DispatchCapabilityFact]
    blockers: list[DispatchReadinessIssue]
    warnings: list[DispatchReadinessIssue]
    frozen_snapshot_hash: str | None


class DispatchSyntheticObservationValue(BaseModel):
    """Declare one finite, explicitly synthetic rule observation."""

    model_config = ConfigDict(extra="forbid")
    observation_type: Literal[
        "node_water_level",
        "section_water_level",
        "gate_head_difference",
        "pump_intake_level",
    ]
    observation_object_id: int = Field(gt=0)
    value: FiniteFloat


class DispatchSyntheticObservationFrame(BaseModel):
    """Declare all synthetic observations available at one replay time."""

    model_config = ConfigDict(extra="forbid")
    time_seconds: FiniteFloat = Field(ge=0)
    values: list[DispatchSyntheticObservationValue] = Field(
        default_factory=list, max_length=500
    )

    @model_validator(mode="after")
    def reject_duplicate_observations(self) -> "DispatchSyntheticObservationFrame":
        """Keep one unambiguous value per observation identity and frame."""

        keys = [
            (item.observation_type, item.observation_object_id)
            for item in self.values
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("synthetic observation frame contains duplicate identities")
        return self


class DispatchSchedulePreviewRequest(BaseModel):
    """Request a non-hydraulic replay of one frozen scheduling policy."""

    model_config = ConfigDict(extra="forbid")
    evidence_class: Literal["SYNTHETIC_DEVELOPMENT_ONLY"]
    observations: list[DispatchSyntheticObservationFrame] = Field(
        min_length=2, max_length=2000
    )

    @model_validator(mode="after")
    def validate_observation_timeline(self) -> "DispatchSchedulePreviewRequest":
        """Require a deterministic timeline that starts at zero and never rewinds."""

        times = [item.time_seconds for item in self.observations]
        if times[0] != 0:
            raise ValueError("synthetic observation replay must start at 0 seconds")
        if any(right <= left for left, right in zip(times, times[1:])):
            raise ValueError("synthetic observation times must be strictly increasing")
        return self


class DispatchReplayTargetRecord(BaseModel):
    """Return one requested and statically resolved control target."""

    structure_type: Literal["gate", "pump"]
    structure_id: int
    command_type: str
    requested_value: float
    resolved_value: float | None
    priority: int
    source_type: Literal["manual", "rule"]
    source_id: int | None
    outcome: Literal["selected", "limited", "rejected"]
    reason: str | None


class DispatchReplayRuleEvent(BaseModel):
    """Return a synthetic rule trigger or recovery audit event."""

    time_seconds: float
    event_type: Literal["triggered", "recovered"]
    rule_id: int | None
    action_template: dict[str, Any]


class DispatchReplayStep(BaseModel):
    """Return selected targets and rule events for one observation frame."""

    time_seconds: float
    targets: list[DispatchReplayTargetRecord]
    conflict_evaluations: int = Field(ge=0)
    rule_events: list[DispatchReplayRuleEvent]


class DispatchSchedulePreview(BaseModel):
    """Return deterministic synthetic scheduling evidence without hydraulic claims."""

    plan_id: int
    evidence_class: Literal["SYNTHETIC_DEVELOPMENT_ONLY"]
    hydraulic_execution_supported: Literal[False]
    no_hydraulic_feedback: Literal[True]
    plan_snapshot_hash: str
    observation_hash: str
    result_hash: str
    steps: list[DispatchReplayStep]
    conflict_evaluations: int = Field(ge=0)
    rule_trigger_count: int = Field(ge=0)
    rule_recovery_count: int = Field(ge=0)
    evaluator_id: str
    tie_break_policy: str
    initial_state_basis: str
    safety_notice: str


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
    run_mode: Literal["legacy", "hydraulic_preview", "production"] = "legacy"
    evidence_class: str | None = None
    engine_id: str | None = None
    control_runtime: str | None = None
    compiled_artifact_hash: str | None = None
    runtime_provenance: dict[str, Any] | None = None
    result_contract: dict[str, Any] | None = None
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
