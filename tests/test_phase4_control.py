"""Phase 4 人工时序、阈值滞回、冷却、优先级和资产约束测试。"""

import pytest
from pydantic import ValidationError

from app.dispatch.schemas import DispatchActionCreate, DispatchRuleCreate
from model.control.constraints import validate_command_value, validate_control_target
from model.control.policy import CompositeControlPolicy, ControlTarget, HydraulicObservation
from model.control.rules import ThresholdRule, ThresholdRulePolicy
from model.control.schedule import ManualSchedulePolicy, ScheduledAction


def _rule(*, priority: int = 5, cooldown: float = 60.0) -> ThresholdRule:
    """构造一个节点水位高于 10 m 时开闸的规则。"""

    return ThresholdRule(
        id=1, name="high-water", observation_type="node_water_level",
        observation_object_id=3, operator=">=", threshold=10.0, hysteresis=0.2,
        minimum_hold_seconds=30.0, cooldown_seconds=cooldown,
        action_template={"structure_type": "gate", "structure_id": 1,
                         "command_type": "gate_opening_m", "target_value": 1.5},
        priority=priority,
    )


def test_threshold_rule_with_hysteresis() -> None:
    """规则满足保持时间后触发，只有低于 9.8 m 才恢复。"""

    policy = ThresholdRulePolicy((_rule(),))
    assert policy.targets_at(0.0, HydraulicObservation(0.0, {("node_water_level", 3): 10.1})) == []
    assert len(policy.targets_at(30.0, HydraulicObservation(30.0, {("node_water_level", 3): 10.1}))) == 1
    assert len(policy.targets_at(40.0, HydraulicObservation(40.0, {("node_water_level", 3): 9.9}))) == 1
    assert policy.targets_at(50.0, HydraulicObservation(50.0, {("node_water_level", 3): 9.7})) == []
    assert policy.recovery_count == 1


def test_rule_cooldown() -> None:
    """规则恢复后在冷却时间结束前不能再次触发。"""

    policy = ThresholdRulePolicy((_rule(cooldown=100.0),))
    policy.targets_at(0.0, HydraulicObservation(0.0, {("node_water_level", 3): 10.1}))
    policy.targets_at(30.0, HydraulicObservation(30.0, {("node_water_level", 3): 10.1}))
    policy.targets_at(40.0, HydraulicObservation(40.0, {("node_water_level", 3): 9.7}))
    policy.targets_at(60.0, HydraulicObservation(60.0, {("node_water_level", 3): 10.1}))
    assert policy.targets_at(100.0, HydraulicObservation(100.0, {("node_water_level", 3): 10.1})) == []
    assert len(policy.targets_at(140.0, HydraulicObservation(140.0, {("node_water_level", 3): 10.1}))) == 1


def test_rule_priority_conflict() -> None:
    """同设备同命令冲突必须选择更高优先级并计数。"""

    low = ManualSchedulePolicy((ScheduledAction(1, 0.0, "gate", 1, "gate_opening_m", 0.5, priority=1),))
    high = ManualSchedulePolicy((ScheduledAction(2, 0.0, "gate", 1, "gate_opening_m", 1.5, priority=10),))
    composite = CompositeControlPolicy((low, high))
    targets = composite.targets_at(0.0, HydraulicObservation(0.0, {}))
    assert targets[0].target_value == 1.5
    assert composite.conflict_count == 1


def test_manual_schedule_event_alignment() -> None:
    """人工动作时刻必须作为求解器同步事件时刻公开。"""

    policy = ManualSchedulePolicy((
        ScheduledAction(1, 30.0, "gate", 1, "gate_opening_m", 0.5),
        ScheduledAction(2, 75.0, "gate", 1, "gate_opening_m", 1.0),
    ))
    assert policy.event_times == (30.0, 75.0)


def test_maintenance_asset_rejects_command() -> None:
    """维护设备的控制命令必须拒绝，不能改静态资产状态。"""

    target = ControlTarget("gate", 1, "gate_opening_m", 1.0, 1, "manual", 1)
    assert validate_control_target(target, "maintenance") == (False, "asset_maintenance")


def test_control_command_value_domains() -> None:
    """比例、布尔、机组数和非负流量必须满足各自量纲域。"""

    assert validate_command_value("gate_opening_ratio", 1.1)[0] is False
    assert validate_command_value("pump_enabled", 0.5)[0] is False
    assert validate_command_value("pump_unit_count", 1.5)[0] is False
    assert validate_command_value("pump_target_flow", -1.0)[0] is False
    assert validate_command_value("pump_unit_count", 2.0) == (True, None)


def test_command_must_match_structure_type() -> None:
    """Gate actions cannot smuggle pump commands through the generic control target."""

    target = ControlTarget("gate", 1, "pump_enabled", 1.0, 1, "manual", 1)
    assert validate_control_target(target, "online") == (
        False,
        "command_structure_type_mismatch",
    )
    with pytest.raises(ValidationError, match="does not match"):
        DispatchActionCreate(
            sequence=1,
            time_seconds=0,
            structure_type="gate",
            gate_id=1,
            command_type="pump_enabled",
            target_value=1,
        )


def test_rule_action_template_is_a_strict_non_executable_contract() -> None:
    """Rule templates reject unknown keys and cannot carry executable expressions."""

    with pytest.raises(ValidationError, match="only structure_type"):
        DispatchRuleCreate(
            name="unsafe",
            observation_type="elapsed_time",
            operator=">=",
            threshold=0,
            action_template={
                "structure_type": "gate",
                "structure_id": 1,
                "command_type": "gate_opening_m",
                "target_value": 1.0,
                "expression": "__import__('os')",
            },
        )
