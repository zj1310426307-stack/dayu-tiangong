"""Parse the documented HYDRO-DATA-01 PFS subset carried in ``.nwk11`` files."""

from __future__ import annotations

import re

from app.hydraulic.importers.common import (
    decode_text,
    file_identity,
    key_value,
    repeated_values,
    safe_code,
)
from app.hydraulic.schemas import (
    HydraulicBranchInput,
    HydraulicChainageInput,
    HydraulicExchangePayload,
)


def _branch_blocks(text: str) -> list[str]:
    """Extract explicit branch sections without claiming arbitrary PFS compatibility."""

    return [
        match.group(1)
        for match in re.finditer(
            r"(?is)\[\s*(?:HYDRAULIC_)?BRANCH\s*\](.*?)(?:EndSect\s*//\s*(?:HYDRAULIC_)?BRANCH|\[/\s*(?:HYDRAULIC_)?BRANCH\s*\])",
            text,
        )
    ]


def parse_nwk11(filename: str, content: bytes, source_srid: int) -> HydraulicExchangePayload:
    """Parse branch identity and ``chainage,x,y`` rows from the declared subset."""

    text = decode_text(content)
    blocks = _branch_blocks(text)
    if not blocks:
        raise ValueError(
            "native NWK11 was not recognized; provide a HYDRO-DATA-01 PFS subset "
            "or validate through a licensed DHI adapter"
        )
    default_code, default_name = file_identity(filename, "NWK11")
    network_code = safe_code(
        key_value(text, "NetworkCode", "NetworkID", default=default_code) or default_code,
        default_code,
    )
    network_name = (
        key_value(text, "NetworkName", "Name", default=default_name) or default_name
    )[:128]
    branches: list[HydraulicBranchInput] = []
    for index, block in enumerate(blocks, start=1):
        branch_name = (
            key_value(block, "BranchName", "Name", default=f"Branch {index}")
            or f"Branch {index}"
        )
        river_name = key_value(block, "RiverName", default=branch_name) or branch_name
        branch_code = safe_code(
            key_value(block, "Code", "BranchCode", "BranchID", default=branch_name)
            or branch_name,
            f"BRANCH-{index:03d}",
        )
        rows = repeated_values(block, "Point", "ChainagePoint", "GeometryPoint")
        if len(rows) < 2:
            raise ValueError(f"branch {branch_code} requires at least two Point rows")
        points: list[HydraulicChainageInput] = []
        for row_number, row in enumerate(rows, start=1):
            if len(row) < 3:
                raise ValueError(
                    f"branch {branch_code} Point row {row_number} must be chainage,x,y"
                )
            points.append(HydraulicChainageInput(
                chainage=float(row[0]), x=float(row[1]), y=float(row[2]),
                z=float(row[3]) if len(row) > 3 and row[3] else None,
                point_code=row[4] if len(row) > 4 and row[4] else None,
            ))
        direction = (key_value(block, "FlowDirection", default="unknown") or "unknown").lower()
        branches.append(HydraulicBranchInput(
            code=branch_code,
            river_name=river_name[:128],
            branch_name=branch_name[:128],
            flow_direction=direction,
            source_revision=key_value(block, "SourceRevision"),
            points=points,
        ))
    return HydraulicExchangePayload(
        network_code=network_code,
        network_name=network_name,
        source_srid=source_srid,
        source_kind="mike11",
        branches=branches,
    )


__all__ = ["parse_nwk11"]
