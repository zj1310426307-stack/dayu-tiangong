"""从版本化河道和横断面快照构建矩形等效计算网格。"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from model.core.errors import HydraulicInputError
from model.core.types import Element, Node, RiverMesh, Section
from model.geometry import build_section_geometry


@dataclass(frozen=True)
class MeshBuildResult:
    """返回可计算河网及因断面不足而跳过的河道代码。"""

    meshes: tuple[RiverMesh, ...]
    skipped_rivers: tuple[str, ...]


def _river_endpoint_ids(segments: list[Mapping[str, Any]]) -> tuple[int | None, int | None]:
    """根据有向河段集合识别单条河道的上下游端点。"""

    upstream_ids = {int(item["upstream_node_id"]) for item in segments}
    downstream_ids = {int(item["downstream_node_id"]) for item in segments}
    starts = sorted(upstream_ids - downstream_ids)
    ends = sorted(downstream_ids - upstream_ids)
    return (starts[0] if starts else None, ends[0] if ends else None)


def build_river_meshes(snapshot: Mapping[str, Any]) -> MeshBuildResult:
    """把 `dayu.model-input.v1` 快照转换为按河道分组的计算网格。"""

    schema_version = snapshot.get("schema_version")
    if schema_version not in {"dayu.model-input.v1", "dayu.model-input.v2"}:
        raise HydraulicInputError("仅支持 dayu.model-input.v1/v2 模型输入快照")
    rivers = snapshot.get("rivers")
    sections = snapshot.get("cross_sections")
    segments = snapshot.get("segments")
    if not isinstance(rivers, list) or not isinstance(sections, list) or not isinstance(segments, list):
        raise HydraulicInputError("模型输入必须包含河道、河段和横断面数组")

    rivers_by_id = {
        int(item["id"]): item for item in rivers if item.get("status", "active") == "active"
    }
    grouped_sections: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    grouped_segments: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for item in sections:
        grouped_sections[int(item["river_id"])].append(item)
    for item in segments:
        grouped_segments[int(item["river_id"])].append(item)

    meshes: list[RiverMesh] = []
    skipped: list[str] = []
    for river_id, river in sorted(rivers_by_id.items()):
        river_code = str(river.get("code", river_id))
        ordered_rows = sorted(
            grouped_sections.get(river_id, []), key=lambda item: float(item["station"])
        )
        if len(ordered_rows) < 3:
            skipped.append(river_code)
            continue
        mesh_sections_list: list[Section] = []
        for item in ordered_rows:
            mode = str(
                item.get(
                    "geometry_type",
                    "tabulated" if schema_version == "dayu.model-input.v2" else "rectangular",
                )
            )
            geometry = build_section_geometry(item["points"], mode=mode)
            reference_stage = geometry.minimum_stage + 0.05
            mesh_sections_list.append(
                Section(
                    id=int(item["id"]),
                    code=str(item["section_code"]),
                    river_id=river_id,
                    river_code=river_code,
                    station=float(item["station"]),
                    width=max(geometry.top_width(reference_stage), 1.0e-6),
                    bed_elevation=geometry.minimum_stage,
                    roughness=float(item["roughness"]),
                    geometry=geometry,
                )
            )
        mesh_sections = tuple(mesh_sections_list)
        element_lengths = tuple(
            downstream.station - upstream.station
            for upstream, downstream in zip(mesh_sections, mesh_sections[1:])
        )
        if any(length <= 0 for length in element_lengths):
            raise HydraulicInputError(f"河道 {river_code} 的断面桩号必须严格递增")
        nodes = tuple(
            Node(index=index, station=section.station)
            for index, section in enumerate(mesh_sections)
        )
        elements = tuple(
            Element(
                index=index,
                upstream_node=index,
                downstream_node=index + 1,
                length=length,
            )
            for index, length in enumerate(element_lengths)
        )
        upstream_node_id, downstream_node_id = _river_endpoint_ids(
            grouped_segments.get(river_id, [])
        )
        meshes.append(
            RiverMesh(
                river_id=river_id,
                river_code=river_code,
                nodes=nodes,
                elements=elements,
                sections=mesh_sections,
                element_lengths=element_lengths,
                upstream_node_id=upstream_node_id,
                downstream_node_id=downstream_node_id,
            )
        )

    if not meshes:
        raise HydraulicInputError("没有至少包含三个物理断面的可计算河道")
    return MeshBuildResult(meshes=tuple(meshes), skipped_rivers=tuple(skipped))
