"""与求解器分离的矩形和表格化非规则断面水力几何。"""

from __future__ import annotations

import bisect
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from model.core.errors import HydraulicInputError


@runtime_checkable
class SectionGeometry(Protocol):
    """定义求解器所需的水位—面积—湿周可逆关系，单位均为 SI。"""

    geometry_type: str
    minimum_stage: float
    maximum_stage: float | None

    def area(self, stage: float) -> float: ...
    def top_width(self, stage: float) -> float: ...
    def wetted_perimeter(self, stage: float) -> float: ...
    def hydraulic_radius(self, stage: float) -> float: ...
    def stage_from_area(self, area: float) -> float: ...


@dataclass(frozen=True)
class RectangularSectionGeometry:
    """使用固定底宽和床面高程的 Phase 3 兼容断面。"""

    width: float
    bed_elevation: float
    geometry_type: str = "rectangular"
    maximum_stage: float | None = None

    def __post_init__(self) -> None:
        """拒绝无效宽度和高程，避免在求解器中产生非有限量。"""

        if not math.isfinite(self.width) or self.width <= 0:
            raise HydraulicInputError("矩形断面宽度必须为有限正数")
        if not math.isfinite(self.bed_elevation):
            raise HydraulicInputError("矩形断面床面高程必须有限")

    @property
    def minimum_stage(self) -> float:
        """返回无水断面的最低水位。"""

        return self.bed_elevation

    def area(self, stage: float) -> float:
        """返回指定水位下的过水面积（m²）。"""

        return self.width * max(stage - self.bed_elevation, 0.0)

    def top_width(self, stage: float) -> float:
        """有水时返回水面宽，干断面返回固定底宽用于稳定线性化。"""

        return self.width

    def wetted_perimeter(self, stage: float) -> float:
        """返回矩形湿周（m）。"""

        depth = max(stage - self.bed_elevation, 0.0)
        return self.width + 2.0 * depth if depth > 0 else self.width

    def hydraulic_radius(self, stage: float) -> float:
        """返回水力半径（m）。"""

        return self.area(stage) / max(self.wetted_perimeter(stage), 1.0e-12)

    def stage_from_area(self, area: float) -> float:
        """把非负过水面积反算为水位。"""

        if not math.isfinite(area) or area < 0:
            raise HydraulicInputError("过水面积必须为有限非负数")
        return self.bed_elevation + area / self.width


@dataclass(frozen=True)
class TabulatedSectionGeometry:
    """由横距—高程折线建立单调水位水力关系并分段线性插值。"""

    points: tuple[tuple[float, float], ...]
    stages: tuple[float, ...]
    areas: tuple[float, ...]
    widths: tuple[float, ...]
    perimeters: tuple[float, ...]
    geometry_type: str = "tabulated"

    @classmethod
    def from_points(
        cls,
        points: Sequence[Sequence[float]],
        *,
        vertical_step: float = 0.05,
    ) -> "TabulatedSectionGeometry":
        """校验原始轮廓并生成不外推的水力查算表。

        横距和高程单位均为米。最高水位取两侧端点中较低的岸顶，避免
        在没有延伸断面信息时无提示外推。
        """

        parsed: list[tuple[float, float]] = []
        for point in points:
            if len(point) < 2:
                raise HydraulicInputError("断面点必须为 [横距, 高程]")
            offset, elevation = float(point[0]), float(point[1])
            if not math.isfinite(offset) or not math.isfinite(elevation):
                raise HydraulicInputError("断面点不得包含 NaN 或 Inf")
            parsed.append((offset, elevation))
        parsed.sort(key=lambda item: item[0])
        if len(parsed) < 3:
            raise HydraulicInputError("表格化断面至少需要三个轮廓点")
        if any(right[0] <= left[0] for left, right in zip(parsed, parsed[1:])):
            raise HydraulicInputError("断面横距必须唯一且严格递增")
        minimum = min(item[1] for item in parsed)
        maximum = min(parsed[0][1], parsed[-1][1])
        if maximum <= minimum:
            raise HydraulicInputError("断面两岸必须高于最低河床")
        if vertical_step <= 0:
            raise HydraulicInputError("断面查算步长必须大于零")

        count = max(2, math.ceil((maximum - minimum) / vertical_step))
        stages = tuple(
            minimum + (maximum - minimum) * index / count
            for index in range(count + 1)
        )
        hydraulic = [_hydraulic_properties(tuple(parsed), stage) for stage in stages]
        areas = tuple(item[0] for item in hydraulic)
        widths = tuple(item[1] for item in hydraulic)
        perimeters = tuple(item[2] for item in hydraulic)
        if any(right <= left for left, right in zip(areas[1:], areas[2:])):
            raise HydraulicInputError("断面面积查算关系必须单调递增")
        return cls(tuple(parsed), stages, areas, widths, perimeters)

    @property
    def minimum_stage(self) -> float:
        """返回最低河床高程。"""

        return self.stages[0]

    @property
    def maximum_stage(self) -> float:
        """返回不允许无提示外推的最低岸顶高程。"""

        return self.stages[-1]

    def _at_stage(self, values: tuple[float, ...], stage: float) -> float:
        """在查算范围内对一个单调水位表执行线性插值。"""

        if not math.isfinite(stage):
            raise HydraulicInputError("水位必须有限")
        if stage < self.minimum_stage - 1.0e-12 or stage > self.maximum_stage + 1.0e-12:
            raise HydraulicInputError(
                f"水位 {stage} 超出断面查算范围 "
                f"[{self.minimum_stage}, {self.maximum_stage}]"
            )
        if stage <= self.minimum_stage:
            return values[0]
        if stage >= self.maximum_stage:
            return values[-1]
        right = bisect.bisect_left(self.stages, stage)
        left = right - 1
        ratio = (stage - self.stages[left]) / (self.stages[right] - self.stages[left])
        return values[left] + ratio * (values[right] - values[left])

    def area(self, stage: float) -> float:
        """返回过水面积（m²）。"""

        return self._at_stage(self.areas, stage)

    def top_width(self, stage: float) -> float:
        """返回水面宽（m）。"""

        return self._at_stage(self.widths, stage)

    def wetted_perimeter(self, stage: float) -> float:
        """返回湿周（m）。"""

        return self._at_stage(self.perimeters, stage)

    def hydraulic_radius(self, stage: float) -> float:
        """返回水力半径（m）。"""

        return self.area(stage) / max(self.wetted_perimeter(stage), 1.0e-12)

    def stage_from_area(self, area: float) -> float:
        """在查算范围内把面积反算为水位，禁止无提示外推。"""

        if not math.isfinite(area) or area < self.areas[0] - 1.0e-12:
            raise HydraulicInputError("过水面积必须为查算范围内的有限非负数")
        if area > self.areas[-1] + 1.0e-12:
            raise HydraulicInputError(
                f"过水面积 {area} 超出断面查算上限 {self.areas[-1]}"
            )
        if area <= self.areas[0]:
            return self.stages[0]
        if area >= self.areas[-1]:
            return self.stages[-1]
        right = bisect.bisect_left(self.areas, area)
        left = right - 1
        ratio = (area - self.areas[left]) / (self.areas[right] - self.areas[left])
        return self.stages[left] + ratio * (self.stages[right] - self.stages[left])


