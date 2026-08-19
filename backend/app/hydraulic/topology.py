"""Deterministic metre-based hydraulic topology construction and branch actions."""

from __future__ import annotations

import hashlib
from collections import defaultdict

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from app.dataset.lifecycle import assert_dataset_version_mutable
from app.gis.models import (
    CrossSection, River, RiverConnection, RiverNode, RiverSegment,
)
from app.hydraulic.models import (
    HydraulicBranch, HydraulicBranchVertex, HydraulicCrossSection, HydraulicNetwork,
    HydraulicNode, HydraulicReach,
)
from app.hydraulic.schemas import HydraulicBranchActionRecord, HydraulicIssue, HydraulicTopologyReport


def _srid(network: HydraulicNetwork) -> int:
    """Return the confirmed projected engineering SRID or fail closed."""

    if not network.engineering_crs or not network.engineering_crs.startswith("EPSG:"):
        raise ValueError("Network engineering CRS is not confirmed")
    value = int(network.engineering_crs.split(":", 1)[1])
    if value in {4326, 4490}:
        raise ValueError("Topology requires a projected metre-based engineering CRS")
    return value


def _node_code(key: tuple[int, int]) -> str:
    """Create a stable code from the snapped engineering-grid key."""

    digest = hashlib.sha256(f"{key[0]}:{key[1]}".encode()).hexdigest()[:14].upper()
    return f"N-{digest}"


def _sync_legacy_topology(
    session: Session,
    network: HydraulicNetwork,
    branches: list[HydraulicBranch],
) -> None:
    """Project the authoritative hydraulic graph into the public GIS compatibility tables."""

    river_ids = [branch.legacy_river_id for branch in branches if branch.legacy_river_id]
    if not river_ids:
        return

    session.execute(delete(RiverConnection).where(RiverConnection.river_id.in_(river_ids)))
    session.execute(delete(RiverSegment).where(RiverSegment.river_id.in_(river_ids)))
    compatibility_prefix = f"HYD-{network.id}-"
    session.execute(delete(RiverNode).where(
        RiverNode.dataset_version_id == network.dataset_version_id,
        RiverNode.node_code.like(f"{compatibility_prefix}%"),
    ))
    session.flush()

    hydraulic_nodes = session.scalars(select(HydraulicNode).where(
        HydraulicNode.network_id == network.id
    ).order_by(HydraulicNode.id)).all()
    incoming: dict[int, int] = defaultdict(int)
    outgoing: dict[int, int] = defaultdict(int)
    for branch in branches:
        if branch.upstream_node_id is not None:
            outgoing[branch.upstream_node_id] += 1
        if branch.downstream_node_id is not None:
            incoming[branch.downstream_node_id] += 1

    coordinates = {
        int(node_id): (float(longitude), float(latitude))
        for node_id, longitude, latitude in session.execute(select(
            HydraulicNode.id,
            func.ST_X(HydraulicNode.geometry),
            func.ST_Y(HydraulicNode.geometry),
        ).where(HydraulicNode.network_id == network.id)).all()
    }
    legacy_nodes: dict[int, RiverNode] = {}
    for node in hydraulic_nodes:
        in_degree, out_degree = incoming[node.id], outgoing[node.id]
        if in_degree == 0 and out_degree > 0:
            node_type = "start"
        elif out_degree == 0 and in_degree > 0:
            node_type = "end"
        elif out_degree > 1:
            node_type = "bifurcation"
        else:
            node_type = "confluence"
        longitude, latitude = coordinates[node.id]
        legacy_node = RiverNode(
            dataset_version_id=network.dataset_version_id,
            node_code=f"{compatibility_prefix}{node.node_code}",
            node_type=node_type,
            longitude=longitude,
            latitude=latitude,
            geometry=node.geometry,
        )
        session.add(legacy_node)
        legacy_nodes[node.id] = legacy_node
    session.flush()

    for branch in branches:
        if (
            branch.legacy_river_id is None
            or branch.upstream_node_id not in legacy_nodes
            or branch.downstream_node_id not in legacy_nodes
        ):
            continue
        upstream = legacy_nodes[branch.upstream_node_id]
        downstream = legacy_nodes[branch.downstream_node_id]
        session.add(RiverSegment(
            dataset_version_id=network.dataset_version_id,
            river_id=branch.legacy_river_id,
            segment_code=f"HYD-{network.id}-{branch.branch_code}",
            upstream_node_id=upstream.id,
            downstream_node_id=downstream.id,
            length=branch.length_m,
            geometry=branch.geometry,
        ))
        session.add(RiverConnection(
            dataset_version_id=network.dataset_version_id,
            from_node_id=upstream.id,
            to_node_id=downstream.id,
            river_id=branch.legacy_river_id,
        ))


