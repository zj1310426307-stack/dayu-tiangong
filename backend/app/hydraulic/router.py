"""HTTP endpoints for hydraulic browsing, staged imports, validation, and export."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.common.http import commit_or_conflict, not_found
from app.database.session import get_database_session
from app import files
from app.hydraulic import engineering, processing, service, topology
from app.hydraulic.exporters import (
    export_native_xns11,
    export_nwk11_subset,
    export_xns11_subset,
)
from app.hydraulic.importers.security import DEFAULT_IMPORT_BUDGET
from app.hydraulic.schemas import (
    CoordinateReferenceSpec,
    HydraulicBatchProcessRequest,
    HydraulicBranchActionRecord,
    HydraulicCapabilityResponse,
    HydraulicImportCommitRequest,
    HydraulicImportJobRecord,
    HydraulicImportPreview,
    HydraulicNetworkRecord,
    HydraulicLocateRequest,
    HydraulicProcessRequest,
    HydraulicProcessingRecord,
    HydraulicSectionDetail,
    HydraulicStructureCreate,
    HydraulicStructureRecord,
    HydraulicStructureScenarioRecord,
    HydraulicStructureScenarioUpsert,
    HydraulicStructureUpdate,
    HydraulicTopologyBuildRequest,
    HydraulicTopologyReport,
    HydraulicValidationRequest,
    HydraulicValidationRunRecord,
    HydraulicNetworkGraphRecord,
    SolverCapabilityRecord,
)


router = APIRouter(prefix="/api/v1/hydraulic", tags=["hydraulic-data"])
SessionDependency = Annotated[Session, Depends(get_database_session)]
FileUpload = Annotated[UploadFile, File()]
VersionForm = Annotated[int, Form(gt=0)]
TEMPLATE_ROOT = Path(__file__).resolve().parents[3] / "outputs" / "HYDRO-DATA-01-20260818"
SUPPORTED_SUFFIXES = {".nwk11", ".xns11", ".xlsx", ".csv", ".geojson", ".json", ".zip", ".dxf"}
MAX_UPLOAD_BYTES = DEFAULT_IMPORT_BUDGET.max_import_bytes


async def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    """Read a bounded supported upload without trusting its supplied path."""

    filename = Path(file.filename or "upload").name
    if Path(filename).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail="仅支持 .nwk11、.xns11、.xlsx、.csv、.geojson、.json、.zip（SHP）和 .dxf",
        )
    content = await files.read_limited_upload(file, MAX_UPLOAD_BYTES)
    if not content:
        raise HTTPException(status_code=422, detail="上传文件为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="上传文件不得超过 100 MB")
    return filename, content


@router.get(
    "/capabilities",
    response_model=HydraulicCapabilityResponse,
    summary="查看当前 MIKE11 交换能力",
)
def read_capabilities() -> HydraulicCapabilityResponse:
    """Return native-runtime availability and the declared subset limitation."""

    return service.capabilities()


@router.get(
    "/engine-capabilities",
    response_model=list[SolverCapabilityRecord],
    summary="查看版本化一维求解能力矩阵",
)
def read_engine_capabilities() -> list[SolverCapabilityRecord]:
    """Return the pinned engine/version capability evidence used by submission gates."""

    return engineering.engine_capabilities()


@router.get(
    "/networks",
    response_model=list[HydraulicNetworkRecord],
    summary="查看河网、河段与断面树",
)
def read_networks(
    session: SessionDependency,
    dataset_version_id: int = Query(gt=0),
) -> list[HydraulicNetworkRecord]:
    """Return the hierarchical hydraulic data browser for one version."""

    return service.list_networks(session, dataset_version_id)


@router.get(
    "/networks/{network_id}/graph",
    response_model=HydraulicNetworkGraphRecord,
    summary="查看河网拓扑关系",
)
def read_network_graph(network_id: int, session: SessionDependency) -> HydraulicNetworkGraphRecord:
    """Return reusable upstream/downstream, node, boundary, and structure relations."""

    try:
        return engineering.network_graph(session, network_id)
    except LookupError as exc:
        raise not_found("水动力网络") from exc


@router.get(
    "/structures",
    response_model=list[HydraulicStructureRecord],
    summary="查看统一水工建筑物",
)
def read_structures(
    session: SessionDependency,
    dataset_version_id: int = Query(gt=0),
    network_id: int | None = Query(default=None, gt=0),
) -> list[HydraulicStructureRecord]:
    """List solver-neutral structures whether or not MASCARET can solve them."""

    return engineering.list_structures(
        session,
        dataset_version_id=dataset_version_id,
        network_id=network_id,
    )


@router.post(
    "/structures",
    response_model=HydraulicStructureRecord,
    status_code=201,
    summary="创建统一水工建筑物",
)
def create_structure(
    payload: HydraulicStructureCreate, session: SessionDependency
) -> HydraulicStructureRecord:
    """Create a validated structure independently from solver compatibility."""

    return commit_or_conflict(session, lambda: engineering.create_structure(session, payload))


@router.get(
    "/structures/{structure_id}",
    response_model=HydraulicStructureRecord,
    summary="查看统一水工建筑物详情",
)
def read_structure(structure_id: int, session: SessionDependency) -> HydraulicStructureRecord:
    """Return one structure and the pinned solver capability decision."""

    value = engineering.get_structure(session, structure_id)
    if value is None:
        raise not_found("统一水工建筑物")
    return value


@router.put(
    "/structures/{structure_id}",
    response_model=HydraulicStructureRecord,
    summary="编辑统一水工建筑物",
)
def update_structure(
    structure_id: int,
    payload: HydraulicStructureUpdate,
    session: SessionDependency,
) -> HydraulicStructureRecord:
    """Update a structure and re-run shared branch-location validation."""

    if engineering.get_structure(session, structure_id) is None:
        raise not_found("统一水工建筑物")
    return commit_or_conflict(
        session,
        lambda: engineering.update_structure(session, structure_id, payload),
    )


@router.delete(
    "/structures/{structure_id}",
    status_code=204,
    response_class=Response,
    summary="删除统一水工建筑物",
)
def delete_structure(structure_id: int, session: SessionDependency) -> Response:
    """Delete the unified row while leaving any linked legacy asset untouched."""

    if engineering.get_structure(session, structure_id) is None:
        raise not_found("统一水工建筑物")
    commit_or_conflict(session, lambda: engineering.delete_structure(session, structure_id))
    return Response(status_code=204)


@router.put(
    "/structures/{structure_id}/scenarios/{case_id}",
    response_model=HydraulicStructureScenarioRecord,
    summary="保存工况建筑物覆盖参数",
)
def upsert_structure_scenario(
    structure_id: int,
    case_id: int,
    payload: HydraulicStructureScenarioUpsert,
    session: SessionDependency,
) -> HydraulicStructureScenarioRecord:
    """Persist scenario-specific operation without duplicating network geometry."""

    if engineering.get_structure(session, structure_id) is None:
        raise not_found("统一水工建筑物")
    try:
        return commit_or_conflict(
            session,
            lambda: engineering.upsert_structure_scenario(session, structure_id, case_id, payload),
        )
    except LookupError as exc:
        raise not_found("计算工况") from exc


@router.get(
    "/cross-sections/{section_id}",
    response_model=HydraulicSectionDetail,
    summary="查看断面高程详情",
)
def read_cross_section(section_id: int, session: SessionDependency) -> HydraulicSectionDetail:
    """Return one profile suitable for distance/elevation charting."""

    record = service.get_section_detail(session, section_id)
    if record is None:
        raise not_found("水动力断面")
    return record


@router.get(
    "/imports",
    response_model=list[HydraulicImportJobRecord],
    summary="查看水动力导入记录",
)
def read_import_jobs(
    session: SessionDependency,
    dataset_version_id: int = Query(gt=0),
) -> list[HydraulicImportJobRecord]:
    """Return parser provenance and validation status for one version."""

    return service.list_import_jobs(session, dataset_version_id)


@router.post(
    "/imports/preview",
    response_model=HydraulicImportPreview,
    summary="预览并校核水动力导入",
)
async def preview_import(
    dataset_version_id: VersionForm,
    file: FileUpload,
    session: SessionDependency,
    source_crs: Annotated[str, Form()],
    engineering_crs: Annotated[str, Form()],
    coordinate_mode: Annotated[str, Form()],
    axis_mapping: Annotated[str, Form()],
    horizontal_unit: Annotated[str, Form()],
    vertical_datum: Annotated[str, Form()],
    central_meridian: Annotated[float, Form()],
    zone_width: Annotated[int, Form()],
    x_field: Annotated[str, Form()] = "x",
    y_field: Annotated[str, Form()] = "y",
    z_field: Annotated[str | None, Form()] = None,
    vertical_unit: Annotated[str, Form()] = "m",
    zone_prefix_mode: Annotated[str, Form()] = "none",
) -> HydraulicImportPreview:
    """Persist a coordinate-audited preview while leaving domain rows unchanged."""

    try:
        coordinate_reference = CoordinateReferenceSpec(
            source_crs=source_crs,
            engineering_crs=engineering_crs,
            coordinate_mode=coordinate_mode,
            axis_mapping=axis_mapping,
            x_field=x_field,
            y_field=y_field,
            z_field=z_field,
            horizontal_unit=horizontal_unit,
            vertical_unit=vertical_unit,
            vertical_datum=vertical_datum,
            central_meridian=central_meridian,
            zone_width=zone_width,
            zone_prefix_mode=zone_prefix_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    filename, content = await _read_upload(file)
    return commit_or_conflict(
        session,
        lambda: service.preview_import(
            session, dataset_version_id, filename, content, coordinate_reference
        ),
    )


@router.post(
    "/imports/commit",
    response_model=HydraulicImportJobRecord,
    summary="确认提交水动力导入",
)
def commit_import(
    payload: HydraulicImportCommitRequest, session: SessionDependency
) -> HydraulicImportJobRecord:
    """Commit a previously validated preview exactly once."""

    return commit_or_conflict(
        session,
        lambda: service.commit_import(session, payload.job_code, payload.preview_config_hash),
    )


@router.post(
    "/networks/{network_id}/topology",
    response_model=HydraulicTopologyReport,
    summary="按米制容差构建正式河网拓扑",
)
def build_network_topology(
    network_id: int, payload: HydraulicTopologyBuildRequest, session: SessionDependency
) -> HydraulicTopologyReport:
    """Build nodes and reaches from endpoints and exact branch intersections."""

    return commit_or_conflict(
        session,
        lambda: topology.build_topology(
            session, network_id, payload.snap_tolerance_m, payload.minimum_reach_length_m
        ),
    )


@router.post(
    "/branches/{branch_id}/reverse",
    response_model=HydraulicBranchActionRecord,
    summary="反转河段流向",
)
def reverse_branch(branch_id: int, session: SessionDependency) -> HydraulicBranchActionRecord:
    """Reverse geometry, chainage, sections, and existing reaches atomically."""

    return commit_or_conflict(session, lambda: topology.reverse_branch(session, branch_id))


@router.post(
    "/branches/{branch_id}/recalculate-chainage",
    response_model=HydraulicBranchActionRecord,
    summary="按工程长度重算桩号",
)
def recalculate_branch_chainage(
    branch_id: int, session: SessionDependency
) -> HydraulicBranchActionRecord:
    """Scale branch, section, vertex, and reach chainage to the projected length."""

    return commit_or_conflict(session, lambda: topology.recalculate_chainage(session, branch_id))


@router.post(
    "/cross-sections/{section_id}/locate",
    response_model=HydraulicSectionDetail,
    summary="按断面轴线计算河段桩号",
)
def locate_cross_section(
    section_id: int, payload: HydraulicLocateRequest, session: SessionDependency
) -> HydraulicSectionDetail:
    """Compute or explicitly override section chainage with an audit trail."""

    return commit_or_conflict(
        session, lambda: processing.locate_section(session, section_id, payload)
    )


@router.post(
    "/profiles/{profile_id}/process",
    response_model=HydraulicProcessingRecord,
    summary="生成断面水力查算表",
)
def process_cross_section_profile(
    profile_id: int, payload: HydraulicProcessRequest, session: SessionDependency
) -> HydraulicProcessingRecord:
    """Build or reuse a profile-hash keyed hydraulic table."""

    return commit_or_conflict(
        session, lambda: processing.process_profile(session, profile_id, payload.vertical_step_m)
    )


@router.post(
    "/profiles/process-batch",
    response_model=list[HydraulicProcessingRecord],
    summary="批量生成断面水力查算表",
)
def process_cross_section_profiles(
    payload: HydraulicBatchProcessRequest, session: SessionDependency
) -> list[HydraulicProcessingRecord]:
    """Process a bounded profile list in one transaction."""

    return commit_or_conflict(
        session,
        lambda: processing.batch_process(session, payload.profile_ids, payload.vertical_step_m),
    )


@router.post(
    "/validation/run",
    response_model=HydraulicValidationRunRecord,
    summary="运行水动力数据校核",
)
def run_validation(
    payload: HydraulicValidationRequest, session: SessionDependency
) -> HydraulicValidationRunRecord:
    """Run and persist the dataset-version hydraulic quality gate."""

    return commit_or_conflict(
        session, lambda: service.run_validation(session, payload.dataset_version_id)
    )


@router.get(
    "/validation/{run_code}",
    response_model=HydraulicValidationRunRecord,
    summary="查看水动力校核结果",
)
def read_validation(run_code: str, session: SessionDependency) -> HydraulicValidationRunRecord:
    """Return one validation run with machine-readable findings."""

    record = service.get_validation_run(session, run_code)
    if record is None:
        raise not_found("水动力校核任务")
    return record


def _export_payload(session: Session, dataset_version_id: int, network_id: int | None):
    """Map export selection errors to a stable client-facing validation response."""

    try:
        return service.build_exchange_payload(session, dataset_version_id, network_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/exports/network.nwk11", summary="导出 NWK11 交换子集")
def export_network(
    session: SessionDependency,
    dataset_version_id: int = Query(gt=0),
    network_id: int | None = Query(default=None, gt=0),
) -> Response:
    """Export the documented deterministic NWK11 exchange subset."""

    payload = _export_payload(session, dataset_version_id, network_id)
    return Response(
        content=export_nwk11_subset(payload),
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="network.nwk11"'},
    )


@router.get("/exports/cross-sections.xns11", summary="导出 XNS11 断面文件")
def export_cross_sections(
    session: SessionDependency,
    dataset_version_id: int = Query(gt=0),
    network_id: int | None = Query(default=None, gt=0),
    native: bool = Query(default=False),
) -> Response:
    """Export native XNS11 when available or the declared deterministic subset."""

    payload = _export_payload(session, dataset_version_id, network_id)
    try:
        content = export_native_xns11(payload) if native else export_xns11_subset(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="cross-sections.xns11"'},
    )


@router.get(
    "/templates/{template_name}",
    response_class=FileResponse,
    summary="下载水动力 Excel 模板",
)
def download_template(template_name: str) -> FileResponse:
    """Return only the two reviewed workbook templates from the repository."""

    allowed = {"river-network": "river_network.xlsx", "cross-section": "cross_section.xlsx"}
    filename = allowed.get(template_name)
    if filename is None:
        raise not_found("水动力 Excel 模板")
    path = TEMPLATE_ROOT / filename
    if not path.is_file():
        raise not_found("水动力 Excel 模板")
    return FileResponse(
        path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
