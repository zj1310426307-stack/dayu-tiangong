"""控制命令与静态资产可用性的通用验证。"""

import math

from model.control.policy import ControlTarget


COMMAND_UNITS = {
    "gate_opening_m": "m",
    "gate_opening_ratio": "ratio",
    "pump_enabled": "boolean_0_or_1",
    "pump_unit_count": "count",
    "pump_target_flow": "m3/s",
}

COMMAND_TYPES_BY_STRUCTURE = {
    "gate": frozenset({"gate_opening_m", "gate_opening_ratio"}),
    "pump": frozenset({"pump_enabled", "pump_unit_count", "pump_target_flow"}),
}


def command_matches_structure(structure_type: str, command_type: str) -> bool:
    """Return whether a whitelisted command belongs to the requested asset type."""

    return command_type in COMMAND_TYPES_BY_STRUCTURE.get(structure_type, frozenset())


def validate_command_value(command_type: str, value: float) -> tuple[bool, str | None]:
    """校验控制量的量纲域；设备上限由结构模型继续限幅。"""

    if not math.isfinite(value):
        return False, "control_target_must_be_finite"
    if command_type == "gate_opening_m" and value < 0:
        return False, "negative_gate_opening"
    if command_type == "gate_opening_ratio" and not 0.0 <= value <= 1.0:
        return False, "gate_opening_ratio_out_of_range"
    if command_type == "pump_enabled" and value not in {0.0, 1.0}:
        return False, "pump_enabled_must_be_0_or_1"
    if command_type == "pump_unit_count" and (value < 0 or not float(value).is_integer()):
        return False, "pump_unit_count_must_be_nonnegative_integer"
    if command_type == "pump_target_flow" and value < 0:
        return False, "negative_pump_target_flow"
    return True, None


def validate_control_target(target: ControlTarget, availability: str) -> tuple[bool, str | None]:
    """拒绝未知命令、结构物类型和维护/故障/离线设备命令。"""

    if target.command_type not in COMMAND_UNITS:
        return False, "unsupported_command_type"
    if target.structure_type not in {"gate", "pump"}:
        return False, "unsupported_structure_type"
    if not command_matches_structure(target.structure_type, target.command_type):
        return False, "command_structure_type_mismatch"
    value_valid, value_reason = validate_command_value(target.command_type, target.target_value)
    if not value_valid:
        return value_valid, value_reason
    if availability != "online":
        return False, f"asset_{availability}"
    return True, None
