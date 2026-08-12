"""泵站曲线、扬程保护、启停约束、流量转输和能耗模型。"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

WATER_DENSITY = 1000.0
GRAVITY = 9.81


@dataclass(frozen=True)
class PumpHydraulicResult:
    """保存泵站实际机组、流量、功率、能耗和约束审计。"""

    requested_units: int
    actual_units: int
    flow: float
    head: float
    efficiency: float
    power_kw: float
    energy_kwh: float
    regime: str
    constraint_flags: tuple[str, ...]


@dataclass
class PumpControlState:
    """保存模拟内部启停状态，绝不写回静态资产表。"""

    running_units: int = 0
    last_change_time: float = 0.0
    starts: int = 0
    runtime_seconds: float = 0.0
    stop_seconds: float = 1.0e12
    energy_kwh: float = 0.0


def interpolate_curve(
    points: list[list[float]] | tuple[tuple[float, float], ...], x: float
) -> float:
    """在 Q-H 或 Q-η 曲线范围内分段线性插值，禁止无提示外推。"""

    ordered = sorted((float(item[0]), float(item[1])) for item in points)
    if len(ordered) < 2 or any(right[0] <= left[0] for left, right in zip(ordered, ordered[1:])):
        raise ValueError("泵站曲线至少需要两个横坐标严格递增的点")
    xs = [item[0] for item in ordered]
    if x < xs[0] or x > xs[-1]:
        raise ValueError(f"曲线查询值 {x} 超出范围 [{xs[0]}, {xs[-1]}]")
    if x == xs[0]:
        return ordered[0][1]
    if x == xs[-1]:
        return ordered[-1][1]
    right = bisect.bisect_left(xs, x)
    left = right - 1
    ratio = (x - xs[left]) / (xs[right] - xs[left])
    return ordered[left][1] + ratio * (ordered[right][1] - ordered[left][1])


def evaluate_pump(
    *,
    requested_units: int,
    target_flow: float | None,
    design_flow_per_unit: float,
    head: float,
    elapsed_seconds: float,
    state: PumpControlState,
    availability: str,
    minimum_running_units: int,
    maximum_running_units: int,
    minimum_run_seconds: float,
    minimum_stop_seconds: float,
    maximum_starts_per_run: int,
    minimum_operating_head: float,
    maximum_operating_head: float,
    efficiency_curve: list[list[float]],
    intake_depth: float | None = None,
    minimum_intake_depth: float = 0.05,
) -> PumpHydraulicResult:
    """应用泵站设备约束并计算质量转输、瞬时功率和时间步能耗。"""

    flags: list[str] = []
    units = int(round(requested_units))
    if availability != "online":
        units = 0
        flags.extend((f"asset_{availability}", "command_rejected"))
    if units > 0 and units < minimum_running_units:
        units = minimum_running_units
        flags.append("minimum_units_clamped")
    if units > maximum_running_units:
        units = maximum_running_units
        flags.append("maximum_units_clamped")
    starting = state.running_units == 0 and units > 0
    stopping = state.running_units > 0 and units == 0
    if starting and state.stop_seconds < minimum_stop_seconds:
        units = 0
        flags.append("minimum_stop_rejected")
    if starting and state.starts >= maximum_starts_per_run:
        units = 0
        flags.append("maximum_starts_rejected")
    if stopping and state.runtime_seconds < minimum_run_seconds:
        units = state.running_units
        flags.append("minimum_run_rejected")
    if units > 0 and not minimum_operating_head <= head <= maximum_operating_head:
        units = 0
        flags.append("head_out_of_range")
    if units > 0 and intake_depth is not None and intake_depth < minimum_intake_depth:
        units = 0
        flags.append("insufficient_intake_depth")

    flow = units * design_flow_per_unit
    if target_flow is not None and units > 0:
        flow = min(max(float(target_flow), 0.0), flow)
        if flow < float(target_flow):
            flags.append("target_flow_limited")
    ratio = flow / max(units * design_flow_per_unit, 1.0e-12) if units else 0.0
    efficiency = interpolate_curve(efficiency_curve, ratio) if units else 0.0
    if units and efficiency <= 0:
        units = 0
        flow = 0.0
        flags.append("invalid_efficiency")
    power_kw = WATER_DENSITY * GRAVITY * flow * head / max(efficiency, 1.0e-12) / 1000.0 if units else 0.0
    energy_kwh = power_kw * max(elapsed_seconds, 0.0) / 3600.0
    return PumpHydraulicResult(
        requested_units=requested_units,
        actual_units=units,
        flow=flow,
        head=head,
        efficiency=efficiency,
        power_kw=power_kw,
        energy_kwh=energy_kwh,
        regime="running" if units else "stopped",
        constraint_flags=tuple(flags),
    )


def pump_discharge(design_flow: float, enabled: bool, status: str = "online") -> float:
    """保留 Phase 3 启停—设计流量兼容函数。"""

    if design_flow < 0:
        raise ValueError("泵站设计流量不能为负")
    return design_flow if enabled and status == "online" else 0.0
