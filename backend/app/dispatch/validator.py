"""调度计划跨版本、动作、规则和水力拓扑校验。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dispatch.schemas import ValidationReport
from app.gis.models import (
    CrossSection, DispatchAction, DispatchPlan, DispatchRule, Gate, Pump,
    RiverNode, RiverSegment, SimulationCase,
)
from model.control.constraints import (
    COMMAND_UNITS,
    command_matches_structure,
    validate_command_value,
    validate_control_target,
)
from model.control.policy import ControlTarget
from model.control.rules import OBSERVATION_TYPES, OPERATORS, ThresholdRule


def validate_plan(session: Session, plan: DispatchPlan) -> ValidationReport:
    """执行冻结前完整校验，返回全部错误而不是首错即停。"""

    errors: list[str] = []
    warnings: list[str] = []
    case = session.get(SimulationCase, plan.simulation_case_id)
    if case is None or case.dataset_version_id != plan.dataset_version_id:
        errors.append("计算方案不存在或与计划数据版本不一致")
    actions = list(session.scalars(select(DispatchAction).where(DispatchAction.plan_id == plan.id)).all())
    rules = list(session.scalars(select(DispatchRule).where(DispatchRule.plan_id == plan.id)).all())
    seen: set[tuple[str, int, float]] = set()
    for action in actions:
        asset_id = action.gate_id if action.structure_type == "gate" else action.pump_id
        key = (action.structure_type, int(asset_id or 0), action.time_seconds)
        if key in seen:
            errors.append(f"设备 {key[0]}:{key[1]} 在 {key[2]} s 存在冲突动作")
        seen.add(key)
        if action.time_seconds < 0 or action.time_seconds > plan.duration_seconds:
            errors.append(f"动作 {action.id} 时间超出计划时长")
        if action.command_type not in COMMAND_UNITS:
            errors.append(f"动作 {action.id} 命令类型不受支持")
        elif not command_matches_structure(action.structure_type, action.command_type):
            errors.append(f"动作 {action.id} 命令类型与设施类型不匹配")
        else:
            value_valid, reason = validate_command_value(action.command_type, action.target_value)
            if not value_valid:
                errors.append(f"动作 {action.id}：{reason}")
        asset = session.get(Gate if action.structure_type == "gate" else Pump, asset_id)
        if asset is None or asset.dataset_version_id != plan.dataset_version_id:
            errors.append(f"动作 {action.id} 设施不存在或跨数据版本")
        elif action.structure_type == "gate" and (
            asset.river_segment_id is None or asset.upstream_node_id is None or asset.downstream_node_id is None
        ):
            errors.append(f"闸门 {asset.id} 缺少已确认水力拓扑")
        elif action.structure_type == "gate":
            references = (
                session.get(RiverSegment, asset.river_segment_id),
                session.get(RiverNode, asset.upstream_node_id),
                session.get(RiverNode, asset.downstream_node_id),
            )
            if any(item is None or item.dataset_version_id != plan.dataset_version_id for item in references):
                errors.append(f"闸门 {asset.id} 水力拓扑引用跨数据版本或不存在")
        elif action.structure_type == "pump":
            transfer_type = asset.transfer_type or "internal_transfer"
            required_ids = (
                (asset.intake_node_id, asset.outlet_node_id)
                if transfer_type == "internal_transfer"
                else (asset.intake_node_id,) if transfer_type == "external_outflow"
                else (asset.outlet_node_id,)
            )
            references = tuple(session.get(RiverNode, node_id) if node_id else None for node_id in required_ids)
            if any(item is None for item in references):
                errors.append(f"泵站 {asset.id} 缺少 {transfer_type} 所需节点")
            elif any(item.dataset_version_id != plan.dataset_version_id for item in references):
                errors.append(f"泵站 {asset.id} 节点引用跨数据版本")
    for rule in rules:
        if rule.observation_type not in OBSERVATION_TYPES or rule.operator not in OPERATORS:
            errors.append(f"规则 {rule.id} 使用非白名单观测或操作符")
            continue
        try:
            ThresholdRule(
                id=rule.id, name=rule.name, enabled=rule.enabled,
                observation_type=rule.observation_type,
                observation_object_id=rule.observation_object_id, operator=rule.operator,
                threshold=rule.threshold, hysteresis=rule.hysteresis,
                minimum_hold_seconds=rule.minimum_hold_seconds,
                cooldown_seconds=rule.cooldown_seconds,
                action_template=rule.action_template, priority=rule.priority,
            )
        except ValueError as exc:
            errors.append(f"规则 {rule.id}：{exc}")
            continue

        observation_models = {
            "node_water_level": RiverNode,
            "section_water_level": CrossSection,
            "gate_head_difference": Gate,
            "pump_intake_level": Pump,
        }
        if rule.observation_type == "elapsed_time":
            if rule.observation_object_id is not None:
                errors.append(f"规则 {rule.id} 的 elapsed_time 不应引用观测对象")
        else:
            observation_model = observation_models.get(rule.observation_type)
            observed = (
                session.get(observation_model, rule.observation_object_id)
                if observation_model is not None and rule.observation_object_id is not None
                else None
            )
            if observed is None or observed.dataset_version_id != plan.dataset_version_id:
                errors.append(f"规则 {rule.id} 的观测对象不存在或跨数据版本")

        template = rule.action_template
        required = {"structure_type", "structure_id", "command_type", "target_value"}
        if not isinstance(template, dict) or set(template) != required:
            errors.append(f"规则 {rule.id} 的动作模板字段不完整或含未授权字段")
            continue
        structure_type = template.get("structure_type")
        structure_id = template.get("structure_id")
        command_type = template.get("command_type")
        target_value = template.get("target_value")
        if (
            structure_type not in {"gate", "pump"}
            or isinstance(structure_id, bool)
            or not isinstance(structure_id, int)
            or structure_id <= 0
            or not isinstance(command_type, str)
            or isinstance(target_value, bool)
            or not isinstance(target_value, (int, float))
        ):
            errors.append(f"规则 {rule.id} 的动作模板类型无效")
            continue
        asset = session.get(Gate if structure_type == "gate" else Pump, structure_id)
        if asset is None or asset.dataset_version_id != plan.dataset_version_id:
            errors.append(f"规则 {rule.id} 的动作设施不存在或跨数据版本")
            continue
        if structure_type == "gate":
            if (
                asset.river_segment_id is None
                or asset.upstream_node_id is None
                or asset.downstream_node_id is None
            ):
                errors.append(f"规则 {rule.id} 引用的闸门缺少已确认水力拓扑")
            else:
                references = (
                    session.get(RiverSegment, asset.river_segment_id),
                    session.get(RiverNode, asset.upstream_node_id),
                    session.get(RiverNode, asset.downstream_node_id),
                )
                if any(
                    item is None or item.dataset_version_id != plan.dataset_version_id
                    for item in references
                ):
                    errors.append(f"规则 {rule.id} 引用的闸门水力拓扑跨数据版本")
        else:
            transfer_type = asset.transfer_type or "internal_transfer"
            required_ids = (
                (asset.intake_node_id, asset.outlet_node_id)
                if transfer_type == "internal_transfer"
                else (asset.intake_node_id,)
                if transfer_type == "external_outflow"
                else (asset.outlet_node_id,)
            )
            references = tuple(
                session.get(RiverNode, node_id) if node_id else None
                for node_id in required_ids
            )
            if any(item is None for item in references):
                errors.append(f"规则 {rule.id} 引用的泵站缺少 {transfer_type} 所需节点")
            elif any(
                item.dataset_version_id != plan.dataset_version_id for item in references
            ):
                errors.append(f"规则 {rule.id} 引用的泵站节点跨数据版本")
        valid_target, reason = validate_control_target(
            ControlTarget(
                structure_type, structure_id, command_type, float(target_value),
                rule.priority, "rule", rule.id,
            ),
            asset.status,
        )
        if not valid_target:
            errors.append(f"规则 {rule.id} 的动作无效：{reason}")
    if not actions and not rules:
        warnings.append("计划没有动作或规则，将与基准工况等效")
    if "warning_level" not in plan.evaluation_config:
        warnings.append("未配置 warning_level，不计算超警戒时长")
    return ValidationReport(plan_id=plan.id, valid=not errors, errors=errors, warnings=warnings)
