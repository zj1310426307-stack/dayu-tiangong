"""Production hydraulic data orchestration and legacy compatibility projection."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from geoalchemy2.elements import WKTElement

from app.common.spatial import geometry_json
from app.dataset.lifecycle import assert_dataset_version_mutable
from app.gis.models import (
    CrossSection, CrossSectionAxis, CrossSectionLocation, CrossSectionPoint,
    CrossSectionProfile, DatasetVersion, River,
)
from app.hydraulic.coordinate import canonical_hash, preview_config_hash, transformation_evidence
from app.hydraulic.importers import HydraulicParseError, parse_hydraulic_file, source_format
from app.hydraulic.models import (
    HydraulicBranch, HydraulicBranchVertex, HydraulicCrossSection,
    HydraulicCrossSectionHydraulicRow, HydraulicCrossSectionPoint,
    HydraulicCrossSectionProcessing, HydraulicCrossSectionProfile, HydraulicImportJob,
    HydraulicNetwork, HydraulicNode, HydraulicReach, HydraulicRoughnessZone,
    HydraulicValidationResult, HydraulicValidationRun,
)
from app.hydraulic.schemas import (
    ALLOWED_ENGINEERING_SRIDS, ALLOWED_SOURCE_SRIDS, CoordinateReferenceSpec,
    HydraulicBranchInput, HydraulicBranchRecord, HydraulicCapabilityResponse,
    HydraulicChainageInput, HydraulicCrossSectionInput, HydraulicExchangePayload,
    HydraulicHydraulicRowRecord, HydraulicImportJobRecord, HydraulicImportPreview,
    HydraulicIssue, HydraulicNetworkRecord, HydraulicNodeRecord, HydraulicProcessingRecord,
    HydraulicProfileRecord, HydraulicReachRecord, HydraulicRoughnessZoneInput,
    HydraulicRoughnessZoneRecord, HydraulicSectionDetail, HydraulicSectionPointInput,
    HydraulicSectionPointRecord, HydraulicSectionSummary, HydraulicValidationRunRecord,
    HydraulicMarkerUpdate,
    HydraulicBatchMarkerDetectionRecord, HydraulicBatchMarkerDetectionRequest,
    HydraulicMarkerDetectionRequest, HydraulicMarkerRecord, HydraulicMarkerWorkflowRecord,
    HydraulicMarkerWorkflowUpdate, HydraulicProcessedPointRecord,
)
from app.hydraulic.marker_processing import (
    ALGORITHM_VERSION, SectionPoint, build_processed_geometry,
    detect_markers, marker_dict,
)
from app.hydraulic.spatial_geometry import derive_section_geometry
from app.hydraulic.validators import validate_exchange


def _code(prefix: str) -> str:
    """Create a short sortable operational code."""

    return f"{prefix}-{datetime.now(UTC):%Y%m%d%H%M%S}-{uuid4().hex[:6]}"


def _source_geometry(
    geometry: dict[str, object], expected_type: str, spec: CoordinateReferenceSpec
):
    """Build EPSG:4490 geometry after applying the declared source-axis mapping."""

    if geometry.get("type") != expected_type:
        raise ValueError(f"geometry.type must be {expected_type}")
    raw = geometry.get("coordinates")
    if expected_type == "Point":
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            raise ValueError("Point requires XY")
        normalized: object = list(spec.normalize_xy(float(raw[0]), float(raw[1])))
    else:
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            raise ValueError("LineString requires at least two XY pairs")
        normalized = [list(spec.normalize_xy(float(v[0]), float(v[1]))) for v in raw]
    source = func.ST_SetSRID(
        func.ST_GeomFromGeoJSON(json.dumps({"type": expected_type, "coordinates": normalized})),
        spec.source_srid,
    )
    return func.ST_Force2D(func.ST_Transform(source, 4490))


def _job_record(entity: HydraulicImportJob) -> HydraulicImportJobRecord:
    """Convert one import job into its stable API contract."""

    return HydraulicImportJobRecord(
        id=entity.id, job_code=entity.job_code, dataset_version_id=entity.dataset_version_id,
        filename=entity.filename, source_format=entity.source_format, source_srid=entity.source_srid,
        source_hash_sha256=entity.source_hash_sha256, config_hash=entity.config_hash,
        coordinate_reference=CoordinateReferenceSpec.model_validate(entity.coordinate_reference),
        transformation_evidence=entity.transformation_evidence,
        parser_profile=entity.parser_profile, status=entity.status,
        record_counts=entity.record_counts,
        issues=[HydraulicIssue.model_validate(v) for v in entity.issues],
        native_validation_status=entity.native_validation_status,
        created_at=entity.created_at, completed_at=entity.completed_at,
    )


def _record_counts(payload: HydraulicExchangePayload | None) -> dict[str, int]:
    """Return bounded entity counts for preview display."""

    if payload is None:
        return {
            "branches": 0, "branch_vertices": 0, "cross_sections": 0,
            "profiles": 0, "profile_points": 0, "thalweg_points": 0,
        }
    return {
        "branches": len(payload.branches),
        "branch_vertices": sum(len(v.points) for v in payload.branches),
        "cross_sections": len({v.section_code for v in payload.sections}),
        "profiles": len(payload.sections),
        "profile_points": sum(len(v.points) for v in payload.sections),
        "thalweg_points": sum(
            point.marker_type == "thalweg"
            for section in payload.sections
            for point in section.points
        ),
    }


def _initial_marker_workflow(
    points: list[HydraulicSectionPointInput],
) -> tuple[dict[str, object], dict[str, object]]:
    """Create legacy-safe FULL_EXTENT markers and a raw-equivalent processed profile."""

    raw = [
        SectionPoint(
            sequence=value.sequence, offset=value.distance, elevation=value.elevation,
            x=value.x, y=value.y, point_code=value.point_code,
        )
        for value in points
    ]
    result = detect_markers(raw, "FULL_EXTENT")
    markers = marker_dict(result)
    explicit = {
        "M1": next((value for value in points if value.marker_type in {"left_bank", "left_levee"}), None),
        "M2": next((value for value in points if value.marker_type in {"main_channel", "thalweg"}), None),
        "M3": next((value for value in points if value.marker_type in {"right_bank", "right_levee"}), None),
    }
    for marker_type, value in explicit.items():
        if value is None:
            continue
        markers[marker_type] = {
            **markers[marker_type],
            "sequence": value.sequence,
            "offset": value.distance,
            "elevation": value.elevation,
            "x": value.x,
            "y": value.y,
            "source": "IMPORT_DEFAULT",
        }
    marker_config: dict[str, object] = {
        "markers": markers,
        "warnings": list(result.warnings),
        "review_status": result.review_status,
        "algorithm_version": ALGORITHM_VERSION,
    }
    processed: dict[str, object] = {
        "algorithm_version": ALGORITHM_VERSION,
        "points": [
            {
                "offset": value.distance, "elevation": value.elevation,
                "virtual": False, "source_sequence": value.sequence,
            }
            for value in points
        ],
        "warnings": [],
    }
    return marker_config, processed


def _known_branch_ranges(
    session: Session, dataset_version_id: int
) -> dict[str, tuple[float, float]]:
    """Return persisted adopted chainage limits for cross-section-only imports."""

    rows = session.execute(select(
        HydraulicBranch.branch_code,
        HydraulicBranch.start_chainage,
        HydraulicBranch.end_chainage,
    ).where(HydraulicBranch.dataset_version_id == dataset_version_id)).all()
    return {code: (float(start), float(end)) for code, start, end in rows}


def _known_branch_roles(session: Session, dataset_version_id: int) -> dict[str, str]:
    """Return persisted centerline semantics for section-only imports."""

    rows = session.execute(select(
        HydraulicBranch.branch_code,
        HydraulicBranch.metadata_json,
    ).where(HydraulicBranch.dataset_version_id == dataset_version_id)).all()
    return {
        code: str((metadata or {}).get("centerline_role", "unknown"))
        for code, metadata in rows
    }


def preview_import(
    session: Session, dataset_version_id: int, filename: str, content: bytes,
    coordinate_reference: CoordinateReferenceSpec,
) -> HydraulicImportPreview:
    """Persist an immutable preview with transformation evidence and no domain writes."""

    if session.get(DatasetVersion, dataset_version_id) is None:
        raise ValueError("Dataset version does not exist.")
    file_format = source_format(filename)
    payload: HydraulicExchangePayload | None = None
    parser_profile, native_status = "not-parsed", "NOT_PARSED"
    try:
        payload, parser_profile, native_status = parse_hydraulic_file(
            filename, content, coordinate_reference.source_srid
        )
        payload.coordinate_reference = coordinate_reference
        known_ranges = _known_branch_ranges(session, dataset_version_id)
        issues = validate_exchange(
            payload,
            set(known_ranges),
            known_ranges,
            _known_branch_roles(session, dataset_version_id),
        )
    except (HydraulicParseError, ValueError) as exc:
        issues = [HydraulicIssue(
            severity="error", code="IMPORT_PARSE_FAILED", message=str(exc)[:500],
            entity_type="file", entity_ref=filename,
        )]
    source_hash = hashlib.sha256(content).hexdigest()
    config_hash = preview_config_hash(source_hash, parser_profile, coordinate_reference)
    existing = session.scalar(select(HydraulicImportJob).where(
        HydraulicImportJob.dataset_version_id == dataset_version_id,
        HydraulicImportJob.source_hash_sha256 == source_hash,
        HydraulicImportJob.config_hash == config_hash,
    ))
    if existing is not None:
        stored = HydraulicExchangePayload.model_validate(existing.normalized_payload) if existing.normalized_payload else None
        return HydraulicImportPreview(job=_job_record(existing), payload=stored)
    rejected = any(v.severity == "error" for v in issues)
    entity = HydraulicImportJob(
        job_code=_code("HYDIMP"), dataset_version_id=dataset_version_id,
        filename=filename[:256], source_format=file_format,
        source_srid=coordinate_reference.source_srid, source_hash_sha256=source_hash,
        config_hash=config_hash,
        coordinate_reference=coordinate_reference.model_dump(mode="json"),
        transformation_evidence=transformation_evidence(session, payload, coordinate_reference),
        raw_content=content, parser_profile=parser_profile,
        status="rejected" if rejected else "previewed", record_counts=_record_counts(payload),
        issues=[v.model_dump(mode="json") for v in issues],
        normalized_payload=payload.model_dump(mode="json") if payload else None,
        native_validation_status=native_status,
        completed_at=datetime.now(UTC) if rejected else None,
    )
    session.add(entity)
    session.flush()
    return HydraulicImportPreview(job=_job_record(entity), payload=payload)


def list_import_jobs(session: Session, dataset_version_id: int) -> list[HydraulicImportJobRecord]:
    """Return newest-first import provenance for one version."""

    return [_job_record(v) for v in session.scalars(select(HydraulicImportJob).where(
        HydraulicImportJob.dataset_version_id == dataset_version_id
    ).order_by(HydraulicImportJob.id.desc())).all()]


def _upsert_network(
    session: Session, dataset_version_id: int, payload: HydraulicExchangePayload,
    spec: CoordinateReferenceSpec,
) -> HydraulicNetwork:
    """Create or update a version-scoped network coordinate contract."""

    network = session.scalar(select(HydraulicNetwork).where(
        HydraulicNetwork.dataset_version_id == dataset_version_id,
        HydraulicNetwork.code == payload.network_code,
    ))
    if network is None:
        network = HydraulicNetwork(dataset_version_id=dataset_version_id, code=payload.network_code)
        session.add(network)
    network.name = payload.network_name
    network.display_crs = "EPSG:4490"
    network.engineering_crs = spec.engineering_crs.upper()
    network.horizontal_unit = "m"
    network.vertical_datum = spec.vertical_datum
    network.vertical_unit = spec.vertical_unit
    network.source_kind = payload.source_kind
    network.metadata_json = {**(network.metadata_json or {}), "coordinate_reference": spec.model_dump(mode="json")}
    session.flush()
    return network


def _upsert_branch(
    session: Session, dataset_version_id: int, network: HydraulicNetwork,
    payload: HydraulicExchangePayload, source: HydraulicBranchInput,
    spec: CoordinateReferenceSpec, import_job_id: int,
) -> HydraulicBranch:
    """Write the authoritative branch and its legacy read projection atomically."""

    raw_geometry = {"type": "LineString", "coordinates": [[p.x, p.y] for p in source.points]}
    geometry = _source_geometry(raw_geometry, "LineString", spec)
    length_m = float(session.scalar(select(func.ST_Length(
        func.ST_Transform(geometry, spec.engineering_srid)
    ))) or 0)
    if length_m <= 0:
        raise ValueError(f"Branch {source.code} has zero projected length")
    branch = session.scalar(select(HydraulicBranch).where(
        HydraulicBranch.dataset_version_id == dataset_version_id,
        HydraulicBranch.branch_code == source.code,
    ))
    river = session.get(River, branch.legacy_river_id) if branch and branch.legacy_river_id else None
    if river is None:
        river = session.scalar(select(River).where(
            River.dataset_version_id == dataset_version_id, River.code == source.code,
        ))
    if river is None:
        river = River(
            dataset_version_id=dataset_version_id, name=source.river_name, code=source.code,
            length=length_m, level="main", status="active",
            description="Hydraulic authoritative branch compatibility projection", geometry=geometry,
        )
        session.add(river)
        session.flush()
    else:
        river.name, river.length, river.geometry = source.river_name, length_m, geometry
    if branch is None:
        branch = HydraulicBranch(
            dataset_version_id=dataset_version_id, network_id=network.id,
            legacy_river_id=river.id, branch_code=source.code,
            river_name=source.river_name, branch_name=source.branch_name,
            start_chainage=source.points[0].chainage,
            end_chainage=source.points[-1].chainage,
            length_m=length_m,
            direction_status=(
                "confirmed" if source.flow_direction in {"forward", "reverse"} else "unknown"
            ),
            geometry=geometry, source_revision=source.source_revision,
            metadata_json={
                "source_flow_direction": source.flow_direction,
                "centerline_role": source.centerline_role,
            },
        )
        session.add(branch)
        session.flush()
    else:
        session.execute(delete(HydraulicBranchVertex).where(HydraulicBranchVertex.branch_id == branch.id))
    branch.network_id = network.id
    branch.legacy_river_id = river.id
    branch.river_name = source.river_name
    branch.branch_name = source.branch_name
    branch.start_chainage = source.points[0].chainage
    branch.end_chainage = source.points[-1].chainage
    branch.length_m = length_m
    branch.direction_status = "confirmed" if source.flow_direction in {"forward", "reverse"} else "unknown"
    branch.geometry = geometry
    branch.source_revision = source.source_revision
    branch.metadata_json = {
        **(branch.metadata_json or {}),
        "source_flow_direction": source.flow_direction,
        "centerline_role": source.centerline_role,
    }
    pipeline = f"axis:{spec.axis_mapping};EPSG:{spec.source_srid}->EPSG:4490"
    for order, point in enumerate(source.points):
        session.add(HydraulicBranchVertex(
            dataset_version_id=dataset_version_id, branch_id=branch.id, vertex_order=order,
            chainage=point.chainage,
            geometry=_source_geometry({"type": "Point", "coordinates": [point.x, point.y]}, "Point", spec),
            source_x=point.x, source_y=point.y, source_z=point.z,
            source_crs=spec.source_crs.upper(), source_axis_mapping=spec.axis_mapping,
            transform_pipeline=pipeline, import_job_id=import_job_id,
            metadata_json={"point_code": point.point_code} if point.point_code else {},
        ))
    return branch


def _section_location(source: HydraulicCrossSectionInput, branch: HydraulicBranch, spec: CoordinateReferenceSpec):
    """Use surveyed location or interpolate adopted chainage on the branch."""

    if source.location_x is not None and source.location_y is not None:
        return _source_geometry({"type": "Point", "coordinates": [source.location_x, source.location_y]}, "Point", spec)
    fraction = (source.chainage - branch.start_chainage) / (branch.end_chainage - branch.start_chainage)
    return func.ST_LineInterpolatePoint(branch.geometry, min(1.0, max(0.0, fraction)))


def _replace_legacy_profile(
    session: Session, legacy: CrossSection, source: HydraulicCrossSectionInput,
    location, axis, spec: CoordinateReferenceSpec,
) -> None:
    """Maintain one active-profile projection for established GIS and v2 consumers."""

    for model in (CrossSectionPoint, CrossSectionLocation, CrossSectionAxis, CrossSectionProfile):
        session.execute(delete(model).where(model.cross_section_id == legacy.id))
    session.add(CrossSectionLocation(
        cross_section_id=legacy.id, dataset_version_id=legacy.dataset_version_id,
        geometry=location, survey_method=source.survey_method or "HYDRO-DATA-01_IMPORT",
    ))
    if axis is not None:
        session.add(CrossSectionAxis(
            cross_section_id=legacy.id, dataset_version_id=legacy.dataset_version_id,
            geometry=axis, left_bank=func.ST_StartPoint(axis), right_bank=func.ST_EndPoint(axis),
            vertical_datum=spec.vertical_datum,
        ))
    for point in source.points:
        point_geometry = None
        if point.x is not None and point.y is not None:
            point_geometry = _source_geometry({"type": "Point", "coordinates": [point.x, point.y]}, "Point", spec)
        session.add(CrossSectionPoint(
            cross_section_id=legacy.id, dataset_version_id=legacy.dataset_version_id,
            point_order=point.sequence, offset=point.distance, elevation=point.elevation,
            geometry=point_geometry,
        ))
    session.add(CrossSectionProfile(
        cross_section_id=legacy.id, dataset_version_id=legacy.dataset_version_id,
        profile={"points": [[p.distance, p.elevation] for p in source.points], "topography_id": source.topography_id},
        vertical_datum=spec.vertical_datum, source_revision="HYDRO-DATA-01",
    ))


def _profile_digest(source: HydraulicCrossSectionInput, spec: CoordinateReferenceSpec) -> str:
    """Hash all solver-significant profile content."""

    return canonical_hash({
        "topography_id": source.topography_id, "vertical_datum": spec.vertical_datum,
        "default_manning_n": source.default_manning_n,
        "points": [p.model_dump(mode="json") for p in source.points],
        "roughness_zones": [z.model_dump(mode="json") for z in source.roughness_zones],
    })


def _upsert_section(
    session: Session, dataset_version_id: int, source: HydraulicCrossSectionInput,
    branch: HydraulicBranch, spec: CoordinateReferenceSpec,
) -> HydraulicCrossSection:
    """Upsert one section location and one Topography ID profile."""

    section = session.scalar(select(HydraulicCrossSection).where(
        HydraulicCrossSection.dataset_version_id == dataset_version_id,
        HydraulicCrossSection.section_code == source.section_code,
    ))
    legacy = session.get(CrossSection, section.legacy_cross_section_id) if section and section.legacy_cross_section_id else None
    if legacy is None:
        legacy = session.scalar(select(CrossSection).where(
            CrossSection.dataset_version_id == dataset_version_id,
            CrossSection.section_code == source.section_code,
        ))
    location = _section_location(source, branch, spec)
    surveyed_point_axis = [
        (point.x, point.y) for point in source.points
        if point.x is not None and point.y is not None
    ]
    axis_coordinates = source.axis_points or (
        surveyed_point_axis if len(surveyed_point_axis) >= 2 and len(surveyed_point_axis) == len(source.points) else []
    )
    axis = _source_geometry(
        {"type": "LineString", "coordinates": [list(v) for v in axis_coordinates]}, "LineString", spec
    ) if axis_coordinates else None
    if legacy is None:
        legacy = CrossSection(
            dataset_version_id=dataset_version_id, river_id=branch.legacy_river_id,
            section_code=source.section_code, section_name=source.section_name or source.section_code,
            station=source.chainage, points={"points": [[p.distance, p.elevation] for p in source.points]},
            roughness=source.default_manning_n, elevation_min=min(p.elevation for p in source.points),
            survey_date=source.survey_date, geometry=location,
        )
        session.add(legacy)
        session.flush()
    else:
        legacy.river_id = branch.legacy_river_id
        legacy.section_name = source.section_name or source.section_code
        legacy.station = source.chainage
        legacy.points = {"points": [[p.distance, p.elevation] for p in source.points]}
        legacy.roughness = source.default_manning_n
        legacy.elevation_min = min(p.elevation for p in source.points)
        legacy.survey_date, legacy.geometry = source.survey_date, location
    _replace_legacy_profile(session, legacy, source, location, axis, spec)
    if section is None:
        section = HydraulicCrossSection(
            dataset_version_id=dataset_version_id, branch_id=branch.id,
            legacy_cross_section_id=legacy.id, section_code=source.section_code,
            section_name=source.section_name or source.section_code,
            chainage=source.chainage, chainage_source="imported",
            location_geometry=location, axis_geometry=axis,
            left_bank=func.ST_StartPoint(axis) if axis is not None else None,
            right_bank=func.ST_EndPoint(axis) if axis is not None else None,
            orientation_status="pending" if axis is None else "confirmed",
            bed_elevation_m=source.bed_elevation_m,
            bed_elevation_source=source.bed_elevation_source,
            bed_elevation_confirmed_by=source.bed_elevation_confirmed_by,
            bed_elevation_confirmed_at=source.bed_elevation_confirmed_at,
        )
        session.add(section)
        session.flush()
    section.branch_id = branch.id
    section.legacy_cross_section_id = legacy.id
    section.section_name = source.section_name or source.section_code
    section.chainage = source.chainage
    section.chainage_source = "imported"
    section.location_geometry = location
    section.axis_geometry = axis
    section.left_bank = func.ST_StartPoint(axis) if axis is not None else None
    section.right_bank = func.ST_EndPoint(axis) if axis is not None else None
    section.orientation_status = "pending" if axis is None else "confirmed"
    section.spatial_geometry_source = "SURVEY_XY" if axis is not None else "UNAVAILABLE"
    section.spatial_geometry_status = "SURVEY" if axis is not None else "UNAVAILABLE"
    section.derived_location_geometry = None
    section.derived_axis_geometry = None
    section.branch_intersection_station = None
    section.anchor_source = "MIDPOINT_FALLBACK"
    section.review_status = "REVIEWED" if axis is not None else "NEEDS_REVIEW"
    section.hydraulic_ready = True
    bed_fields = {
        "bed_elevation_m",
        "bed_elevation_source",
        "bed_elevation_confirmed_by",
        "bed_elevation_confirmed_at",
    }
    if bed_fields.intersection(source.model_fields_set):
        section.bed_elevation_m = source.bed_elevation_m
        section.bed_elevation_source = source.bed_elevation_source
        section.bed_elevation_confirmed_by = source.bed_elevation_confirmed_by
        section.bed_elevation_confirmed_at = source.bed_elevation_confirmed_at
    profile = session.scalar(select(HydraulicCrossSectionProfile).where(
        HydraulicCrossSectionProfile.cross_section_id == section.id,
        HydraulicCrossSectionProfile.topography_id == source.topography_id,
    ))
    session.execute(HydraulicCrossSectionProfile.__table__.update().where(
        HydraulicCrossSectionProfile.cross_section_id == section.id
    ).values(is_active=False))
    if profile is None:
        profile = HydraulicCrossSectionProfile(
            dataset_version_id=dataset_version_id, cross_section_id=section.id,
            topography_id=source.topography_id,
            survey_date=source.survey_date, survey_method=source.survey_method,
            vertical_datum=spec.vertical_datum, vertical_unit=spec.vertical_unit,
            default_manning_n=source.default_manning_n,
            profile_hash=_profile_digest(source, spec), is_active=True,
        )
        session.add(profile)
        session.flush()
    else:
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
    profile.survey_date = source.survey_date
    profile.survey_method = source.survey_method
    profile.vertical_datum = spec.vertical_datum
    profile.vertical_unit = spec.vertical_unit
    profile.default_manning_n = source.default_manning_n
    raw_profile_hash = _profile_digest(source, spec)
    profile.profile_hash = raw_profile_hash
    initial_marker_config, initial_processed_geometry = _initial_marker_workflow(source.points)
    profile.marker_detection_mode = "FULL_EXTENT"
    profile.active_extent_mode = "FULL_EXTENT"
    profile.overbank_treatment = "REAL_GEOMETRY"
    profile.extension_top_elevation_m = None
    profile.design_max_water_level_m = None
    profile.safety_freeboard_m = 0.0
    profile.marker_config_json = initial_marker_config
    profile.processed_geometry_json = initial_processed_geometry
    profile.processing_config_version = ALGORITHM_VERSION
    profile.metadata_json = {
        **(profile.metadata_json or {}),
        "raw_profile_hash": raw_profile_hash,
    }
    profile.is_active = True
    # Bulk-clearing the previous active row can leave an existing ORM instance
    # stale in long-lived import transactions.  Write the active flag directly
    # as the final profile-state assertion so downstream Marker/processing APIs
    # always see exactly one active profile for this section.
    session.execute(
        update(HydraulicCrossSectionProfile)
        .where(HydraulicCrossSectionProfile.id == profile.id)
        .values(is_active=True)
    )
    for point in source.points:
        point_geometry = None
        if point.x is not None and point.y is not None:
            point_geometry = _source_geometry({"type": "Point", "coordinates": [point.x, point.y]}, "Point", spec)
        session.add(HydraulicCrossSectionPoint(
            dataset_version_id=dataset_version_id, profile_id=profile.id,
            sequence=point.sequence, distance=point.distance, elevation=point.elevation,
            marker_type=point.marker_type, point_code=point.point_code,
            geometry=point_geometry, source_x=point.x, source_y=point.y, source_z=point.z,
            source_crs=spec.source_crs.upper() if point.x is not None else None,
            source_axis_mapping=spec.axis_mapping if point.x is not None else None,
        ))
    zones = source.roughness_zones or [HydraulicRoughnessZoneInput(
        zone_order=0, offset_start_m=source.points[0].distance,
        offset_end_m=source.points[-1].distance, manning_n=source.default_manning_n,
    )]
    for zone in zones:
        session.add(HydraulicRoughnessZone(
            dataset_version_id=dataset_version_id, profile_id=profile.id, **zone.model_dump()
        ))
    return section


def _engineering_vertices(session: Session, branch: HydraulicBranch, network: HydraulicNetwork):
    """Read branch vertices in the network's projected engineering CRS."""

    if not network.engineering_crs or not network.engineering_crs.upper().startswith("EPSG:"):
        raise ValueError("branch engineering CRS is unavailable")
    srid = int(network.engineering_crs.split(":", 1)[1])
    rows = session.execute(
        select(
            HydraulicBranchVertex.chainage,
            func.ST_X(func.ST_Transform(HydraulicBranchVertex.geometry, srid)),
            func.ST_Y(func.ST_Transform(HydraulicBranchVertex.geometry, srid)),
        )
        .where(HydraulicBranchVertex.branch_id == branch.id)
        .order_by(HydraulicBranchVertex.vertex_order)
    ).all()
    vertices = [(float(chainage), float(x), float(y)) for chainage, x, y in rows]
    if len(vertices) < 2:
        raise ValueError("branch has no usable ordered vertices")
    return vertices, srid


