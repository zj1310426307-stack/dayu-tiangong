"""闸门孔流、堰流、倒流和开度约束的纯水力模型。"""

from __future__ import annotations

import math
from dataclasses import dataclass

GRAVITY = 9.81


@dataclass(frozen=True)
class GateHydraulicResult:
    """保存闸门实际通量、流态和控制约束审计。"""

    requested_opening: float
    actual_opening: float
    upstream_level: float
    downstream_level: float
    head_difference: float
    flow: float
    regime: str
    constraint_flags: tuple[str, ...]


@dataclass
class GateControlState:
    """保存上一步实际开度和变化时刻，静态资产状态不在此修改。"""

    opening: float = 0.0
    # 初始状态并非“刚发生变位”；首个 t=0 指令不应被最小保持时长误拒绝。
    last_change_time: float = -1.0e12


def constrain_gate_opening(
    requested_opening: float,
    *,
    previous_opening: float,
    elapsed_seconds: float,
    minimum_opening: float,
    maximum_opening: float,
    opening_rate_limit: float,
    minimum_hold_seconds: float,
    time_since_change: float,
    availability: str,
) -> tuple[float, tuple[str, ...]]:
    """执行可用性、范围、保持时间和开度变化率约束。"""

    flags: list[str] = []
    if availability != "online":
        return previous_opening, (f"asset_{availability}", "command_rejected")
    target = requested_opening
    if target <= 0:
        target = 0.0
    elif target < minimum_opening:
        target = minimum_opening
        flags.append("minimum_opening_clamped")
    if target > maximum_opening:
        target = maximum_opening
        flags.append("maximum_opening_clamped")
    if not math.isclose(target, previous_opening) and time_since_change < minimum_hold_seconds:
        target = previous_opening
        flags.append("minimum_hold_rejected")
    maximum_delta = max(opening_rate_limit, 0.0) * max(elapsed_seconds, 0.0)
    delta = target - previous_opening
    if maximum_delta > 0 and abs(delta) > maximum_delta:
        target = previous_opening + math.copysign(maximum_delta, delta)
        flags.append("opening_rate_limited")
    return target, tuple(flags)


def evaluate_gate(
    *,
    width: float,
    requested_opening: float,
    actual_opening: float,
    upstream_level: float,
    downstream_level: float,
    crest_elevation: float,
    discharge_coefficient: float = 0.62,
    weir_coefficient: float = 1.7,
    maximum_flow: float | None = None,
    allow_reverse_flow: bool = False,
) -> GateHydraulicResult:
    """按关闭、自由孔流、淹没孔流和闸顶堰流计算连续稳定通量。"""

    if width <= 0 or requested_opening < 0 or actual_opening < 0:
        raise ValueError("闸门宽度和开度必须有效")
    if discharge_coefficient <= 0 or weir_coefficient <= 0:
        raise ValueError("闸门流量系数必须为正")
    flags: list[str] = []
    head_difference = upstream_level - downstream_level
    direction = 1.0
    high_level = upstream_level
    low_level = downstream_level
    if head_difference < 0:
        if not allow_reverse_flow:
            return GateHydraulicResult(
                requested_opening,
                actual_opening,
                upstream_level,
                downstream_level,
                head_difference,
                0.0,
                "reverse_blocked",
                ("reverse_flow_blocked",),
            )
        direction = -1.0
        high_level, low_level = downstream_level, upstream_level
        flags.append("reverse_flow")
    if actual_opening <= 1.0e-9:
        return GateHydraulicResult(
            requested_opening, actual_opening, upstream_level, downstream_level,
            head_difference, 0.0, "closed", tuple(flags)
        )
    upstream_head = max(high_level - crest_elevation, 0.0)
    downstream_head = max(low_level - crest_elevation, 0.0)
    if upstream_head <= 1.0e-12:
        flow = 0.0
        regime = "dry"
    elif upstream_head <= actual_opening:
        flow = weir_coefficient * width * upstream_head ** 1.5
        regime = "weir_overflow"
    elif downstream_head >= 0.67 * upstream_head:
        flow = discharge_coefficient * width * actual_opening * math.sqrt(
            2.0 * GRAVITY * max(upstream_head - downstream_head, 0.0)
        )
        regime = "submerged_orifice"
    else:
        flow = discharge_coefficient * width * actual_opening * math.sqrt(
            2.0 * GRAVITY * upstream_head
        )
        regime = "free_orifice"
    if maximum_flow is not None and flow > max(maximum_flow, 0.0):
        flow = max(maximum_flow, 0.0)
        flags.append("maximum_flow_limited")
    return GateHydraulicResult(
        requested_opening=requested_opening,
        actual_opening=actual_opening,
        upstream_level=upstream_level,
        downstream_level=downstream_level,
        head_difference=head_difference,
        flow=direction * flow,
        regime=regime,
        constraint_flags=tuple(flags),
    )


def gate_discharge(
    width: float,
    opening: float,
    upstream_level: float,
    downstream_level: float,
    bottom_elevation: float,
    discharge_coefficient: float = 0.62,
    maximum_flow: float | None = None,
) -> float:
    """保留 Phase 3 公共函数并映射到新的自由/淹没/堰流模型。"""

    return evaluate_gate(
        width=width,
        requested_opening=opening,
        actual_opening=opening,
        upstream_level=upstream_level,
        downstream_level=downstream_level,
        crest_elevation=bottom_elevation,
        discharge_coefficient=discharge_coefficient,
        maximum_flow=maximum_flow,
    ).flow
