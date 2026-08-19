"""HYDRO-DATA-02 fail-closed gates for untrusted import resources."""

from dataclasses import replace
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook
from pydantic import ValidationError
import pytest

from app.hydraulic.importers import HydraulicParseError, parse_hydraulic_file
from app.hydraulic.importers.excel import parse_excel
from app.hydraulic.importers.security import (
    DEFAULT_IMPORT_BUDGET,
    validate_import_envelope,
)
from app.hydraulic.importers.tabular import parse_csv
from app.hydraulic.schemas import CoordinateReferenceSpec
from app.hydraulic.validators import validate_exchange


def _workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "network_code"
    sheet["B1"] = "branch_code"
    sheet["B3"] = "BR-01"
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _compression_bomb_bytes() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "A" * (2 * 1024 * 1024))
    return output.getvalue()


def test_wrong_crs_and_projected_coordinate_range_are_rejected() -> None:
    """Neither an unapproved CRS nor degree-like XY may reach a projected import."""

    with pytest.raises(ValidationError, match="source_crs must be one of"):
        CoordinateReferenceSpec(
            source_crs="EPSG:3857",
            engineering_crs="EPSG:4547",
            coordinate_mode="projected",
            axis_mapping="x_easting_y_northing",
            horizontal_unit="m",
            vertical_datum="1985 National Height Datum",
            central_meridian=114,
            zone_width=3,
        )

    csv_content = (
        "record_type,network_code,branch_code,chainage,x,y\n"
        "branch_point,SECURITY,BR-01,0,22,113\n"
        "branch_point,SECURITY,BR-01,10,23,114\n"
    ).encode()
    payload = parse_csv("wrong-range.csv", csv_content, 4547)
    issues = validate_exchange(payload)
    assert any(
        issue.severity == "error" and issue.code == "PROJECTED_COORDINATE_RANGE"
        for issue in issues
    )
    assert not any(issue.code == "EXCHANGE_PRECHECK_PASSED" for issue in issues)


def test_oversized_csv_bytes_rows_and_columns_hit_independent_budgets() -> None:
    """Compressed-byte limits do not replace CSV row and column structure limits."""

    assert DEFAULT_IMPORT_BUDGET.max_import_bytes == 100 * 1024 * 1024
    assert DEFAULT_IMPORT_BUDGET.max_csv_rows == 250_000
    assert DEFAULT_IMPORT_BUDGET.max_csv_columns == 128
    byte_budget = replace(DEFAULT_IMPORT_BUDGET, max_import_bytes=16)
    with pytest.raises(ValueError, match="17 bytes; limit is 16 bytes"):
        validate_import_envelope("oversized.csv", b"x" * 17, budget=byte_budget)

    row_budget = replace(DEFAULT_IMPORT_BUDGET, max_csv_rows=2)
    content = (
        "record_type,branch_code,chainage,x,y\n"
        "branch_point,BR-01,0,500000,2500000\n"
        "branch_point,BR-01,10,500010,2500000\n"
        "branch_point,BR-01,20,500020,2500000\n"
    ).encode()
    with pytest.raises(ValueError, match="more than 2 data rows"):
        parse_csv("too-many-rows.csv", content, 4547, budget=row_budget)

    column_budget = replace(DEFAULT_IMPORT_BUDGET, max_csv_columns=2)
    with pytest.raises(ValueError, match="declares 3 columns; limit is 2"):
        parse_csv(
            "too-many-columns.csv",
            b"record_type,branch_code,chainage\n",
            4547,
            budget=column_budget,
        )


def test_xlsx_compression_bomb_and_declared_cell_explosion_are_rejected() -> None:
    """ZIP expansion is checked before openpyxl and sheet dimensions before iteration."""

    assert DEFAULT_IMPORT_BUDGET.max_archive_uncompressed_bytes == 512 * 1024 * 1024
    assert DEFAULT_IMPORT_BUDGET.max_xlsx_cells == 2_000_000
    with pytest.raises(HydraulicParseError, match="compression ratio"):
        parse_hydraulic_file("bomb.xlsx", _compression_bomb_bytes(), 4547)

    cell_budget = replace(DEFAULT_IMPORT_BUDGET, max_xlsx_cells=4)
    with pytest.raises(ValueError, match="declares 6 cells; limit is 4"):
        parse_excel("too-many-cells.xlsx", _workbook_bytes(), 4547, budget=cell_budget)
