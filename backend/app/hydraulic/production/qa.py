"""Central production model QA with one authoritative run gate."""

from __future__ import annotations

from collections import Counter, defaultdict
import math
from statistics import mean, median

from app.hydraulic.production.contracts import (
    HydraulicModelQARequest,
    HydraulicModelQAResult,
    ProductionBranch,
    ProductionCrossSection,
    QAIssue,
)


RULESET_VERSION = "hydraulic-production-qa-v1"


def _point_geometry(point: tuple[float, float] | None) -> dict[str, object] | None:
    """Return map-ready geometry without inventing a location."""

    if point is None:
        return None
    return {"type": "Point", "coordinates": [float(point[0]), float(point[1])]}


def _line_geometry(points: list[tuple[float, float]]) -> dict[str, object] | None:
    """Return a factual LineString when an axis or centerline exists."""

    if len(points) < 2:
        return None
    return {
        "type": "LineString",
        "coordinates": [[float(x), float(y)] for x, y in points],
    }


def _orientation(
    left: tuple[float, float], right: tuple[float, float], point: tuple[float, float]
) -> float:
    """Return the signed two-dimensional orientation determinant."""

    return (right[0] - left[0]) * (point[1] - left[1]) - (
        right[1] - left[1]
    ) * (point[0] - left[0])


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    """Detect a proper/touching intersection for QA geometry diagnostics."""

    first, second = _orientation(a, b, c), _orientation(a, b, d)
    third, fourth = _orientation(c, d, a), _orientation(c, d, b)
    return first * second <= 0 and third * fourth <= 0


def _axis_intersections(section: ProductionCrossSection, branch: ProductionBranch) -> int:
    """Count axis/centerline segment intersections."""

    return sum(
        _segments_intersect(left, right, start, end)
        for left, right in zip(section.axis, section.axis[1:])
        for start, end in zip(branch.centerline, branch.centerline[1:])
    )


