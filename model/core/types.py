"""与框架无关的一维河道网格、配置和结果数据结构。"""

from dataclasses import dataclass, field
from typing import Any

from model.geometry.sections import SectionGeometry


@dataclass(frozen=True)
class Node:
    """Represent one one-dimensional computational node at a section station."""

    index: int
    station: float


@dataclass(frozen=True)
class Element:
    """Connect two ordered computational nodes with a metre-based length."""

    index: int
    upstream_node: int
    downstream_node: int
    length: float


@dataclass(frozen=True)
class Section:
    """表示一个具有可逆水力几何关系的计算断面。"""

    id: int
    code: str
    river_id: int
    river_code: str
    station: float
    width: float
    bed_elevation: float
    roughness: float
    geometry: SectionGeometry


@dataclass(frozen=True)
class RiverMesh:
    """保存单条河道的有序断面和相邻计算距离。"""

    river_id: int
    river_code: str
    nodes: tuple[Node, ...]
    elements: tuple[Element, ...]
    sections: tuple[Section, ...]
    element_lengths: tuple[float, ...]
    upstream_node_id: int | None = None
    downstream_node_id: int | None = None


@dataclass(frozen=True)
class SolverConfig:
    """定义一次求解的时间、初始条件和稳定性控制。"""

    duration_seconds: float = 3600.0
    requested_time_step: float = 60.0
    output_interval: float = 300.0
    cfl_number: float = 0.75
    initial_water_level: float | None = None
    initial_flow: float = 0.0
    minimum_depth: float = 0.05
    maximum_steps: int = 100_000


@dataclass
class SectionSeries:
    """保存一个断面的水位、流量和流速时序。"""

    section: Section
    time: list[float] = field(default_factory=list)
    water_level: list[float] = field(default_factory=list)
    flow: list[float] = field(default_factory=list)
    velocity: list[float] = field(default_factory=list)

    def append(self, time_seconds: float, area: float, discharge: float) -> None:
        """把守恒变量转换为水位和流速后追加一个时间片。"""

        stage = self.section.geometry.stage_from_area(max(area, 0.0))
        self.time.append(round(time_seconds, 6))
        self.water_level.append(stage)
        self.flow.append(discharge)
        self.velocity.append(discharge / max(area, 1e-12))

    def to_dict(self) -> dict[str, Any]:
        """生成后端可持久化和 JSON 序列化的结果映射。"""

        return {
            "section_id": self.section.id,
            "section_code": self.section.code,
            "river_id": self.section.river_id,
            "river_code": self.section.river_code,
            "station": self.section.station,
            "time": self.time,
            "water_level": self.water_level,
            "flow": self.flow,
            "velocity": self.velocity,
        }


@dataclass(frozen=True)
class EngineResult:
    """聚合 v1/v2 断面、节点、结构物、调度和来源结果。"""

    series: tuple[SectionSeries, ...]
    diagnostics: dict[str, Any]
    schema_version: str = "dayu.hydraulic-result.v1"
    node_series: tuple[dict[str, Any], ...] = ()
    structure_series: tuple[dict[str, Any], ...] = ()
    dispatch_events: tuple[dict[str, Any], ...] = ()
    water_balance: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """输出稳定的纯 JSON 结果契约。"""

        if self.schema_version == "dayu.hydraulic-result.v1":
            return {
                "schema_version": self.schema_version,
                "series": [item.to_dict() for item in self.series],
                "diagnostics": self.diagnostics,
            }
        return {
            "schema_version": self.schema_version,
            "section_series": [item.to_dict() for item in self.series],
            "node_series": list(self.node_series),
            "structure_series": list(self.structure_series),
            "dispatch_events": list(self.dispatch_events),
            "water_balance": self.water_balance or {},
            "metrics": self.metrics or {},
            "diagnostics": self.diagnostics,
            "provenance": self.provenance or {},
        }
