"""Case-scoped, fail-closed helpers for HYDRO-DATA-02 production validation.

The functions in this module intentionally separate survey interpretation from the
database importers.  A case must provide an explicit CAD layer/feature mapping; the
runtime never guesses a CRS, a river role, or a profile drawing group from coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from app.hydraulic.schemas import (
    CoordinateReferenceSpec,
    HydraulicBranchInput,
    HydraulicChainageInput,
    HydraulicCrossSectionInput,
    HydraulicExchangePayload,
    HydraulicSectionPointInput,
)


Point = tuple[float, float]
CHAINAGE_PATTERN = re.compile(r"^K\s*(\d+)\s*\+\s*(\d+(?:\.\d+)?)$", re.IGNORECASE)
PROFILE_OFFSET_PATTERN = re.compile(r"^([+-]?)(\d+)\s*\+\s*(\d+(?:\.\d+)?)$")


@dataclass(frozen=True)
class LineProjection:
    """Nearest point and tangent on a polyline in projected metres."""

    along_m: float
    fraction: float
    distance_m: float
    point: Point
    tangent: Point


@dataclass(frozen=True)
class SurveyBranch:
    """One explicitly selected CAD centreline with adopted chainage evidence."""

    code: str
    name: str
    river_name: str
    source_ordinal: int
    coordinates: tuple[Point, ...]
    chainage_start_m: float
    chainage_end_m: float
    annotation_count: int
    annotation_rmse_m: float
    source_order_reversed: bool


@dataclass(frozen=True)
class SectionAxis:
    """One surveyed section axis located against an adopted branch."""

    source_ordinal: int
    branch_code: str
    coordinates: tuple[Point, ...]
    chainage_m: float
    location: Point
    snap_distance_m: float
    intersection_angle_deg: float
    perpendicular_deviation_deg: float
    quality: str


@dataclass(frozen=True)
class SurveyProfile:
    """One profile reconstructed from an explicitly mapped CAD drawing frame."""

    group_code: str
    branch_code: str
    source_chainage_m: float
    drawing_label: str
    drawing_label_xy: Point
    raw_points: tuple[tuple[float, float], ...]


def _finite(value: object, field: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _xy(value: Sequence[object]) -> Point:
    if len(value) < 2:
        raise ValueError("coordinate requires X and Y")
    return _finite(value[0], "x"), _finite(value[1], "y")


def parse_chainage(value: object) -> float | None:
    """Parse an exact CAD chainage label such as ``K1+234.50``."""

    match = CHAINAGE_PATTERN.fullmatch(str(value or "").strip())
    if match is None:
        return None
    return int(match.group(1)) * 1000.0 + float(match.group(2))


def parse_profile_offset(value: object) -> float | None:
    """Parse signed profile notation such as ``-0+155.5`` without guessing units."""

    match = PROFILE_OFFSET_PATTERN.fullmatch(str(value or "").strip())
    if match is None:
        return None
    magnitude = int(match.group(2)) * 1000.0 + float(match.group(3))
    return -magnitude if match.group(1) == "-" else magnitude


def polyline_length(coordinates: Sequence[Point]) -> float:
    """Return the two-dimensional length of a projected polyline."""

    return sum(math.dist(left, right) for left, right in zip(coordinates, coordinates[1:]))


def _point_segment_projection(point: Point, left: Point, right: Point) -> tuple[Point, float, float]:
    dx, dy = right[0] - left[0], right[1] - left[1]
    squared = dx * dx + dy * dy
    if squared <= 0:
        return left, 0.0, math.dist(point, left)
    ratio = ((point[0] - left[0]) * dx + (point[1] - left[1]) * dy) / squared
    ratio = min(1.0, max(0.0, ratio))
    projected = left[0] + ratio * dx, left[1] + ratio * dy
    return projected, ratio, math.dist(point, projected)


def project_point(point: Point, coordinates: Sequence[Point]) -> LineProjection:
    """Project a point to a polyline and retain deterministic along-line distance."""

    if len(coordinates) < 2:
        raise ValueError("polyline requires at least two points")
    total = polyline_length(coordinates)
    if total <= 0:
        raise ValueError("polyline length must be positive")
    best: tuple[float, float, Point, Point] | None = None
    cumulative = 0.0
    for left, right in zip(coordinates, coordinates[1:]):
        segment_length = math.dist(left, right)
        projected, ratio, distance = _point_segment_projection(point, left, right)
        along = cumulative + ratio * segment_length
        tangent = right[0] - left[0], right[1] - left[1]
        candidate = distance, along, projected, tangent
        if best is None or candidate[:2] < best[:2]:
            best = candidate
        cumulative += segment_length
    assert best is not None
    distance, along, projected, tangent = best
    return LineProjection(
        along_m=along,
        fraction=along / total,
        distance_m=distance,
        point=projected,
        tangent=tangent,
    )


def _segment_intersection(
    first_left: Point, first_right: Point, second_left: Point, second_right: Point
) -> tuple[Point, float, float] | None:
    """Return a proper/touching segment intersection and both segment fractions."""

    rx, ry = first_right[0] - first_left[0], first_right[1] - first_left[1]
    sx, sy = second_right[0] - second_left[0], second_right[1] - second_left[1]
    denominator = rx * sy - ry * sx
    if abs(denominator) <= 1.0e-12:
        return None
    qx, qy = second_left[0] - first_left[0], second_left[1] - first_left[1]
    first_ratio = (qx * sy - qy * sx) / denominator
    second_ratio = (qx * ry - qy * rx) / denominator
    tolerance = 1.0e-9
    if not (-tolerance <= first_ratio <= 1 + tolerance):
        return None
    if not (-tolerance <= second_ratio <= 1 + tolerance):
        return None
    point = first_left[0] + first_ratio * rx, first_left[1] + first_ratio * ry
    return point, min(1.0, max(0.0, first_ratio)), min(1.0, max(0.0, second_ratio))


def locate_axis(axis: Sequence[Point], branch: Sequence[Point]) -> LineProjection:
    """Locate an axis on a branch, preferring an actual intersection over proximity."""

    if len(axis) < 2 or len(branch) < 2:
        raise ValueError("axis and branch require at least two points")
    cumulative = 0.0
    intersections: list[LineProjection] = []
    total = polyline_length(branch)
    for branch_left, branch_right in zip(branch, branch[1:]):
        branch_length = math.dist(branch_left, branch_right)
        for axis_left, axis_right in zip(axis, axis[1:]):
            intersection = _segment_intersection(
                branch_left, branch_right, axis_left, axis_right
            )
            if intersection is not None:
                point, branch_ratio, _ = intersection
                along = cumulative + branch_ratio * branch_length
                intersections.append(LineProjection(
                    along_m=along,
                    fraction=along / total,
                    distance_m=0.0,
                    point=point,
                    tangent=(
                        branch_right[0] - branch_left[0],
                        branch_right[1] - branch_left[1],
                    ),
                ))
        cumulative += branch_length
    if intersections:
        return min(intersections, key=lambda value: value.along_m)

    candidates = [project_point(point, branch) for point in axis]
    cumulative = 0.0
    for index, branch_point in enumerate(branch):
        axis_projection = project_point(branch_point, axis)
        if index == 0:
            tangent = branch[1][0] - branch[0][0], branch[1][1] - branch[0][1]
        else:
            tangent = (
                branch[index][0] - branch[index - 1][0],
                branch[index][1] - branch[index - 1][1],
            )
        candidates.append(LineProjection(
            along_m=cumulative,
            fraction=cumulative / total,
            distance_m=axis_projection.distance_m,
            point=branch_point,
            tangent=tangent,
        ))
        if index < len(branch) - 1:
            cumulative += math.dist(branch[index], branch[index + 1])
    return min(candidates, key=lambda value: (value.distance_m, value.along_m))


def _properties(feature: Mapping[str, Any]) -> Mapping[str, Any]:
    value = feature.get("properties") or {}
    return value if isinstance(value, Mapping) else {}


def _feature_text(feature: Mapping[str, Any]) -> str:
    return str(_properties(feature).get("text") or "").strip()


def _line(feature: Mapping[str, Any]) -> tuple[Point, ...] | None:
    geometry = feature.get("geometry") or {}
    if geometry.get("type") != "LineString":
        return None
    coordinates = tuple(_xy(value) for value in geometry.get("coordinates") or [])
    return coordinates if len(coordinates) >= 2 else None


def _point(feature: Mapping[str, Any]) -> Point | None:
    geometry = feature.get("geometry") or {}
    if geometry.get("type") != "Point":
        return None
    return _xy(geometry.get("coordinates") or [])


def _linear_fit(values: Sequence[tuple[float, float]]) -> tuple[float, float, float]:
    """Return slope, intercept, and RMSE for chainage against along-line distance."""

    if len(values) < 2:
        raise ValueError("at least two chainage annotations are required")
    mean_x = sum(value[0] for value in values) / len(values)
    mean_y = sum(value[1] for value in values) / len(values)
    denominator = sum((value[0] - mean_x) ** 2 for value in values)
    if denominator <= 0:
        raise ValueError("chainage annotations collapse to one line position")
    slope = sum(
        (value[0] - mean_x) * (value[1] - mean_y) for value in values
    ) / denominator
    intercept = mean_y - slope * mean_x
    rmse = math.sqrt(sum(
        (slope * value[0] + intercept - value[1]) ** 2 for value in values
    ) / len(values))
    return slope, intercept, rmse


def extract_survey_branches(
    features: Sequence[Mapping[str, Any]],
    branch_specs: Sequence[Mapping[str, Any]],
    *,
    annotation_snap_m: float = 40.0,
) -> tuple[list[SurveyBranch], list[dict[str, object]]]:
    """Select mapped CAD features and orient them using surveyed chainage labels."""

    line_features = [feature for feature in features if _line(feature) is not None]
    labels = [
        (point, parsed, _feature_text(feature))
        for feature in features
        if (point := _point(feature)) is not None
        if (parsed := parse_chainage(_feature_text(feature))) is not None
    ]
    branches: list[SurveyBranch] = []
    reports: list[dict[str, object]] = []
    for spec in branch_specs:
        ordinal = int(spec["source_ordinal"])
        if ordinal < 1 or ordinal > len(line_features):
            raise ValueError(f"mapped centreline ordinal {ordinal} does not exist")
        coordinates = tuple(_line(line_features[ordinal - 1]) or ())
        assigned: list[tuple[float, float, str, float]] = []
        for point, chainage, label in labels:
            projection = project_point(point, coordinates)
            if projection.distance_m <= annotation_snap_m:
                assigned.append((projection.along_m, chainage, label, projection.distance_m))
        if len(assigned) < 2:
            raise ValueError(f"branch ordinal {ordinal} has fewer than two mapped chainage labels")
        slope, _, _ = _linear_fit([(value[0], value[1]) for value in assigned])
        reversed_order = slope < 0
        if reversed_order:
            coordinates = tuple(reversed(coordinates))
            assigned = [
                (polyline_length(coordinates) - value[0], value[1], value[2], value[3])
                for value in assigned
            ]
        slope, intercept, rmse = _linear_fit([(value[0], value[1]) for value in assigned])
        if slope <= 0:
            raise ValueError(f"branch ordinal {ordinal} chainage direction is indeterminate")
        start = min(value[1] for value in assigned)
        end = max(value[1] for value in assigned)
        expected_end = spec.get("expected_end_chainage_m")
        if expected_end is not None and not math.isclose(
            end, float(expected_end), abs_tol=float(spec.get("end_tolerance_m", 0.05))
        ):
            raise ValueError(
                f"branch ordinal {ordinal} end chainage {end:g} does not match explicit mapping"
            )
        branch = SurveyBranch(
            code=str(spec["code"]),
            name=str(spec.get("name") or spec["code"]),
            river_name=str(spec.get("river_name") or spec.get("name") or spec["code"]),
            source_ordinal=ordinal,
            coordinates=coordinates,
            chainage_start_m=start,
            chainage_end_m=end,
            annotation_count=len(assigned),
            annotation_rmse_m=rmse,
            source_order_reversed=reversed_order,
        )
        branches.append(branch)
        reports.append({
            "branch": branch.code,
            "source_feature_ordinal": ordinal,
            "upstream_node": {"x": coordinates[0][0], "y": coordinates[0][1]},
            "downstream_node": {"x": coordinates[-1][0], "y": coordinates[-1][1]},
            "direction": "increasing_survey_chainage",
            "confidence": "high" if len(assigned) >= 3 and rmse <= 0.5 else "medium",
            "evidence": "CAD chainage annotations fitted to explicitly selected centreline",
            "annotation_count": len(assigned),
            "annotation_rmse_m": rmse,
            "fit_slope": slope,
            "fit_intercept": intercept,
            "human_flow_direction_confirmation": "pending",
        })
    if len({branch.code for branch in branches}) != len(branches):
        raise ValueError("branch mapping contains duplicate codes")
    return branches, reports


def locate_section_axes(
    features: Sequence[Mapping[str, Any]],
    branches: Sequence[SurveyBranch],
    *,
    snap_tolerance_m: float = 5.0,
    perpendicular_tolerance_deg: float = 20.0,
) -> list[SectionAxis]:
    """Assign every mapped survey axis to the nearest branch and compute QA evidence."""

    axes: list[SectionAxis] = []
    for ordinal, feature in enumerate(features, start=1):
        coordinates = _line(feature)
        if coordinates is None:
            continue
        source_ordinal = int(_properties(feature).get("validation_source_ordinal", ordinal))
        candidates = [(locate_axis(coordinates, branch.coordinates), branch) for branch in branches]
        projection, branch = min(
            candidates, key=lambda value: (value[0].distance_m, value[0].along_m)
        )
        axis_vector = (
            coordinates[-1][0] - coordinates[0][0],
            coordinates[-1][1] - coordinates[0][1],
        )
        axis_norm = math.hypot(*axis_vector)
        tangent_norm = math.hypot(*projection.tangent)
        if axis_norm <= 0 or tangent_norm <= 0:
            raise ValueError(f"section axis ordinal {ordinal} has zero length")
        cosine = abs(
            (axis_vector[0] * projection.tangent[0] + axis_vector[1] * projection.tangent[1])
            / (axis_norm * tangent_norm)
        )
        acute_angle = math.degrees(math.acos(min(1.0, max(0.0, cosine))))
        deviation = abs(90.0 - acute_angle)
        quality = "passed"
        if projection.distance_m > snap_tolerance_m:
            quality = "error"
        elif deviation > perpendicular_tolerance_deg:
            quality = "warning"
        chainage = branch.chainage_start_m + projection.fraction * (
            branch.chainage_end_m - branch.chainage_start_m
        )
        axes.append(SectionAxis(
            source_ordinal=source_ordinal,
            branch_code=branch.code,
            coordinates=coordinates,
            chainage_m=chainage,
            location=projection.point,
            snap_distance_m=projection.distance_m,
            intersection_angle_deg=acute_angle,
            perpendicular_deviation_deg=deviation,
            quality=quality,
        ))
    return axes


def _matches_group(point: Point, rule: Mapping[str, Any]) -> bool:
    for key, index, operation in (
        ("label_x_min", 0, lambda left, right: left >= right),
        ("label_x_max", 0, lambda left, right: left < right),
        ("label_y_min", 1, lambda left, right: left >= right),
        ("label_y_max", 1, lambda left, right: left < right),
    ):
        if key in rule and not operation(point[index], float(rule[key])):
            return False
    return True


def extract_survey_profiles(
    frame_features: Sequence[Mapping[str, Any]],
    profile_features: Sequence[Mapping[str, Any]],
    group_rules: Sequence[Mapping[str, Any]],
    *,
    offset_y_window: tuple[float, float] = (4.0, 10.0),
    elevation_y_window: tuple[float, float] = (20.0, 35.0),
    pair_x_tolerance_m: float = 2.0,
) -> list[SurveyProfile]:
    """Extract profile offset/elevation pairs from explicitly mapped CAD drawing frames."""

    labels: list[tuple[Point, float, str]] = []
    for feature in frame_features:
        point = _point(feature)
        chainage = parse_chainage(_feature_text(feature))
        if point is not None and chainage is not None:
            labels.append((point, chainage, _feature_text(feature)))
    profile_texts = [
        (point, _feature_text(feature))
        for feature in profile_features
        if (point := _point(feature)) is not None and _feature_text(feature)
    ]

    def owned_by(point: Point, label_xy: Point) -> bool:
        """Assign drawing text to the nearest chainage label (Voronoi frame split)."""

        nearest = min(
            labels,
            key=lambda value: (
                math.dist(point, value[0]), value[0][1], value[0][0], value[2]
            ),
        )
        return nearest[0] == label_xy

    results: list[SurveyProfile] = []
    for group in group_rules:
        group_labels = [value for value in labels if _matches_group(value[0], group)]
        expected_count = int(group.get("expected_count", len(group_labels)))
        if len(group_labels) != expected_count:
            raise ValueError(
                f"profile group {group['code']} has {len(group_labels)} labels, expected {expected_count}"
            )
        for label_xy, chainage, label in group_labels:
            offsets = [
                (point, offset)
                for point, text in profile_texts
                if owned_by(point, label_xy)
                if offset_y_window[0] <= point[1] - label_xy[1] <= offset_y_window[1]
                if (offset := parse_profile_offset(text)) is not None
            ]
            elevations = [
                (point, _finite(text, "profile elevation"))
                for point, text in profile_texts
                if owned_by(point, label_xy)
                if elevation_y_window[0] <= point[1] - label_xy[1] <= elevation_y_window[1]
                if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text)
            ]
            paired: list[tuple[float, float]] = []
            used: set[int] = set()
            for offset_point, offset in sorted(offsets, key=lambda value: value[0][0]):
                choices = [
                    (abs(elevation_point[0] - offset_point[0]), index, elevation)
                    for index, (elevation_point, elevation) in enumerate(elevations)
                    if index not in used
                ]
                if not choices:
                    continue
                difference, index, elevation = min(choices)
                if difference <= pair_x_tolerance_m:
                    used.add(index)
                    paired.append((offset, elevation))
            unique: dict[float, float] = {}
            for offset, elevation in paired:
                key = round(offset, 6)
                if key in unique and not math.isclose(unique[key], elevation, abs_tol=0.02):
                    raise ValueError(
                        f"profile {group['code']} {label} has conflicting duplicate offsets"
                    )
                unique.setdefault(key, elevation)
            points = tuple(sorted(unique.items()))
            if len(points) < 3:
                raise ValueError(
                    f"profile {group['code']} {label} has fewer than three paired points"
                )
            results.append(SurveyProfile(
                group_code=str(group["code"]),
                branch_code=str(group["branch_code"]),
                source_chainage_m=chainage,
                drawing_label=label,
                drawing_label_xy=label_xy,
                raw_points=points,
            ))
    return sorted(results, key=lambda value: (value.branch_code, value.source_chainage_m))


def match_profiles_to_axes(
    profiles: Sequence[SurveyProfile],
    axes: Sequence[SectionAxis],
    *,
    maximum_chainage_delta_m: float = 35.0,
) -> tuple[list[tuple[SurveyProfile, SectionAxis]], list[dict[str, object]]]:
    """Match profiles one-to-one to surveyed axes on the same mapped branch."""

    used: set[int] = set()
    matches: list[tuple[SurveyProfile, SectionAxis]] = []
    reports: list[dict[str, object]] = []
    for profile in profiles:
        choices = [
            (abs(axis.chainage_m - profile.source_chainage_m), index, axis)
            for index, axis in enumerate(axes)
            if index not in used and axis.branch_code == profile.branch_code
        ]
        if not choices:
            raise ValueError(f"profile {profile.drawing_label} has no section axis on its branch")
        difference, index, axis = min(choices)
        if difference > maximum_chainage_delta_m:
            raise ValueError(
                f"profile {profile.drawing_label} chainage differs from its nearest axis by "
                f"{difference:.3f} m (limit {maximum_chainage_delta_m:.3f} m)"
            )
        if axis.quality == "error":
            raise ValueError(
                f"profile {profile.drawing_label} matched rejected axis "
                f"{axis.source_ordinal}"
            )
        used.add(index)
        matches.append((profile, axis))
        reports.append({
            "section": f"{profile.branch_code}-CS-{profile.source_chainage_m:08.2f}",
            "branch": profile.branch_code,
            "source_axis_ordinal": axis.source_ordinal,
            "survey_chainage_m": profile.source_chainage_m,
            "computed_axis_chainage_m": axis.chainage_m,
            "chainage_delta_m": difference,
            "snap_distance_m": axis.snap_distance_m,
            "intersection_angle_deg": axis.intersection_angle_deg,
            "perpendicular_deviation_deg": axis.perpendicular_deviation_deg,
            "point_count": len(profile.raw_points),
            "issue": (
                "chainage_delta" if difference > maximum_chainage_delta_m else
                "axis_snap" if axis.quality == "error" else
                "axis_angle" if axis.quality == "warning" else ""
            ),
            "level": (
                "error" if difference > maximum_chainage_delta_m or axis.quality == "error" else
                "warning" if axis.quality == "warning" else "passed"
            ),
        })
    return matches, reports


def _branch_input(branch: SurveyBranch, source_revision: str) -> HydraulicBranchInput:
    length = polyline_length(branch.coordinates)
    span = branch.chainage_end_m - branch.chainage_start_m
    cumulative = 0.0
    points: list[HydraulicChainageInput] = []
    prior: Point | None = None
    for index, point in enumerate(branch.coordinates):
        if prior is not None:
            segment = math.dist(prior, point)
            if segment <= 1.0e-9:
                continue
            cumulative += segment
        points.append(HydraulicChainageInput(
            chainage=branch.chainage_start_m + cumulative / length * span,
            x=point[0],
            y=point[1],
            point_code=f"CAD-{branch.source_ordinal:02d}-{index + 1:03d}",
        ))
        prior = point
    points[-1].chainage = branch.chainage_end_m
    return HydraulicBranchInput(
        code=branch.code,
        river_name=branch.river_name,
        branch_name=branch.name,
        # Survey chainage order is geometric evidence only.  It must not be
        # promoted to a confirmed hydraulic upstream/downstream direction.
        flow_direction="unknown",
        source_revision=source_revision,
        points=points,
    )


def build_exchange_payload(
    branches: Sequence[SurveyBranch],
    matches: Sequence[tuple[SurveyProfile, SectionAxis]],
    coordinate_reference: CoordinateReferenceSpec,
    *,
    network_code: str,
    network_name: str,
    survey_date: str | None,
    source_revision: str,
    topography_id: str,
    default_manning_n: float,
) -> HydraulicExchangePayload:
    """Build the canonical payload without inventing unavailable survey point XY values."""

    sections: list[HydraulicCrossSectionInput] = []
    for profile, axis in matches:
        minimum = profile.raw_points[0][0]
        points = [HydraulicSectionPointInput(
            sequence=index,
            distance=offset - minimum,
            elevation=elevation,
            point_code=f"RAW_OFFSET={offset:g}",
        ) for index, (offset, elevation) in enumerate(profile.raw_points)]
        section_code = f"{profile.branch_code}-CS-{profile.source_chainage_m:08.2f}"
        sections.append(HydraulicCrossSectionInput(
            section_code=section_code,
            section_name=f"{profile.branch_code} K{profile.source_chainage_m / 1000:.5f}",
            branch_code=profile.branch_code,
            chainage=profile.source_chainage_m,
            topography_id=topography_id,
            survey_date=survey_date,
            survey_method="DWG section drawing + surveyed axis explicit mapping",
            default_manning_n=default_manning_n,
            location_x=axis.location[0],
            location_y=axis.location[1],
            axis_points=list(axis.coordinates),
            points=points,
        ))
    return HydraulicExchangePayload(
        network_code=network_code,
        network_name=network_name,
        source_srid=coordinate_reference.source_srid,
        source_kind="api",
        coordinate_reference=coordinate_reference,
        branches=[_branch_input(branch, source_revision) for branch in branches],
        sections=sections,
    )


def payload_geojson(payload: HydraulicExchangePayload) -> dict[str, object]:
    """Serialize a canonical role-tagged GeoJSON accepted by the vector importer."""

    features: list[dict[str, object]] = []
    for branch in payload.branches:
        features.append({
            "type": "Feature",
            "properties": {
                "feature_role": "branch",
                "network_code": payload.network_code,
                "network_name": payload.network_name,
                "branch_code": branch.code,
                "river_name": branch.river_name,
                "branch_name": branch.branch_name,
                "flow_direction": branch.flow_direction,
                "start_chainage": branch.points[0].chainage,
                "end_chainage": branch.points[-1].chainage,
                "source_revision": branch.source_revision,
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [[point.x, point.y] for point in branch.points],
            },
        })
    for section in payload.sections:
        features.append({
            "type": "Feature",
            "properties": {
                "feature_role": "cross_section_axis",
                "network_code": payload.network_code,
                "network_name": payload.network_name,
                "section_code": section.section_code,
                "branch_code": section.branch_code,
                "chainage": section.chainage,
                "topography_id": section.topography_id,
                "location_x": section.location_x,
                "location_y": section.location_y,
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [list(value) for value in section.axis_points],
            },
        })
        for point in section.points:
            features.append({
                "type": "Feature",
                "properties": {
                    "feature_role": "cross_section_point",
                    "network_code": payload.network_code,
                    "network_name": payload.network_name,
                    "section_code": section.section_code,
                    "section_name": section.section_name,
                    "branch_code": section.branch_code,
                    "chainage": section.chainage,
                    "topography_id": section.topography_id,
                    "survey_date": section.survey_date.isoformat() if section.survey_date else None,
                    "survey_method": section.survey_method,
                    "default_manning_n": section.default_manning_n,
                    "distance": point.distance,
                    "elevation": point.elevation,
                    "point_code": point.point_code,
                    "location_x": section.location_x,
                    "location_y": section.location_y,
                    "omit_source_xy": True,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [section.location_x, section.location_y],
                },
            })
    return {"type": "FeatureCollection", "features": features}


def normalize_xyz_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    point_field: str,
    x_field: str,
    y_field: str,
    z_field: str,
    coordinate_reference: CoordinateReferenceSpec,
) -> list[dict[str, object]]:
    """Normalize an explicit 点号/X/Y/H mapping; never infer fields or axes."""

    normalized: list[dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        missing = [field for field in (point_field, x_field, y_field, z_field) if field not in row]
        if missing:
            raise ValueError(f"survey row {index} is missing explicit fields: {', '.join(missing)}")
        raw_x, raw_y = _finite(row[x_field], x_field), _finite(row[y_field], y_field)
        easting, northing = coordinate_reference.normalize_xy(raw_x, raw_y)
        if coordinate_reference.coordinate_mode == "projected" and not (
            100_000 <= easting <= 1_000_000 and 0 <= northing <= 10_000_000
        ):
            raise ValueError(f"survey row {index} is outside the declared projected coordinate range")
        normalized.append({
            "point_code": str(row[point_field]),
            "source_x": raw_x,
            "source_y": raw_y,
            "easting": easting,
            "northing": northing,
            "elevation": _finite(row[z_field], z_field),
        })
    if not normalized:
        raise ValueError("survey XYZ input is empty")
    return normalized


def control_point_residual_gate(
    rows: Sequence[Mapping[str, object]],
    *,
    threshold_m: float = 0.5,
    minimum_count: int = 10,
) -> dict[str, object]:
    """Evaluate independent expected engineering coordinates and fail closed if absent."""

    required = ("point_code", "computed_x", "computed_y", "expected_x", "expected_y")
    if len(rows) < minimum_count:
        return {
            "status": "blocked",
            "passed": False,
            "reason": f"requires at least {minimum_count} authoritative control points",
            "control_point_count": len(rows),
            "threshold_m": threshold_m,
            "residuals": [],
        }
    residuals: list[dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        missing = [field for field in required if row.get(field) in (None, "")]
        if missing:
            return {
                "status": "blocked",
                "passed": False,
                "reason": f"control point row {index} lacks independent expected coordinates",
                "control_point_count": len(rows),
                "threshold_m": threshold_m,
                "residuals": residuals,
            }
        dx = _finite(row["computed_x"], "computed_x") - _finite(row["expected_x"], "expected_x")
        dy = _finite(row["computed_y"], "computed_y") - _finite(row["expected_y"], "expected_y")
        residuals.append({
            "point_code": str(row["point_code"]),
            "dx_m": dx,
            "dy_m": dy,
            "residual_m": math.hypot(dx, dy),
        })
    maximum = max(float(value["residual_m"]) for value in residuals)
    rmse = math.sqrt(sum(float(value["residual_m"]) ** 2 for value in residuals) / len(residuals))
    passed = maximum < threshold_m
    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "control_point_count": len(residuals),
        "threshold_m": threshold_m,
        "maximum_residual_m": maximum,
        "rmse_m": rmse,
        "residuals": residuals,
    }