def _distance_point_segment(
    point: tuple[float, float], left: tuple[float, float], right: tuple[float, float]
) -> float:
    """Return a Euclidean projected distance for the declared engineering CRS."""

    dx, dy = right[0] - left[0], right[1] - left[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 0:
        return math.hypot(point[0] - left[0], point[1] - left[1])
    fraction = max(
        0.0,
        min(1.0, ((point[0] - left[0]) * dx + (point[1] - left[1]) * dy) / length_squared),
    )
    projection = (left[0] + fraction * dx, left[1] + fraction * dy)
    return math.hypot(point[0] - projection[0], point[1] - projection[1])


def _distance_to_branch(point: tuple[float, float], branch: ProductionBranch) -> float:
    """Return minimum point-to-centerline distance."""

    return min(
        _distance_point_segment(point, left, right)
        for left, right in zip(branch.centerline, branch.centerline[1:])
    )


class HydraulicModelQA:
    """Run all pre-simulation production checks from one backend-owned ruleset."""

    def validate(self, request: HydraulicModelQARequest) -> HydraulicModelQAResult:
        """Return errors, warnings, statistics, and the non-bypassable run decision."""

        issues: list[QAIssue] = []
        self._validate_crs(request, issues)
        branch_by_id = self._validate_network(request, issues)
        spacing, thalweg = self._validate_sections(request, branch_by_id, issues)
        self._validate_boundaries(request, branch_by_id, issues)
        self._validate_structures(request, branch_by_id, issues)
        self._validate_observations(request, issues)
        counts = Counter(issue.severity for issue in issues)
        return HydraulicModelQAResult(
            ruleset_version=RULESET_VERSION,
            error_count=counts["ERROR"],
            warning_count=counts["WARNING"],
            info_count=counts["INFO"],
            run_allowed=counts["ERROR"] == 0,
            issues=issues,
            spacing_statistics=spacing,
            thalweg_profile=thalweg,
        )

    @staticmethod
    def _validate_crs(request: HydraulicModelQARequest, issues: list[QAIssue]) -> None:
        """Fail closed on geographic/unknown engineering CRS or vertical datum."""

        crs = request.engineering_crs.strip().upper()
        if not crs.startswith("EPSG:") or crs in {"EPSG:4326", "EPSG:4490"}:
            issues.append(
                QAIssue(
                    code="QA_CRS_ENGINEERING_PROJECTED_REQUIRED",
                    severity="ERROR",
                    category="CRS",
                    entity_type="Network",
                    message="Production chainage and spacing require a confirmed projected engineering CRS.",
                    suggestion="Declare the surveyed projected CRS, central meridian, unit, and axis order.",
                    context={"engineering_crs": request.engineering_crs},
                )
            )
        if request.horizontal_unit != "m":
            issues.append(
                QAIssue(
                    code="QA_CRS_HORIZONTAL_UNIT_M_REQUIRED",
                    severity="ERROR",
                    category="CRS",
                    entity_type="Network",
                    message="Production hydraulic distances must use metres.",
                    context={"horizontal_unit": request.horizontal_unit},
                )
            )
        if request.vertical_datum.strip().upper() == "UNKNOWN":
            issues.append(
                QAIssue(
                    code="QA_DATUM_UNKNOWN",
                    severity="ERROR",
                    category="CRS",
                    entity_type="Network",
                    message="Vertical datum is unknown; elevations cannot be combined safely.",
                    suggestion="Confirm one datum or provide an explicit audited transformation.",
                )
            )

    @staticmethod
    def _validate_network(
        request: HydraulicModelQARequest, issues: list[QAIssue]
    ) -> dict[str, ProductionBranch]:
        """Check branch identities, direction, nodes, and centerline geometry."""

        if not request.branches:
            issues.append(
                QAIssue(
                    code="QA_NETWORK_EMPTY",
                    severity="ERROR",
                    category="Network",
                    entity_type="Network",
                    message="Hydraulic network contains no branches.",
                )
            )
            return {}
        duplicates = {
            value for value, count in Counter(branch.branch_id for branch in request.branches).items()
            if count > 1
        }
        branch_by_id: dict[str, ProductionBranch] = {}
        for branch in request.branches:
            branch_by_id.setdefault(branch.branch_id, branch)
            geometry = _line_geometry(branch.centerline)
            if branch.branch_id in duplicates:
                issues.append(
                    QAIssue(
                        code="QA_NETWORK_DUPLICATE_BRANCH_ID",
                        severity="ERROR",
                        category="Network",
                        entity_type="Branch",
                        entity_id=branch.branch_id,
                        message="Branch identifier is duplicated.",
                        location=geometry,
                    )
                )
            if not branch.direction_confirmed:
                issues.append(
                    QAIssue(
                        code="QA_NETWORK_DIRECTION_UNCONFIRMED",
                        severity="ERROR",
                        category="Network",
                        entity_type="Branch",
                        entity_id=branch.branch_id,
                        message="Branch hydraulic direction is not confirmed.",
                        suggestion="Confirm upstream/downstream direction before simulation.",
                        location=geometry,
                    )
                )
            if not branch.upstream_node_id or not branch.downstream_node_id:
                issues.append(
                    QAIssue(
                        code="QA_NETWORK_ENDPOINT_NODE_MISSING",
                        severity="ERROR",
                        category="Network",
                        entity_type="Branch",
                        entity_id=branch.branch_id,
                        message="Branch requires explicit upstream and downstream nodes.",
                        location=geometry,
                    )
                )
            if len(set(branch.centerline)) != len(branch.centerline):
                issues.append(
                    QAIssue(
                        code="QA_NETWORK_DUPLICATE_CENTERLINE_VERTEX",
                        severity="WARNING",
                        category="Network",
                        entity_type="Branch",
                        entity_id=branch.branch_id,
                        message="Branch centerline contains duplicate vertices.",
                        location=geometry,
                    )
                )
        return branch_by_id

    @staticmethod
    def _validate_sections(
        request: HydraulicModelQARequest,
        branch_by_id: dict[str, ProductionBranch],
        issues: list[QAIssue],
    ) -> tuple[dict[str, float | int | None], list[dict[str, float | str]]]:
        """Check ordering, spacing, geometry, orientation, and thalweg behavior."""

        grouped: dict[str, list[ProductionCrossSection]] = defaultdict(list)
        identities = Counter(
            (section.branch_id, float(section.chainage_m)) for section in request.cross_sections
        )
        thalweg: list[dict[str, float | str]] = []
        all_spacings: list[float] = []
        for section in request.cross_sections:
            grouped[section.branch_id].append(section)
            branch = branch_by_id.get(section.branch_id)
            location = _line_geometry(section.axis) or _point_geometry(section.location)
            if branch is None:
                issues.append(
                    QAIssue(
                        code="QA_SECTION_BRANCH_UNKNOWN",
                        severity="ERROR",
                        category="CrossSection",
                        entity_type="CrossSection",
                        entity_id=section.section_id,
                        message="Cross Section references an unknown Branch.",
                        location=location,
                    )
                )
                continue
            if not branch.start_chainage_m <= section.chainage_m <= branch.end_chainage_m:
                issues.append(
                    QAIssue(
                        code="QA_SECTION_CHAINAGE_OUT_OF_RANGE",
                        severity="ERROR",
                        category="CrossSection",
                        entity_type="CrossSection",
                        entity_id=section.section_id,
                        message="Cross Section chainage lies outside its Branch.",
                        location=location,
                    )
                )
            if identities[(section.branch_id, float(section.chainage_m))] > 1:
                issues.append(
                    QAIssue(
                        code="QA_SECTION_DUPLICATE_BRANCH_CHAINAGE",
                        severity="ERROR",
                        category="CrossSection",
                        entity_type="CrossSection",
                        entity_id=section.section_id,
                        message="More than one Cross Section uses the same Branch and chainage.",
                        location=location,
                    )
                )
            offsets = [float(value) for value in section.offsets_m]
            if any(right <= left for left, right in zip(offsets, offsets[1:])):
                issues.append(
                    QAIssue(
                        code="QA_SECTION_OFFSET_NON_MONOTONIC",
                        severity="ERROR",
                        category="CrossSection",
                        entity_type="CrossSection",
                        entity_id=section.section_id,
                        message="Cross Section offsets must be strictly increasing in the adopted orientation.",
                        location=location,
                    )
                )
            if not section.orientation_confirmed:
                issues.append(
                    QAIssue(
                        code="QA_SECTION_ORIENTATION_UNCONFIRMED",
                        severity="ERROR",
                        category="CrossSection",
                        entity_type="CrossSection",
                        entity_id=section.section_id,
                        message="Cross Section left-to-right orientation is not confirmed.",
                        location=location,
                    )
                )
            if section.vertical_datum != request.vertical_datum:
                issues.append(
                    QAIssue(
                        code="QA_SECTION_DATUM_MISMATCH",
                        severity="ERROR",
                        category="CRS",
                        entity_type="CrossSection",
                        entity_id=section.section_id,
                        message="Cross Section datum differs from the Network datum.",
                        location=location,
                        context={
                            "network_datum": request.vertical_datum,
                            "section_datum": section.vertical_datum,
                        },
                    )
                )
            if section.axis:
                intersections = _axis_intersections(section, branch)
                if intersections == 0:
                    issues.append(
                        QAIssue(
                            code="QA_SECTION_AXIS_NO_CENTERLINE_INTERSECTION",
                            severity="ERROR",
                            category="CrossSection",
                            entity_type="CrossSection",
                            entity_id=section.section_id,
                            message="Cross Section axis does not intersect its Branch centerline.",
                            location=location,
                        )
                    )
                elif intersections > 1:
                    issues.append(
                        QAIssue(
                            code="QA_SECTION_AXIS_MULTIPLE_INTERSECTIONS",
                            severity="WARNING",
                            category="CrossSection",
                            entity_type="CrossSection",
                            entity_id=section.section_id,
                            message="Cross Section axis intersects the Branch centerline more than once.",
                            location=location,
                            context={"intersection_count": intersections},
                        )
                    )
            elif section.location is not None:
                distance = _distance_to_branch(section.location, branch)
                if distance > request.thresholds.maximum_projection_distance_m:
                    issues.append(
                        QAIssue(
                            code="QA_SECTION_PROJECTION_TOO_FAR",
                            severity="ERROR",
                            category="CrossSection",
                            entity_type="CrossSection",
                            entity_id=section.section_id,
                            message="Cross Section location is too far from its Branch centerline.",
                            location=location,
                            context={"projection_distance_m": distance},
                        )
                    )
            bed = min(float(value) for value in section.elevations_m)
            thalweg.append(
                {
                    "branch_id": section.branch_id,
                    "section_id": section.section_id,
                    "chainage_m": float(section.chainage_m),
                    "bed_elevation_m": bed,
                }
            )
        for branch_id, sections in grouped.items():
            ordered = sorted(sections, key=lambda item: item.chainage_m)
            for left, right in zip(ordered, ordered[1:]):
                spacing = float(right.chainage_m - left.chainage_m)
                all_spacings.append(spacing)
                severity = None
                code = ""
                message = ""
                if spacing < request.thresholds.minimum_section_spacing_m:
                    severity, code = "WARNING", "QA_SECTION_SPACING_TOO_SMALL"
                    message = "Adjacent Cross Sections are closer than the project warning threshold."
                elif spacing > request.thresholds.maximum_section_spacing_m:
                    severity, code = "WARNING", "QA_SECTION_SPACING_TOO_LARGE"
                    message = "Adjacent Cross Sections exceed the project spacing warning threshold."
                if severity:
                    issues.append(
                        QAIssue(
                            code=code,
                            severity=severity,
                            category="CrossSection",
                            entity_type="Branch",
                            entity_id=branch_id,
                            message=message,
                            context={"spacing_m": spacing},
                        )
                    )
                left_bed = min(float(value) for value in left.elevations_m)
                right_bed = min(float(value) for value in right.elevations_m)
                jump = right_bed - left_bed
                if abs(jump) > request.thresholds.maximum_bed_jump_m:
                    issues.append(
                        QAIssue(
                            code="QA_SECTION_BED_JUMP",
                            severity="WARNING",
                            category="CrossSection",
                            entity_type="Branch",
                            entity_id=branch_id,
                            message="Adjacent thalweg elevations contain a large jump.",
                            context={"bed_jump_m": jump, "spacing_m": spacing},
                        )
                    )
                if spacing > 0 and jump / spacing > request.thresholds.maximum_reverse_bed_slope:
                    issues.append(
                        QAIssue(
                            code="QA_SECTION_REVERSE_BED_SLOPE",
                            severity="WARNING",
                            category="CrossSection",
                            entity_type="Branch",
                            entity_id=branch_id,
                            message="Thalweg profile has a reverse-slope segment; no automatic fix was applied.",
                            context={"slope": jump / spacing},
                        )
                    )
        statistics: dict[str, float | int | None] = {
            "count": len(all_spacings),
            "minimum_m": min(all_spacings) if all_spacings else None,
            "maximum_m": max(all_spacings) if all_spacings else None,
            "mean_m": mean(all_spacings) if all_spacings else None,
            "median_m": median(all_spacings) if all_spacings else None,
        }
        return statistics, sorted(thalweg, key=lambda item: (str(item["branch_id"]), float(item["chainage_m"])))

    @staticmethod
    def _validate_boundaries(
        request: HydraulicModelQARequest,
        branch_by_id: dict[str, ProductionBranch],
        issues: list[QAIssue],
    ) -> None:
        """Require endpoint coverage, valid time coverage, and factual locations."""

        endpoint_keys = Counter((item.branch_id, item.location) for item in request.boundaries)
        upstream_nodes = {branch.upstream_node_id for branch in request.branches if branch.upstream_node_id}
        downstream_nodes = {branch.downstream_node_id for branch in request.branches if branch.downstream_node_id}
        for branch in request.branches:
            external_upstream = branch.upstream_node_id not in downstream_nodes
            external_downstream = branch.downstream_node_id not in upstream_nodes
            for location, required in (("upstream", external_upstream), ("downstream", external_downstream)):
                count = endpoint_keys[(branch.branch_id, location)]
                if required and count == 0:
                    issues.append(
                        QAIssue(
                            code="QA_BOUNDARY_ENDPOINT_MISSING",
                            severity="ERROR",
                            category="Boundary",
                            entity_type="Branch",
                            entity_id=branch.branch_id,
                            message=f"External {location} endpoint has no boundary condition.",
                            location=_line_geometry(branch.centerline),
                        )
                    )
                if count > 1:
                    issues.append(
                        QAIssue(
                            code="QA_BOUNDARY_ENDPOINT_DUPLICATE",
                            severity="ERROR",
                            category="Boundary",
                            entity_type="Branch",
                            entity_id=branch.branch_id,
                            message=f"Branch has duplicate {location} boundary conditions.",
                        )
                    )
        for boundary in request.boundaries:
            branch = branch_by_id.get(boundary.branch_id)
            if branch is None:
                issues.append(
                    QAIssue(
                        code="QA_BOUNDARY_BRANCH_UNKNOWN",
                        severity="ERROR",
                        category="Boundary",
                        entity_type="Boundary",
                        entity_id=boundary.boundary_id,
                        message="Boundary references an unknown Branch.",
                    )
                )
                continue
            if boundary.chainage_m is not None and not (
                branch.start_chainage_m <= boundary.chainage_m <= branch.end_chainage_m
            ):
                issues.append(
                    QAIssue(
                        code="QA_BOUNDARY_CHAINAGE_OUT_OF_RANGE",
                        severity="ERROR",
                        category="Boundary",
                        entity_type="Boundary",
                        entity_id=boundary.boundary_id,
                        message="Lateral boundary chainage lies outside its Branch.",
                    )
                )
            good = [
                sample
                for sample in boundary.series.samples
                if sample.quality_flag == "GOOD" and sample.value is not None
            ]
            if not good or good[0].time_seconds > 0 or good[-1].time_seconds < request.simulation_duration_seconds:
                issues.append(
                    QAIssue(
                        code="QA_BOUNDARY_TIME_COVERAGE_INCOMPLETE",
                        severity="ERROR",
                        category="Boundary",
                        entity_type="Boundary",
                        entity_id=boundary.boundary_id,
                        message="Boundary series does not cover the full simulation period.",
                        context={"simulation_duration_seconds": request.simulation_duration_seconds},
                    )
                )

    @staticmethod
    def _validate_structures(
        request: HydraulicModelQARequest,
        branch_by_id: dict[str, ProductionBranch],
        issues: list[QAIssue],
    ) -> None:
        """Block active unsupported/unverified structures before runtime."""

        for structure in request.structures:
            if structure.status != "active":
                continue
            branch = branch_by_id.get(structure.branch_id)
            location = _point_geometry(structure.location)
            if branch is None or not branch.start_chainage_m <= structure.chainage_m <= branch.end_chainage_m:
                issues.append(
                    QAIssue(
                        code="QA_STRUCTURE_LOCATION_INVALID",
                        severity="ERROR",
                        category="Structure",
                        entity_type="Structure",
                        entity_id=structure.structure_id,
                        message="Active Structure has an invalid Branch or chainage.",
                        location=location,
                    )
                )
            if structure.vertical_datum != request.vertical_datum:
                issues.append(
                    QAIssue(
                        code="QA_STRUCTURE_DATUM_MISMATCH",
                        severity="ERROR",
                        category="Structure",
                        entity_type="Structure",
                        entity_id=structure.structure_id,
                        message="Structure elevation datum differs from the Network datum.",
                        location=location,
                    )
                )
            if structure.capability_status not in {"VERIFIED_NATIVE", "VERIFIED_EQUIVALENT"}:
                issues.append(
                    QAIssue(
                        code="MODEL_ENGINE_INCOMPATIBLE",
                        severity="ERROR",
                        category="Structure",
                        entity_type="Structure",
                        entity_id=structure.structure_id,
                        message=(
                            f"{structure.structure_type} capability is "
                            f"{structure.capability_status}; runtime remains fail closed."
                        ),
                        location=location,
                    )
                )

    @staticmethod
    def _validate_observations(
        request: HydraulicModelQARequest, issues: list[QAIssue]
    ) -> None:
        """Check observation location, datum, coverage, and quality flags."""

        branch_ids = {branch.branch_id for branch in request.branches}
        for series in request.observations:
            if series.variable not in {"water_level", "discharge"}:
                issues.append(
                    QAIssue(
                        code="QA_OBSERVATION_VARIABLE_UNSUPPORTED",
                        severity="ERROR",
                        category="Observation",
                        entity_type="ObservationStation",
                        entity_id=series.station_id or series.series_id,
                        message="Production observations support Water Level or Discharge only.",
                    )
                )
            if series.branch_id not in branch_ids or series.chainage_m is None:
                issues.append(
                    QAIssue(
                        code="QA_OBSERVATION_LOCATION_MISSING",
                        severity="ERROR",
                        category="Observation",
                        entity_type="ObservationStation",
                        entity_id=series.station_id or series.series_id,
                        message="Observation requires an explicit Branch and chainage mapping.",
                    )
                )
            if series.variable == "water_level" and series.vertical_datum != request.vertical_datum:
                issues.append(
                    QAIssue(
                        code="QA_OBSERVATION_DATUM_MISMATCH",
                        severity="ERROR",
                        category="Observation",
                        entity_type="ObservationStation",
                        entity_id=series.station_id or series.series_id,
                        message="Observed water-level datum differs from the Network datum.",
                    )
                )
            good_count = sum(sample.quality_flag == "GOOD" for sample in series.samples)
            missing_count = sum(sample.quality_flag == "MISSING" for sample in series.samples)
            if good_count == 0:
                issues.append(
                    QAIssue(
                        code="QA_OBSERVATION_NO_GOOD_SAMPLES",
                        severity="ERROR",
                        category="Observation",
                        entity_type="ObservationSeries",
                        entity_id=series.series_id,
                        message="Observation series contains no GOOD samples.",
                    )
                )
            elif missing_count:
                issues.append(
                    QAIssue(
                        code="QA_OBSERVATION_MISSING_SAMPLES",
                        severity="WARNING",
                        category="Observation",
                        entity_type="ObservationSeries",
                        entity_id=series.series_id,
                        message="Missing observations remain excluded from metrics; they were not filled with zero.",
                        context={"missing_sample_count": missing_count},
                    )
                )


__all__ = ["HydraulicModelQA", "RULESET_VERSION"]