def _display_geometry(session: Session, x: float, y: float, srid: int) -> tuple[float, float]:
    """Transform one projected derived point to the platform display CRS."""

    row = session.execute(
        select(
            func.ST_X(func.ST_Transform(func.ST_SetSRID(func.ST_MakePoint(x, y), srid), 4490)),
            func.ST_Y(func.ST_Transform(func.ST_SetSRID(func.ST_MakePoint(x, y), srid), 4490)),
        )
    ).one()
    return float(row[0]), float(row[1])


def derive_section_spatial_geometry(
    session: Session, section_id: int, *, regenerate: bool = True
) -> HydraulicSectionDetail:
    """Derive one section line and marker points from branch+chainage.

    Survey ``axis_geometry`` and surveyed point ``geometry`` are authoritative and
    never overwritten.  Derived columns are disposable and can be regenerated.
    """

    section = session.get(HydraulicCrossSection, section_id)
    if section is None:
        raise ValueError("Hydraulic cross-section does not exist")
    assert_dataset_version_mutable(session, section.dataset_version_id)
    branch = session.get(HydraulicBranch, section.branch_id)
    network = session.get(HydraulicNetwork, branch.network_id) if branch else None
    if branch is None or network is None:
        raise ValueError("Cross-section branch or network does not exist")
    if section.axis_geometry is not None:
        section.spatial_geometry_source = "SURVEY_XY"
        section.spatial_geometry_status = "SURVEY"
        section.hydraulic_ready = True
        return get_section_detail(session, section.id)  # type: ignore[return-value]
    profile = session.scalar(
        select(HydraulicCrossSectionProfile)
        .where(
            HydraulicCrossSectionProfile.cross_section_id == section.id,
            HydraulicCrossSectionProfile.is_active.is_(True),
        )
        .order_by(HydraulicCrossSectionProfile.id.desc())
    )
    if profile is None:
        raise ValueError("Active cross-section profile does not exist")
    points = session.scalars(
        select(HydraulicCrossSectionPoint)
        .where(HydraulicCrossSectionPoint.profile_id == profile.id)
        .order_by(HydraulicCrossSectionPoint.sequence)
    ).all()
    if len(points) < 2:
        raise ValueError("cross-section profile has fewer than two points")
    # ``thalweg`` is the backwards-compatible imported representation of an
    # explicit MIKE11 Marker 2 in older workbooks; new imports use main_channel.
    marker2 = next(
        (point for point in points if point.marker_type in {"main_channel", "thalweg"}),
        None,
    )
    if marker2 is not None:
        anchor, anchor_source = marker2.distance, "MARKER_2_DERIVED"
        review_status = "REVIEWED" if marker2.marker_type == "main_channel" else "NEEDS_REVIEW"
    else:
        anchor = (points[0].distance + points[-1].distance) / 2.0
        anchor_source, review_status = "MIDPOINT_FALLBACK", "NEEDS_REVIEW"
    vertices, engineering_srid = _engineering_vertices(session, branch, network)
    derived = derive_section_geometry(
        vertices,
        section.chainage,
        [point.distance for point in points],
        anchor,
        {
            "marker1": next((point.distance for point in points if point.marker_type in {"left_bank", "left_levee"}), points[0].distance),
            "marker2": marker2.distance if marker2 is not None else anchor,
            "marker3": next((point.distance for point in points if point.marker_type in {"right_bank", "right_levee"}), points[-1].distance),
        },
    )
    if regenerate:
        display_points = [_display_geometry(session, x, y, engineering_srid) for x, y in derived.profile_points]
        intersection = _display_geometry(session, *derived.intersection, engineering_srid)
        line_wkt = "LINESTRING(" + ",".join(f"{x:.12f} {y:.12f}" for x, y in display_points) + ")"
        section.derived_location_geometry = WKTElement(
            f"POINT({intersection[0]:.12f} {intersection[1]:.12f})", srid=4490
        )
        section.derived_axis_geometry = WKTElement(line_wkt, srid=4490)
        section.branch_intersection_station = anchor
        section.anchor_source = anchor_source
        section.review_status = review_status
        section.spatial_geometry_source = "DERIVED_FROM_BRANCH"
        section.spatial_geometry_status = "DERIVED"
        section.orientation_status = "confirmed"
        section.hydraulic_ready = True
        for point, xy in zip(points, display_points):
            # Keep raw/survey geometry intact; only fill the disposable derived field.
            point.derived_geometry = WKTElement(
                f"POINT({xy[0]:.12f} {xy[1]:.12f})", srid=4490
            )
            point.metadata_json = {
                **(point.metadata_json or {}),
                "spatial_geometry_source": "DERIVED_FROM_BRANCH",
                "branch_intersection_station": anchor,
            }
        session.flush()
    result = get_section_detail(session, section.id)
    if result is None:
        raise ValueError("Hydraulic cross-section could not be reloaded")
    return result


