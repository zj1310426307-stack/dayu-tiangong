"""Coordinate validated uploads and GDAL imports inside controlled project storage."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from uuid import uuid4

from app.data_converter import gdal_service, validator


STORAGE_ROOT = Path(__file__).resolve().parents[2] / "storage" / "conversions"


def stage_upload(filename: str, content: bytes, expected: str = "any") -> tuple[str, str, Path]:
    """Store one validated source under a random job directory and return its usable path."""

    input_format = validator.validate_upload(filename, content, expected)
    job_id = uuid4().hex
    job_root = STORAGE_ROOT / job_id
    job_root.mkdir(parents=True, exist_ok=False)
    safe_name = f"source{Path(filename).suffix.lower()}"
    archive_path = job_root / safe_name
    archive_path.write_bytes(content)
    if input_format != "ESRI Shapefile":
        return job_id, input_format, archive_path
    extract_root = job_root / "source"
    extract_root.mkdir()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            target = extract_root / Path(member.filename).name
            with archive.open(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
    shape = next(extract_root.glob("*.shp"), None)
    if shape is None:
        raise validator.ConversionValidationError("Shapefile ZIP contains no .shp dataset")
    return job_id, input_format, shape


def import_postgis(source: Path, layer_name: str, target_srid: int) -> None:
    """Import a staged vector source to the shared PostGIS imports schema."""

    gdal_service.vector_to_postgis(
        source, validator.validate_layer_name(layer_name), validator.validate_srid(target_srid)
    )
