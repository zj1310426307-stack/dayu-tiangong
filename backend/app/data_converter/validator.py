"""Validate uploaded geospatial data before GDAL receives filesystem paths."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path, PurePosixPath


MAX_UPLOAD_BYTES = 100 * 1024 * 1024
SAFE_LAYER_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")
VECTOR_SUFFIXES = {".zip", ".geojson", ".json", ".kml", ".dxf"}
RASTER_SUFFIXES = {".tif", ".tiff"}


class ConversionValidationError(ValueError):
    """Indicate that uploaded data violates the conversion security contract."""


def validate_upload(filename: str, content: bytes, expected: str = "any") -> str:
    """Validate size, suffix, and Shapefile archive safety and return the normalized format."""

    if not content:
        raise ConversionValidationError("uploaded geospatial file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ConversionValidationError("uploaded geospatial file exceeds 100 MB")
    suffix = Path(filename).suffix.lower()
    accepted = VECTOR_SUFFIXES | RASTER_SUFFIXES
    if expected == "vector":
        accepted = VECTOR_SUFFIXES
    if expected == "raster":
        accepted = RASTER_SUFFIXES
    if suffix not in accepted:
        raise ConversionValidationError(f"unsupported geospatial suffix: {suffix or 'none'}")
    if suffix == ".zip":
        _validate_shapefile_zip(content)
        return "ESRI Shapefile"
    return {
        ".geojson": "GeoJSON", ".json": "GeoJSON", ".kml": "KML", ".dxf": "DXF",
        ".tif": "GeoTIFF", ".tiff": "GeoTIFF",
    }[suffix]


def _validate_shapefile_zip(content: bytes) -> None:
    """Reject traversal, decompression bombs, and incomplete Shapefile bundles."""

    from io import BytesIO

    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            files = [member for member in archive.infolist() if not member.is_dir()]
            if len(files) > 200:
                raise ConversionValidationError("Shapefile archive contains too many files")
            total_size = sum(member.file_size for member in files)
            if total_size > 250 * 1024 * 1024:
                raise ConversionValidationError("Shapefile archive expands beyond 250 MB")
            for member in files:
                path = PurePosixPath(member.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts:
                    raise ConversionValidationError("Shapefile archive contains an unsafe path")
            suffixes = {PurePosixPath(member.filename).suffix.lower() for member in files}
            if not {".shp", ".shx", ".dbf"}.issubset(suffixes):
                raise ConversionValidationError("Shapefile ZIP requires .shp, .shx and .dbf")
    except zipfile.BadZipFile as exc:
        raise ConversionValidationError("Shapefile archive is not a valid ZIP") from exc


def validate_layer_name(value: str) -> str:
    """Constrain imported table names to one unquoted PostgreSQL identifier."""

    if not SAFE_LAYER_NAME.fullmatch(value):
        raise ConversionValidationError("layer_name must match [A-Za-z][A-Za-z0-9_]{0,62}")
    return value.lower()


def validate_srid(value: int) -> int:
    """Limit target CRS values to the explicit DGIS conversion allowlist."""

    if value not in {4326, 4490, 3857}:
        raise ConversionValidationError("target_srid must be one of 4326, 4490, 3857")
    return value
