"""从 Phase 2 有向拓扑和断面网格构建可联合求解的河网。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from model.core.errors import HydraulicInputError
from model.mesh.builder import build_river_meshes
from model.network.types import JunctionNode, NetworkEdge, NetworkMesh, RiverBranch


def build_network_mesh(snapshot: Mapping[str, Any]) -> NetworkMesh:
    """校验有向图并把河道端点映射为同步计算分支。"""

    mesh_result = build_river_meshes(snapshot)
    raw_nodes = snapshot.get("nodes", [])
    raw_connections = snapshot.get("connections", [])
    if not isinstance(raw_nodes, list) or not isinstance(raw_connections, list):
        raise HydraulicInputError("河网输入必须包含 nodes 和 connections 数组")
    node_ids = {int(item["id"]) for item in raw_nodes}
    edges: set[tuple[int, int, int]] = set()
    network_edges: list[NetworkEdge] = []
    for item in raw_connections:
        start = int(item["from_node_id"])
        end = int(item["to_node_id"])
        river_id = int(item["river_id"])
        if start == end:
            raise HydraulicInputError(f"河网存在自环节点 {start}")
        if start not in node_ids or end not in node_ids:
            raise HydraulicInputError("河网连接引用不存在的节点")
        edge = (start, end, river_id)
        if edge in edges:
            raise HydraulicInputError("河网存在重复有向边")
        edges.add(edge)
        matching_segment = next(
            (
                segment
                for segment in snapshot.get("segments", [])
                if int(segment["river_id"]) == river_id
                and int(segment["upstream_node_id"]) == start
                and int(segment["downstream_node_id"]) == end
            ),
            None,
        )
        if matching_segment is None:
            raise HydraulicInputError("河网连接没有对应的河段长度")
        length = float(matching_segment["length"])
        if length <= 0:
            raise HydraulicInputError("河网河段长度必须大于零")
        network_edges.append(
            NetworkEdge(
                segment_id=int(matching_segment["id"]),
                river_id=river_id,
                upstream_node_id=start,
                downstream_node_id=end,
                length=length,
            )
        )

    branches: list[RiverBranch] = []
    incoming: dict[int, list[int]] = defaultdict(list)
    outgoing: dict[int, list[int]] = defaultdict(list)
    for mesh in mesh_result.meshes:
        if mesh.upstream_node_id is None or mesh.downstream_node_id is None:
            raise HydraulicInputError(f"河道 {mesh.river_code} 无法识别有向端点")
        if mesh.upstream_node_id not in node_ids or mesh.downstream_node_id not in node_ids:
            raise HydraulicInputError(f"河道 {mesh.river_code} 端点不属于当前数据版本")
        branches.append(
            RiverBranch(mesh, mesh.upstream_node_id, mesh.downstream_node_id)
        )
    for edge in network_edges:
        outgoing[edge.upstream_node_id].append(edge.river_id)
        incoming[edge.downstream_node_id].append(edge.river_id)

    referenced_nodes = sorted(set(incoming) | set(outgoing))
    nodes = tuple(
        JunctionNode(
            node_id=node_id,
            incoming_river_ids=tuple(sorted(set(incoming.get(node_id, [])))),
            outgoing_river_ids=tuple(sorted(set(outgoing.get(node_id, [])))),
        )
        for node_id in referenced_nodes
    )
    if not any(item.is_junction for item in nodes) and len(branches) > 1:
        raise HydraulicInputError("多河道输入没有可识别的共享汇分流节点")
    return NetworkMesh(
        branches=tuple(sorted(branches, key=lambda item: item.mesh.river_id)),
        edges=tuple(sorted(network_edges, key=lambda item: item.segment_id)),
        nodes=nodes,
        diagnostics={
            "branch_count": len(branches),
            "node_count": len(nodes),
            "junction_count": sum(item.is_junction for item in nodes),
            "external_source_count": sum(item.is_external_source for item in nodes),
            "external_sink_count": sum(item.is_external_sink for item in nodes),
            "skipped_rivers": list(mesh_result.skipped_rivers),
            "topology_method": "directed shared-node graph",
        },
    )
