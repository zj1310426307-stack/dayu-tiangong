"""控制命令与静态资产可用性的通用验证。"""

import math
from collections.abc import Mapping

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

CONTINUOUS_COMMAND_TYPES = frozenset(
    {"gate_opening_m", "gate_opening_ratio", "pump_target_flow"}
)
DISCRETE_COMMAND_TYPES = frozenset({"pump_enabled", "pump_unit_count"})


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


def validate_interpolation(
    command_type: str, interpolation: str
) -> tuple[bool, str | None]:
    """Reject interpolation modes that would create fractional discrete commands."""

    if interpolation not in {"step", "linear"}:
        return False, "unsupported_interpolation"
    if command_type in DISCRETE_COMMAND_TYPES and interpolation != "step":
        return False, "discrete_command_requires_step_interpolation"
    if command_type not in CONTINUOUS_COMMAND_TYPES | DISCRETE_COMMAND_TYPES:
        return False, "unsupported_command_type"
    return True, None


def validate_target_against_asset(
    target: ControlTarget,
    constraints: Mapping[str, object],
) -> tuple[bool, str | None]:
    """Validate one requested target against frozen, solver-neutral asset limits."""

    availability = str(constraints.get("availability", "offline"))
    valid, reason = validate_control_target(target, availability)
    if not valid:
        return valid, reason

    if target.structure_type == "gate":
        height = float(constraints.get("height_m", 0.0))
        minimum = float(constraints.get("minimum_opening_m", 0.0))
        maximum = float(constraints.get("maximum_opening_m", height))
        rate_limit = float(constraints.get("opening_rate_limit_m_per_s", 0.0))
        minimum_hold = float(constraints.get("minimum_hold_seconds", 0.0))
        initial_opening = float(constraints.get("initial_opening_m", 0.0))
        explicit_initial_state = constraints.get("initial_state_explicit", False) is True
        initial_state_valid = (
            (
                math.isclose(initial_opening, 0.0, rel_tol=0.0, abs_tol=1.0e-12)
                or minimum <= initial_opening <= maximum
            )
            if explicit_initial_state
            else math.isclose(initial_opening, 0.0, rel_tol=0.0, abs_tol=1.0e-12)
        )
        if (
            not all(
                math.isfinite(value)
                for value in (
                    height,
                    minimum,
                    maximum,
                    rate_limit,
                    minimum_hold,
                    initial_opening,
                )
            )
            or height <= 0
            or minimum < 0
            or maximum < minimum
            or maximum > height
            or rate_limit < 0
            or minimum_hold < 0
            or not initial_state_valid
        ):
            return False, "gate_constraint_configuration_invalid"
        opening = (
            target.target_value
            if target.command_type == "gate_opening_m"
            else target.target_value * height
        )
        if opening < minimum and not math.isclose(opening, 0.0):
            return False, "gate_opening_below_minimum"
        if opening > maximum:
            return False, "gate_opening_above_maximum"
        return True, None

    unit_count = int(constraints.get("unit_count", 0))
    minimum_units = int(constraints.get("minimum_running_units", 0))
    maximum_units = int(constraints.get("maximum_running_units", unit_count))
    design_flow_capacity = float(
        constraints.get("design_flow_capacity_m3s", 0.0)
    )
    minimum_run = float(constraints.get("minimum_run_seconds", 0.0))
    minimum_stop = float(constraints.get("minimum_stop_seconds", 0.0))
    maximum_starts = int(constraints.get("maximum_starts_per_replay", 0))
    initial_running_units = int(constraints.get("initial_running_units", 0))
    initial_stop_satisfied = constraints.get(
        "initial_stop_constraint_satisfied", False
    )
    explicit_initial_state = constraints.get("initial_state_explicit", False) is True
    if explicit_initial_state:
        initial_runtime = float(constraints.get("initial_runtime_seconds", 0.0))
        initial_stop = float(constraints.get("initial_stop_seconds", 0.0))
        initial_state_valid = (
            0 <= initial_running_units <= maximum_units
            and math.isfinite(initial_runtime)
            and initial_runtime >= 0
            and math.isfinite(initial_stop)
            and initial_stop >= 0
            and not (initial_running_units > 0 and initial_stop > 0)
            and not (initial_running_units == 0 and initial_runtime > 0)
        )
    else:
        initial_state_valid = (
            initial_running_units == 0 and initial_stop_satisfied is True
        )
    if (
        not all(
            math.isfinite(value)
            for value in (design_flow_capacity, minimum_run, minimum_stop)
        )
        or unit_count <= 0
        or minimum_units < 0
        or maximum_units < minimum_units
        or maximum_units > unit_count
        or design_flow_capacity < 0
        or minimum_run < 0
        or minimum_stop < 0
        or maximum_starts < 0
        or not initial_state_valid
    ):
        return False, "pump_constraint_configuration_invalid"
    if target.command_type == "pump_unit_count":
        requested_units = int(target.target_value)
        if requested_units > maximum_units:
            return False, "pump_units_above_maximum"
        if 0 < requested_units < minimum_units:
            return False, "pump_units_below_minimum"
    if (
        target.command_type == "pump_enabled"
        and target.target_value > 0
        and maximum_units < max(1, minimum_units)
    ):
        return False, "pump_no_running_units_available"
    if target.command_type == "pump_target_flow":
        if target.target_value > design_flow_capacity:
            return False, "pump_target_flow_above_static_capacity"
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