def build_topology(
    session: Session, network_id: int, snap_tolerance_m: float, minimum_reach_length_m: float
) -> HydraulicTopologyReport:
    """Create endpoint/intersection nodes and ordered reaches in the engineering CRS."""

    network = session.get(HydraulicNetwork, network_id)
    if network is None:
        raise ValueError("Hydraulic network does not exist")
    assert_dataset_version_mutable(session, network.dataset_version_id)
    engineering_srid = _srid(network)
    branches = session.scalars(select(HydraulicBranch).where(
        HydraulicBranch.network_id == network.id
    ).order_by(HydraulicBranch.id)).all()
    if not branches:
        raise ValueError("Hydraulic network has no branches")

    candidates: dict[int, list[tuple[float, tuple[int, int], float, float]]] = defaultdict(list)
    memberships: dict[tuple[int, int], set[int]] = defaultdict(set)
    issues: list[HydraulicIssue] = []

    endpoint_rows = session.execute(text("""
        SELECT id,
               ST_X(ST_StartPoint(ST_Transform(centerline, :srid))) AS sx,
               ST_Y(ST_StartPoint(ST_Transform(centerline, :srid))) AS sy,
               ST_X(ST_EndPoint(ST_Transform(centerline, :srid))) AS ex,
               ST_Y(ST_EndPoint(ST_Transform(centerline, :srid))) AS ey
          FROM hydraulic.branch WHERE network_id = :network_id ORDER BY id
    """), {"srid": engineering_srid, "network_id": network.id}).all()
    for branch_id, sx, sy, ex, ey in endpoint_rows:
        for fraction, x, y in ((0.0, float(sx), float(sy)), (1.0, float(ex), float(ey))):
            key = (round(x / snap_tolerance_m), round(y / snap_tolerance_m))
            candidates[int(branch_id)].append((fraction, key, x, y))
            memberships[key].add(int(branch_id))

    intersection_rows = session.execute(text("""
        WITH lines AS (
          SELECT id, ST_Transform(centerline, :srid) AS g
            FROM hydraulic.branch WHERE network_id = :network_id
        ), points AS (
          SELECT a.id AS a_id, b.id AS b_id,
                 (ST_Dump(ST_CollectionExtract(ST_Intersection(a.g, b.g), 1))).geom AS p,
                 a.g AS a_g, b.g AS b_g
            FROM lines a JOIN lines b ON a.id < b.id
           WHERE ST_Intersects(a.g, b.g)
        )
        SELECT a_id, b_id, ST_X(p), ST_Y(p),
               ST_LineLocatePoint(a_g, p), ST_LineLocatePoint(b_g, p)
          FROM points ORDER BY a_id, b_id, ST_X(p), ST_Y(p)
    """), {"srid": engineering_srid, "network_id": network.id}).all()
    for a_id, b_id, x, y, a_fraction, b_fraction in intersection_rows:
        key = (round(float(x) / snap_tolerance_m), round(float(y) / snap_tolerance_m))
        candidates[int(a_id)].append((float(a_fraction), key, float(x), float(y)))
        candidates[int(b_id)].append((float(b_fraction), key, float(x), float(y)))
        memberships[key].update((int(a_id), int(b_id)))

    overlap_rows = session.execute(text("""
        WITH lines AS (
          SELECT id, ST_Transform(centerline, :srid) AS g
            FROM hydraulic.branch WHERE network_id = :network_id
        )
        SELECT a.id, b.id
          FROM lines a JOIN lines b ON a.id < b.id
         WHERE ST_Intersects(a.g, b.g)
           AND ST_Dimension(ST_Intersection(a.g, b.g)) = 1
         ORDER BY a.id, b.id
    """), {"srid": engineering_srid, "network_id": network.id}).all()
    for a_id, b_id in overlap_rows:
        issues.append(HydraulicIssue(
            severity="error", code="OVERLAPPING_BRANCHES",
            message="河段中心线存在重叠区间，无法确定唯一拓扑分段",
            entity_type="branch", entity_ref=f"{a_id},{b_id}",
        ))

    session.execute(HydraulicBranch.__table__.update().where(
        HydraulicBranch.network_id == network.id
    ).values(upstream_node_id=None, downstream_node_id=None))
    branch_ids = [branch.id for branch in branches]
    session.execute(delete(HydraulicReach).where(HydraulicReach.branch_id.in_(branch_ids)))
    session.execute(delete(HydraulicNode).where(HydraulicNode.network_id == network.id))
    session.flush()

    nodes: dict[tuple[int, int], HydraulicNode] = {}
    for key in sorted(memberships):
        x, y = key[0] * snap_tolerance_m, key[1] * snap_tolerance_m
        node = HydraulicNode(
            dataset_version_id=network.dataset_version_id, network_id=network.id,
            node_code=_node_code(key), node_name=None,
            node_type="junction" if len(memberships[key]) > 1 else "boundary",
            geometry=func.ST_Transform(func.ST_SetSRID(func.ST_MakePoint(x, y), engineering_srid), 4490),
            metadata_json={"engineering_x": x, "engineering_y": y, "snap_tolerance_m": snap_tolerance_m},
        )
        session.add(node)
        nodes[key] = node
    session.flush()

    adjacency: dict[int, set[int]] = defaultdict(set)
    edge_keys: set[tuple[int, int]] = set()
    reach_count = 0
    for branch in branches:
        by_key: dict[tuple[int, int], tuple[float, tuple[int, int], float, float]] = {}
        for value in sorted(candidates[branch.id], key=lambda item: item[0]):
            prior = by_key.get(value[1])
            if prior is None or value[0] < prior[0]:
                by_key[value[1]] = value
        ordered = sorted(by_key.values(), key=lambda item: item[0])
        if len(ordered) < 2:
            issues.append(HydraulicIssue(
                severity="error", code="BRANCH_ENDPOINT_MISSING", message="河段无法形成两个不同拓扑节点",
                entity_type="branch", entity_ref=str(branch.id),
            ))
            continue
        branch.upstream_node_id = nodes[ordered[0][1]].id
        branch.downstream_node_id = nodes[ordered[-1][1]].id
        if branch.upstream_node_id == branch.downstream_node_id:
            issues.append(HydraulicIssue(
                severity="error", code="SELF_LOOP", message="河段首尾吸附到同一节点",
                entity_type="branch", entity_ref=str(branch.id),
            ))
            continue
        for index, (left, right) in enumerate(zip(ordered, ordered[1:]), start=1):
            start_fraction, end_fraction = left[0], right[0]
            if end_fraction <= start_fraction:
                continue
            upstream, downstream = nodes[left[1]], nodes[right[1]]
            length_m = float(session.scalar(select(func.ST_Length(func.ST_LineSubstring(
                func.ST_Transform(branch.geometry, engineering_srid), start_fraction, end_fraction
            )))) or 0)
            start_chainage = branch.start_chainage + (branch.end_chainage - branch.start_chainage) * start_fraction
            end_chainage = branch.start_chainage + (branch.end_chainage - branch.start_chainage) * end_fraction
            if length_m < minimum_reach_length_m:
                issues.append(HydraulicIssue(
                    severity="error", code="SHORT_REACH", message="拓扑分段短于最小 Reach 长度",
                    entity_type="branch", entity_ref=str(branch.id),
                    context={"length_m": length_m, "minimum_reach_length_m": minimum_reach_length_m},
                ))
                continue
            edge_key = (upstream.id, downstream.id)
            if edge_key in edge_keys:
                issues.append(HydraulicIssue(
                    severity="warning", code="DUPLICATE_EDGE", message="存在同向重复节点连接",
                    entity_type="branch", entity_ref=str(branch.id),
                ))
            edge_keys.add(edge_key)
            adjacency[upstream.id].add(downstream.id)
            adjacency[downstream.id].add(upstream.id)
            session.add(HydraulicReach(
                dataset_version_id=network.dataset_version_id, branch_id=branch.id,
                reach_code=f"{branch.branch_code}-R{index:03d}", reach_type="channel",
                start_chainage_m=start_chainage, end_chainage_m=end_chainage,
                upstream_node_id=upstream.id, downstream_node_id=downstream.id,
                length_m=length_m,
                geometry=func.ST_Transform(func.ST_LineSubstring(
                    func.ST_Transform(branch.geometry, engineering_srid), start_fraction, end_fraction
                ), 4490),
                parameter_json={"start_fraction": start_fraction, "end_fraction": end_fraction},
            ))
            reach_count += 1

    node_ids = {node.id for node in nodes.values()}
    unseen = set(node_ids)
    components = 0
    while unseen:
        components += 1
        stack = [unseen.pop()]
        while stack:
            current = stack.pop()
            neighbours = adjacency[current] & unseen
            unseen -= neighbours
            stack.extend(neighbours)
    if components > 1:
        issues.append(HydraulicIssue(
            severity="warning", code="DISCONNECTED_COMPONENTS", message="河网包含不连通分量",
            entity_type="network", entity_ref=str(network.id), context={"component_count": components},
        ))
    for node_id in sorted(node_ids):
        if len(adjacency[node_id]) == 1:
            issues.append(HydraulicIssue(
                severity="info", code="DANGLING_BOUNDARY", message="节点为单连接边界端点",
                entity_type="node", entity_ref=str(node_id),
            ))
    session.flush()
    _sync_legacy_topology(session, network, branches)
    session.flush()
    return HydraulicTopologyReport(
        network_id=network.id, engineering_crs=network.engineering_crs or "",
        snap_tolerance_m=snap_tolerance_m, node_count=len(nodes),
        branch_count=len(branches), reach_count=reach_count, issues=issues,
    )