def derive_dataset_spatial_geometry(session: Session, dataset_version_id: int) -> int:
    """Regenerate disposable geometry for every section in one dataset version."""

    assert_dataset_version_mutable(session, dataset_version_id)
    sections = session.scalars(
        select(HydraulicCrossSection).where(
            HydraulicCrossSection.dataset_version_id == dataset_version_id
        ).order_by(HydraulicCrossSection.id)
    ).all()
    for section in sections:
        try:
            derive_section_spatial_geometry(session, section.id)
        except ValueError:
            # Spatial geometry is a GIS capability, not a hydraulic readiness gate.
            # Keep the section calculable and expose the missing spatial evidence.
            section.derived_location_geometry = None
            section.derived_axis_geometry = None
            section.branch_intersection_station = None
            session.execute(
                update(HydraulicCrossSectionPoint)
                .where(
                    HydraulicCrossSectionPoint.profile_id.in_(
                        select(HydraulicCrossSectionProfile.id).where(
                            HydraulicCrossSectionProfile.cross_section_id == section.id
                        )
                    )
                )
                .values(derived_geometry=None)
            )
            section.spatial_geometry_source = "UNAVAILABLE"
            section.spatial_geometry_status = "UNAVAILABLE"
            section.review_status = "NEEDS_REVIEW"
            section.hydraulic_ready = True
    return len(sections)


