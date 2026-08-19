"""Fail-closed resource budgets for untrusted hydraulic import files."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import BadZipFile, ZipFile


@dataclass(frozen=True, slots=True)
class HydraulicImportBudget:
    """Bound compressed bytes and parser-visible structure before normalisation."""

    max_import_bytes: int = 100 * 1024 * 1024
    max_archive_members: int = 2_048
    max_archive_member_bytes: int = 256 * 1024 * 1024
    max_archive_uncompressed_bytes: int = 512 * 1024 * 1024
    max_archive_compression_ratio: float = 200.0
    max_csv_rows: int = 250_000
    max_csv_columns: int = 128
    max_xlsx_cells: int = 2_000_000


DEFAULT_IMPORT_BUDGET = HydraulicImportBudget()


def _validate_archive(content: bytes, budget: HydraulicImportBudget) -> None:
    """Inspect ZIP metadata without extracting attacker-controlled members."""

    try:
        with ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
    except BadZipFile as exc:
        raise ValueError("ZIP/XLSX container is invalid") from exc
    if len(members) > budget.max_archive_members:
        raise ValueError(
            f"archive contains {len(members)} members; limit is "
            f"{budget.max_archive_members}"
        )
    total_uncompressed = 0
    for member in members:
        path = PurePosixPath(member.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"archive member path is unsafe: {member.filename}")
        if member.flag_bits & 0x1:
            raise ValueError(f"encrypted archive member is not supported: {member.filename}")
        if member.file_size > budget.max_archive_member_bytes:
            raise ValueError(
                f"archive member {member.filename} expands beyond the per-member budget"
            )
        total_uncompressed += member.file_size
        if total_uncompressed > budget.max_archive_uncompressed_bytes:
            raise ValueError("archive expands beyond the total uncompressed-byte budget")
        if member.file_size:
            if member.compress_size <= 0:
                raise ValueError(f"archive member {member.filename} has an invalid size ratio")
            ratio = member.file_size / member.compress_size
            if ratio > budget.max_archive_compression_ratio:
                raise ValueError(
                    f"archive member {member.filename} compression ratio {ratio:.1f} "
                    f"exceeds {budget.max_archive_compression_ratio:.1f}"
                )


def validate_import_envelope(
    filename: str,
    content: bytes,
    *,
    budget: HydraulicImportBudget = DEFAULT_IMPORT_BUDGET,
) -> None:
    """Reject oversized bytes and hazardous ZIP containers before any parser runs."""

    if not content:
        raise ValueError("hydraulic import file is empty")
    if len(content) > budget.max_import_bytes:
        raise ValueError(
            f"hydraulic import file is {len(content)} bytes; limit is "
            f"{budget.max_import_bytes} bytes"
        )
    if Path(filename).suffix.lower() in {".xlsx", ".zip"}:
        _validate_archive(content, budget)


def validate_xlsx_cell_budget(
    workbook: Any,
    *,
    budget: HydraulicImportBudget = DEFAULT_IMPORT_BUDGET,
) -> None:
    """Use declared sheet dimensions to stop sparse or dense cell explosions."""

    total_cells = 0
    for sheet in workbook.worksheets:
        rows = max(int(sheet.max_row or 0), 0)
        columns = max(int(sheet.max_column or 0), 0)
        total_cells += rows * columns
        if total_cells > budget.max_xlsx_cells:
            raise ValueError(
                f"XLSX declares {total_cells} cells; limit is {budget.max_xlsx_cells}"
            )