def reverse_branch(session: Session, branch_id: int) -> HydraulicBranchActionRecord:
    """Reverse branch direction, chainage, sections, and reach orientation atomically."""

    branch = session.get(HydraulicBranch, branch_id)
    if branch is None:
        raise ValueError("Hydraulic branch does not exist")
    assert_dataset_version_mutable(session, branch.dataset_version_id)
    start, end = branch.start_chainage, branch.end_chainage
    vertices = session.scalars(select(HydraulicBranchVertex).where(
        HydraulicBranchVertex.branch_id == branch.id
    ).order_by(HydraulicBranchVertex.vertex_order)).all()
    snapshots = [{
        "chainage": start + end - v.chainage, "geometry": v.geometry,
        "source_x": v.source_x, "source_y": v.source_y, "source_z": v.source_z,
        "source_crs": v.source_crs, "source_axis_mapping": v.source_axis_mapping,
        "transform_pipeline": v.transform_pipeline, "import_job_id": v.import_job_id,
        "metadata_json": v.metadata_json,
    } for v in reversed(vertices)]
    session.execute(delete(HydraulicBranchVertex).where(HydraulicBranchVertex.branch_id == branch.id))
    session.flush()
    for order, value in enumerate(snapshots):
        session.add(HydraulicBranchVertex(
            dataset_version_id=branch.dataset_version_id, branch_id=branch.id,
            vertex_order=order, **value,
        ))
    branch.geometry = func.ST_Reverse(branch.geometry)
    branch.upstream_node_id, branch.downstream_node_id = branch.downstream_node_id, branch.upstream_node_id
    metadata = dict(branch.metadata_json or {})
    metadata["source_flow_direction"] = "reverse" if metadata.get("source_flow_direction") == "forward" else "forward"
    branch.metadata_json = metadata
    branch.direction_status = "confirmed"
    legacy_section_ids = session.scalars(select(HydraulicCrossSection.legacy_cross_section_id).where(
        HydraulicCrossSection.branch_id == branch.id,
        HydraulicCrossSection.legacy_cross_section_id.is_not(None),
    )).all()
    session.execute(update(HydraulicCrossSection).where(
        HydraulicCrossSection.branch_id == branch.id
    ).values(
        chainage=start + end - HydraulicCrossSection.chainage,
        computed_chainage_m=start + end - HydraulicCrossSection.computed_chainage_m,
    ).execution_options(synchronize_session=False))
    if legacy_section_ids:
        session.execute(update(CrossSection).where(
            CrossSection.id.in_(legacy_section_ids)
        ).values(station=start + end - CrossSection.station).execution_options(
            synchronize_session=False
        ))
    reaches = session.scalars(select(HydraulicReach).where(HydraulicReach.branch_id == branch.id)).all()
    for reach in reaches:
        old_start, old_end = reach.start_chainage_m, reach.end_chainage_m
        reach.start_chainage_m, reach.end_chainage_m = start + end - old_end, start + end - old_start
        reach.upstream_node_id, reach.downstream_node_id = reach.downstream_node_id, reach.upstream_node_id
        reach.geometry = func.ST_Reverse(reach.geometry)
    if branch.legacy_river_id:
        river = session.get(River, branch.legacy_river_id)
        if river:
            river.geometry = branch.geometry
    session.flush()
    network = session.get(HydraulicNetwork, branch.network_id)
    if network is not None:
        _sync_legacy_topology(session, network, session.scalars(select(HydraulicBranch).where(
            HydraulicBranch.network_id == network.id
        ).order_by(HydraulicBranch.id)).all())
        session.flush()
    return HydraulicBranchActionRecord(
        branch_id=branch.id, direction_status=branch.direction_status,
        start_chainage_m=branch.start_chainage, end_chainage_m=branch.end_chainage,
        length_m=branch.length_m,
    )


