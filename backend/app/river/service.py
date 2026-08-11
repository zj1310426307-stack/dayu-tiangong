"""河道 CRUD、几何序列化与拓扑自动生成业务服务。"""

import math
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.common.spatial import geometry_expression, geometry_json
from app.gis.models import River, RiverConnection, RiverNode, RiverSegment
from app.river.schemas import (
    RiverCreate,
    RiverListResponse,
    RiverRecord,
    RiverUpdate,
    TopologyResponse,
)


def _record(session: Session, river: River) -> RiverRecord:
    """把 ORM 河道转换为稳定响应契约。"""

    return RiverRecord(
        id=river.id,
        dataset_version_id=river.dataset_version_id,
        name=river.name,
        code=river.code,
        length=river.length,
        level=river.level,
        status=river.status,
        description=river.description,
        geometry=geometry_json(session, river.geometry),
        created_time=river.created_time,
    )


def list_rivers(
    session: Session,
    dataset_version_id: int | None,
    search: str | None,
    limit: int,
    offset: int,
) -> RiverListResponse:
    """按数据版本和关键词分页查询河道。"""

    conditions: list[Any] = []
    if dataset_version_id is not None:
        conditions.append(River.dataset_version_id == dataset_version_id)
    if search:
        token = f"%{search.strip()}%"
        conditions.append(or_(River.name.ilike(token), River.code.ilike(token)))
    total = session.scalar(select(func.count(River.id)).where(*conditions)) or 0
    rivers = session.scalars(
        select(River).where(*conditions).order_by(River.id).limit(limit).offset(offset)
    ).all()
    return RiverListResponse(
        items=[_record(session, river) for river in rivers],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_river(session: Session, river_id: int) -> RiverRecord | None:
    """按主键读取河道。"""

    river = session.get(River, river_id)
    return _record(session, river) if river else None


def create_river(session: Session, payload: RiverCreate) -> RiverRecord:
    """新增河道并刷新数据库生成字段。"""

    values = payload.model_dump(exclude={"geometry"})
    river = River(**values, geometry=geometry_expression(payload.geometry, "LineString"))
    session.add(river)
    session.flush()
    return _record(session, river)


def update_river(session: Session, river: River, payload: RiverUpdate) -> RiverRecord:
    """局部更新河道，未提供字段保持不变。"""

    values = payload.model_dump(exclude_unset=True)
    geometry = values.pop("geometry", None)
    for key, value in values.items():
        setattr(river, key, value)
    if geometry is not None:
        river.geometry = geometry_expression(geometry, "LineString")
    session.flush()
    return _record(session, river)


def delete_river(session: Session, river: River) -> None:
    """删除河道；数据库负责级联断面与拓扑、限制关联建筑物。"""

    session.delete(river)
    session.flush()


def _endpoint_key(longitude: float, latitude: float, tolerance: float) -> tuple[int, int]:
    """按容差量化端点，使共享坐标生成同一拓扑节点。"""

    return round(longitude / tolerance), round(latitude / tolerance)


def generate_topology(
    session: Session, dataset_version_id: int, tolerance: float
) -> TopologyResponse:
    """从版本内每条 LineString 的首尾坐标幂等重建节点、河段和连接。"""

    session.execute(
        delete(RiverConnection).where(RiverConnection.dataset_version_id == dataset_version_id)
    )
    session.execute(
        delete(RiverSegment).where(RiverSegment.dataset_version_id == dataset_version_id)
    )
    session.execute(delete(RiverNode).where(RiverNode.dataset_version_id == dataset_version_id))

    rows = session.execute(
        select(River, func.ST_AsGeoJSON(River.geometry, 8)).where(
            River.dataset_version_id == dataset_version_id
        ).order_by(River.id)
    ).all()
    import json

    decoded_rows = [(river, json.loads(raw_geometry)["coordinates"]) for river, raw_geometry in rows]
    coordinate_use: dict[tuple[int, int], int] = {}
    for _, coordinates in decoded_rows:
        for longitude, latitude in coordinates:
            key = _endpoint_key(float(longitude), float(latitude), tolerance)
            coordinate_use[key] = coordinate_use.get(key, 0) + 1

    node_by_key: dict[tuple[int, int], RiverNode] = {}
    for river, coordinates in decoded_rows:
        nodes: list[RiverNode] = []
        for coordinate_index, position in enumerate(coordinates):
            longitude, latitude = float(position[0]), float(position[1])
            key = _endpoint_key(longitude, latitude, tolerance)
            node = node_by_key.get(key)
            if node is None:
                if coordinate_use[key] > 1:
                    node_type = "confluence"
                elif coordinate_index == 0:
                    node_type = "start"
                elif coordinate_index == len(coordinates) - 1:
                    node_type = "end"
                else:
                    node_type = "bifurcation"
                node = RiverNode(
                    dataset_version_id=dataset_version_id,
                    node_code=f"V{dataset_version_id}-N{len(node_by_key) + 1:04d}",
                    node_type=node_type,
                    longitude=longitude,
                    latitude=latitude,
                    geometry=geometry_expression(
                        {"type": "Point", "coordinates": [longitude, latitude]}, "Point"
                    ),
                )
                session.add(node)
                session.flush()
                node_by_key[key] = node
            elif coordinate_use[key] > 1:
                node.node_type = "confluence"
            nodes.append(node)

        edge_lengths = [
            math.hypot(
                float(coordinates[index + 1][0]) - float(coordinates[index][0]),
                float(coordinates[index + 1][1]) - float(coordinates[index][1]),
            )
            for index in range(len(coordinates) - 1)
        ]
        total_edge_length = sum(edge_lengths) or 1.0
        for edge_index, (upstream, downstream) in enumerate(zip(nodes, nodes[1:]), start=1):
            edge_coordinates = [coordinates[edge_index - 1], coordinates[edge_index]]
            segment = RiverSegment(
                dataset_version_id=dataset_version_id,
                river_id=river.id,
                segment_code=f"{river.code}-S{edge_index:02d}",
                upstream_node_id=upstream.id,
                downstream_node_id=downstream.id,
                length=river.length * edge_lengths[edge_index - 1] / total_edge_length,
                geometry=geometry_expression(
                    {"type": "LineString", "coordinates": edge_coordinates}, "LineString"
                ),
            )
            session.add(segment)
            session.add(
                RiverConnection(
                    dataset_version_id=dataset_version_id,
                    from_node_id=upstream.id,
                    to_node_id=downstream.id,
                    river_id=river.id,
                )
            )
    session.flush()
    return get_topology(session, dataset_version_id)


def get_topology(session: Session, dataset_version_id: int) -> TopologyResponse:
    """读取指定版本的节点、河段和连接。"""

    nodes = session.scalars(
        select(RiverNode).where(RiverNode.dataset_version_id == dataset_version_id).order_by(RiverNode.id)
    ).all()
    segments = session.scalars(
        select(RiverSegment).where(RiverSegment.dataset_version_id == dataset_version_id).order_by(RiverSegment.id)
    ).all()
    connections = session.scalars(
        select(RiverConnection).where(RiverConnection.dataset_version_id == dataset_version_id).order_by(RiverConnection.id)
    ).all()
    return TopologyResponse(
        dataset_version_id=dataset_version_id,
        nodes=[
            {
                "id": node.id,
                "dataset_version_id": node.dataset_version_id,
                "node_code": node.node_code,
                "node_type": node.node_type,
                "longitude": node.longitude,
                "latitude": node.latitude,
                "geometry": geometry_json(session, node.geometry),
            }
            for node in nodes
        ],
        segments=[
            {
                "id": segment.id,
                "dataset_version_id": segment.dataset_version_id,
                "river_id": segment.river_id,
                "segment_code": segment.segment_code,
                "upstream_node_id": segment.upstream_node_id,
                "downstream_node_id": segment.downstream_node_id,
                "length": segment.length,
                "geometry": geometry_json(session, segment.geometry),
            }
            for segment in segments
        ],
        connections=[
            {
                "id": connection.id,
                "dataset_version_id": connection.dataset_version_id,
                "from_node_id": connection.from_node_id,
                "to_node_id": connection.to_node_id,
                "river_id": connection.river_id,
            }
            for connection in connections
        ],
    )
