"""HTTP boundary for GDAL capability, inspection, conversion, and PostGIS import."""

from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.data_converter import exporter, gdal_service, importer, validator
from app.dgis.schemas import ConversionCapabilityResponse, ConversionJobResponse


router = APIRouter(prefix="/api/v1/dgis/conversions", tags=["dgis-conversion"])
FileUpload = Annotated[UploadFile, File()]
TargetSrid = Annotated[int, Form()]


async def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    """Read one upload after preserving its client filename for suffix validation."""

    return file.filename or "upload", await file.read()


def _error(exc: Exception) -> HTTPException:
    """Map validation and GDAL failures to stable HTTP semantics."""

    if isinstance(exc, validator.ConversionValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=503, detail=str(exc))


@router.get("/capabilities", response_model=ConversionCapabilityResponse, summary="读取 GDAL 转换能力")
def read_capabilities() -> ConversionCapabilityResponse:
    """Report the actual GDAL runtime and the fixed input/output format contract."""

    installed = gdal_service.version()
    return ConversionCapabilityResponse(
        status="online" if installed else "offline",
        gdal_version=installed,
        vector_inputs=["ESRI Shapefile ZIP", "GeoJSON", "KML", "DXF"],
        raster_inputs=["GeoTIFF"],
        outputs=["PostGIS", "GeoJSON", "COG"],
        cad_note="CAD support uses GDAL/OGR DXF; DWG requires a separately licensed GDAL driver.",
    )


@router.post("/inspect", response_model=ConversionJobResponse, summary="校验并检查空间文件")
async def inspect_file(file: FileUpload) -> ConversionJobResponse:
    """Stage and inspect one supported vector or raster source through GDAL."""

    filename, content = await _read_upload(file)
    try:
        job_id, input_format, source = importer.stage_upload(filename, content)
        details = gdal_service.inspect(source, input_format == "GeoTIFF")
    except (validator.ConversionValidationError, gdal_service.GDALServiceError) as exc:
        raise _error(exc) from exc
    return ConversionJobResponse(
        job_id=job_id, operation="inspect", status="success", input_format=input_format,
        output_format="metadata", output_name=None, details=details,
    )


@router.post("/geojson", response_model=ConversionJobResponse, summary="转换为 GeoJSON")
async def convert_geojson(file: FileUpload, target_srid: TargetSrid = 4490) -> ConversionJobResponse:
    """Convert a supported vector source to a controlled GeoJSON artifact."""

    filename, content = await _read_upload(file)
    try:
        job_id, input_format, source = importer.stage_upload(filename, content, "vector")
        target = exporter.to_geojson(source, target_srid)
    except (validator.ConversionValidationError, gdal_service.GDALServiceError) as exc:
        raise _error(exc) from exc
    return ConversionJobResponse(
        job_id=job_id, operation="geojson", status="success", input_format=input_format,
        output_format="GeoJSON", output_name=target.name, details={"target_srid": target_srid},
    )


@router.post("/cog", response_model=ConversionJobResponse, summary="转换为 COG")
async def convert_cog(file: FileUpload, target_srid: TargetSrid = 4490) -> ConversionJobResponse:
    """Convert a GeoTIFF into a tiled, compressed Cloud Optimized GeoTIFF."""

    filename, content = await _read_upload(file)
    try:
        job_id, input_format, source = importer.stage_upload(filename, content, "raster")
        target = exporter.to_cog(source, target_srid)
    except (validator.ConversionValidationError, gdal_service.GDALServiceError) as exc:
        raise _error(exc) from exc
    return ConversionJobResponse(
        job_id=job_id, operation="cog", status="success", input_format=input_format,
        output_format="COG", output_name=target.name, details={"target_srid": target_srid},
    )


@router.post("/postgis", response_model=ConversionJobResponse, summary="导入 PostGIS")
async def import_to_postgis(
    file: FileUpload,
    layer_name: Annotated[str, Form(min_length=1, max_length=63)],
    target_srid: TargetSrid = 4490,
) -> ConversionJobResponse:
    """Import a vector source into the isolated imports schema in the shared database."""

    filename, content = await _read_upload(file)
    try:
        job_id, input_format, source = importer.stage_upload(filename, content, "vector")
        importer.import_postgis(source, layer_name, target_srid)
    except (validator.ConversionValidationError, gdal_service.GDALServiceError) as exc:
        raise _error(exc) from exc
    return ConversionJobResponse(
        job_id=job_id, operation="postgis", status="success", input_format=input_format,
        output_format="PostGIS", output_name=f"imports.{layer_name.lower()}",
        details={"target_srid": target_srid, "database": "shared dayu_tiangong"},
    )
