"""解析上游流量和下游水位的定值或分段线性时间序列。"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any

from model.core.errors import HydraulicInputError
from model.core.types import RiverMesh


def _finite_number(value: Any, label: str) -> float:
    """Return one finite numeric boundary value with a domain error on failure."""

    if isinstance(value, bool):
        raise HydraulicInputError(f"{label} 必须是有限数值")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HydraulicInputError(f"{label} 必须是有限数值") from exc
    if not math.isfinite(number):
        raise HydraulicInputError(f"{label} 必须是有限数值")
    return number


@dataclass(frozen=True)
class BoundarySignal:
    """表示一种绑定到河网节点的可插值边界信号。"""

    boundary_type: str
    target_node_id: int | None
    times: tuple[float, ...]
    values: tuple[float, ...]

    def value_at(self, time_seconds: float) -> float:
        """按有限时刻返回常值或覆盖域内的分段线性插值值。"""

        query_time = _finite_number(time_seconds, "边界求值 time_seconds")
        if len(self.times) == 1:
            return self.values[0]
        if query_time < self.times[0] or query_time > self.times[-1]:
            raise HydraulicInputError(
                f"{self.boundary_type} 序列不覆盖 time_seconds={query_time}"
            )
        if query_time == self.times[0]:
            return self.values[0]
        if query_time == self.times[-1]:
            return self.values[-1]
        for index in range(1, len(self.times)):
            if query_time <= self.times[index]:
                left_time = self.times[index - 1]
                right_time = self.times[index]
                ratio = (query_time - left_time) / (right_time - left_time)
                return self.values[index - 1] + ratio * (
                    self.values[index] - self.values[index - 1]
                )
        raise HydraulicInputError(
            f"{self.boundary_type} 序列无法求值 time_seconds={query_time}"
        )


@dataclass(frozen=True)
class BoundarySet:
    """按河道保存可选的上下游边界信号。"""

    upstream_flow: dict[int, BoundarySignal]
    downstream_level: dict[int, BoundarySignal]
    by_node: dict[int, BoundarySignal]


def _parse_values(
    boundary_type: str, target_node_id: int | None, payload: Any
) -> BoundarySignal:
    """把 Phase 2 JSON 边界值转换为单调时间序列。"""

    if not isinstance(payload, Mapping):
        raise HydraulicInputError(f"边界 {boundary_type} 的 values 必须是对象")
    mode = payload.get("mode", "constant")
    if mode == "constant":
        if "value" not in payload:
            raise HydraulicInputError(f"常值边界 {boundary_type} 缺少 value")
        times = (0.0,)
        values = (
            _finite_number(payload["value"], f"常值边界 {boundary_type} value"),
        )
    elif mode == "series":
        raw_times = payload.get("times")
        raw_values = payload.get("values")
        if (
            not isinstance(raw_times, Sequence)
            or isinstance(raw_times, (str, bytes))
            or not isinstance(raw_values, Sequence)
            or isinstance(raw_values, (str, bytes))
        ):
            raise HydraulicInputError(f"序列边界 {boundary_type} 缺少 times/values")
        times = tuple(
            _finite_number(value, f"序列边界 {boundary_type} times[{index}]")
            for index, value in enumerate(raw_times)
        )
        values = tuple(
            _finite_number(value, f"序列边界 {boundary_type} values[{index}]")
            for index, value in enumerate(raw_values)
        )
        if len(times) < 2 or len(times) != len(values):
            raise HydraulicInputError(f"序列边界 {boundary_type} 时间和值数量不一致")
        if any(right <= left for left, right in zip(times, times[1:])):
            raise HydraulicInputError(f"序列边界 {boundary_type} 时间必须严格递增")
    else:
        raise HydraulicInputError(f"不支持的边界模式：{mode}")
    return BoundarySignal(boundary_type, target_node_id, times, values)


def build_boundary_set(
    snapshot: Mapping[str, Any], meshes: tuple[RiverMesh, ...]
) -> BoundarySet:
    """按目标节点绑定边界，并对 v2 正式输入拒绝重复或缺失外边界。"""

    upstream: dict[int, BoundarySignal] = {}
    downstream: dict[int, BoundarySignal] = {}
    by_node: dict[int, BoundarySignal] = {}
    boundaries = snapshot.get("boundary_conditions", [])
    if not isinstance(boundaries, list):
        raise HydraulicInputError("boundary_conditions 必须是数组")
    for item in boundaries:
        boundary_type = str(item.get("boundary_type", ""))
        if boundary_type not in {"upstream_flow", "downstream_water_level"}:
            continue
        target = item.get("target_node_id")
        target_node_id = int(target) if target is not None else None
        signal = _parse_values(boundary_type, target_node_id, item.get("values"))
        if target_node_id is not None:
            if target_node_id in by_node:
                existing = by_node[target_node_id]
                if existing.boundary_type == boundary_type:
                    raise HydraulicInputError(
                        f"节点 {target_node_id} 存在重复流量边界"
                        if boundary_type == "upstream_flow"
                        else f"节点 {target_node_id} 存在重复水位边界"
                    )
                raise HydraulicInputError(
                    f"节点 {target_node_id} 不能同时配置流量和水位边界"
                )
            by_node[target_node_id] = signal
        for mesh in meshes:
            if boundary_type == "upstream_flow" and (
                target_node_id is None or target_node_id == mesh.upstream_node_id
            ):
                if mesh.river_id in upstream:
                    raise HydraulicInputError(
                        f"河道 {mesh.river_code} 上游节点存在重复流量边界"
                    )
                upstream[mesh.river_id] = signal
            if boundary_type == "downstream_water_level" and (
                target_node_id is None or target_node_id == mesh.downstream_node_id
            ):
                if mesh.river_id in downstream:
                    raise HydraulicInputError(
                        f"河道 {mesh.river_code} 下游节点存在重复水位边界"
                    )
                downstream[mesh.river_id] = signal
    return BoundarySet(
        upstream_flow=upstream,
        downstream_level=downstream,
        by_node=by_node,
    )
