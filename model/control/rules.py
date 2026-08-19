"""白名单阈值、滞回、保持时间和冷却规则策略。"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from model.control.policy import ControlTarget, HydraulicObservation

OBSERVATION_TYPES = {
    "elapsed_time",
    "node_water_level",
    "section_water_level",
    "gate_head_difference",
    "pump_intake_level",
}
OPERATORS = {">", ">=", "<", "<="}


@dataclass(frozen=True)
class ThresholdRule:
    """保存一条受控阈值规则；action_template 是结构化命令而非代码。"""

    id: int | None
    name: str
    observation_type: str
    observation_object_id: int | None
    operator: str
    threshold: float
    hysteresis: float
    minimum_hold_seconds: float
    cooldown_seconds: float
    action_template: dict[str, float | int | str]
    priority: int
    enabled: bool = True

    def __post_init__(self) -> None:
        """构造时拒绝任意观测/操作符和不完整动作。"""

        if self.observation_type not in OBSERVATION_TYPES:
            raise ValueError("不允许的规则观测类型")
        if self.operator not in OPERATORS:
            raise ValueError("不允许的规则操作符")
        required = {"structure_type", "structure_id", "command_type", "target_value"}
        if not required.issubset(self.action_template):
            raise ValueError("规则动作模板字段不完整")
        numeric_fields = {
            "threshold": self.threshold,
            "hysteresis": self.hysteresis,
            "minimum_hold_seconds": self.minimum_hold_seconds,
            "cooldown_seconds": self.cooldown_seconds,
            "target_value": self.action_template["target_value"],
        }
        for name, value in numeric_fields.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"规则 {name} 必须是有限数值")
            if not math.isfinite(float(value)):
                raise ValueError(f"规则 {name} 必须是有限数值")
        if self.hysteresis < 0 or self.minimum_hold_seconds < 0 or self.cooldown_seconds < 0:
            raise ValueError("规则滞回、保持时间和冷却时间不得为负")


@dataclass
class _RuleRuntime:
    """保存规则触发/恢复、首次满足和最后触发时刻。"""

    active: bool = False
    condition_since: float | None = None
    last_trigger_time: float | None = None


@dataclass
class ThresholdRulePolicy:
    """确定性评估规则，并以滞回避免阈值附近频繁启停。"""

    rules: tuple[ThresholdRule, ...]
    runtime: dict[int, _RuleRuntime] = field(default_factory=dict)
    trigger_count: int = 0
    recovery_count: int = 0
    audit_events: list[dict[str, object]] = field(default_factory=list)

    @staticmethod
    def _matches(value: float, operator: str, threshold: float) -> bool:
        """在操作符白名单上比较数值，不使用 eval。"""

        return {
            ">": value > threshold,
            ">=": value >= threshold,
            "<": value < threshold,
            "<=": value <= threshold,
        }[operator]

    def targets_at(
        self, time_seconds: float, state: HydraulicObservation
    ) -> list[ControlTarget]:
        """按保持/冷却/滞回推进状态并返回当时有效的目标。"""

        targets: list[ControlTarget] = []
        for index, rule in enumerate(self.rules):
            if not rule.enabled:
                continue
            runtime = self.runtime.setdefault(rule.id or -(index + 1), _RuleRuntime())
            value = state.value(rule.observation_type, rule.observation_object_id)
            matches = self._matches(value, rule.operator, rule.threshold)
            recovery_threshold = (
                rule.threshold - rule.hysteresis
                if rule.operator in {">", ">="}
                else rule.threshold + rule.hysteresis
            )
            recovered = not self._matches(value, rule.operator, recovery_threshold)
            if runtime.active and recovered:
                runtime.active = False
                runtime.condition_since = None
                self.recovery_count += 1
                self.audit_events.append({
                    "time_seconds": time_seconds, "event_type": "recovered",
                    "rule_id": rule.id, "action_template": dict(rule.action_template),
                })
            if matches and not runtime.active:
                if runtime.condition_since is None:
                    runtime.condition_since = time_seconds
                held = time_seconds - runtime.condition_since >= rule.minimum_hold_seconds
                cooled = runtime.last_trigger_time is None or (
                    time_seconds - runtime.last_trigger_time >= rule.cooldown_seconds
                )
                if held and cooled:
                    runtime.active = True
                    runtime.last_trigger_time = time_seconds
                    self.trigger_count += 1
                    self.audit_events.append({
                        "time_seconds": time_seconds, "event_type": "triggered",
                        "rule_id": rule.id, "action_template": dict(rule.action_template),
                    })
            elif not matches and not runtime.active:
                runtime.condition_since = None
            if runtime.active:
                template = rule.action_template
                targets.append(
                    ControlTarget(
                        str(template["structure_type"]),
                        int(template["structure_id"]),
                        str(template["command_type"]),
                        float(template["target_value"]),
                        rule.priority,
                        "rule",
                        rule.id,
                    )
                )
        return targets

    def consume_audit_events(self) -> list[dict[str, object]]:
        """取出本轮新增触发/恢复审计，避免后续评估重复持久化。"""

        events = self.audit_events[:]
        self.audit_events.clear()
        return events
