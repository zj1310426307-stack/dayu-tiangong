"""Cross-section location and deterministic hydraulic-table processing."""

from __future__ import annotations

from datetime import UTC, datetime
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dataset.lifecycle import assert_dataset_version_mutable
from app.hydraulic.models import (
    HydraulicBranch,
    HydraulicCrossSection,
    HydraulicCrossSectionHydraulicRow,
    HydraulicCrossSectionPoint,
    HydraulicCrossSectionProcessing,
    HydraulicCrossSectionProfile,
    HydraulicNetwork,
    HydraulicRoughnessZone,
)
from app.hydraulic.location import locate_geometry_on_branch
from app.hydraulic.schemas import HydraulicLocateRequest, HydraulicProcessingRecord
from model.geometry import TabulatedSectionGeometry


PROCESSOR_VERSION = "tabulated-section-v2-segmented-roughness"


def _submerged_interval_metrics(
    points: list[tuple[float, float]], stage_m: float, left_m: float, right_m: float
) -> tuple[float, float, float]:
    """Integrate wetted area, top width, and bed perimeter over one offset interval."""

    area_m2 = top_width_m = wetted_perimeter_m = 0.0
    for (x1, z1), (x2, z2) in zip(points, points[1:]):
        segment_left, segment_right = max(x1, left_m), min(x2, right_m)
        if segment_right <= segment_left:
            continue
        span = x2 - x1
        left_ratio = (segment_left - x1) / span
        right_ratio = (segment_right - x1) / span
        left_z = z1 + (z2 - z1) * left_ratio
        right_z = z1 + (z2 - z1) * right_ratio
        left_depth, right_depth = stage_m - left_z, stage_m - right_z
        if left_depth <= 0 and right_depth <= 0:
            continue
        width = segment_right - segment_left
        if left_depth >= 0 and right_depth >= 0:
            area_m2 += 0.5 * (left_depth + right_depth) * width
            top_width_m += width
            wetted_perimeter_m += math.hypot(width, right_z - left_z)
            continue
        crossing_ratio = left_depth / (left_depth - right_depth)
        crossing_x = segment_left + crossing_ratio * width
        if left_depth > 0:
            wet_width = crossing_x - segment_left
            wet_vertical = stage_m - left_z
            positive_depth = left_depth
        else:
            wet_width = segment_right - crossing_x
            wet_vertical = right_z - stage_m
            positive_depth = right_depth
        area_m2 += 0.5 * positive_depth * wet_width
        top_width_m += wet_width
        wetted_perimeter_m += math.hypot(wet_width, wet_vertical)
    return area_m2, top_width_m, wetted_perimeter_m


def _roughness_intervals(
    points: list[tuple[float, float]],
    zones: list[HydraulicRoughnessZone],
    default_manning_n: float,
) -> list[tuple[float, float, float]]:
    """Fill uncovered profile spans with default Manning n and reject overlap."""

    lower, upper = points[0][0], points[-1][0]
    cursor = lower
    intervals: list[tuple[float, float, float]] = []
    for zone in sorted(zones, key=lambda value: value.offset_start_m):
        start, end = max(lower, zone.offset_start_m), min(upper, zone.offset_end_m)
        if end <= start:
            continue
        if start < cursor - 1.0e-9:
            raise ValueError("Persisted roughness zones overlap")
        if start > cursor:
            intervals.append((cursor, start, default_manning_n))
        intervals.append((start, end, zone.manning_n))
        cursor = end
    if cursor < upper:
        intervals.append((cursor, upper, default_manning_n))
    return intervals or [(lower, upper, default_manning_n)]


def _processing_record(
    session: Session, value: HydraulicCrossSectionProcessing
) -> HydraulicProcessingRecord:
    """Return one persisted table in API shape."""

    from app.hydraulic.service import _processing_record as record

    result = record(session, value)
    assert result is not None
    return result


