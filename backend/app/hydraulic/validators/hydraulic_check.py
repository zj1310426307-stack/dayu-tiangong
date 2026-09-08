"""Validate normalized hydraulic imports before any core-table mutation."""

from __future__ import annotations

import math

from app.hydraulic.schemas import HydraulicExchangePayload, HydraulicIssue


def _finite(value: float) -> bool:
    """Return whether one imported numeric value is finite and serializable."""

    return math.isfinite(value)


def validate_exchange(
    payload: HydraulicExchangePayload,
    known_branch_codes: set[str] | None = None,
    known_branch_ranges: dict[str, tuple[float, float]] | None = None,
    known_branch_roles: dict[str, str] | None = None,
) -> list[HydraulicIssue]:
    """Apply CRS, topology, chainage, and profile gates to one normalized payload."""

    issues: list[HydraulicIssue] = []
    available_branches = set(known_branch_codes or set()) | set(known_branch_ranges or {}) | {
        branch.code for branch in payload.branches
    }
    for branch in payload.branches:
        if any(
            not _finite(value)
            for point in branch.points
            for value in (point.chainage, point.x, point.y)
        ):
            issues.append(
                HydraulicIssue(
                    severity="error",
                    code="BRANCH_NONFINITE_VALUE",
                    message="河段包含 NaN 或无穷数值",
                    entity_type="branch",
                    entity_ref=branch.code,
                )
            )
        if len({(point.x, point.y) for point in branch.points}) < 2:
            issues.append(
                HydraulicIssue(
                    severity="error",
                    code="BRANCH_ZERO_GEOMETRY",
                    message="河段至少需要两个不同坐标点",
                    entity_type="branch",
                    entity_ref=branch.code,
                )
            )
        if branch.flow_direction == "unknown":
            issues.append(
                HydraulicIssue(
                    severity="warning",
                    code="BRANCH_FLOW_UNKNOWN",
                    message="河段流向尚未确认，模型使用前必须复核",
                    entity_type="branch",
                    entity_ref=branch.code,
                )
            )
        if payload.source_srid in {4326, 4490}:
            for point in branch.points:
                if not (-180 <= point.x <= 180 and -90 <= point.y <= 90):
                    issues.append(
                        HydraulicIssue(
                            severity="error",
                            code="GEOGRAPHIC_COORDINATE_RANGE",
                            message="地理坐标超出经纬度有效范围",
                            entity_type="branch",
                            entity_ref=branch.code,
                            context={"x": point.x, "y": point.y},
                        )
                    )
                    break
        else:
            for point in branch.points:
                if not (
                    100_000 <= point.x <= 2_000_000
                    and 0 <= point.y <= 10_000_000
                ):
                    issues.append(
                        HydraulicIssue(
                            severity="error",
                            code="PROJECTED_COORDINATE_RANGE",
                            message="CGCS2000 投影坐标超出受控工程范围",
                            entity_type="branch",
                            entity_ref=branch.code,
                            context={"x": point.x, "y": point.y, "srid": payload.source_srid},
                        )
                    )
                    break

    branch_ranges = dict(known_branch_ranges or {})
    branch_ranges.update({
        branch.code: (branch.points[0].chainage, branch.points[-1].chainage)
        for branch in payload.branches
    })
    branch_roles = dict(known_branch_roles or {})
    branch_roles.update({branch.code: branch.centerline_role for branch in payload.branches})
    previous_section_by_branch: dict[str, tuple[str, float]] = {}
    for section in payload.sections:
        previous_section = previous_section_by_branch.get(section.branch_code)
        if previous_section is not None and section.chainage < previous_section[1]:
            issues.append(
                HydraulicIssue(
                    severity="error",
                    code="SECTION_CHAINAGE_ORDER_INVALID",
                    message="横断面组必须按上游到下游、里程非递减顺序依次输入",
                    entity_type="cross_section",
                    entity_ref=section.section_code,
                    context={
                        "branch_code": section.branch_code,
                        "previous_section_code": previous_section[0],
                        "previous_chainage": previous_section[1],
                        "chainage": section.chainage,
                    },
                )
            )
        previous_section_by_branch[section.branch_code] = (
            section.section_code,
            section.chainage,
        )
        if section.branch_code not in available_branches:
            issues.append(
                HydraulicIssue(
                    severity="error",
                    code="SECTION_BRANCH_MISSING",
                    message=(
                        "断面引用的河段编码在本次文件和当前数据版本中均不存在；"
                        "横断面文件可不含河段，但必须先在同一数据版本提交对应的河道中心线"
                    ),
                    entity_type="cross_section",
                    entity_ref=section.section_code,
                    context={"branch_code": section.branch_code},
                )
            )
        if section.branch_code in branch_ranges:
            start, end = branch_ranges[section.branch_code]
            if not start <= section.chainage <= end:
                issues.append(
                    HydraulicIssue(
                        severity="error",
                        code="SECTION_CHAINAGE_OUTSIDE_BRANCH",
                        message="断面桩号不在河段起止桩号范围内",
                        entity_type="cross_section",
                        entity_ref=section.section_code,
                        context={"chainage": section.chainage, "start": start, "end": end},
                    )
                )
        if not section.axis_points and section.branch_code in branch_ranges:
            issues.append(
                HydraulicIssue(
                    severity="info",
                    code="SECTION_AXIS_DERIVED_FROM_BRANCH",
                    message=(
                        "未提供实测横断面 XY；提交后按河段中心线+桩号派生空间测线，"
                        "Station/Offset 与水力计算不受影响"
                    ),
                    entity_type="cross_section",
                    entity_ref=section.section_code,
                    context={"spatial_geometry_source": "DERIVED_FROM_BRANCH"},
                )
            )
        thalweg_points = [
            point for point in section.points if point.marker_type == "thalweg"
        ]
        if branch_roles.get(section.branch_code) == "thalweg" and not thalweg_points:
            issues.append(
                HydraulicIssue(
                    severity="error",
                    code="SECTION_THALWEG_MISSING",
                    message="深泓线河段上的每个断面必须标记至少一个最低高程深泓点",
                    entity_type="cross_section",
                    entity_ref=section.section_code,
                )
            )
        if len(thalweg_points) > 1:
            issues.append(
                HydraulicIssue(
                    severity="warning",
                    code="SECTION_THALWEG_TIE",
                    message="断面存在多个同高最低点，已全部保留为深泓点候选并等待人工复核",
                    entity_type="cross_section",
                    entity_ref=section.section_code,
                    context={
                        "count": len(thalweg_points),
                        "offsets_m": [point.distance for point in thalweg_points],
                        "elevation_m": min(point.elevation for point in thalweg_points),
                    },
                )
            )
        marker1_points = [
            point for point in section.points
            if point.marker_type in {"left_bank", "left_levee"}
        ]
        marker3_points = [
            point for point in section.points
            if point.marker_type in {"right_bank", "right_levee"}
        ]
        if not marker1_points or not marker3_points:
            issues.append(
                HydraulicIssue(
                    severity="warning",
                    code="MIKE11_MARKER_EXTENT_UNDECLARED",
                    message=(
                        "未同时声明 MIKE11 Marker 1/3；当前按全断面点计算，"
                        "请在横断面数据库中补充左右堤防点后重新处理断面"
                    ),
                    entity_type="cross_section",
                    entity_ref=section.section_code,
                    context={
                        "marker1_count": len(marker1_points),
                        "marker3_count": len(marker3_points),
                        "fallback": "full_profile",
                    },
                )
            )
        elevations = [point.elevation for point in section.points]
        if any(not _finite(value) for value in elevations):
            issues.append(
                HydraulicIssue(
                    severity="error",
                    code="SECTION_NONFINITE_ELEVATION",
                    message="断面高程包含 NaN 或无穷值",
                    entity_type="cross_section",
                    entity_ref=section.section_code,
                )
            )
        if elevations and max(elevations) - min(elevations) > 500:
            issues.append(
                HydraulicIssue(
                    severity="warning",
                    code="SECTION_ELEVATION_RANGE",
                    message="断面高程差超过 500 m，请复核单位和高程基准",
                    entity_type="cross_section",
                    entity_ref=section.section_code,
                    context={"minimum": min(elevations), "maximum": max(elevations)},
                )
            )
    if not any(issue.severity == "error" for issue in issues):
        issues.append(
            HydraulicIssue(
                severity="passed",
                code="EXCHANGE_PRECHECK_PASSED",
                message="交换数据通过提交前结构、坐标与顺序检查",
                entity_type="dataset",
                entity_ref=payload.network_code,
            )
        )
    return issues
