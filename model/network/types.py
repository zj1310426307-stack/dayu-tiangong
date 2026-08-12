"""与数据库无关的河网分支、节点和联合计算结果类型。"""

from dataclasses import dataclass
from typing import Any

from model.core.types import RiverMesh, SectionSeries


@dataclass(frozen=True)
class RiverBranch:
    """把一条计算河道映射为具有明确起止拓扑节点的分支。"""

    mesh: RiverMesh
    upstream_node_id: int
    downstream_node_id: int


@dataclass(frozen=True)
class NetworkEdge:
    """表示拓扑图中一个具有米制长度的有向计算河段。"""

    segment_id: int
    river_id: int
    upstream_node_id: int
    downstream_node_id: int
    length: float


@dataclass(frozen=True)
class JunctionNode:
    """保存一个拓扑节点连接的入流与出流分支 ID。"""

    node_id: int
    incoming_river_ids: tuple[int, ...]
    outgoing_river_ids: tuple[int, ...]

    @property
    def is_external_source(self) -> bool:
        """没有入流但有出流的节点是外部入口。"""

        return not self.incoming_river_ids and bool(self.outgoing_river_ids)

    @property
    def is_external_sink(self) -> bool:
        """有入流但没有出流的节点是外部出口。"""

        return bool(self.incoming_river_ids) and not self.outgoing_river_ids

    @property
    def is_junction(self) -> bool:
        """多于两个分支连接，或同时存在入流出流时视为内部联合节点。"""

        return (
            len(self.incoming_river_ids) + len(self.outgoing_river_ids) > 2
            or bool(self.incoming_river_ids and self.outgoing_river_ids)
        )


@dataclass(frozen=True)
class NetworkMesh:
    """保存有向分支集合、节点连接和拓扑诊断。"""

    branches: tuple[RiverBranch, ...]
    edges: tuple[NetworkEdge, ...]
    nodes: tuple[JunctionNode, ...]
    diagnostics: dict[str, Any]


@dataclass(frozen=True)
class NetworkSolveResult:
    """保存断面、节点时序及全网诊断。"""

    series: tuple[SectionSeries, ...]
    node_series: tuple[dict[str, Any], ...]
    structure_series: tuple[dict[str, Any], ...]
    dispatch_events: tuple[dict[str, Any], ...]
    diagnostics: dict[str, Any]
