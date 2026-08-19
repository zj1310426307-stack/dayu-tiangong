"""Dispatch supported hydraulic files into one normalized exchange payload."""

from pathlib import Path

from app.hydraulic.importers.excel import parse_excel
from app.hydraulic.importers.security import validate_import_envelope
from app.hydraulic.importers.tabular import parse_csv
from app.hydraulic.importers.vector import parse_vector
from app.hydraulic_adapters.mike11_nwk11 import parse_nwk11
from app.hydraulic_adapters.mike11_xns11 import native_xns11_available, parse_xns11
from app.hydraulic.schemas import HydraulicExchangePayload


class HydraulicParseError(ValueError):
    """Indicate that a file cannot be safely normalized by a supported parser."""


def source_format(filename: str) -> str:
    """Return the normalized format key from an explicit filename suffix."""

    suffix = Path(filename).suffix.lower()
    formats = {
        ".nwk11": "nwk11",
        ".xns11": "xns11",
        ".xlsx": "xlsx",
        ".csv": "csv",
        ".geojson": "geojson",
        ".json": "geojson",
        ".zip": "shp",
        ".dxf": "dxf",
    }
    try:
        return formats[suffix]
    except KeyError as exc:
        raise HydraulicParseError(
            "supported hydraulic suffixes are .nwk11, .xns11, .xlsx, .csv, "
            ".geojson, .json, .zip, and .dxf"
        ) from exc


def parse_hydraulic_file(
    filename: str, content: bytes, source_srid: int
) -> tuple[HydraulicExchangePayload, str, str]:
    """Dispatch one upload and return payload, parser profile, and native status."""

    kind = source_format(filename)
    try:
        validate_import_envelope(filename, content)
        if kind == "nwk11":
            payload = parse_nwk11(filename, content, source_srid)
            return payload, "hydro-data-01-pfs-subset-v1", "ROUNDTRIP_VALIDATED_ONLY"
        if kind == "xns11":
            return parse_xns11(filename, content, source_srid)
        if kind == "xlsx":
            return parse_excel(filename, content, source_srid), "hydraulic-xlsx-v1", "NOT_APPLICABLE"
        if kind == "csv":
            return parse_csv(filename, content, source_srid), "hydraulic-csv-v1", "NOT_APPLICABLE"
        return parse_vector(filename, content, source_srid, kind), "gdal-hydraulic-v1", "NOT_APPLICABLE"
    except HydraulicParseError:
        raise
    except Exception as exc:
        raise HydraulicParseError(str(exc)[:500]) from exc


__all__ = [
    "HydraulicParseError",
    "native_xns11_available",
    "parse_hydraulic_file",
    "source_format",
]
