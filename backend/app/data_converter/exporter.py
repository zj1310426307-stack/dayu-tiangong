"""Create GeoJSON and COG outputs with GDAL inside the conversion job directory."""

from pathlib import Path

from app.data_converter import gdal_service, validator
from app.files import atomic_output_path


def to_geojson(source: Path, target_srid: int) -> Path:
    """Export a staged vector source to RFC 7946 GeoJSON."""

    with atomic_output_path(source.parent, "output.geojson") as (temporary, target):
        gdal_service.vector_to_geojson(
            source, temporary, validator.validate_srid(target_srid)
        )
    return target


def to_cog(source: Path, target_srid: int) -> Path:
    """Export a staged raster source to a Cloud Optimized GeoTIFF."""

    with atomic_output_path(source.parent, "output.cog.tif") as (temporary, target):
        gdal_service.raster_to_cog(
            source, temporary, validator.validate_srid(target_srid)
        )
    return target
