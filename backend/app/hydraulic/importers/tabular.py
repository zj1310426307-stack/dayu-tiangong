"""Parse UTF-8 CSV rows into the neutral hydraulic exchange DTO."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date
from io import StringIO

from app.hydraulic.importers.common import file_identity, safe_code
from app.hydraulic.importers.security import (
    DEFAULT_IMPORT_BUDGET,
    HydraulicImportBudget,
    validate_import_envelope,
)
from app.hydraulic.schemas import (
    HydraulicBranchInput,
    HydraulicChainageInput,
    HydraulicCrossSectionInput,
    HydraulicExchangePayload,
    HydraulicRoughnessZoneInput,
    HydraulicSectionPointInput,
)


def _number(row: dict[str, str], name: str) -> float:
    """Read one required numeric CSV field with a stable error message."""

    value = (row.get(name) or "").strip()
    if not value:
        raise ValueError(f"CSV field {name} is required")
    return float(value)


def parse_csv(
    filename: str,
    content: bytes,
    source_srid: int,
    *,
    budget: HydraulicImportBudget = DEFAULT_IMPORT_BUDGET,
) -> HydraulicExchangePayload:
    """Parse rows distinguished by ``record_type`` as branch or section points."""

    validate_import_envelope(filename, content, budget=budget)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8 or UTF-8 with BOM") from exc
    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV header is required")
    if len(reader.fieldnames) > budget.max_csv_columns:
        raise ValueError(
            f"CSV declares {len(reader.fieldnames)} columns; limit is "
            f"{budget.max_csv_columns}"
        )
    rows: list[dict[str, str]] = []
    for row_index, row in enumerate(reader, start=1):
        if row_index > budget.max_csv_rows:
            raise ValueError(
                f"CSV contains more than {budget.max_csv_rows} data rows"
            )
        if None in row:
            raise ValueError(f"CSV row {row_index + 1} contains undeclared columns")
        rows.append({
            str(key).strip().lower(): (value or "").strip()
            for key, value in row.items()
        })
    branch_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    section_rows: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for index, row in enumerate(rows, start=2):
        record_type = row.get("record_type", "").lower()
        if record_type in {"branch", "branch_point"}:
            branch_rows[safe_code(row.get("branch_code", ""), f"BRANCH-{index:03d}")].append(row)
        elif record_type in {"section", "section_point"}:
            section_code = safe_code(row.get("section_code", ""), f"XS-{index:04d}")
            topography_id = (row.get("topography_id") or "DEFAULT")[:64]
            section_rows[(section_code, topography_id)].append(row)
        else:
            raise ValueError(f"CSV row {index} record_type must be branch_point or section_point")
    branches: list[HydraulicBranchInput] = []
    for code, group in branch_rows.items():
        ordered = sorted(group, key=lambda row: _number(row, "chainage"))
        first = ordered[0]
        branches.append(HydraulicBranchInput(
            code=code,
            river_name=(first.get("river_name") or first.get("branch_name") or code)[:128],
            branch_name=(first.get("branch_name") or code)[:128],
            flow_direction=(first.get("flow_direction") or "unknown").lower(),
            source_revision=first.get("source_revision") or None,
            points=[HydraulicChainageInput(
                chainage=_number(row, "chainage"), x=_number(row, "x"), y=_number(row, "y"),
                z=float(row["z"]) if row.get("z") else None,
                point_code=row.get("point_code") or None,
            ) for row in ordered],
        ))
    sections: list[HydraulicCrossSectionInput] = []
    for (code, topography_id), group in section_rows.items():
        ordered = sorted(group, key=lambda row: int(row.get("sequence") or 0))
        first = ordered[0]
        axis_points: list[tuple[float, float]] = []
        for row in ordered:
            if row.get("axis_x") and row.get("axis_y"):
                point = (float(row["axis_x"]), float(row["axis_y"]))
                if point not in axis_points:
                    axis_points.append(point)
        roughness_by_order: dict[int, HydraulicRoughnessZoneInput] = {}
        for row in ordered:
            if not row.get("roughness_zone_order"):
                continue
            zone_order = int(row["roughness_zone_order"])
            roughness_by_order[zone_order] = HydraulicRoughnessZoneInput(
                zone_order=zone_order,
                offset_start_m=_number(row, "roughness_start"),
                offset_end_m=_number(row, "roughness_end"),
                manning_n=_number(row, "roughness_n"),
                zone_type=(row.get("roughness_type") or "custom")[:32],
            )
        survey_date = None
        if first.get("survey_date"):
            survey_date = date.fromisoformat(first["survey_date"][:10])
        sections.append(HydraulicCrossSectionInput(
            section_code=code,
            section_name=first.get("section_name") or code,
            branch_code=safe_code(first.get("branch_code", ""), "BRANCH-UNKNOWN"),
            chainage=_number(first, "chainage"),
            topography_id=topography_id,
            survey_date=survey_date,
            survey_method=first.get("survey_method") or None,
            default_manning_n=float(
                first.get("default_manning_n") or first.get("manning_n") or 0.03
            ),
            location_x=float(first["location_x"]) if first.get("location_x") else None,
            location_y=float(first["location_y"]) if first.get("location_y") else None,
            axis_points=axis_points,
            roughness_zones=[roughness_by_order[key] for key in sorted(roughness_by_order)],
            points=[HydraulicSectionPointInput(
                sequence=int(row.get("sequence") or index),
                distance=_number(row, "distance"), elevation=_number(row, "elevation"),
                marker_type=(row.get("marker_type") or "none").lower(),
                point_code=row.get("point_code") or None,
                x=float(row["point_x"]) if row.get("point_x") else None,
                y=float(row["point_y"]) if row.get("point_y") else None,
                z=float(row["point_z"]) if row.get("point_z") else None,
            ) for index, row in enumerate(ordered)],
        ))
    code, name = file_identity(filename, "HYDRAULIC-CSV")
    if rows:
        code = safe_code(rows[0].get("network_code", ""), code)
        name = (rows[0].get("network_name") or name)[:128]
    return HydraulicExchangePayload(
        network_code=code, network_name=name, source_srid=source_srid,
        source_kind="csv", branches=branches, sections=sections,
    )