def clear_section_spatial_geometry(session: Session, section_id: int) -> HydraulicSectionDetail:
    """Remove only disposable branch-derived geometry so it can be regenerated."""

    section = session.get(HydraulicCrossSection, section_id)
    if section is None:
        raise ValueError("Hydraulic cross-section does not exist")
    assert_dataset_version_mutable(session, section.dataset_version_id)
    if section.axis_geometry is not None:
        section.spatial_geometry_source = "SURVEY_XY"
        section.spatial_geometry_status = "SURVEY"
    else:
        section.spatial_geometry_source = "UNAVAILABLE"
        section.spatial_geometry_status = "UNAVAILABLE"
    section.derived_location_geometry = None
    section.derived_axis_geometry = None
    section.branch_intersection_station = None
    # The schema keeps anchor_source non-null for auditability.  With the
    # disposable geometry cleared there is no active anchor, so retain the
    # explicit review-required fallback label rather than inventing a station.
    section.anchor_source = "MIDPOINT_FALLBACK"
    section.review_status = "NEEDS_REVIEW"
    section.hydraulic_ready = True
    session.execute(
        update(HydraulicCrossSectionPoint)
        .where(
            HydraulicCrossSectionPoint.profile_id.in_(
                select(HydraulicCrossSectionProfile.id).where(
                    HydraulicCrossSectionProfile.cross_section_id == section.id
                )
            )
        )
        .values(derived_geometry=None)
    )
    session.flush()
    result = get_section_detail(session, section.id)
    if result is None:
        raise ValueError("Hydraulic cross-section could not be reloaded")
    return result