def _hydraulic_properties(
    points: tuple[tuple[float, float], ...], stage: float
) -> tuple[float, float, float]:
    """对折线逐段积分面积、水面宽和湿周。"""

    area = 0.0
    perimeter = 0.0
    intersections: list[float] = []
    for left, right in zip(points, points[1:]):
        dx = right[0] - left[0]
        left_depth = max(stage - left[1], 0.0)
        right_depth = max(stage - right[1], 0.0)
        if left_depth > 0 and right_depth > 0:
            area += 0.5 * (left_depth + right_depth) * dx
            perimeter += math.hypot(dx, right[1] - left[1])
        elif left_depth > 0 or right_depth > 0:
            wet = left if left_depth > 0 else right
            dry = right if left_depth > 0 else left
            ratio = (stage - wet[1]) / (dry[1] - wet[1])
            intersection_x = wet[0] + ratio * (dry[0] - wet[0])
            wet_dx = abs(intersection_x - wet[0])
            area += 0.5 * max(left_depth, right_depth) * wet_dx
            perimeter += math.hypot(wet_dx, stage - wet[1])
            intersections.append(intersection_x)
        if math.isclose(left[1], stage, abs_tol=1.0e-12):
            intersections.append(left[0])
        if math.isclose(right[1], stage, abs_tol=1.0e-12):
            intersections.append(right[0])
    submerged_x = [point[0] for point in points if point[1] < stage] + intersections
    width = max(submerged_x) - min(submerged_x) if len(submerged_x) >= 2 else 0.0
    return max(area, 0.0), max(width, 0.0), max(perimeter, 0.0)


def build_section_geometry(points_payload: Any, *, mode: str = "tabulated") -> SectionGeometry:
    """从 Phase 2 JSON 轮廓构建指定几何，并为 v1 保留矩形模式。"""

    raw = points_payload.get("points") if isinstance(points_payload, Mapping) else None
    if not isinstance(raw, Sequence):
        raise HydraulicInputError("横断面 points 必须包含点数组")
    if mode == "tabulated":
        return TabulatedSectionGeometry.from_points(raw)
    if mode == "rectangular":
        offsets = [float(point[0]) for point in raw if len(point) >= 2]
        elevations = [float(point[1]) for point in raw if len(point) >= 2]
        if len(offsets) < 2:
            raise HydraulicInputError("矩形等效断面至少需要两个点")
        return RectangularSectionGeometry(max(offsets) - min(offsets), min(elevations))
    raise HydraulicInputError(f"不支持的断面几何模式：{mode}")
