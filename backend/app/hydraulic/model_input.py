"""Build solver-ready dayu.model-input.v3 from authoritative hydraulic tables."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.common.spatial import geometry_json
from app.dataset.service import build_model_input_v2
from app.gis.models import SimulationCase
from app.hydraulic.compatibility import (
    HydraulicCompatibilityMappingError, build_hydraulic_compatibility_mapping,
    rewrite_legacy_topology_references,
)
from app.hydraulic.models import (
    HydraulicBranch, HydraulicCrossSection, HydraulicCrossSectionHydraulicRow,
    HydraulicCrossSectionPoint, HydraulicCrossSectionProcessing,
    HydraulicCrossSectionProfile, HydraulicNetwork, HydraulicNode, HydraulicReach,
    HydraulicRoughnessZone,
)


def _build_structure_control_envelopes(
    payload: dict[str, object],
    *,
    legacy_river_to_branch: dict[int, int],
    legacy_segment_by_branch: dict[int, int],
) -> tuple[dict[str, list[dict[str, object]]], dict[str, object]]:
    """Build the authoritative v3 structure/control projection.

    ``structures`` is the structured source for v3 consumers.  The caller mirrors
    these exact rewritten values to the established top-level ``gates``/``pumps``
    fields for backward compatibility, without creating a second source of truth.
    """

    raw_gates = payload.get("gates", [])
    raw_pumps = payload.get("pumps", [])
    if not isinstance(raw_gates, list) or not isinstance(raw_pumps, list):
        raise ValueError("model-input.v3 gates and pumps must be arrays")

    dataset = payload.get("dataset_version")
    if not isinstance(dataset, dict):
        raise ValueError("model-input.v3 dataset_version must be an object")
    dataset_provenance = {
        key: dataset.get(key)
        for key in ("id", "version", "content_hash", "source_batch_id")
    }
    dispatch_plan = payload.get("dispatch_plan")
    rules: list[object] = []
    if dispatch_plan is not None:
        if not isinstance(dispatch_plan, dict):
            raise ValueError("model-input.v3 dispatch_plan must be an object")
        raw_rules = dispatch_plan.get("rules", [])
        if not isinstance(raw_rules, list):
            raise ValueError("model-input.v3 dispatch_plan.rules must be an array")
        rules = raw_rules
    state_source = (
        "frozen_dispatch_plan" if dispatch_plan is not None else "uninitialized"
    )
    state_mode = "dispatch" if dispatch_plan is not None else "uninitialized"

    def branch_for(row: dict[str, object], structure_type: str) -> int:
        """Resolve one public river identity to its verified hydraulic Branch."""

        identity = row.get("id")
        legacy_river_id = row.get("river_id")
        if isinstance(legacy_river_id, bool) or not isinstance(legacy_river_id, int):
            raise ValueError(
                f"model-input.v3 {structure_type} {identity} has no valid legacy river"
            )
        branch_id = legacy_river_to_branch.get(legacy_river_id)
        if branch_id is None:
            raise ValueError(
                f"model-input.v3 {structure_type} {identity} has no verified hydraulic branch"
            )
        return branch_id

    gates: list[dict[str, object]] = []
    for raw_gate in raw_gates:
        if not isinstance(raw_gate, dict):
            raise ValueError("model-input.v3 gate items must be objects")
        gate = dict(raw_gate)
        branch_id = branch_for(gate, "gate")
        branch_reference = gate.get("river_segment_id")
        if branch_reference is not None and branch_reference != branch_id:
            raise ValueError(
                f"model-input.v3 gate {gate.get('id')} branch references disagree"
            )
        chainage = gate.get("station")
        gate.update({
            "id": gate.get("id"),
            "dataset_version_id": gate.get("dataset_version_id"),
            "branch_id": branch_id,
            "chainage": chainage,
            "geometry": gate.get("geometry"),
            "parameters": {
                key: gate.get(key)
                for key in (
                    "gate_type", "opening_direction", "width", "height", "max_flow",
                    "bottom_elevation", "crest_elevation", "discharge_coefficient",
                    "minimum_opening", "maximum_opening", "opening_rate_limit",
                    "minimum_hold_seconds", "allow_reverse_flow",
                )
            } | {
                "opening_min": gate.get("minimum_opening"),
                "opening_max": gate.get("maximum_opening"),
            },
            "control_state": {
                # Static asset control_mode is metadata, not an initialized opening.
                "mode": state_mode,
                "control_mode": gate.get("control_mode"),
                "status": "uninitialized",
                "availability": gate.get("status"),
                "opening": None,
                "state_source": state_source,
            },
            "provenance": {
                "source_table": "public.gate",
                "source_id": gate.get("id"),
                "dataset_version": dataset_provenance,
                "legacy_river_id": gate.get("river_id"),
                "legacy_river_segment_id": legacy_segment_by_branch.get(branch_id),
                "topology_mapping": "verified_public_to_hydraulic_branch",
                "chainage_source": (
                    "public.gate.station" if chainage is not None else "unconfirmed"
                ),
                "reach_id": gate.get("reach_id"),
            },
        })
        gates.append(gate)

    pumps: list[dict[str, object]] = []
    for raw_pump in raw_pumps:
        if not isinstance(raw_pump, dict):
            raise ValueError("model-input.v3 pump items must be objects")
        pump = dict(raw_pump)
        branch_id = branch_for(pump, "pump")
        pump.update({
            "id": pump.get("id"),
            "dataset_version_id": pump.get("dataset_version_id"),
            "branch_id": branch_id,
            # The public Pump model has no authoritative station/chainage field.
            # Geometry is retained, but no projected chainage may be invented here.
            "chainage": None,
            "geometry": pump.get("geometry"),
            "parameters": {
                key: pump.get(key)
                for key in (
                    "design_flow", "head", "head_curve", "efficiency_curve", "power",
                    "transfer_type", "unit_count", "minimum_running_units",
                    "maximum_running_units", "minimum_run_seconds", "minimum_stop_seconds",
                    "maximum_starts_per_run", "minimum_operating_head",
                    "maximum_operating_head", "reverse_flow_protection",
                )
            } | {"pump_count": pump.get("unit_count")},
            "control_state": {
                # Static asset control_mode is metadata, not an initialized run state.
                "mode": state_mode,
                "control_mode": pump.get("control_mode"),
                "status": "uninitialized",
                "availability": pump.get("status"),
                "enabled": None,
                "running_units": None,
                "state_source": state_source,
            },
            "provenance": {
                "source_table": "public.pump",
                "source_id": pump.get("id"),
                "dataset_version": dataset_provenance,
                "legacy_river_id": pump.get("river_id"),
                "topology_mapping": "verified_public_to_hydraulic_branch",
                "chainage_source": "unavailable_not_inferred",
                "reach_id": pump.get("reach_id"),
            },
        })
        pumps.append(pump)

    raw_controls = payload.get("controls") or {}
    if not isinstance(raw_controls, dict):
        raise ValueError("model-input.v3 controls must be an object")
    controls = dict(raw_controls)
    controls["rules"] = rules
    return {"gates": gates, "pumps": pumps}, controls


def build_model_input_v3(
    session: Session,
    case_id: int,
    *,
    controls: dict[str, object] | None = None,
    dispatch_plan: dict[str, object] | None = None,
    engine_version: str = "dayu-hydraulic-5.0.0",
) -> dict[str, object] | None:
    """Build a full topology/profile snapshot and reject incomplete hydraulic data."""

    case = session.get(SimulationCase, case_id)
    if case is None:
        return None
    base = build_model_input_v2(
        session, case_id, controls={"section_geometry": "tabulated", **(controls or {})},
        dispatch_plan=dispatch_plan, engine_version=engine_version,
    )
    if base is None:
        return None
    networks = session.scalars(select(HydraulicNetwork).where(
        HydraulicNetwork.dataset_version_id == case.dataset_version_id
    ).order_by(HydraulicNetwork.id)).all()
    if len(networks) != 1:
        raise ValueError("model-input.v3 requires exactly one hydraulic network in the Dataset Version")
    network = networks[0]
    if not network.engineering_crs:
        raise ValueError("model-input.v3 requires a confirmed engineering CRS")
    nodes = session.scalars(select(HydraulicNode).where(
        HydraulicNode.network_id == network.id
    ).order_by(HydraulicNode.id)).all()
    branches = session.scalars(select(HydraulicBranch).where(
        HydraulicBranch.network_id == network.id
    ).order_by(HydraulicBranch.id)).all()
    if not nodes or not branches:
        raise ValueError("model-input.v3 requires built nodes and branches")
    engineering_srid = int(network.engineering_crs.split(":", 1)[1])
    overlap_count = int(session.scalar(text("""
        WITH lines AS (
          SELECT id, ST_Transform(centerline, :srid) AS geometry
            FROM hydraulic.branch WHERE network_id = :network_id
        )
        SELECT COUNT(*)
          FROM lines a JOIN lines b ON a.id < b.id
         WHERE ST_Intersects(a.geometry, b.geometry)
           AND ST_Dimension(ST_Intersection(a.geometry, b.geometry)) = 1
    """), {"srid": engineering_srid, "network_id": network.id}) or 0)
    if overlap_count:
        raise ValueError("model-input.v3 rejects overlapping branch centerlines")
    branch_rows: list[dict[str, object]] = []
    reach_rows: list[dict[str, object]] = []
    section_rows: list[dict[str, object]] = []
    profile_rows: list[dict[str, object]] = []
    roughness_rows: list[dict[str, object]] = []
    hydraulic_table_rows: list[dict[str, object]] = []
    errors: list[str] = []
    for branch in branches:
        if branch.direction_status != "confirmed" or branch.upstream_node_id is None or branch.downstream_node_id is None:
            errors.append(f"branch {branch.branch_code} direction/topology is not confirmed")
        reaches = session.scalars(select(HydraulicReach).where(
            HydraulicReach.branch_id == branch.id
        ).order_by(HydraulicReach.start_chainage_m)).all()
        if not reaches:
            errors.append(f"branch {branch.branch_code} has no reaches")
        branch_rows.append({
            "id": branch.id, "legacy_river_id": branch.legacy_river_id,
            "branch_code": branch.branch_code, "river_name": branch.river_name,
            "branch_name": branch.branch_name, "upstream_node_id": branch.upstream_node_id,
            "downstream_node_id": branch.downstream_node_id,
            "start_chainage_m": branch.start_chainage, "end_chainage_m": branch.end_chainage,
            "length_m": branch.length_m, "direction_status": branch.direction_status,
            "centerline": geometry_json(session, branch.geometry),
            "source_revision": branch.source_revision,
        })
        reach_rows.extend({
            "id": reach.id, "branch_id": reach.branch_id, "reach_code": reach.reach_code,
            "reach_type": reach.reach_type, "start_chainage_m": reach.start_chainage_m,
            "end_chainage_m": reach.end_chainage_m,
            "upstream_node_id": reach.upstream_node_id,
            "downstream_node_id": reach.downstream_node_id,
            "length_m": reach.length_m, "geometry": geometry_json(session, reach.geometry),
            "parameters": reach.parameter_json,
        } for reach in reaches)
        sections = session.scalars(select(HydraulicCrossSection).where(
            HydraulicCrossSection.branch_id == branch.id
        ).order_by(HydraulicCrossSection.chainage)).all()
        if len(sections) < 3:
            errors.append(f"branch {branch.branch_code} requires at least three cross sections")
        for section in sections:
            if section.orientation_status != "confirmed":
                errors.append(f"cross section {section.section_code} orientation is not confirmed")
            profile = session.scalar(select(HydraulicCrossSectionProfile).where(
                HydraulicCrossSectionProfile.cross_section_id == section.id,
                HydraulicCrossSectionProfile.is_active.is_(True),
            ).order_by(HydraulicCrossSectionProfile.id.desc()))
            if profile is None:
                errors.append(f"cross section {section.section_code} has no active profile")
                continue
            processing = session.scalar(select(HydraulicCrossSectionProcessing).where(
                HydraulicCrossSectionProcessing.profile_id == profile.id,
                HydraulicCrossSectionProcessing.profile_hash == profile.profile_hash,
                HydraulicCrossSectionProcessing.status == "ready",
            ).order_by(HydraulicCrossSectionProcessing.id.desc()))
            if processing is None:
                errors.append(f"profile {profile.id} has no current processed hydraulic table")
                continue
            points = session.scalars(select(HydraulicCrossSectionPoint).where(
                HydraulicCrossSectionPoint.profile_id == profile.id
            ).order_by(HydraulicCrossSectionPoint.sequence)).all()
            zones = session.scalars(select(HydraulicRoughnessZone).where(
                HydraulicRoughnessZone.profile_id == profile.id
            ).order_by(HydraulicRoughnessZone.zone_order)).all()
            table = session.scalars(select(HydraulicCrossSectionHydraulicRow).where(
                HydraulicCrossSectionHydraulicRow.processing_id == processing.id
            ).order_by(HydraulicCrossSectionHydraulicRow.stage_m)).all()
            section_rows.append({
                "id": section.id, "branch_id": branch.id,
                "section_code": section.section_code, "section_name": section.section_name,
                "chainage_m": section.chainage, "computed_chainage_m": section.computed_chainage_m,
                "chainage_source": section.chainage_source,
                "snap_distance_m": section.snap_distance_m,
                "orientation_status": section.orientation_status,
                "location": geometry_json(session, section.location_geometry),
                "axis": geometry_json(session, section.axis_geometry) if section.axis_geometry is not None else None,
                "active_profile_id": profile.id,
            })
            profile_rows.append({
                "id": profile.id, "cross_section_id": section.id, "branch_id": branch.id,
                "section_code": section.section_code, "chainage_m": section.chainage,
                "topography_id": profile.topography_id,
                "survey_date": profile.survey_date.isoformat() if profile.survey_date else None,
                "survey_method": profile.survey_method, "vertical_datum": profile.vertical_datum,
                "vertical_unit": profile.vertical_unit,
                "default_manning_n": profile.default_manning_n,
                "profile_hash": profile.profile_hash,
                "points": [{
                    "sequence": p.sequence, "offset_m": p.distance,
                    "elevation_m": p.elevation, "marker_type": p.marker_type,
                    "point_code": p.point_code,
                } for p in points],
                "roughness_zones": [{
                    "zone_order": z.zone_order, "offset_start_m": z.offset_start_m,
                    "offset_end_m": z.offset_end_m, "manning_n": z.manning_n,
                    "zone_type": z.zone_type,
                } for z in zones],
                "processing": {
                    "id": processing.id, "processor_version": processing.processor_version,
                    "vertical_step_m": processing.vertical_step_m,
                    "minimum_stage_m": processing.minimum_stage_m,
                    "maximum_stage_m": processing.maximum_stage_m,
                    "hydraulic_table": [{
                        "stage_m": row.stage_m, "area_m2": row.area_m2,
                        "top_width_m": row.top_width_m,
                        "wetted_perimeter_m": row.wetted_perimeter_m,
                        "hydraulic_radius_m": row.hydraulic_radius_m,
                        "conveyance": row.conveyance,
                    } for row in table],
                },
            })
            roughness_rows.extend({
                "profile_id": profile.id, "zone_order": z.zone_order,
                "offset_start_m": z.offset_start_m,
                "offset_end_m": z.offset_end_m,
                "manning_n": z.manning_n, "zone_type": z.zone_type,
            } for z in zones)
            hydraulic_table_rows.extend({
                "profile_id": profile.id, "processing_id": processing.id,
                "profile_hash": profile.profile_hash,
                "processor_version": processing.processor_version,
                "vertical_step_m": processing.vertical_step_m,
                "stage_m": row.stage_m, "area_m2": row.area_m2,
                "top_width_m": row.top_width_m,
                "wetted_perimeter_m": row.wetted_perimeter_m,
                "hydraulic_radius_m": row.hydraulic_radius_m,
                "conveyance": row.conveyance,
            } for row in table)
    if errors:
        raise ValueError("model-input.v3 readiness failed: " + "; ".join(errors[:20]))
    try:
        compatibility_mapping = build_hydraulic_compatibility_mapping(session, network)
        base = rewrite_legacy_topology_references(base, compatibility_mapping)
    except HydraulicCompatibilityMappingError as exc:
        raise ValueError(f"model-input.v3 readiness failed: {exc}") from exc
    legacy_river_to_branch = {
        int(branch.legacy_river_id): branch.id
        for branch in branches
        if branch.legacy_river_id is not None
    }
    legacy_segment_by_branch = {
        hydraulic_id: legacy_id
        for legacy_id, hydraulic_id in (
            compatibility_mapping.legacy_segment_to_hydraulic_branch.items()
        )
    }
    structures, control_envelope = _build_structure_control_envelopes(
        base,
        legacy_river_to_branch=legacy_river_to_branch,
        legacy_segment_by_branch=legacy_segment_by_branch,
    )
    base = {
        **base,
        "gates": structures["gates"],
        "pumps": structures["pumps"],
        "controls": control_envelope,
    }
    legacy_node_ids = {
        hydraulic_id: legacy_id
        for legacy_id, hydraulic_id in (
            compatibility_mapping.legacy_node_to_hydraulic_node.items()
        )
    }
    legacy_segment_ids = {
        hydraulic_id: legacy_id
        for legacy_id, hydraulic_id in (
            compatibility_mapping.legacy_segment_to_hydraulic_branch.items()
        )
    }
    for branch_row in branch_rows:
        branch_row["legacy_segment_id"] = legacy_segment_ids.get(int(branch_row["id"]))
    payload: dict[str, object] = {
        key: value for key, value in base.items()
        if key not in {"rivers", "nodes", "segments", "connections", "cross_sections"}
    }
    payload.update({
        "schema_version": "dayu.model-input.v3",
        "coordinate_reference": {
            "display_crs": network.display_crs,
            "engineering_crs": network.engineering_crs,
            "horizontal_unit": network.horizontal_unit,
            "vertical_datum": network.vertical_datum,
            "vertical_unit": network.vertical_unit,
        },
        "networks": [{
            "id": network.id, "code": network.code, "name": network.name,
            "display_crs": network.display_crs, "engineering_crs": network.engineering_crs,
        }],
        "nodes": [{
            "id": node.id, "node_code": node.node_code, "node_name": node.node_name,
            "node_type": node.node_type, "geometry": geometry_json(session, node.geometry),
            "elevation_m": node.elevation_m,
            "legacy_node_id": legacy_node_ids.get(node.id),
        } for node in nodes],
        "branches": branch_rows, "reaches": reach_rows,
        "cross_sections": section_rows, "cross_section_profiles": profile_rows,
        "roughness_zones": roughness_rows,
        "hydraulic_tables": hydraulic_table_rows,
        "structures": structures,
        "controls": control_envelope,
        "units": {**dict(base.get("units", {})), "chainage": "m", "roughness": "Manning n"},
        "distance_basis": f"PostGIS projected geometry in {network.engineering_crs}; adopted chainage in metres",
        "compatibility_mapping": compatibility_mapping.as_payload(),
        "engine_version": engine_version,
    })
    return payload
