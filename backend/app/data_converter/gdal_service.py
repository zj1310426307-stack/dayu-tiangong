"""Execute bounded GDAL/OGR subprocesses without shell interpolation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


class GDALServiceError(RuntimeError):
    """Represent a missing engine or failed GDAL command with sanitized output."""


def _executable(name: str) -> str:
    """Resolve one required GDAL binary from the runtime PATH."""

    value = shutil.which(name)
    if value is None:
        raise GDALServiceError(f"{name} is not installed in the backend runtime")
    return value


def _run(
    arguments: list[str], timeout: int = 120, environment: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run one fixed argument vector with a timeout and no shell."""

    try:
        result = subprocess.run(
            arguments, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False, shell=False, env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GDALServiceError("GDAL operation could not complete within the runtime boundary") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["unknown error"]
        raise GDALServiceError(f"GDAL operation failed: {detail[0][:400]}")
    return result


def version() -> str | None:
    """Return the installed GDAL version without treating absence as an exception."""

    try:
        return _run([_executable("gdalinfo"), "--version"], timeout=10).stdout.strip()
    except GDALServiceError:
        return None


def inspect(path: Path, raster: bool) -> dict[str, Any]:
    """Read GDAL/OGR metadata as JSON for validation and preview."""

    tool = "gdalinfo" if raster else "ogrinfo"
    arguments = [_executable(tool), "-json", str(path)]
    if not raster:
        arguments.insert(1, "-so")
        arguments.insert(2, "-al")
    payload = _run(arguments).stdout
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise GDALServiceError("GDAL metadata response is not valid JSON") from exc
    return value if isinstance(value, dict) else {"value": value}


def detect_source_crs(metadata: dict[str, Any]) -> str:
    """Extract an auditable source CRS label from common GDAL/OGR JSON shapes."""

    def coordinate_system_label(value: object) -> str | None:
        """Return a CRS identifier or bounded WKT, never a geometry type."""

        if not isinstance(value, dict):
            return None
        identifier = value.get("id")
        if isinstance(identifier, dict):
            authority = identifier.get("authority")
            code = identifier.get("code")
            if authority and code is not None:
                return f"{authority}:{code}"[:64]
        projjson = value.get("projjson")
        if isinstance(projjson, dict):
            identifier = projjson.get("id")
            if isinstance(identifier, dict):
                authority = identifier.get("authority")
                code = identifier.get("code")
                if authority and code is not None:
                    return f"{authority}:{code}"[:64]
        wkt = value.get("wkt")
        if isinstance(wkt, str) and wkt.strip():
            return wkt.strip()[:64]
        return None

    layers = metadata.get("layers")
    if isinstance(layers, list) and layers:
        layer = layers[0] if isinstance(layers[0], dict) else {}
        fields = layer.get("geometryFields")
        if isinstance(fields, list) and fields and isinstance(fields[0], dict):
            label = coordinate_system_label(fields[0].get("coordinateSystem"))
            if label:
                return label
        srs_name = layer.get("srsName")
        if isinstance(srs_name, str) and srs_name.strip():
            return srs_name.strip()[:64]
        label = coordinate_system_label(layer.get("coordinateSystem"))
        if label:
            return label
    label = coordinate_system_label(metadata.get("coordinateSystem"))
    if label:
        return label
    return "unknown"


def vector_to_geojson(source: Path, target: Path, target_srid: int) -> None:
    """Convert a vector dataset through ogr2ogr and normalize its target CRS."""

    _run([
        _executable("ogr2ogr"), "-f", "GeoJSON", "-t_srs", f"EPSG:{target_srid}",
        "-lco", "RFC7946=YES", str(target), str(source),
    ])


def raster_to_cog(source: Path, target: Path, target_srid: int) -> None:
    """Create a tiled, compressed Cloud Optimized GeoTIFF with GDAL's COG driver."""

    _run([
        _executable("gdalwarp"), "-of", "COG", "-t_srs", f"EPSG:{target_srid}",
        "-co", "COMPRESS=DEFLATE", "-co", "BIGTIFF=IF_SAFER", str(source), str(target),
    ])


def vector_to_postgis(source: Path, table_name: str, target_srid: int) -> None:
    """Create one batch-scoped immutable raw table in the shared PostGIS instance."""

    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "dayu_tiangong")
    user = os.getenv("POSTGRES_USER", "dayu")
    env_dsn = f"PG:host={host} port={port} dbname={database} user={user}"
    password = os.getenv("POSTGRES_PASSWORD")
    environment = os.environ.copy()
    if password:
        environment["PGPASSWORD"] = password
    _run([
        _executable("ogr2ogr"), "-f", "PostgreSQL", env_dsn, str(source),
        "-nln", f"imports.{table_name}", "-nlt", "PROMOTE_TO_MULTI", "-t_srs",
        f"EPSG:{target_srid}", "-lco", "GEOMETRY_NAME=geometry",
    ], environment=environment)