def _apply_payload(session: Session, job: HydraulicImportJob, payload: HydraulicExchangePayload) -> None:
    """Apply one validated payload inside the caller transaction."""

    spec = CoordinateReferenceSpec.model_validate(job.coordinate_reference)
    if payload.branches:
        network = _upsert_network(session, job.dataset_version_id, payload, spec)
    else:
        first = session.scalar(select(HydraulicBranch).where(
            HydraulicBranch.dataset_version_id == job.dataset_version_id,
            HydraulicBranch.branch_code == payload.sections[0].branch_code,
        ))
        if first is None:
            raise ValueError("Cross-section import cannot resolve its first branch")
        network = session.get(HydraulicNetwork, first.network_id)
        if network is None or network.engineering_crs != spec.engineering_crs.upper():
            raise ValueError("Cross-section coordinate contract does not match target network")
    branches = {v.branch_code: v for v in session.scalars(select(HydraulicBranch).where(
        HydraulicBranch.dataset_version_id == job.dataset_version_id,
        HydraulicBranch.network_id == network.id,
    )).all()}
    for source in payload.branches:
        branches[source.code] = _upsert_branch(
            session, job.dataset_version_id, network, payload, source, spec, job.id
        )
    session.flush()
    for source in payload.sections:
        branch = branches.get(source.branch_code)
        if branch is None:
            raise ValueError(f"Branch {source.branch_code} does not exist in target network")
        _upsert_section(session, job.dataset_version_id, source, branch, spec)
    session.flush()
    # Spatial lines are derived only after all branch vertices and profiles exist.
    # This keeps import atomic while leaving raw hydraulic values untouched.
    derive_dataset_spatial_geometry(session, job.dataset_version_id)


def commit_import(session: Session, job_code: str, preview_hash: str) -> HydraulicImportJobRecord:
    """Commit exactly the bytes and coordinate configuration that were previewed."""

    job = session.scalar(select(HydraulicImportJob).where(HydraulicImportJob.job_code == job_code))
    if job is None:
        raise ValueError("Hydraulic import job does not exist")
    assert_dataset_version_mutable(session, job.dataset_version_id)
    job = session.scalar(select(HydraulicImportJob).where(
        HydraulicImportJob.id == job.id
    ).with_for_update().execution_options(populate_existing=True))
    if job is None or job.status != "previewed" or job.normalized_payload is None:
        raise ValueError("Only a successfully previewed import can be committed once")
    if preview_hash != job.config_hash:
        raise ValueError("Preview configuration changed; run preview again before commit")
    payload = HydraulicExchangePayload.model_validate(job.normalized_payload)
    known_ranges = _known_branch_ranges(session, job.dataset_version_id)
    issues = validate_exchange(
        payload,
        set(known_ranges),
        known_ranges,
        _known_branch_roles(session, job.dataset_version_id),
    )
    job.issues = [v.model_dump(mode="json") for v in issues]
    if any(v.severity == "error" for v in issues):
        job.status, job.completed_at = "rejected", datetime.now(UTC)
    else:
        _apply_payload(session, job, payload)
        job.status, job.completed_at = "committed", datetime.now(UTC)
    session.flush()
    return _job_record(job)


def _processing_record(session: Session, value: HydraulicCrossSectionProcessing | None) -> HydraulicProcessingRecord | None:
    """Return one processing cache including its stage rows."""

    if value is None:
        return None
    rows = session.scalars(select(HydraulicCrossSectionHydraulicRow).where(
        HydraulicCrossSectionHydraulicRow.processing_id == value.id
    ).order_by(HydraulicCrossSectionHydraulicRow.stage_m)).all()
    return HydraulicProcessingRecord(
        id=value.id, profile_hash=value.profile_hash, processor_version=value.processor_version,
        vertical_step_m=value.vertical_step_m, status=value.status,
        minimum_stage_m=value.minimum_stage_m, maximum_stage_m=value.maximum_stage_m,
        generated_at=value.generated_at, diagnostics=value.diagnostics_json,
        rows=[HydraulicHydraulicRowRecord.model_validate(r, from_attributes=True) for r in rows],
    )


def _marker_workflow_record(profile: HydraulicCrossSectionProfile) -> HydraulicMarkerWorkflowRecord:
    """Serialize the independent Marker/Processed layer without touching raw points."""

    config = profile.marker_config_json or {}
    geometry = profile.processed_geometry_json or {}
    markers = config.get("markers", {})
    return HydraulicMarkerWorkflowRecord(
        profile_id=profile.id,
        marker_detection_mode=profile.marker_detection_mode,
        active_extent_mode=profile.active_extent_mode,
        overbank_treatment=profile.overbank_treatment,
        extension_top_elevation_m=profile.extension_top_elevation_m,
        design_max_water_level_m=profile.design_max_water_level_m,
        safety_freeboard_m=profile.safety_freeboard_m,
        processing_config_version=profile.processing_config_version,
        review_status=str(config.get("review_status", "NEEDS_REVIEW")),
        warnings=[str(value) for value in config.get("warnings", [])],
        markers=[
            HydraulicMarkerRecord.model_validate(markers[key])
            for key in ("M1", "M2", "M3") if key in markers
        ],
        processed_points=[
            HydraulicProcessedPointRecord.model_validate(value)
            for value in geometry.get("points", [])
        ],
    )


def _profile_record(session: Session, profile: HydraulicCrossSectionProfile) -> HydraulicProfileRecord:
    """Return ordered profile points, roughness, and newest matching processing cache."""

    points = session.scalars(select(HydraulicCrossSectionPoint).where(
        HydraulicCrossSectionPoint.profile_id == profile.id
    ).order_by(HydraulicCrossSectionPoint.sequence)).all()
    zones = session.scalars(select(HydraulicRoughnessZone).where(
        HydraulicRoughnessZone.profile_id == profile.id
    ).order_by(HydraulicRoughnessZone.zone_order)).all()
    processing = session.scalar(select(HydraulicCrossSectionProcessing).where(
        HydraulicCrossSectionProcessing.profile_id == profile.id,
        HydraulicCrossSectionProcessing.profile_hash == profile.profile_hash,
    ).order_by(HydraulicCrossSectionProcessing.id.desc()))
    return HydraulicProfileRecord(
        id=profile.id, topography_id=profile.topography_id, survey_date=profile.survey_date,
        survey_method=profile.survey_method, vertical_datum=profile.vertical_datum,
        vertical_unit=profile.vertical_unit, default_manning_n=profile.default_manning_n,
        profile_hash=profile.profile_hash, is_active=profile.is_active,
        points=[HydraulicSectionPointRecord(
            sequence=p.sequence, distance=p.distance, elevation=p.elevation,
            marker_type=p.marker_type, point_code=p.point_code,
            x=p.source_x, y=p.source_y, z=p.source_z,
            derived_x=(geometry_json(session, p.derived_geometry)["coordinates"][0]
                       if p.derived_geometry is not None else None),
            derived_y=(geometry_json(session, p.derived_geometry)["coordinates"][1]
                       if p.derived_geometry is not None else None),
        ) for p in points],
        roughness_zones=[HydraulicRoughnessZoneRecord.model_validate(z, from_attributes=True) for z in zones],
        processing=_processing_record(session, processing),
        marker_workflow=_marker_workflow_record(profile),
    )


