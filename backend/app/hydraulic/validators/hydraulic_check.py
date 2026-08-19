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
) -> list[HydraulicIssue]:
    """Apply CRS, topology, chainage, and profile gates to one normalized payload."""

    issues: list[HydraulicIssue] = []
    available_branches = set(known_branch_codes or set()) | {
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

    branch_ranges = {
        branch.code: (branch.points[0].chainage, branch.points[-1].chainage)
        for branch in payload.branches
    }
    for section in payload.sections:
        if section.branch_code not in available_branches:
            issues.append(
                HydraulicIssue(
                    severity="error",
                    code="SECTION_BRANCH_MISSING",
                    message="断面引用的河段编码在本次导入和目标版本中均不存在",
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
        if not section.axis_points:
            issues.append(
                HydraulicIssue(
                    severity="warning",
                    code="SECTION_AXIS_UNAVAILABLE",
                    message="断面仅有位置/剖面数据，尚无可核对方向的断面线",
                    entity_type="cross_section",
                    entity_ref=section.section_code,
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
