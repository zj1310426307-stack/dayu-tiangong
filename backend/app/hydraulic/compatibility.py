"""Bridge established GIS tables and the authoritative hydraulic schema."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from app.gis.models import (
    CrossSection, CrossSectionAxis, CrossSectionLocation, CrossSectionPoint, River,
    RiverNode, RiverSegment,
)
from app.hydraulic.coordinate import canonical_hash
from app.hydraulic.models import (
    HydraulicBranch, HydraulicBranchVertex, HydraulicCrossSection,
    HydraulicCrossSectionHydraulicRow, HydraulicCrossSectionPoint,
    HydraulicCrossSectionProcessing, HydraulicCrossSectionProfile,
    HydraulicNetwork, HydraulicNode, HydraulicRoughnessZone,
)


class HydraulicCompatibilityMappingError(ValueError):
    """Reject an unverified or incomplete public/hydraulic identity bridge."""


@dataclass(frozen=True)
class HydraulicCompatibilityMapping:
    """Map public compatibility identifiers to authoritative hydraulic identifiers."""

    legacy_node_to_hydraulic_node: dict[int, int]
    legacy_segment_to_hydraulic_branch: dict[int, int]
    legacy_cross_section_to_hydraulic_cross_section: dict[int, int]

    def as_payload(self) -> dict[str, object]:
        """Return deterministic, JSON-safe evidence for a model-input snapshot."""

        return {
            "strategy": (
                "HYD-{network_id}-{semantic_code}; verified by Dataset Version, "
                "geometry, river identity, and directed endpoints; cross-sections "
                "use their explicit version-safe legacy foreign key"
            ),
            "river_nodes": [
                {
                    "legacy_river_node_id": legacy_id,
                    "hydraulic_node_id": hydraulic_id,
                }
                for legacy_id, hydraulic_id in sorted(
                    self.legacy_node_to_hydraulic_node.items()
                )
            ],
            "river_segments": [
                {
                    "legacy_river_segment_id": legacy_id,
                    "hydraulic_branch_id": hydraulic_id,
                }
                for legacy_id, hydraulic_id in sorted(
                    self.legacy_segment_to_hydraulic_branch.items()
                )
            ],
            "cross_sections": [
                {
                    "legacy_cross_section_id": legacy_id,
                    "hydraulic_cross_section_id": hydraulic_id,
                }
                for legacy_id, hydraulic_id in sorted(
                    self.legacy_cross_section_to_hydraulic_cross_section.items()
                )
            ],
        }


def build_hydraulic_compatibility_mapping(
    session: Session, network: HydraulicNetwork
) -> HydraulicCompatibilityMapping:
    """Build and verify the identity bridge emitted by ``_sync_legacy_topology``."""

    compatibility_prefix = f"HYD-{network.id}-"
    node_rows = session.execute(
        select(
            HydraulicNode.id,
            RiverNode.id,
            func.ST_Equals(HydraulicNode.geometry, RiverNode.geometry),
        )
        .join(
            RiverNode,
            and_(
                RiverNode.dataset_version_id == HydraulicNode.dataset_version_id,
                RiverNode.node_code
                == func.concat(compatibility_prefix, HydraulicNode.node_code),
            ),
        )
        .where(HydraulicNode.network_id == network.id)
        .order_by(HydraulicNode.id)
    ).all()
    node_mapping: dict[int, int] = {}
    for hydraulic_id, legacy_id, same_geometry in node_rows:
        if not same_geometry:
            raise HydraulicCompatibilityMappingError(
                f"compatibility river_node {legacy_id} geometry does not match "
                f"hydraulic.node {hydraulic_id}"
            )
        legacy_id, hydraulic_id = int(legacy_id), int(hydraulic_id)
        if legacy_id in node_mapping and node_mapping[legacy_id] != hydraulic_id:
            raise HydraulicCompatibilityMappingError(
                f"compatibility river_node {legacy_id} maps to multiple hydraulic nodes"
            )
        node_mapping[legacy_id] = hydraulic_id

    segment_rows = session.execute(
        select(
            HydraulicBranch.id,
            HydraulicBranch.legacy_river_id,
            HydraulicBranch.upstream_node_id,
            HydraulicBranch.downstream_node_id,
            RiverSegment.id,
            RiverSegment.river_id,
            RiverSegment.upstream_node_id,
            RiverSegment.downstream_node_id,
            func.ST_Equals(HydraulicBranch.geometry, RiverSegment.geometry),
        )
        .join(
            RiverSegment,
            and_(
                RiverSegment.dataset_version_id == HydraulicBranch.dataset_version_id,
                RiverSegment.segment_code
                == func.concat(compatibility_prefix, HydraulicBranch.branch_code),
            ),
        )
        .where(HydraulicBranch.network_id == network.id)
        .order_by(HydraulicBranch.id)
    ).all()
    segment_mapping: dict[int, int] = {}
    for (
        hydraulic_id,
        legacy_river_id,
        hydraulic_upstream_id,
        hydraulic_downstream_id,
        legacy_segment_id,
        segment_river_id,
        legacy_upstream_id,
        legacy_downstream_id,
        same_geometry,
    ) in segment_rows:
        if legacy_river_id is None or int(segment_river_id) != int(legacy_river_id):
            raise HydraulicCompatibilityMappingError(
                f"compatibility river_segment {legacy_segment_id} has the wrong river identity"
            )
        if not same_geometry:
            raise HydraulicCompatibilityMappingError(
                f"compatibility river_segment {legacy_segment_id} geometry does not match "
                f"hydraulic.branch {hydraulic_id}"
            )
        mapped_upstream_id = node_mapping.get(int(legacy_upstream_id))
        mapped_downstream_id = node_mapping.get(int(legacy_downstream_id))
        if (
            hydraulic_upstream_id is None
            or hydraulic_downstream_id is None
            or mapped_upstream_id != int(hydraulic_upstream_id)
            or mapped_downstream_id != int(hydraulic_downstream_id)
        ):
            raise HydraulicCompatibilityMappingError(
                f"compatibility river_segment {legacy_segment_id} directed endpoints do not "
                f"match hydraulic.branch {hydraulic_id}"
            )
        legacy_segment_id, hydraulic_id = int(legacy_segment_id), int(hydraulic_id)
        if (
            legacy_segment_id in segment_mapping
            and segment_mapping[legacy_segment_id] != hydraulic_id
        ):
            raise HydraulicCompatibilityMappingError(
                f"compatibility river_segment {legacy_segment_id} maps to multiple branches"
            )
        segment_mapping[legacy_segment_id] = hydraulic_id

    section_rows = session.execute(
        select(
            HydraulicCrossSection.id,
            HydraulicCrossSection.legacy_cross_section_id,
        )
        .join(
            HydraulicBranch,
            HydraulicBranch.id == HydraulicCrossSection.branch_id,
        )
        .join(
            CrossSection,
            and_(
                CrossSection.id == HydraulicCrossSection.legacy_cross_section_id,
                CrossSection.dataset_version_id
                == HydraulicCrossSection.dataset_version_id,
            ),
        )
        .where(
            HydraulicBranch.network_id == network.id,
            HydraulicCrossSection.legacy_cross_section_id.is_not(None),
        )
        .order_by(HydraulicCrossSection.id)
    ).all()
    section_mapping: dict[int, int] = {}
    for hydraulic_id, legacy_id in section_rows:
        legacy_id, hydraulic_id = int(legacy_id), int(hydraulic_id)
        if legacy_id in section_mapping and section_mapping[legacy_id] != hydraulic_id:
            raise HydraulicCompatibilityMappingError(
                f"compatibility cross_section {legacy_id} maps to multiple hydraulic "
                "cross-sections"
            )
        section_mapping[legacy_id] = hydraulic_id

    return HydraulicCompatibilityMapping(
        node_mapping,
        segment_mapping,
        section_mapping,
    )


def rewrite_legacy_topology_references(
    payload: dict[str, Any], mapping: HydraulicCompatibilityMapping
) -> dict[str, Any]:
    """Rewrite legacy node/segment references for authoritative v3 topology IDs."""

    rewritten = dict(payload)
    collection_fields = {
        "boundary_conditions": {
            "target_node_id": (
                "river_node", mapping.legacy_node_to_hydraulic_node
            ),
        },
        "gates": {
            "upstream_node_id": (
                "river_node", mapping.legacy_node_to_hydraulic_node
            ),
            "downstream_node_id": (
                "river_node", mapping.legacy_node_to_hydraulic_node
            ),
            "river_segment_id": (
                "river_segment", mapping.legacy_segment_to_hydraulic_branch
            ),
        },
        "pumps": {
            "intake_node_id": (
                "river_node", mapping.legacy_node_to_hydraulic_node
            ),
            "outlet_node_id": (
                "river_node", mapping.legacy_node_to_hydraulic_node
            ),
        },
    }
    for collection_name, field_mappings in collection_fields.items():
        rows = payload.get(collection_name, [])
        if not isinstance(rows, list):
            raise HydraulicCompatibilityMappingError(
                f"{collection_name} must be a list before compatibility rewriting"
            )
        rewritten_rows: list[dict[str, Any]] = []
        for index, source_row in enumerate(rows):
            if not isinstance(source_row, dict):
                raise HydraulicCompatibilityMappingError(
                    f"{collection_name}[{index}] must be an object"
                )
            row = dict(source_row)
            identity = row.get("id", index)
            for field_name, (legacy_table, identifier_mapping) in field_mappings.items():
                legacy_id = row.get(field_name)
                if legacy_id is None:
                    continue
                try:
                    normalized_legacy_id = int(legacy_id)
                except (TypeError, ValueError) as exc:
                    raise HydraulicCompatibilityMappingError(
                        f"{collection_name} item {identity} field {field_name} has an "
                        f"invalid {legacy_table} id {legacy_id!r}"
                    ) from exc
                hydraulic_id = identifier_mapping.get(normalized_legacy_id)
                if hydraulic_id is None:
                    raise HydraulicCompatibilityMappingError(
                        f"{collection_name} item {identity} field {field_name} references "
                        f"{legacy_table} {normalized_legacy_id} without a verified "
                        "hydraulic topology mapping"
                    )
                row[field_name] = hydraulic_id
            rewritten_rows.append(row)
        rewritten[collection_name] = rewritten_rows

    dispatch_plan = payload.get("dispatch_plan")
    if dispatch_plan is not None:
        if not isinstance(dispatch_plan, dict):
            raise HydraulicCompatibilityMappingError(
                "dispatch_plan must be an object before compatibility rewriting"
            )
        rules = dispatch_plan.get("rules", [])
        if not isinstance(rules, list):
            raise HydraulicCompatibilityMappingError(
                "dispatch_plan.rules must be a list before compatibility rewriting"
            )
        rewritten_rules: list[dict[str, Any]] = []
        observation_mappings = {
            "node_water_level": (
                "river_node", mapping.legacy_node_to_hydraulic_node
            ),
            "section_water_level": (
                "cross_section",
                mapping.legacy_cross_section_to_hydraulic_cross_section,
            ),
        }
        passthrough_observations = {
            "gate_head_difference": "gate",
            "pump_intake_level": "pump",
        }
        for index, source_rule in enumerate(rules):
            if not isinstance(source_rule, dict):
                raise HydraulicCompatibilityMappingError(
                    f"dispatch_plan.rules[{index}] must be an object"
                )
            rule = dict(source_rule)
            identity = rule.get("id", index)
            observation_type = rule.get("observation_type")
            legacy_id = rule.get("observation_object_id")
            if observation_type == "elapsed_time":
                if legacy_id is not None:
                    raise HydraulicCompatibilityMappingError(
                        f"dispatch rule {identity} elapsed_time must not reference "
                        "observation_object_id"
                    )
            elif observation_type in observation_mappings:
                legacy_table, identifier_mapping = observation_mappings[observation_type]
                if isinstance(legacy_id, bool) or not isinstance(legacy_id, int) or legacy_id <= 0:
                    raise HydraulicCompatibilityMappingError(
                        f"dispatch rule {identity} field observation_object_id has an "
                        f"invalid {legacy_table} id {legacy_id!r}"
                    )
                hydraulic_id = identifier_mapping.get(legacy_id)
                if hydraulic_id is None:
                    raise HydraulicCompatibilityMappingError(
                        f"dispatch rule {identity} field observation_object_id references "
                        f"{legacy_table} {legacy_id} without a verified hydraulic "
                        "topology mapping"
                    )
                rule["observation_object_id"] = hydraulic_id
            elif observation_type in passthrough_observations:
                if isinstance(legacy_id, bool) or not isinstance(legacy_id, int) or legacy_id <= 0:
                    raise HydraulicCompatibilityMappingError(
                        f"dispatch rule {identity} field observation_object_id has an "
                        f"invalid {passthrough_observations[observation_type]} id "
                        f"{legacy_id!r}"
                    )
            else:
                raise HydraulicCompatibilityMappingError(
                    f"dispatch rule {identity} has unsupported or missing observation_type "
                    f"{observation_type!r}; observation_object_id cannot be mapped safely"
                )
            rewritten_rules.append(rule)
        rewritten_dispatch_plan = dict(dispatch_plan)
        rewritten_dispatch_plan["rules"] = rewritten_rules
        rewritten["dispatch_plan"] = rewritten_dispatch_plan
    return rewritten


def sync_legacy_river(session: Session, river: River) -> HydraulicBranch:
    """Mirror a GIS river but leave its engineering CRS visibly unconfirmed."""

    network = session.scalar(select(HydraulicNetwork).where(
        HydraulicNetwork.dataset_version_id == river.dataset_version_id,
        HydraulicNetwork.code == f"LEGACY-V{river.dataset_version_id}",
    ))
    if network is None:
        network = HydraulicNetwork(
            dataset_version_id=river.dataset_version_id,
            code=f"LEGACY-V{river.dataset_version_id}",
            name=f"Dataset Version {river.dataset_version_id} legacy network",
            display_crs="EPSG:4490", engineering_crs=None,
            horizontal_unit="m", vertical_datum="unknown", vertical_unit="m",
            source_kind="legacy", metadata_json={"engineering_crs_status": "unconfirmed"},
        )
        session.add(network)
        session.flush()
    branch = session.scalar(select(HydraulicBranch).where(HydraulicBranch.legacy_river_id == river.id))
    end_chainage = max(float(river.length), 0.001)
    if branch is None:
        branch = HydraulicBranch(
            dataset_version_id=river.dataset_version_id, network_id=network.id,
            legacy_river_id=river.id, branch_code=river.code,
            river_name=river.name, branch_name=river.name,
            start_chainage=0, end_chainage=end_chainage,
            length_m=end_chainage, direction_status="inferred",
            geometry=river.geometry,
            metadata_json={
                "source_flow_direction": "unknown",
                "engineering_crs_status": "unconfirmed",
            },
        )
        session.add(branch)
        session.flush()
    else:
        session.execute(delete(HydraulicBranchVertex).where(HydraulicBranchVertex.branch_id == branch.id))
    branch.river_name = river.name
    branch.branch_name = river.name
    branch.start_chainage = 0
    branch.end_chainage = end_chainage
    branch.length_m = end_chainage
    branch.direction_status = "inferred"
    branch.geometry = river.geometry
    branch.metadata_json = {"source_flow_direction": "unknown", "engineering_crs_status": "unconfirmed"}
    for order, (chainage, geometry) in enumerate((
        (0.0, func.ST_StartPoint(river.geometry)),
        (end_chainage, func.ST_EndPoint(river.geometry)),
    )):
        session.add(HydraulicBranchVertex(
            dataset_version_id=river.dataset_version_id, branch_id=branch.id,
            vertex_order=order, chainage=chainage, geometry=geometry,
            source_x=func.ST_X(geometry), source_y=func.ST_Y(geometry), source_z=None,
            source_crs="EPSG:4490", source_axis_mapping="x_easting_y_northing",
            transform_pipeline="legacy EPSG:4490 identity; engineering CRS unconfirmed",
            metadata_json={},
        ))
    session.flush()
    return branch


def _profile_rows(session: Session, section: CrossSection):
    """Prefer normalized GIS points and fall back to legacy JSON."""

    points = session.scalars(select(CrossSectionPoint).where(
        CrossSectionPoint.cross_section_id == section.id
    ).order_by(CrossSectionPoint.point_order)).all()
    if points:
        return [(p.point_order, p.offset, p.elevation, p.geometry) for p in points]
    return [(i, float(p[0]), float(p[1]), None) for i, p in enumerate(section.points.get("points", []))]


def sync_legacy_cross_section(session: Session, section: CrossSection) -> HydraulicCrossSection:
    """Mirror one legacy section into a single DEFAULT profile without guessing an axis."""

    branch = session.scalar(select(HydraulicBranch).where(
        HydraulicBranch.legacy_river_id == section.river_id
    ))
    if branch is None:
        river = session.get(River, section.river_id)
        if river is None:
            raise ValueError("Cross-section river does not exist")
        branch = sync_legacy_river(session, river)
    location = session.scalar(select(CrossSectionLocation.geometry).where(
        CrossSectionLocation.cross_section_id == section.id
    ))
    if location is None:
        location = section.geometry
    axis = session.scalar(select(CrossSectionAxis.geometry).where(
        CrossSectionAxis.cross_section_id == section.id
    ))
    semantic = session.scalar(select(HydraulicCrossSection).where(
        HydraulicCrossSection.legacy_cross_section_id == section.id
    ))
    if semantic is None:
        semantic = HydraulicCrossSection(
            dataset_version_id=section.dataset_version_id, branch_id=branch.id,
            legacy_cross_section_id=section.id, section_code=section.section_code,
            section_name=section.section_name, chainage=section.station,
            chainage_source="imported", location_geometry=location,
            axis_geometry=axis,
            left_bank=func.ST_StartPoint(axis) if axis is not None else None,
            right_bank=func.ST_EndPoint(axis) if axis is not None else None,
            orientation_status="confirmed" if axis is not None else "pending",
        )
        session.add(semantic)
        session.flush()
    semantic.branch_id = branch.id
    semantic.section_code = section.section_code
    semantic.section_name = section.section_name
    semantic.chainage = section.station
    semantic.chainage_source = "imported"
    semantic.location_geometry = location
    semantic.axis_geometry = axis
    semantic.left_bank = func.ST_StartPoint(axis) if axis is not None else None
    semantic.right_bank = func.ST_EndPoint(axis) if axis is not None else None
    semantic.orientation_status = "confirmed" if axis is not None else "pending"
    profile = session.scalar(select(HydraulicCrossSectionProfile).where(
        HydraulicCrossSectionProfile.cross_section_id == semantic.id,
        HydraulicCrossSectionProfile.topography_id == "DEFAULT",
    ))
    if profile is None:
        rows = _profile_rows(session, section)
        profile_hash = canonical_hash({
            "points": [[row[1], row[2]] for row in rows],
            "default_manning_n": section.roughness,
            "vertical_datum": "unknown",
        })
        profile = HydraulicCrossSectionProfile(
            dataset_version_id=section.dataset_version_id,
            cross_section_id=semantic.id, topography_id="DEFAULT",
            survey_date=section.survey_date, vertical_datum="unknown",
            vertical_unit="m", default_manning_n=section.roughness,
            profile_hash=profile_hash, is_active=True,
        )
        session.add(profile)
        session.flush()
    processing_ids = select(HydraulicCrossSectionProcessing.id).where(
        HydraulicCrossSectionProcessing.profile_id == profile.id
    )
    session.execute(delete(HydraulicCrossSectionHydraulicRow).where(
        HydraulicCrossSectionHydraulicRow.processing_id.in_(processing_ids)
    ))
    session.execute(delete(HydraulicCrossSectionProcessing).where(
        HydraulicCrossSectionProcessing.profile_id == profile.id
    ))
    session.execute(delete(HydraulicCrossSectionPoint).where(HydraulicCrossSectionPoint.profile_id == profile.id))
    session.execute(delete(HydraulicRoughnessZone).where(HydraulicRoughnessZone.profile_id == profile.id))
    rows = _profile_rows(session, section)
    profile.survey_date = section.survey_date
    profile.vertical_datum = "unknown"
    profile.vertical_unit = "m"
    profile.default_manning_n = section.roughness
    profile.profile_hash = canonical_hash({
        "points": [[row[1], row[2]] for row in rows],
        "default_manning_n": section.roughness, "vertical_datum": "unknown",
    })
    profile.is_active = True
    for sequence, distance, elevation, geometry in rows:
        session.add(HydraulicCrossSectionPoint(
            dataset_version_id=section.dataset_version_id, profile_id=profile.id,
            sequence=sequence, distance=distance, elevation=elevation,
            marker_type="none", geometry=geometry,
            source_x=func.ST_X(geometry) if geometry is not None else None,
            source_y=func.ST_Y(geometry) if geometry is not None else None,
            source_z=elevation, source_crs="EPSG:4490" if geometry is not None else None,
            source_axis_mapping="x_easting_y_northing" if geometry is not None else None,
            metadata_json={},
        ))
    if rows:
        session.add(HydraulicRoughnessZone(
            dataset_version_id=section.dataset_version_id, profile_id=profile.id,
            zone_order=0, offset_start_m=float(rows[0][1]), offset_end_m=float(rows[-1][1]),
            manning_n=section.roughness, zone_type="channel",
        ))
    session.flush()
    return semantic
