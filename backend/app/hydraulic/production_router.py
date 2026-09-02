"""Production-04 APIs composed from small solver-neutral domain operations."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import files
from app.common.http import commit_or_conflict
from app.database.session import get_database_session
from app.hydraulic.importers.security import DEFAULT_IMPORT_BUDGET
from app.hydraulic.production.calibration import (
    build_parameter_sweep,
    evaluate_acceptance,
    evaluate_validation_independence,
    rank_calibration_candidates,
)
from app.hydraulic.production.comparison import compare_external_result
from app.hydraulic.production.contracts import (
    AcceptanceEvaluation,
    AcceptanceEvaluationRequest,
    AcceptanceManifest,
    AcceptanceManifestRequest,
    CalibrationCandidate,
    CalibrationPromotionRequest,
    CalibrationRankingRequest,
    ExternalComparisonRequest,
    ExternalComparisonResult,
    ExternalResultImportOptions,
    ExternalResultPreview,
    HydraulicMetrics,
    HydraulicModelQARequest,
    HydraulicModelQAResult,
    MetricEvaluationRequest,
    ParameterSweepPlan,
    ParameterSweepRequest,
    ProductionCapabilityResponse,
    ResultProductBundle,
    ResultProductRequest,
    TimeSeriesImportOptions,
    TimeSeriesImportPreview,
    ValidationIndependenceRequest,
    ValidationIndependenceResult,
)
from app.hydraulic.production.importers import EngineeringDataImporter
from app.hydraulic.production.metrics import align_and_score
from app.hydraulic.production import persistence
from app.hydraulic.production.products import (
    build_result_products,
    export_product_csv,
    export_product_geojson,
    export_product_xlsx,
)
from app.hydraulic.production.qa import HydraulicModelQA
from app.hydraulic.production.records import (
    AuditEventRecord,
    CalibrationRunCommitRequest,
    CalibrationRunRecord,
    CalibrationPromotionResponse,
    CalibrationSweepCreateRequest,
    CalibrationSweepRunResponse,
    ExternalResultCommitRequest,
    ExternalResultRecord,
    ObservationCommitRequest,
    ObservationRecord,
    ProductionApprovalRequest,
    ProductionRunRecord,
    ProductionTaskCreateRequest,
    ResultProductCommitRequest,
    ResultProductRecord,
    ValidationRunCommitRequest,
    ValidationRunRecord,
)
from app.hydraulic.production.workflow import build_acceptance_manifest


router = APIRouter(prefix="/api/v1/hydraulic/production", tags=["hydraulic-production"])
FileUpload = Annotated[UploadFile, File()]
OptionsForm = Annotated[str, Form()]
PositiveIdForm = Annotated[int, Form(gt=0)]
CodeForm = Annotated[str, Form(min_length=1, max_length=128)]
SessionDependency = Annotated[Session, Depends(get_database_session)]


@router.get("/capabilities", response_model=ProductionCapabilityResponse)
def production_capabilities() -> ProductionCapabilityResponse:
    """Expose implemented framework capabilities and the current real-data gate."""

    return ProductionCapabilityResponse(
        engineering_import=[
            "CSV",
            "XLSX",
            "GeoJSON",
            "Shapefile ZIP",
            "DXF existing pipeline",
            "boundary/observation/external time series",
        ],
        model_qa=True,
        calibration=["manual candidate", "bounded parameter sweep", "controlled promotion"],
        validation=["dataset separation", "project acceptance criteria"],
        external_comparison=["MIKE11 legal CSV", "MIKE11 legal XLSX", "generic external result"],
        result_products=["max envelope", "profile", "scenario delta", "afflux", "CSV/XLSX/GeoJSON"],
        real_project_reason=(
            "The controlled survey fragments lack authoritative boundaries, observations, "
            "independent validation events, and MIKE11 exported results."
        ),
    )


@router.post(
    "/runs",
    response_model=ProductionRunRecord,
    status_code=status.HTTP_201_CREATED,
)
def create_production_run(
    payload: ProductionTaskCreateRequest, session: SessionDependency
) -> ProductionRunRecord:
    """Atomically create a formal task and its reproducible backend/Worker QA gate."""

    return commit_or_conflict(
        session, lambda: persistence.create_production_run(session, payload)
    )


@router.get("/runs", response_model=list[ProductionRunRecord])
def list_production_runs(
    session: SessionDependency,
    dataset_version_id: int | None = Query(default=None, gt=0),
) -> list[ProductionRunRecord]:
    """List formal production runs without exposing mutable engine workspaces."""

    return persistence.list_production_runs(session, dataset_version_id)


@router.post(
    "/calibration/runs",
    response_model=CalibrationRunRecord,
    status_code=status.HTTP_201_CREATED,
)
def commit_calibration_run(
    payload: CalibrationRunCommitRequest, session: SessionDependency
) -> CalibrationRunRecord:
    """Persist a bounded calibration experiment without overwriting source parameters."""

    return commit_or_conflict(
        session, lambda: persistence.commit_calibration_run(session, payload)
    )


@router.post(
    "/calibration/sweeps/create",
    response_model=CalibrationSweepRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_calibration_sweep(
    payload: CalibrationSweepCreateRequest, session: SessionDependency
) -> CalibrationSweepRunResponse:
    """Create bounded candidate tasks through the existing immutable Job Manager."""

    return commit_or_conflict(
        session, lambda: persistence.create_calibration_sweep(session, payload)
    )


@router.post(
    "/calibration/runs/{calibration_run_id}/accept",
    response_model=CalibrationPromotionResponse,
)
def accept_calibration_candidate(
    calibration_run_id: int,
    payload: CalibrationPromotionRequest,
    session: SessionDependency,
) -> CalibrationPromotionResponse:
    """Promote one qualified candidate without editing the authoritative source model."""

    return commit_or_conflict(
        session,
        lambda: persistence.promote_calibration_candidate(
            session, calibration_run_id, payload
        ),
    )


@router.post(
    "/validation/runs",
    response_model=ValidationRunRecord,
    status_code=status.HTTP_201_CREATED,
)
def commit_validation_run(
    payload: ValidationRunCommitRequest, session: SessionDependency
) -> ValidationRunRecord:
    """Persist validation evidence while enforcing the independent-data rule."""

    return commit_or_conflict(
        session, lambda: persistence.commit_validation_run(session, payload)
    )


@router.post(
    "/products/commit",
    response_model=ResultProductRecord,
    status_code=status.HTTP_201_CREATED,
)
def commit_result_product(
    payload: ResultProductCommitRequest, session: SessionDependency
) -> ResultProductRecord:
    """Persist a content-addressed result product and append an export audit event."""

    return commit_or_conflict(
        session, lambda: persistence.commit_result_product(session, payload)
    )


@router.get("/audit", response_model=list[AuditEventRecord])
def list_audit_events(
    session: SessionDependency,
    dataset_version_id: int | None = Query(default=None, gt=0),
) -> list[AuditEventRecord]:
    """List append-only production audit events, optionally by Dataset Version."""

    return persistence.list_audit_events(session, dataset_version_id)


@router.post("/runs/{run_id}/approve", response_model=ProductionRunRecord)
def approve_production_run(
    run_id: int,
    payload: ProductionApprovalRequest,
    session: SessionDependency,
) -> ProductionRunRecord:
    """Advance VALIDATED to PRODUCTION_APPROVED only with explicit professional sign-off."""

    return commit_or_conflict(
        session, lambda: persistence.approve_production_run(session, run_id, payload)
    )


@router.post("/qa/evaluate", response_model=HydraulicModelQAResult)
def evaluate_model_qa(payload: HydraulicModelQARequest) -> HydraulicModelQAResult:
    """Run the centralized backend QA gate used before a production run."""

    return HydraulicModelQA().validate(payload)


@router.post("/metrics/evaluate", response_model=HydraulicMetrics)
def evaluate_metrics(payload: MetricEvaluationRequest) -> HydraulicMetrics:
    """Compute dimensional metrics under the requested alignment policy."""

    return align_and_score(payload.observed, payload.simulated, payload.alignment)


@router.post("/calibration/sweeps/plan", response_model=ParameterSweepPlan)
def plan_calibration_sweep(payload: ParameterSweepRequest) -> ParameterSweepPlan:
    """Plan a bounded sweep before any candidate task is queued."""

    try:
        return build_parameter_sweep(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/calibration/candidates/rank", response_model=list[CalibrationCandidate])
def rank_candidates(payload: CalibrationRankingRequest) -> list[CalibrationCandidate]:
    """Rank completed candidates using the explicit weighted objective."""

    try:
        return rank_calibration_candidates(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/validation/independence", response_model=ValidationIndependenceResult)
def validate_independence(
    payload: ValidationIndependenceRequest,
) -> ValidationIndependenceResult:
    """Detect reused or overlapping calibration and validation evidence."""

    try:
        return evaluate_validation_independence(payload.calibration, payload.validation)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/validation/acceptance", response_model=AcceptanceEvaluation)
def validate_acceptance(payload: AcceptanceEvaluationRequest) -> AcceptanceEvaluation:
    """Evaluate project policy while keeping professional approval external."""

    try:
        return evaluate_acceptance(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/external-results/preview", response_model=ExternalResultPreview)
async def preview_external_result(file: FileUpload, options_json: OptionsForm) -> ExternalResultPreview:
    """Preview a legal external CSV/XLSX export without database mutation."""

    filename = Path(file.filename or "external-result").name
    if Path(filename).suffix.lower() not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=415, detail="external results support .csv or .xlsx only")
    content = await files.read_limited_upload(file, DEFAULT_IMPORT_BUDGET.max_import_bytes)
    if not content:
        raise HTTPException(status_code=422, detail="uploaded external result is empty")
    try:
        options = ExternalResultImportOptions.model_validate_json(options_json)
        preview = EngineeringDataImporter().preview_external(filename, content, options)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)[:1000]) from exc
    return preview.model_copy(update={"points": preview.points[:1000]})


@router.post("/time-series/preview", response_model=TimeSeriesImportPreview)
async def preview_time_series(file: FileUpload, options_json: OptionsForm) -> TimeSeriesImportPreview:
    """Preview boundary or observation CSV/XLSX without database mutation."""

    filename = Path(file.filename or "hydraulic-series").name
    if Path(filename).suffix.lower() not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=415, detail="time series support .csv or .xlsx only")
    content = await files.read_limited_upload(file, DEFAULT_IMPORT_BUDGET.max_import_bytes)
    if not content:
        raise HTTPException(status_code=422, detail="uploaded time series is empty")
    try:
        options = TimeSeriesImportOptions.model_validate_json(options_json)
        return EngineeringDataImporter().preview_series(filename, content, options)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)[:1000]) from exc


@router.post(
    "/observations/import",
    response_model=ObservationRecord,
    status_code=status.HTTP_201_CREATED,
)
async def import_observation(
    file: FileUpload,
    options_json: OptionsForm,
    dataset_version_id: PositiveIdForm,
    actor: CodeForm,
    session: SessionDependency,
) -> ObservationRecord:
    """Re-read and atomically persist a complete observation file after preview."""

    filename = Path(file.filename or "observation-series").name
    if Path(filename).suffix.lower() not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=415, detail="observation import supports .csv or .xlsx")
    content = await files.read_limited_upload(file, DEFAULT_IMPORT_BUDGET.max_import_bytes)
    try:
        options = TimeSeriesImportOptions.model_validate_json(options_json)
        if options.series_kind != "observation":
            raise ValueError("observation import requires series_kind=observation")
        preview = EngineeringDataImporter().preview_series(filename, content, options)
        request = ObservationCommitRequest(
            dataset_version_id=dataset_version_id,
            preview=preview,
            actor=actor,
        )
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)[:1000]) from exc
    return commit_or_conflict(
        session, lambda: persistence.commit_observation(session, request)
    )


@router.post(
    "/external-results/import",
    response_model=ExternalResultRecord,
    status_code=status.HTTP_201_CREATED,
)
async def import_external_result(
    file: FileUpload,
    options_json: OptionsForm,
    dataset_version_id: PositiveIdForm,
    result_code: CodeForm,
    actor: CodeForm,
    session: SessionDependency,
) -> ExternalResultRecord:
    """Re-read and atomically persist every row of a legal external CSV/XLSX export."""

    filename = Path(file.filename or "external-result").name
    if Path(filename).suffix.lower() not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=415, detail="external results support .csv or .xlsx only")
    content = await files.read_limited_upload(file, DEFAULT_IMPORT_BUDGET.max_import_bytes)
    try:
        options = ExternalResultImportOptions.model_validate_json(options_json)
        preview = EngineeringDataImporter().preview_external(filename, content, options)
        request = ExternalResultCommitRequest(
            dataset_version_id=dataset_version_id,
            result_code=result_code,
            actor=actor,
            preview=preview,
        )
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)[:1000]) from exc
    return commit_or_conflict(
        session, lambda: persistence.commit_external_result(session, request)
    )


@router.post("/external-results/compare", response_model=ExternalComparisonResult)
def compare_external(payload: ExternalComparisonRequest) -> ExternalComparisonResult:
    """Compare Dayu and external series without declaring the external model truth."""

    try:
        return compare_external_result(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/products/generate", response_model=ResultProductBundle)
def generate_products(payload: ResultProductRequest) -> ResultProductBundle:
    """Generate reusable product tables and map features from unified results."""

    try:
        return build_result_products(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/products/export.csv")
def export_products_csv(payload: ResultProductRequest) -> Response:
    """Export the key-section table as safe UTF-8 CSV."""

    bundle = build_result_products(payload)
    return Response(
        export_product_csv(bundle),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="hydraulic-key-sections.csv"'},
    )


@router.post("/products/export.xlsx")
def export_products_xlsx(payload: ResultProductRequest) -> Response:
    """Export all available product tables as a safe XLSX workbook."""

    bundle = build_result_products(payload)
    return Response(
        export_product_xlsx(bundle),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="hydraulic-products.xlsx"'},
    )


@router.post("/products/export.geojson")
def export_products_geojson(payload: ResultProductRequest) -> Response:
    """Export factual result locations; unavailable geometry remains null."""

    bundle = build_result_products(payload)
    return Response(
        export_product_geojson(bundle),
        media_type="application/geo+json",
        headers={"Content-Disposition": 'attachment; filename="hydraulic-products.geojson"'},
    )


@router.post("/acceptance-manifest", response_model=AcceptanceManifest)
def acceptance_manifest(payload: AcceptanceManifestRequest) -> AcceptanceManifest:
    """Build a canonical evidence artifact without writing it into source control."""

    return build_acceptance_manifest(payload)


__all__ = ["router"]