def recalculate_chainage(session: Session, branch_id: int) -> HydraulicBranchActionRecord:
    """Scale adopted chainage to the projected branch length while preserving start value."""

    branch = session.get(HydraulicBranch, branch_id)
    if branch is None:
        raise ValueError("Hydraulic branch does not exist")
    assert_dataset_version_mutable(session, branch.dataset_version_id)
    old_start, old_end = branch.start_chainage, branch.end_chainage
    new_end = old_start + branch.length_m
    scale = branch.length_m / (old_end - old_start)
    session.execute(update(HydraulicBranchVertex).where(
        HydraulicBranchVertex.branch_id == branch.id
    ).values(
        chainage=old_start + (HydraulicBranchVertex.chainage - old_start) * scale
    ).execution_options(synchronize_session=False))
    legacy_section_ids = session.scalars(select(HydraulicCrossSection.legacy_cross_section_id).where(
        HydraulicCrossSection.branch_id == branch.id,
        HydraulicCrossSection.legacy_cross_section_id.is_not(None),
    )).all()
    session.execute(update(HydraulicCrossSection).where(
        HydraulicCrossSection.branch_id == branch.id
    ).values(
        chainage=old_start + (HydraulicCrossSection.chainage - old_start) * scale,
        computed_chainage_m=old_start + (
            HydraulicCrossSection.computed_chainage_m - old_start
        ) * scale,
    ).execution_options(synchronize_session=False))
    if legacy_section_ids:
        session.execute(update(CrossSection).where(
            CrossSection.id.in_(legacy_section_ids)
        ).values(
            station=old_start + (CrossSection.station - old_start) * scale
        ).execution_options(synchronize_session=False))
    session.execute(update(HydraulicReach).where(
        HydraulicReach.branch_id == branch.id
    ).values(
        start_chainage_m=old_start + (HydraulicReach.start_chainage_m - old_start) * scale,
        end_chainage_m=old_start + (HydraulicReach.end_chainage_m - old_start) * scale,
    ).execution_options(synchronize_session=False))
    branch.end_chainage = new_end
    if branch.legacy_river_id:
        river = session.get(River, branch.legacy_river_id)
        if river:
            river.length = branch.length_m
    session.flush()
    network = session.get(HydraulicNetwork, branch.network_id)
    if network is not None:
        _sync_legacy_topology(session, network, session.scalars(select(HydraulicBranch).where(
            HydraulicBranch.network_id == network.id
        ).order_by(HydraulicBranch.id)).all())
        session.flush()
    return HydraulicBranchActionRecord(
        branch_id=branch.id, direction_status=branch.direction_status,
        start_chainage_m=branch.start_chainage, end_chainage_m=branch.end_chainage,
        length_m=branch.length_m,
    )