def process_profile(
    session: Session, profile_id: int, vertical_step_m: float
) -> HydraulicProcessingRecord:
    """Build or reuse an immutable stage/property table keyed by profile hash."""

    profile = session.get(HydraulicCrossSectionProfile, profile_id)
    if profile is None:
        raise ValueError("Hydraulic cross-section profile does not exist")
    assert_dataset_version_mutable(session, profile.dataset_version_id)
    cached = session.scalar(
        select(HydraulicCrossSectionProcessing).where(
            HydraulicCrossSectionProcessing.profile_id == profile.id,
            HydraulicCrossSectionProcessing.profile_hash == profile.profile_hash,
            HydraulicCrossSectionProcessing.processor_version == PROCESSOR_VERSION,
            HydraulicCrossSectionProcessing.vertical_step_m == vertical_step_m,
            HydraulicCrossSectionProcessing.status == "ready",
        )
    )
    if cached is not None:
        return _processing_record(session, cached)
    points = session.scalars(
        select(HydraulicCrossSectionPoint)
        .where(HydraulicCrossSectionPoint.profile_id == profile.id)
        .order_by(HydraulicCrossSectionPoint.sequence)
    ).all()
    roughness_zones = session.scalars(
        select(HydraulicRoughnessZone)
        .where(HydraulicRoughnessZone.profile_id == profile.id)
        .order_by(HydraulicRoughnessZone.zone_order)
    ).all()
    profile_points = [(value.distance, value.elevation) for value in points]
    geometry = TabulatedSectionGeometry.from_points(profile_points, vertical_step=vertical_step_m)
    intervals = _roughness_intervals(
        profile_points, list(roughness_zones), profile.default_manning_n
    )
    processing = HydraulicCrossSectionProcessing(
        dataset_version_id=profile.dataset_version_id,
        profile_id=profile.id,
        profile_hash=profile.profile_hash,
        processor_version=PROCESSOR_VERSION,
        vertical_step_m=vertical_step_m,
        status="ready",
        minimum_stage_m=geometry.minimum_stage,
        maximum_stage_m=geometry.maximum_stage,
        generated_at=datetime.now(UTC),
        diagnostics_json={
            "stage_count": len(geometry.stages),
            "roughness_method": "segmented_manning_conveyance",
            "roughness_interval_count": len(intervals),
        },
    )
    session.add(processing)
    session.flush()
    for stage in geometry.stages:
        area = top_width = perimeter = conveyance = 0.0
        for left, right, manning_n in intervals:
            zone_area, zone_width, zone_perimeter = _submerged_interval_metrics(
                profile_points, stage, left, right
            )
            area += zone_area
            top_width += zone_width
            perimeter += zone_perimeter
            zone_radius = zone_area / max(zone_perimeter, 1.0e-12)
            if zone_area > 0:
                conveyance += zone_area * zone_radius ** (2.0 / 3.0) / manning_n
        radius = area / max(perimeter, 1.0e-12)
        session.add(
            HydraulicCrossSectionHydraulicRow(
                dataset_version_id=profile.dataset_version_id,
                processing_id=processing.id,
                stage_m=stage,
                area_m2=area,
                top_width_m=top_width,
                wetted_perimeter_m=perimeter,
                hydraulic_radius_m=radius,
                conveyance=conveyance,
            )
        )
    session.flush()
    return _processing_record(session, processing)


def batch_process(
    session: Session, profile_ids: list[int], vertical_step_m: float
) -> list[HydraulicProcessingRecord]:
    """Process a bounded profile selection in deterministic input order."""

    return [process_profile(session, profile_id, vertical_step_m) for profile_id in profile_ids]


def locate_section(session: Session, section_id: int, request: HydraulicLocateRequest):
    """Compute branch chainage from the surveyed axis in the engineering CRS."""

    section = session.get(HydraulicCrossSection, section_id)
    if section is None:
        raise ValueError("Hydraulic cross-section does not exist")
    assert_dataset_version_mutable(session, section.dataset_version_id)
    branch = session.get(HydraulicBranch, section.branch_id)
    network = session.get(HydraulicNetwork, branch.network_id) if branch else None
    if branch is None or network is None or network.engineering_crs is None:
        raise ValueError("Cross-section branch or engineering CRS is unavailable")
    if section.axis_geometry is None:
        raise ValueError("Cross-section axis is required for chainage computation")
    computed, distance_m = locate_geometry_on_branch(
        session, branch, network, section.axis_geometry
    )
    section.computed_chainage_m = computed
    section.snap_distance_m = distance_m
    if distance_m > request.snap_tolerance_m:
        raise ValueError("Cross-section axis is outside the configured branch snap tolerance")
    if request.manual_chainage_m is not None:
        section.chainage = request.manual_chainage_m
        section.chainage_source = "manual_override"
        section.manual_override_reason = request.override_reason
        section.manual_override_actor = request.actor
        section.manual_override_at = datetime.now(UTC)
    else:
        section.chainage = computed
        section.chainage_source = "computed"
    section.orientation_status = "confirmed"
    session.flush()
    from app.hydraulic.service import get_section_detail

    return get_section_detail(session, section.id)
