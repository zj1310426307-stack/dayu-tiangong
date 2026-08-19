"""Export deterministic MIKE11 exchange subsets and optional native XNS11 files."""

from __future__ import annotations

from app.hydraulic.schemas import HydraulicExchangePayload


def _quoted(value: str) -> str:
    """Quote one external string while neutralizing embedded single quotes."""

    return "'" + value.replace("'", "''") + "'"


def export_nwk11_subset(payload: HydraulicExchangePayload) -> bytes:
    """Serialize branches to the documented, deterministic PFS exchange subset."""

    lines = [
        "// HYDRO-DATA-01-NWK11",
        "// ROUNDTRIP_VALIDATED_ONLY: native DHI PFS validation is still required.",
        "[HYDRO_NETWORK]",
        f"  NetworkCode = {_quoted(payload.network_code)}",
        f"  NetworkName = {_quoted(payload.network_name)}",
        f"  SourceCRS = 'EPSG:{payload.source_srid}'",
    ]
    for branch in payload.branches:
        lines.extend([
            "  [BRANCH]",
            f"    Code = {_quoted(branch.code)}",
            f"    RiverName = {_quoted(branch.river_name)}",
            f"    BranchName = {_quoted(branch.branch_name)}",
            f"    FlowDirection = {_quoted(branch.flow_direction)}",
        ])
        if branch.source_revision:
            lines.append(f"    SourceRevision = {_quoted(branch.source_revision)}")
        for point in branch.points:
            values = [f"{point.chainage:.6f}", f"{point.x:.9f}", f"{point.y:.9f}"]
            if point.z is not None or point.point_code:
                values.extend([
                    "" if point.z is None else f"{point.z:.6f}",
                    _quoted(point.point_code) if point.point_code else "",
                ])
            lines.append("    Point = " + ", ".join(values))
        lines.append("  EndSect  // BRANCH")
    lines.append("EndSect  // HYDRO_NETWORK")
    return ("\n".join(lines) + "\n").encode("utf-8")


def export_xns11_subset(payload: HydraulicExchangePayload) -> bytes:
    """Serialize raw distance/elevation sections to the deterministic text subset."""

    lines = [
        "// HYDRO-DATA-01-XNS11",
        "// ROUNDTRIP_VALIDATED_ONLY: native DHI validation is an external acceptance step.",
        f"NetworkCode = {_quoted(payload.network_code)}",
        f"NetworkName = {_quoted(payload.network_name)}",
        f"SourceCRS = 'EPSG:{payload.source_srid}'",
    ]
    for section in payload.sections:
        lines.extend([
            "[CROSS_SECTION]",
            f"  SectionCode = {_quoted(section.section_code)}",
            f"  BranchCode = {_quoted(section.branch_code)}",
            f"  Chainage = {section.chainage:.6f}",
            f"  TopographyID = {_quoted(section.topography_id)}",
        ])
        if section.section_name:
            lines.append(f"  SectionName = {_quoted(section.section_name)}")
        if section.survey_date:
            lines.append(f"  SurveyDate = {_quoted(section.survey_date.isoformat())}")
        if section.survey_method:
            lines.append(f"  SurveyMethod = {_quoted(section.survey_method)}")
        lines.append(f"  DefaultManningN = {section.default_manning_n:.9f}")
        if section.location_x is not None and section.location_y is not None:
            lines.append(f"  Location = {section.location_x:.9f}, {section.location_y:.9f}")
        lines.extend(f"  AxisPoint = {x:.9f}, {y:.9f}" for x, y in section.axis_points)
        for point in section.points:
            values = [
                str(point.sequence), f"{point.distance:.6f}", f"{point.elevation:.6f}",
                "" if point.x is None else f"{point.x:.9f}",
                "" if point.y is None else f"{point.y:.9f}",
                "" if point.z is None else f"{point.z:.6f}",
                point.marker_type, _quoted(point.point_code) if point.point_code else "",
            ]
            lines.append("  Point = " + ", ".join(values))
        lines.extend(
            "  RoughnessZone = "
            f"{zone.zone_order}, {zone.offset_start_m:.6f}, {zone.offset_end_m:.6f}, "
            f"{zone.manning_n:.9f}, {zone.zone_type}"
            for zone in section.roughness_zones
        )
        lines.append("EndSect  // CROSS_SECTION")
    return ("\n".join(lines) + "\n").encode("utf-8")


def export_native_xns11(payload: HydraulicExchangePayload) -> bytes:
    """Refuse native output because licensed DHI validation is an external adapter boundary."""

    del payload
    raise RuntimeError(
        "native XNS11 export is not part of the server runtime; use the deterministic "
        "exchange subset and validate/convert it in the licensed external environment"
    )
