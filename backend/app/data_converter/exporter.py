"""Create GeoJSON and COG outputs with GDAL inside the conversion job directory."""

from pathlib import Path

from app.data_converter import gdal_service, validator


def to_geojson(source: Path, target_srid: int) -> Path:
    """Export a staged vector source to RFC 7946 GeoJSON."""

    target = source.parent / "output.geojson"
    gdal_service.vector_to_geojson(source, target, validator.validate_srid(target_srid))
    return target


def to_cog(source: Path, target_srid: int) -> Path:
    """Export a staged raster source to a Cloud Optimized GeoTIFF."""

    target = source.parent / "output.cog.tif"
    gdal_service.raster_to_cog(source, target, validator.validate_srid(target_srid))
    return target