def list_networks(session: Session, dataset_version_id: int) -> list[HydraulicNetworkRecord]:
    """Return the Network–Node–Branch–Reach–Section tree for one version."""

    records: list[HydraulicNetworkRecord] = []
    for network in session.scalars(select(HydraulicNetwork).where(
        HydraulicNetwork.dataset_version_id == dataset_version_id
    ).order_by(HydraulicNetwork.id)).all():
        nodes = session.scalars(select(HydraulicNode).where(
            HydraulicNode.network_id == network.id
        ).order_by(HydraulicNode.node_code)).all()
        branch_records: list[HydraulicBranchRecord] = []
        reach_total = 0
        for branch in session.scalars(select(HydraulicBranch).where(
            HydraulicBranch.network_id == network.id
        ).order_by(HydraulicBranch.branch_code)).all():
            vertex_count = int(session.scalar(select(func.count(HydraulicBranchVertex.id)).where(
                HydraulicBranchVertex.branch_id == branch.id
            )) or 0)
            reaches = session.scalars(select(HydraulicReach).where(
                HydraulicReach.branch_id == branch.id
            ).order_by(HydraulicReach.start_chainage_m)).all()
            reach_total += len(reaches)
            summaries: list[HydraulicSectionSummary] = []
            for section in session.scalars(select(HydraulicCrossSection).where(
                HydraulicCrossSection.branch_id == branch.id
            ).order_by(HydraulicCrossSection.chainage)).all():
                profile = session.scalar(select(HydraulicCrossSectionProfile).where(
                    HydraulicCrossSectionProfile.cross_section_id == section.id,
                    HydraulicCrossSectionProfile.is_active.is_(True),
                ).order_by(HydraulicCrossSectionProfile.id.desc()))
                summaries.append(HydraulicSectionSummary(
                    id=section.id, section_code=section.section_code, chainage=section.chainage,
                    topography_id=profile.topography_id if profile else "UNASSIGNED",
                    profile_count=int(session.scalar(select(func.count(HydraulicCrossSectionProfile.id)).where(
                        HydraulicCrossSectionProfile.cross_section_id == section.id
                    )) or 0),
                    point_count=int(session.scalar(select(func.count(HydraulicCrossSectionPoint.id)).where(
                        HydraulicCrossSectionPoint.profile_id == profile.id
                    )) or 0) if profile else 0,
                    orientation_status=section.orientation_status,
                    marker_review_status=(
                        str((profile.marker_config_json or {}).get("review_status", "NEEDS_REVIEW"))
                        if profile else "NEEDS_REVIEW"
                    ),
                    bed_elevation_m=section.bed_elevation_m,
                    bed_elevation_source=section.bed_elevation_source,
                ))
            reach_records = [HydraulicReachRecord(
                id=r.id, reach_code=r.reach_code, reach_type=r.reach_type,
                start_chainage_m=r.start_chainage_m, end_chainage_m=r.end_chainage_m,
                upstream_node_id=r.upstream_node_id, downstream_node_id=r.downstream_node_id,
                length_m=r.length_m, geometry=geometry_json(session, r.geometry),
            ) for r in reaches]
            branch_records.append(HydraulicBranchRecord(
                id=branch.id, legacy_river_id=branch.legacy_river_id,
                branch_code=branch.branch_code, river_name=branch.river_name,
                branch_name=branch.branch_name, start_chainage=branch.start_chainage,
                end_chainage=branch.end_chainage, length_m=branch.length_m,
                flow_direction=(branch.metadata_json or {}).get("source_flow_direction", "unknown"),
                centerline_role=(branch.metadata_json or {}).get("centerline_role", "unknown"),
                direction_status=branch.direction_status,
                source_revision=branch.source_revision,
                upstream_node_id=branch.upstream_node_id,
                downstream_node_id=branch.downstream_node_id,
                vertex_count=vertex_count, section_count=len(summaries), reach_count=len(reaches),
                reaches=reach_records, sections=summaries,
            ))
        records.append(HydraulicNetworkRecord(
            id=network.id, dataset_version_id=network.dataset_version_id,
            code=network.code, name=network.name, display_crs=network.display_crs,
            engineering_crs=network.engineering_crs, horizontal_unit=network.horizontal_unit,
            vertical_datum=network.vertical_datum, vertical_unit=network.vertical_unit,
            source_kind=network.source_kind, branch_count=len(branch_records),
            node_count=len(nodes), reach_count=reach_total,
            nodes=[HydraulicNodeRecord(
                id=n.id, node_code=n.node_code, node_name=n.node_name,
                node_type=n.node_type, geometry=geometry_json(session, n.geometry),
            ) for n in nodes], branches=branch_records,
        ))
    return records


def get_section_detail(session: Session, section_id: int) -> HydraulicSectionDetail | None:
    """Return a section location and all Topography ID profiles."""

    section = session.get(HydraulicCrossSection, section_id)
    if section is None:
        return None
    branch = session.get(HydraulicBranch, section.branch_id)
    if branch is None:
        return None
    profiles = session.scalars(select(HydraulicCrossSectionProfile).where(
        HydraulicCrossSectionProfile.cross_section_id == section.id
    ).order_by(HydraulicCrossSectionProfile.topography_id)).all()
    return HydraulicSectionDetail(
        id=section.id, dataset_version_id=section.dataset_version_id,
        branch_id=branch.id, branch_code=branch.branch_code,
        legacy_cross_section_id=section.legacy_cross_section_id,
        section_code=section.section_code, section_name=section.section_name,
        chainage=section.chainage, computed_chainage_m=section.computed_chainage_m,
        chainage_source=section.chainage_source, snap_distance_m=section.snap_distance_m,
        orientation_status=section.orientation_status,
        bed_elevation_m=section.bed_elevation_m,
        bed_elevation_source=section.bed_elevation_source,
        bed_elevation_confirmed_by=section.bed_elevation_confirmed_by,
        bed_elevation_confirmed_at=section.bed_elevation_confirmed_at,
        location_geometry=geometry_json(
            session, section.derived_location_geometry or section.location_geometry
        ),
        axis_geometry=(
            geometry_json(session, section.axis_geometry or section.derived_axis_geometry)
            if section.axis_geometry is not None or section.derived_axis_geometry is not None
            else None
        ),
        branch_intersection_station=section.branch_intersection_station,
        anchor_source=section.anchor_source,
        review_status=section.review_status,
        spatial_geometry_source=section.spatial_geometry_source,
        spatial_geometry_status=section.spatial_geometry_status,
        hydraulic_ready=section.hydraulic_ready,
        profiles=[_profile_record(session, v) for v in profiles],
    )


def _raw_marker_points(points: list[HydraulicCrossSectionPoint]) -> list[SectionPoint]:
    """Project ORM points to immutable pure-algorithm inputs."""

    return [
        SectionPoint(
            sequence=point.sequence,
            offset=point.distance,
            elevation=point.elevation,
            x=point.source_x,
            y=point.source_y,
            point_code=point.point_code,
        )
        for point in points
    ]


def _persist_processed_geometry(
    profile: HydraulicCrossSectionProfile,
    points: list[HydraulicCrossSectionPoint],
) -> None:
    """Regenerate disposable processed geometry from persisted workflow state."""

    config = profile.marker_config_json or {}
    processed, warnings = build_processed_geometry(
        _raw_marker_points(points),
        config.get("markers", {}),
        profile.active_extent_mode,
        profile.overbank_treatment,
        profile.extension_top_elevation_m,
        profile.design_max_water_level_m,
        profile.safety_freeboard_m,
    )
    raw_profile_hash = str(
        (profile.metadata_json or {}).get("raw_profile_hash")
        or (profile.processed_geometry_json or {}).get("raw_profile_hash")
        or profile.profile_hash
    )
    profile.metadata_json = {
        **(profile.metadata_json or {}),
        "raw_profile_hash": raw_profile_hash,
    }
    profile.processed_geometry_json = {
        "algorithm_version": ALGORITHM_VERSION,
        "raw_profile_hash": raw_profile_hash,
        "points": [
            {
                "offset": value.offset,
                "elevation": value.elevation,
                "virtual": value.virtual,
                "source_sequence": value.source_sequence,
            }
            for value in processed
        ],
        "warnings": warnings,
    }
    if warnings:
        profile.marker_config_json = {
            **config,
            "warnings": list(dict.fromkeys([*config.get("warnings", []), *warnings])),
            "review_status": "NEEDS_REVIEW",
        }


def _active_profile_and_points(
    session: Session, section: HydraulicCrossSection
) -> tuple[HydraulicCrossSectionProfile, list[HydraulicCrossSectionPoint]]:
    """Load one active profile and its stable raw point order."""

    profile = session.scalar(
        select(HydraulicCrossSectionProfile).where(
            HydraulicCrossSectionProfile.cross_section_id == section.id,
            HydraulicCrossSectionProfile.is_active.is_(True),
        ).order_by(HydraulicCrossSectionProfile.id.desc())
    )
    if profile is None:
        raise ValueError("Active cross-section profile does not exist")
    points = list(session.scalars(
        select(HydraulicCrossSectionPoint).where(
            HydraulicCrossSectionPoint.profile_id == profile.id
        ).order_by(HydraulicCrossSectionPoint.sequence)
    ).all())
    return profile, points


