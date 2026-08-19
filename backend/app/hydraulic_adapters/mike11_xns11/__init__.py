"""Deterministic XNS11 exchange-subset adapter without licensed runtime coupling."""

from __future__ import annotations

from datetime import date
import re

from app.hydraulic.importers.common import (
    decode_text,
    file_identity,
    key_value,
    repeated_values,
    safe_code,
)
from app.hydraulic.schemas import (
    HydraulicCrossSectionInput,
    HydraulicExchangePayload,
    HydraulicRoughnessZoneInput,
    HydraulicSectionPointInput,
)


def _section_blocks(text: str) -> list[str]:
    """Extract explicit exchange-profile cross-section blocks."""

    return [
        match.group(1)
        for match in re.finditer(
            r"(?is)\[\s*(?:HYDRAULIC_)?CROSS_SECTION\s*\](.*?)(?:EndSect\s*//\s*(?:HYDRAULIC_)?CROSS_SECTION|\[/\s*(?:HYDRAULIC_)?CROSS_SECTION\s*\])",
            text,
        )
    ]


def parse_exchange_subset(
    filename: str, text: str, source_srid: int
) -> HydraulicExchangePayload:
    """Parse the documented HYDRO-DATA-01 ``.xns11`` text subset."""

    blocks = _section_blocks(text)
    if not blocks:
        raise ValueError("file does not contain HYDRO-DATA-01 CROSS_SECTION blocks")
    default_code, default_name = file_identity(filename, "XNS11")
    sections: list[HydraulicCrossSectionInput] = []
    for index, block in enumerate(blocks, start=1):
        branch_code = safe_code(
            key_value(block, "BranchCode", "LocationID", "ReachID", default="") or "",
            f"BRANCH-{index:03d}",
        )
        section_code = safe_code(
            key_value(block, "SectionCode", "Info", default=f"XS-{index:04d}")
            or f"XS-{index:04d}",
            f"XS-{index:04d}",
        )
        raw_points = repeated_values(block, "Point", "RawPoint", "XZPoint")
        points: list[HydraulicSectionPointInput] = []
        for row_number, row in enumerate(raw_points):
            if len(row) == 2:
                sequence, distance, elevation = row_number, float(row[0]), float(row[1])
                x = y = z = None
            elif len(row) >= 3:
                sequence, distance, elevation = int(row[0]), float(row[1]), float(row[2])
                x = float(row[3]) if len(row) > 4 and row[3] and row[4] else None
                y = float(row[4]) if len(row) > 4 and row[3] and row[4] else None
                z = float(row[5]) if len(row) > 5 and row[5] else None
            else:
                raise ValueError(f"section {section_code} contains an incomplete Point row")
            points.append(HydraulicSectionPointInput(
                sequence=sequence, distance=distance, elevation=elevation,
                x=x, y=y, z=z,
                marker_type=row[6].lower() if len(row) > 6 and row[6] else "none",
                point_code=row[7] if len(row) > 7 and row[7] else None,
            ))
        location = repeated_values(block, "Location")
        axis = repeated_values(block, "AxisPoint", "Coordinate")
        roughness = repeated_values(block, "RoughnessZone")
        survey_date_text = key_value(block, "SurveyDate")
        sections.append(HydraulicCrossSectionInput(
            section_code=section_code,
            section_name=key_value(block, "SectionName", "Name"),
            branch_code=branch_code,
            chainage=float(key_value(block, "Chainage", default="0") or 0),
            topography_id=(
                key_value(block, "TopographyID", "TopoID", default="DEFAULT") or "DEFAULT"
            )[:64],
            survey_date=date.fromisoformat(survey_date_text[:10]) if survey_date_text else None,
            survey_method=key_value(block, "SurveyMethod"),
            default_manning_n=float(
                key_value(block, "DefaultManningN", default="0.03") or 0.03
            ),
            location_x=float(location[0][0]) if location and len(location[0]) >= 2 else None,
            location_y=float(location[0][1]) if location and len(location[0]) >= 2 else None,
            axis_points=[(float(row[0]), float(row[1])) for row in axis if len(row) >= 2],
            roughness_zones=[HydraulicRoughnessZoneInput(
                zone_order=int(row[0]), offset_start_m=float(row[1]),
                offset_end_m=float(row[2]), manning_n=float(row[3]),
                zone_type=row[4] if len(row) > 4 and row[4] else "custom",
            ) for row in roughness if len(row) >= 4],
            points=points,
        ))
    return HydraulicExchangePayload(
        network_code=safe_code(
            key_value(text, "NetworkCode", default=default_code) or default_code, default_code
        ),
        network_name=(
            key_value(text, "NetworkName", default=default_name) or default_name
        )[:128],
        source_srid=source_srid,
        source_kind="mike11",
        sections=sections,
    )


def native_xns11_available() -> bool:
    """Native MIKE11 is an external acceptance environment, never a server dependency."""

    return False


def parse_xns11(filename: str, content: bytes, source_srid: int):
    """Parse only the declared auditable text subset and fail closed otherwise."""

    try:
        text = decode_text(content)
    except ValueError as exc:
        raise ValueError(
            "native XNS11 is not parsed by the application runtime; validate it in a "
            "licensed external environment"
        ) from exc
    if not (_section_blocks(text) or "HYDRO-DATA-01-XNS11" in text):
        raise ValueError(
            "native XNS11 is not parsed by the application runtime; provide the declared "
            "HYDRO-DATA-01 subset and validate native files externally"
        )
    return (
        parse_exchange_subset(filename, text, source_srid),
        "hydro-data-01-xns11-subset-v1",
        "ROUNDTRIP_VALIDATED_ONLY",
    )


__all__ = ["native_xns11_available", "parse_exchange_subset", "parse_xns11"]
