"""REAL-01 read-only data admission checks over the unified hydraulic domain.

The service deliberately reports evidence already persisted in the authoritative
Dataset Version.  It never fills an engineering value, promotes a version, or
enables a pilot.  This makes a missing-data register reproducible without
introducing a parallel pilot database.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dataset.schemas import (
    Real01DomainStatus,
    Real01IssueRecord,
    Real01ReadinessRecord,
)
from app.gis.models import BoundaryCondition, DatasetVersion
from app.hydraulic.models import (
    HydraulicBranch,
    HydraulicCrossSection,
    HydraulicCrossSectionPoint,
    HydraulicCrossSectionProfile,
    HydraulicImportJob,
    HydraulicNode,
    HydraulicObservationSeries,
    HydraulicRoughnessZone,
    HydraulicStructure,
    HydraulicValidationRun,
    HydraulicNetwork,
)
from app.hydraulic.snapshot import engineering_graph_content_hash


REAL01_EXPECTED_RIVER_COUNT = 5
REAL01_EXPECTED_GATE_COUNT = 2


def _count(session: Session, model: Any, version_id: int) -> int:
    """Count one version-owned model with an explicit Dataset Version filter."""

    return int(
        session.scalar(
            select(func.count()).select_from(model).where(model.dataset_version_id == version_id)
        )
        or 0
    )


def _domain(
    domain: str,
    status: str,
    detail: str,
    *,
    blocker_code: str | None = None,
) -> tuple[Real01DomainStatus, Real01IssueRecord | None]:
    """Create a domain status and its blocking missing-data record when needed."""

    record = Real01DomainStatus(domain=domain, status=status, detail=detail)
    if status == "AVAILABLE":
        return record, None
    return record, Real01IssueRecord(
        code=blocker_code or f"REAL01_{domain}_INCOMPLETE",
        severity="BLOCKER" if status == "MISSING" else "WARNING",
        domain=domain,
        message=detail,
    )


def _known_datum(value: str | None) -> bool:
    """Return whether a persisted vertical datum has an explicit non-placeholder value."""

    return bool(value and value.strip() and value.strip().lower() not in {"unknown", "unk"})


def _has_source_reference(values: dict[str, Any] | None) -> bool:
    """Require an explicit source/evidence reference instead of accepting a default."""

    if not isinstance(values, dict):
        return False
    return any(
        bool(values.get(key))
        for key in ("source", "source_file", "source_sha256", "evidence_reference")
    )


def _all_profiles_have_points(
    session: Session, profiles: Iterable[HydraulicCrossSectionProfile]
) -> bool:
    """Require at least two source points for each profile in the candidate graph."""

    for profile in profiles:
        point_count = session.scalar(
            select(func.count())
            .select_from(HydraulicCrossSectionPoint)
            .where(HydraulicCrossSectionPoint.profile_id == profile.id)
        )
        if int(point_count or 0) < 2:
            return False
    return True


def build_real01_readiness(session: Session, version: DatasetVersion) -> Real01ReadinessRecord:
    """Derive REAL-01 readiness exclusively from persisted engineering evidence.

    ``AVAILABLE`` is intentionally conservative.  For example, a Manning value
    without source revision/evidence remains incomplete rather than being treated
    as a real surveyed roughness.  The result is a reporting function only and is
    therefore safe to call for Draft, reviewed, or frozen versions.
    """

    version_id = version.id
    networks = list(
        session.scalars(
            select(HydraulicNetwork).where(HydraulicNetwork.dataset_version_id == version_id)
        ).all()
    )
    branches = list(
        session.scalars(
            select(HydraulicBranch).where(HydraulicBranch.dataset_version_id == version_id)
        ).all()
    )
    sections = list(
        session.scalars(
            select(HydraulicCrossSection).where(HydraulicCrossSection.dataset_version_id == version_id)
        ).all()
    )
    profiles = list(
        session.scalars(
            select(HydraulicCrossSectionProfile).where(
                HydraulicCrossSectionProfile.dataset_version_id == version_id,
                HydraulicCrossSectionProfile.is_active.is_(True),
            )
        ).all()
    )
    structures = list(
        session.scalars(
            select(HydraulicStructure).where(HydraulicStructure.dataset_version_id == version_id)
        ).all()
    )
    boundaries = list(
        session.scalars(
            select(BoundaryCondition).where(BoundaryCondition.dataset_version_id == version_id)
        ).all()
    )
    import_jobs = list(
        session.scalars(
            select(HydraulicImportJob).where(HydraulicImportJob.dataset_version_id == version_id)
        ).all()
    )

    counts = {
        "networks": len(networks),
        "nodes": _count(session, HydraulicNode, version_id),
        "branches": len(branches),
        "cross_sections": len(sections),
        "active_profiles": len(profiles),
        "cross_section_points": _count(session, HydraulicCrossSectionPoint, version_id),
        "roughness_zones": _count(session, HydraulicRoughnessZone, version_id),
        "gates": sum(item.structure_type == "gate" for item in structures),
        "pumps": sum(item.structure_type == "pump" for item in structures),
        "boundary_conditions": len(boundaries),
        "observation_series": _count(session, HydraulicObservationSeries, version_id),
        "import_jobs": len(import_jobs),
        "passed_qa_runs": int(
            session.scalar(
                select(func.count())
                .select_from(HydraulicValidationRun)
                .where(
                    HydraulicValidationRun.dataset_version_id == version_id,
                    HydraulicValidationRun.status == "passed",
                )
            )
            or 0
        ),
    }

    domains: list[Real01DomainStatus] = []
    missing: list[Real01IssueRecord] = []
    assumptions: list[Real01IssueRecord] = []

    def add(domain: str, status: str, detail: str, code: str | None = None) -> None:
        """Append one derived status, retaining incomplete evidence for review."""

        record, issue = _domain(domain, status, detail, blocker_code=code)
        domains.append(record)
        if issue is not None:
            missing.append(issue)

    committed_jobs = [item for item in import_jobs if item.status == "committed"]
    source_ok = bool(committed_jobs) and all(
        item.source_hash_sha256 and item.config_hash and item.coordinate_reference
        for item in committed_jobs
    )
    add(
        "SOURCE_EVIDENCE",
        "AVAILABLE" if source_ok else ("PARTIAL" if import_jobs else "MISSING"),
        "已提交导入必须具备原始 SHA-256、配置 hash 与坐标转换证据。"
        if source_ok
        else "未发现带完整哈希、配置与坐标证据的已提交真实资料导入。",
        "REAL01_SOURCE_EVIDENCE_REQUIRED",
    )

    crs_ok = bool(networks) and all(
        network.engineering_crs and _known_datum(network.vertical_datum) for network in networks
    ) and all(_known_datum(profile.vertical_datum) for profile in profiles)
    add(
        "CRS_VERTICAL_DATUM",
        "AVAILABLE" if crs_ok else ("PARTIAL" if networks else "MISSING"),
        "所有网络均记录工程 CRS 与高程基准，活动断面剖面也有明确高程基准。"
        if crs_ok
        else "工程 CRS、中央子午线/轴映射证据或 1985 高程等垂直基准尚未完整落库。",
        "REAL01_CRS_OR_VERTICAL_DATUM_REQUIRED",
    )

    river_count = len({item.river_name for item in branches if item.river_name})
    network_ok = counts["nodes"] > 0 and bool(branches) and river_count >= REAL01_EXPECTED_RIVER_COUNT
    add(
        "RIVER_NETWORK",
        "AVAILABLE" if network_ok else ("PARTIAL" if branches else "MISSING"),
        f"已识别 {river_count} 条有向河流；REAL-01 准入至少需要 {REAL01_EXPECTED_RIVER_COUNT} 条并有节点拓扑。"
        if not network_ok
        else "五河河网、节点、河段和方向均已存在于统一水力 Domain。",
        "REAL01_NETWORK_REQUIRED",
    )

    section_ok = bool(sections) and len(profiles) >= len(sections) and _all_profiles_have_points(session, profiles)
    add(
        "CROSS_SECTION",
        "AVAILABLE" if section_ok else ("PARTIAL" if sections else "MISSING"),
        "所有断面均有活动剖面和至少两个原始 Station/Elevation 点。"
        if section_ok
        else "断面、活动剖面或 Station/Elevation 原始点未完整映射到统一 Domain。",
        "REAL01_CROSS_SECTION_REQUIRED",
    )

    roughness_evidence = all(
        profile.source_revision or _has_source_reference(profile.metadata_json) for profile in profiles
    )
    roughness_ok = bool(profiles) and roughness_evidence
    add(
        "ROUGHNESS",
        "AVAILABLE" if roughness_ok else ("PARTIAL" if profiles else "MISSING"),
        "每个活动剖面均附带粗糙率来源版本或证据引用。"
        if roughness_ok
        else "粗糙率可以有数值，但尚无逐剖面来源证据；不得把默认值升级为真实工程参数。",
        "REAL01_ROUGHNESS_PROVENANCE_REQUIRED",
    )

    gates = [item for item in structures if item.structure_type == "gate"]
    gate_geometry_ok = all(
        item.branch_id and item.chainage_m is not None and item.invert_elevation_m is not None
        and item.width_m is not None and item.hydraulic_parameters
        for item in gates
    )
    gate_ok = len(gates) == REAL01_EXPECTED_GATE_COUNT and gate_geometry_ok
    add(
        "GATE",
        "AVAILABLE" if gate_ok else ("PARTIAL" if gates else "MISSING"),
        f"已识别 {len(gates)} 座 Gate；REAL-01 需要 {REAL01_EXPECTED_GATE_COUNT} 座具备位置、底槛、孔宽和水力参数来源。"
        if not gate_ok
        else "两座 Gate 的统一建筑物参数和位置均已具备。",
        "REAL01_GATE_REQUIRED",
    )

    upstream = [item for item in boundaries if item.boundary_type == "upstream_discharge"]
    downstream = [item for item in boundaries if item.boundary_type == "downstream_water_level"]
    boundary_ok = bool(upstream) and bool(downstream) and all(
        item.values and item.unit and _has_source_reference(item.values)
        for item in (*upstream, *downstream)
    )
    add(
        "BOUNDARY_INITIAL_CONDITION",
        "AVAILABLE" if boundary_ok else ("PARTIAL" if upstream or downstream else "MISSING"),
        "上游 Q(t) 与下游 H/H(t) 均有单位、值和来源/时间基准证据。"
        if boundary_ok
        else "上游 Q(t)、下游 H/H(t)、单位、时间基准或来源证据尚未完整录入。",
        "REAL01_BOUNDARY_REQUIRED",
    )

    observation_count = counts["observation_series"]
    observation_ok = observation_count > 0
    domains.append(
        Real01DomainStatus(
            domain="OBSERVATION",
            status="AVAILABLE" if observation_ok else "MISSING",
            detail="已存在带单位、基准、质量和来源证据的观测序列。"
            if observation_ok
            else "尚无用于率定和独立验证的实测 H/Q 序列；不阻断资料入库，但阻断率定/验证。",
        )
    )
    if not observation_ok:
        assumptions.append(
            Real01IssueRecord(
                code="REAL01_OBSERVATION_DATA_REQUIRED",
                severity="WARNING",
                domain="OBSERVATION",
                message="当前仅可进入未率定资料审查，不能声明已率定或已独立验证。",
            )
        )

    qa_ok = counts["passed_qa_runs"] > 0
    add(
        "QA_REVIEW",
        "AVAILABLE" if qa_ok else "MISSING",
        "统一水力 QA 已保留通过记录。" if qa_ok else "尚无通过的统一水力 QA 记录。",
        "REAL01_QA_REQUIRED",
    )

    blocking_statuses = {"MISSING", "PARTIAL"}
    base_domains = {"SOURCE_EVIDENCE", "CRS_VERTICAL_DATUM", "RIVER_NETWORK", "CROSS_SECTION", "ROUGHNESS", "GATE", "BOUNDARY_INITIAL_CONDITION", "QA_REVIEW"}
    base_ready = not any(
        item.domain in base_domains and item.status in blocking_statuses for item in domains
    )
    calibration_ready = base_ready and observation_ok
    validation_ready = calibration_ready
    can_freeze = base_ready and version.status in {"draft", "review"}
    overall = "DATA_READY_FOR_REVIEW" if base_ready else "FRAMEWORK_READY_DATA_REQUIRED"
    return Real01ReadinessRecord(
        dataset_version_id=version_id,
        dataset_version=version.version,
        dataset_status=version.status,
        engineering_content_hash=engineering_graph_content_hash(session, version_id),
        counts=counts,
        domains=domains,
        missing_data_records=missing,
        assumption_records=assumptions,
        base_model_ready=base_ready,
        calibration_ready=calibration_ready,
        validation_ready=validation_ready,
        dflow_pilot_ready=False,
        production_ready=False,
        can_freeze=can_freeze,
        overall_status=overall,
    )