def detect_section_markers(
    session: Session, section_id: int, payload: HydraulicMarkerDetectionRequest
) -> HydraulicSectionDetail:
    """Run a deterministic marker strategy while preserving locked/manual markers."""

    section = session.get(HydraulicCrossSection, section_id)
    if section is None:
        raise ValueError("Hydraulic cross-section does not exist")
    assert_dataset_version_mutable(session, section.dataset_version_id)
    profile, points = _active_profile_and_points(session, section)
    existing = (profile.marker_config_json or {}).get("markers", {})
    result = detect_markers(_raw_marker_points(points), payload.mode, existing, force=payload.force)
    if not result.markers:
        raise ValueError(", ".join(result.warnings))
    records = marker_dict(result)
    warnings = list(result.warnings)
    if section.orientation_status != "confirmed" and section.spatial_geometry_source == "UNAVAILABLE":
        warnings.append("UNKNOWN_ORIENTATION")
    # marker_type is retained as a compatibility projection only.  Raw offset,
    # elevation, XYZ and point code remain unchanged.
    by_sequence = {point.sequence: point for point in points}
    for point in points:
        if point.marker_type in {"left_bank", "right_bank", "left_levee", "right_levee", "main_channel"}:
            point.marker_type = "none"
    for key, marker_type in (("M1", "left_levee"), ("M2", "main_channel"), ("M3", "right_levee")):
        by_sequence[int(records[key]["sequence"])].marker_type = marker_type
    profile.marker_detection_mode = payload.mode
    profile.marker_config_json = {
        "markers": records,
        "warnings": list(dict.fromkeys(warnings)),
        "review_status": "NEEDS_REVIEW" if warnings else result.review_status,
        "algorithm_version": ALGORITHM_VERSION,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    section.review_status = "NEEDS_REVIEW" if warnings else "REVIEWED"
    _persist_processed_geometry(profile, points)
    profile.profile_hash = canonical_hash({
        "raw_profile_hash": profile.metadata_json["raw_profile_hash"],
        "marker_config": profile.marker_config_json,
        "processing": {
            "active_extent_mode": profile.active_extent_mode,
            "overbank_treatment": profile.overbank_treatment,
            "extension_top_elevation_m": profile.extension_top_elevation_m,
        },
    })
    session.flush()
    if section.axis_geometry is None:
        return derive_section_spatial_geometry(session, section.id)
    result_detail = get_section_detail(session, section.id)
    if result_detail is None:
        raise ValueError("Hydraulic cross-section could not be reloaded")
    return result_detail


def update_marker_workflow(
    session: Session, profile_id: int, payload: HydraulicMarkerWorkflowUpdate
) -> HydraulicMarkerWorkflowRecord:
    """Update Active Extent and overbank treatment and rebuild derived geometry."""

    profile = session.get(HydraulicCrossSectionProfile, profile_id)
    if profile is None:
        raise ValueError("Hydraulic cross-section profile does not exist")
    assert_dataset_version_mutable(session, profile.dataset_version_id)
    points = list(session.scalars(
        select(HydraulicCrossSectionPoint).where(
            HydraulicCrossSectionPoint.profile_id == profile.id
        ).order_by(HydraulicCrossSectionPoint.sequence)
    ).all())
    profile.active_extent_mode = payload.active_extent_mode
    profile.overbank_treatment = payload.overbank_treatment
    profile.extension_top_elevation_m = payload.extension_top_elevation_m
    profile.design_max_water_level_m = payload.design_max_water_level_m
    profile.safety_freeboard_m = payload.safety_freeboard_m
    profile.processing_config_version = ALGORITHM_VERSION
    _persist_processed_geometry(profile, points)
    profile.profile_hash = canonical_hash({
        "raw_profile_hash": profile.metadata_json["raw_profile_hash"],
        "marker_config": profile.marker_config_json,
        "workflow": payload.model_dump(mode="json"),
        "algorithm_version": ALGORITHM_VERSION,
    })
    session.flush()
    return _marker_workflow_record(profile)


def batch_detect_markers(
    session: Session, payload: HydraulicBatchMarkerDetectionRequest
) -> HydraulicBatchMarkerDetectionRecord:
    """Process up to 1000 active profiles synchronously and return review statistics."""

    assert_dataset_version_mutable(session, payload.dataset_version_id)
    profiles = list(session.scalars(
        select(HydraulicCrossSectionProfile).where(
            HydraulicCrossSectionProfile.dataset_version_id == payload.dataset_version_id,
            HydraulicCrossSectionProfile.is_active.is_(True),
        ).order_by(HydraulicCrossSectionProfile.id).limit(1000)
    ).all())
    detected = needs_review = failed = locked_skipped = unknown_orientation = invalid_order = 0
    for profile in profiles:
        section = session.get(HydraulicCrossSection, profile.cross_section_id)
        unknown_orientation += bool(section and section.orientation_status != "confirmed")
        existing = (profile.marker_config_json or {}).get("markers", {})
        if existing and all(value.get("locked") for value in existing.values()) and not payload.force:
            locked_skipped += 1
            continue
        try:
            detail = detect_section_markers(
                session,
                profile.cross_section_id,
                HydraulicMarkerDetectionRequest(mode=payload.mode, force=payload.force),
            )
            detected += 1
            workflow = next(value.marker_workflow for value in detail.profiles if value.id == profile.id)
            needs_review += workflow.review_status == "NEEDS_REVIEW"
            invalid_order += "INVALID_MARKER_ORDER" in workflow.warnings
        except ValueError as exc:
            failed += 1
            invalid_order += "INVALID_MARKER_ORDER" in str(exc)
    return HydraulicBatchMarkerDetectionRecord(
        total_sections=len(profiles), detected=detected, needs_review=needs_review,
        failed=failed, locked_skipped=locked_skipped, unknown_orientation=unknown_orientation,
        invalid_marker_order=invalid_order,
    )


def update_section_markers(
    session: Session, section_id: int, payload: HydraulicMarkerUpdate
) -> HydraulicSectionDetail:
    """Persist MIKE11 Marker 1/3 selections without changing surveyed elevations."""

    section = session.get(HydraulicCrossSection, section_id)
    if section is None:
        raise ValueError("Hydraulic cross-section does not exist")
    assert_dataset_version_mutable(session, section.dataset_version_id)
    profile = session.scalar(
        select(HydraulicCrossSectionProfile).where(
            HydraulicCrossSectionProfile.cross_section_id == section.id,
            HydraulicCrossSectionProfile.is_active.is_(True),
        ).order_by(HydraulicCrossSectionProfile.id.desc())
    )
    if profile is None:
        # Older imports may have left every profile inactive after a bulk
        # replacement.  Promote the newest profile rather than blocking a
        # safe Marker edit; the section still remains version-scoped and the
        # promotion is recorded by the same transaction as the edit.
        profile = session.scalar(
            select(HydraulicCrossSectionProfile).where(
                HydraulicCrossSectionProfile.cross_section_id == section.id,
            ).order_by(HydraulicCrossSectionProfile.id.desc())
        )
        if profile is None:
            raise ValueError("Active cross-section profile does not exist")
        session.execute(
            update(HydraulicCrossSectionProfile)
            .where(HydraulicCrossSectionProfile.cross_section_id == section.id)
            .values(is_active=False)
        )
        profile.is_active = True
        session.flush()
    points = session.scalars(
        select(HydraulicCrossSectionPoint).where(
            HydraulicCrossSectionPoint.profile_id == profile.id
        ).order_by(HydraulicCrossSectionPoint.sequence)
    ).all()
    by_sequence = {point.sequence: point for point in points}
    for sequence in (payload.marker1_sequence, payload.marker2_sequence, payload.marker3_sequence):
        if sequence is not None and sequence not in by_sequence:
            raise ValueError(f"Marker sequence {sequence} does not exist in the active profile")
    # Replace only explicit MIKE11 control markers.  Raw elevation and station
    # values remain untouched, and thalweg/low-flow semantics are preserved.
    for point in points:
        if point.marker_type in {"left_bank", "right_bank", "left_levee", "right_levee", "main_channel"}:
            point.marker_type = "none"
    if payload.marker1_sequence is not None:
        by_sequence[payload.marker1_sequence].marker_type = "left_levee"
    if payload.marker2_sequence is not None:
        by_sequence[payload.marker2_sequence].marker_type = "main_channel"
    if payload.marker3_sequence is not None:
        by_sequence[payload.marker3_sequence].marker_type = "right_levee"
    manual_markers: dict[str, dict[str, object]] = {}
    marker_specs = (
        ("M1", "LEFT_LEVEE", payload.marker1_sequence, payload.lock_marker1),
        ("M2", "CHANNEL_LOW_POINT", payload.marker2_sequence, payload.lock_marker2),
        ("M3", "RIGHT_LEVEE", payload.marker3_sequence, payload.lock_marker3),
    )
    for marker_type, role, sequence, locked in marker_specs:
        if sequence is None:
            continue
        point = by_sequence[sequence]
        manual_markers[marker_type] = {
            "type": marker_type,
            "role": role,
            "sequence": point.sequence,
            "offset": point.distance,
            "elevation": point.elevation,
            "x": point.source_x,
            "y": point.source_y,
            "source": "MANUAL",
            "confidence": 1.0,
            "locked": locked,
            "review_status": "REVIEWED",
            "algorithm_version": ALGORITHM_VERSION,
            "notes": payload.notes,
        }
    profile.marker_detection_mode = "MANUAL"
    profile.marker_config_json = {
        "markers": manual_markers,
        "warnings": [],
        "review_status": "REVIEWED" if len(manual_markers) == 3 else "NEEDS_REVIEW",
        "algorithm_version": ALGORITHM_VERSION,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    section.review_status = "REVIEWED" if len(manual_markers) == 3 else "NEEDS_REVIEW"
    _persist_processed_geometry(profile, points)
    profile.metadata_json = {
        **(profile.metadata_json or {}),
        "mike11_marker_policy": "marker_1_to_3_active_extent",
        "marker1_sequence": payload.marker1_sequence,
        "marker2_sequence": payload.marker2_sequence,
        "marker3_sequence": payload.marker3_sequence,
        "marker_actor": payload.actor,
        "marker_updated_at": datetime.now(UTC).isoformat(),
    }
    profile.profile_hash = canonical_hash({
        "raw_profile_hash": profile.metadata_json["raw_profile_hash"],
        "marker1_sequence": payload.marker1_sequence,
        "marker2_sequence": payload.marker2_sequence,
        "marker3_sequence": payload.marker3_sequence,
        "points": [
            {"sequence": point.sequence, "distance": point.distance,
             "elevation": point.elevation, "marker_type": point.marker_type}
            for point in points
        ],
    })
    session.flush()
    if section.axis_geometry is None:
        return derive_section_spatial_geometry(session, section.id)
    result = get_section_detail(session, section.id)
    if result is None:
        raise ValueError("Hydraulic cross-section could not be reloaded")
    return result


def _point_xy(session: Session, geometry) -> tuple[float, float]:
    value = geometry_json(session, geometry)["coordinates"]
    return float(value[0]), float(value[1])


def build_exchange_payload(
    session: Session, dataset_version_id: int, network_id: int | None = None
) -> HydraulicExchangePayload:
    """Build an EPSG:4490 DTO while preserving every Topography ID."""

    statement = select(HydraulicNetwork).where(HydraulicNetwork.dataset_version_id == dataset_version_id)
    if network_id is not None:
        statement = statement.where(HydraulicNetwork.id == network_id)
    networks = session.scalars(statement.order_by(HydraulicNetwork.id)).all()
    if not networks:
        raise ValueError("Hydraulic network does not exist for the selected version")
    if len(networks) > 1:
        raise ValueError("network_id is required when a Dataset Version has multiple networks")
    network = networks[0]
    branches: list[HydraulicBranchInput] = []
    sections: list[HydraulicCrossSectionInput] = []
    for branch in session.scalars(select(HydraulicBranch).where(
        HydraulicBranch.network_id == network.id
    ).order_by(HydraulicBranch.branch_code)).all():
        vertices = session.scalars(select(HydraulicBranchVertex).where(
            HydraulicBranchVertex.branch_id == branch.id
        ).order_by(HydraulicBranchVertex.vertex_order)).all()
        branches.append(HydraulicBranchInput(
            code=branch.branch_code, river_name=branch.river_name,
            branch_name=branch.branch_name,
            flow_direction=(branch.metadata_json or {}).get("source_flow_direction", "unknown"),
            centerline_role=(branch.metadata_json or {}).get("centerline_role", "unknown"),
            source_revision=branch.source_revision,
            points=[HydraulicChainageInput(
                chainage=p.chainage, x=_point_xy(session, p.geometry)[0],
                y=_point_xy(session, p.geometry)[1], z=p.source_z,
            ) for p in vertices],
        ))
        for section in session.scalars(select(HydraulicCrossSection).where(
            HydraulicCrossSection.branch_id == branch.id
        ).order_by(HydraulicCrossSection.chainage)).all():
            location = _point_xy(session, section.location_geometry)
            axis: list[tuple[float, float]] = []
            if section.axis_geometry is not None:
                axis = [tuple(map(float, v[:2])) for v in geometry_json(session, section.axis_geometry)["coordinates"]]
            for profile in session.scalars(select(HydraulicCrossSectionProfile).where(
                HydraulicCrossSectionProfile.cross_section_id == section.id
            ).order_by(HydraulicCrossSectionProfile.topography_id)).all():
                detail = _profile_record(session, profile)
                sections.append(HydraulicCrossSectionInput(
                    section_code=section.section_code, section_name=section.section_name,
                    branch_code=branch.branch_code, chainage=section.chainage,
                    topography_id=profile.topography_id, survey_date=profile.survey_date,
                    survey_method=profile.survey_method, default_manning_n=profile.default_manning_n,
                    bed_elevation_m=section.bed_elevation_m,
                    bed_elevation_source=section.bed_elevation_source,
                    bed_elevation_confirmed_by=section.bed_elevation_confirmed_by,
                    bed_elevation_confirmed_at=section.bed_elevation_confirmed_at,
                    location_x=location[0], location_y=location[1], axis_points=axis,
                    roughness_zones=[HydraulicRoughnessZoneInput.model_validate(z.model_dump()) for z in detail.roughness_zones],
                    points=[HydraulicSectionPointInput.model_validate(p.model_dump()) for p in detail.points],
                ))
    return HydraulicExchangePayload(
        network_code=network.code, network_name=network.name, source_srid=4490,
        source_kind="api", branches=branches, sections=sections,
    )


def run_validation(session: Session, dataset_version_id: int) -> HydraulicValidationRunRecord:
    """Persist the production data-readiness gate for one version."""

    if session.get(DatasetVersion, dataset_version_id) is None:
        raise ValueError("Dataset version does not exist")
    run = HydraulicValidationRun(
        run_code=_code("HYDVAL"), dataset_version_id=dataset_version_id,
        status="running", summary={},
    )
    session.add(run)
    session.flush()
    networks = session.scalars(select(HydraulicNetwork).where(
        HydraulicNetwork.dataset_version_id == dataset_version_id
    )).all()
    issues: list[HydraulicIssue] = []
    if not networks:
        issues.append(HydraulicIssue(
            severity="error", code="NETWORK_MISSING", message="目标数据版本没有水动力网络",
            entity_type="dataset", entity_ref=str(dataset_version_id),
        ))
    for network in networks:
        if network.engineering_crs is None:
            issues.append(HydraulicIssue(
                severity="error", code="ENGINEERING_CRS_UNCONFIRMED",
                message="河网尚未确认米制工程坐标系", entity_type="network", entity_ref=str(network.id),
            ))
        branches = session.scalars(select(HydraulicBranch).where(HydraulicBranch.network_id == network.id)).all()
        if not branches:
            issues.append(HydraulicIssue(
                severity="error", code="BRANCH_MISSING", message="河网没有河段",
                entity_type="network", entity_ref=str(network.id),
            ))
        for branch in branches:
            if branch.direction_status != "confirmed":
                issues.append(HydraulicIssue(
                    severity="error", code="FLOW_DIRECTION_UNCONFIRMED", message="河段流向未确认",
                    entity_type="branch", entity_ref=str(branch.id),
                ))
            if branch.upstream_node_id is None or branch.downstream_node_id is None:
                issues.append(HydraulicIssue(
                    severity="error", code="TOPOLOGY_NOT_BUILT", message="河段尚未连接正式拓扑节点",
                    entity_type="branch", entity_ref=str(branch.id),
                ))
        try:
            issues.extend(validate_exchange(build_exchange_payload(session, dataset_version_id, network.id)))
        except ValueError as exc:
            issues.append(HydraulicIssue(
                severity="error", code="EXCHANGE_BUILD_FAILED", message=str(exc),
                entity_type="network", entity_ref=str(network.id),
            ))
    counts = {key: sum(v.severity == key for v in issues) for key in ("error", "warning", "info", "passed")}
    run.status = "failed" if counts["error"] else "passed"
    run.summary = {**counts, "passed_gate": counts["error"] == 0}
    run.completed_at = datetime.now(UTC)
    for issue in issues:
        context = {**issue.context, **({"entity_ref": issue.entity_ref} if issue.entity_ref else {})}
        session.add(HydraulicValidationResult(
            run_id=run.id, severity=issue.severity, rule_code=issue.code,
            entity_type=issue.entity_type or "dataset", message=issue.message, context=context,
        ))
    session.flush()
    return _validation_record(session, run)


def _validation_record(session: Session, run: HydraulicValidationRun) -> HydraulicValidationRunRecord:
    rows = session.scalars(select(HydraulicValidationResult).where(
        HydraulicValidationResult.run_id == run.id
    ).order_by(HydraulicValidationResult.id)).all()
    return HydraulicValidationRunRecord(
        id=run.id, run_code=run.run_code, dataset_version_id=run.dataset_version_id,
        status=run.status, summary=run.summary, created_at=run.created_at,
        completed_at=run.completed_at,
        results=[HydraulicIssue(
            severity=row.severity, code=row.rule_code, message=row.message,
            entity_type=row.entity_type, entity_ref=(row.context or {}).get("entity_ref"),
            context={k: v for k, v in (row.context or {}).items() if k != "entity_ref"},
        ) for row in rows],
    )


def get_validation_run(session: Session, run_code: str) -> HydraulicValidationRunRecord | None:
    run = session.scalar(select(HydraulicValidationRun).where(HydraulicValidationRun.run_code == run_code))
    return _validation_record(session, run) if run is not None else None


def capabilities() -> HydraulicCapabilityResponse:
    """Describe the in-process and external-adapter boundaries."""

    return HydraulicCapabilityResponse(
        exchange_profile="HYDRO-DATA-01 production exchange v2",
        native_xns11_available=False, native_nwk11_available=False,
        supported_imports=[".nwk11 subset", ".xns11 subset", ".xlsx", ".csv", ".geojson", ".json", ".zip (SHP)", ".dxf"],
        supported_exports=[".nwk11 deterministic subset", ".xns11 deterministic subset"],
        source_srids=sorted(ALLOWED_SOURCE_SRIDS),
        engineering_srids=sorted(ALLOWED_ENGINEERING_SRIDS),
        axis_mappings=["x_easting_y_northing", "x_northing_y_easting"],
        limitation=(
            "Native MIKE11 parsing and writing are outside the server runtime; "
            "licensed-environment validation remains an external acceptance step."
        ),
    )
