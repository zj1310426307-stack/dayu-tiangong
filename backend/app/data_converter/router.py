"""HTTP boundary for GDAL capability, inspection, conversion, and PostGIS import."""

import hashlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app.data_converter import exporter, gdal_service, importer, validator
from app.dgis.schemas import ConversionCapabilityResponse, ConversionJobResponse
from app.gis.models import DatasetVersion, GISImportBatch


router = APIRouter(prefix="/api/v1/dgis/conversions", tags=["dgis-conversion"])
FileUpload = Annotated[UploadFile, File()]
TargetSrid = Annotated[int, Form()]
SessionDependency = Annotated[Session, Depends(get_database_session)]
GovernedEntityType = Literal["river", "cross_section", "gate", "pump"]


ENTITY_TYPE_ALIASES: dict[str, GovernedEntityType] = {
    "river": "river",
    "rivers": "river",
    "cross_section": "cross_section",
    "cross_sections": "cross_section",
    "gate": "gate",
    "gates": "gate",
    "pump": "pump",
    "pumps": "pump",
}


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
    session: SessionDependency,
    target_srid: TargetSrid = 4490,
    entity_type: Annotated[GovernedEntityType | None, Form()] = None,
    parent_version_id: Annotated[int | None, Form(gt=0)] = None,
    operator: Annotated[str, Form(min_length=1, max_length=64)] = "legacy-gdal-api",
) -> ConversionJobResponse:
    """Land one explicit governed entity in an immutable raw table and source batch."""

    filename, content = await _read_upload(file)
    batch: GISImportBatch | None = None
    try:
        target_srid = validator.validate_governed_target_srid(target_srid)
        logical_label = validator.validate_layer_name(layer_name).lower()
        resolved_entity_type = entity_type or ENTITY_TYPE_ALIASES.get(logical_label)
        if resolved_entity_type is None:
            raise validator.ConversionValidationError(
                "entity_type is required when layer_name is not a known governed alias"
            )
        normalized_operator = operator.strip()
        if not normalized_operator:
            raise validator.ConversionValidationError("operator must not be blank")

        parent_version: DatasetVersion | None = None
        if parent_version_id is not None:
            parent_version = session.get(DatasetVersion, parent_version_id)
            if parent_version is None:
                raise validator.ConversionValidationError(
                    "parent_version_id does not identify an existing dataset version"
                )
            if parent_version.status not in {"approved", "published", "retired"}:
                raise validator.ConversionValidationError(
                    "parent dataset version must be approved, published, or retired"
                )
            if not (parent_version.content_hash or "").strip():
                raise validator.ConversionValidationError(
                    "parent dataset version must have a content_hash"
                )

        job_id, input_format, source = importer.stage_upload(filename, content, "vector")
        table_name = importer.immutable_table_name(job_id, layer_name)
        raw_location = f"imports.{table_name}"
        governance_metadata = {
            "raw_landing": {
                "status": "pending",
                "location": raw_location,
                "table_name": table_name,
            },
            "standardization": {"status": "required"},
        }
        batch = GISImportBatch(
            batch_code=job_id,
            entity_type=resolved_entity_type,
            source_filename=filename,
            source_format=input_format,
            source_size=len(content),
            source_hash_sha256=hashlib.sha256(content).hexdigest(),
            source_crs="unknown",
            target_crs=f"EPSG:{target_srid}",
            mapping_version="raw-v1",
            operator=normalized_operator,
            status="created",
            raw_location=raw_location,
            raw_table_name=table_name,
            metadata_json={"_governance": governance_metadata},
            notes=f"RAW_LANDING_PENDING: {raw_location}; logical layer label: {layer_name}",
            parent_version_id=parent_version_id,
            parent_content_hash=parent_version.content_hash if parent_version else None,
        )
        session.add(batch)
        session.commit()

        metadata = gdal_service.inspect(source, False)
        serialized_metadata = json.loads(json.dumps(metadata, default=str))
        serialized_metadata["_governance"] = governance_metadata
        batch.source_crs = gdal_service.detect_source_crs(metadata)
        batch.metadata_json = serialized_metadata
        session.commit()

        importer.import_postgis(source, table_name, target_srid)
        batch.metadata_json = {
            **serialized_metadata,
            "_governance": {
                "raw_landing": {
                    "status": "completed",
                    "location": raw_location,
                    "table_name": table_name,
                },
                "standardization": {"status": "required"},
            },
        }
        batch.notes = (
            f"RAW_LANDING_COMPLETED: {raw_location}; logical layer label: {layer_name}; "
            "standardization to staging_qgis is still required"
        )
        session.commit()
    except (validator.ConversionValidationError, gdal_service.GDALServiceError) as exc:
        if batch is not None:
            session.rollback()
            failure = str(exc)[:500]
            existing_metadata = batch.metadata_json or {}
            existing_governance = existing_metadata.get("_governance", {})
            batch.metadata_json = {
                **existing_metadata,
                "_governance": {
                    **existing_governance,
                    "raw_landing": {
                        "status": "failed",
                        "location": batch.raw_location,
                        "table_name": batch.raw_table_name,
                        "error": failure,
                    },
                    "standardization": {"status": "blocked"},
                },
            }
            batch.notes = f"RAW_LANDING_FAILED: {failure}"
            session.commit()
        raise _error(exc) from exc
    return ConversionJobResponse(
        job_id=job_id, operation="postgis", status="success", input_format=input_format,
        output_format="PostGIS", output_name=f"imports.{table_name}",
        details={
            "target_srid": target_srid,
            "database": "shared dayu_tiangong",
            "logical_layer_name": layer_name,
            "entity_type": batch.entity_type,
            "batch_id": batch.id,
            "batch_status": batch.status,
            "raw_landing_status": "completed",
            "parent_version_id": batch.parent_version_id,
            "source_hash_sha256": batch.source_hash_sha256,
            "source_size": batch.source_size,
            "source_crs": batch.source_crs,
        },
    )
