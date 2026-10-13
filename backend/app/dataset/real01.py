"""REAL-01 read-only data admission checks over the unified hydraulic domain.

The service deliberately reports evidence already persisted in the authoritative
Dataset Version.  It never fills an engineering value, promotes a version, or
enables a pilot.  This makes a missing-data register reproducible without
introducing a parallel pilot database.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
import math
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dataset.schemas import (
    Real01DomainStatus,
    Real01IssueRecord,
    Real01ReadinessRecord,
)
from app.gis.models import BoundaryCondition, DatasetVersion, SimulationCase
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
        severity="BLOCKER",
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


def _coordinate_contract_ready(network: HydraulicNetwork) -> bool:
    """Require the persisted projected CRS, axis mapping, units, and datum evidence."""

    metadata = network.metadata_json if isinstance(network.metadata_json, dict) else {}
    coordinate = metadata.get("coordinate_reference")
    return bool(
        network.engineering_crs
        and str(network.engineering_crs).startswith("EPSG:")
        and network.horizontal_unit == "m"
        and network.vertical_unit == "m"
        and _known_datum(network.vertical_datum)
        and isinstance(coordinate, dict)
        and coordinate.get("source_crs")
        and coordinate.get("engineering_crs") == network.engineering_crs
        and coordinate.get("axis_mapping")
        and coordinate.get("vertical_datum") == network.vertical_datum
    )


def _network_topology_ready(branches: Iterable[HydraulicBranch]) -> bool:
    """Accept branching networks while rejecting unlocated or disconnected Branch graphs."""

    grouped: dict[int, list[HydraulicBranch]] = defaultdict(list)
    for branch in branches:
        grouped[branch.network_id].append(branch)
    if not grouped:
        return False
    for network_branches in grouped.values():
        if any(
            branch.direction_status != "confirmed"
            or branch.upstream_node_id is None
            or branch.downstream_node_id is None
            or branch.upstream_node_id == branch.downstream_node_id
            or not math.isfinite(branch.start_chainage)
            or not math.isfinite(branch.end_chainage)
            or branch.end_chainage <= branch.start_chainage
            for branch in network_branches
        ):
            return False
        adjacency: dict[int, set[int]] = defaultdict(set)
        for branch in network_branches:
            upstream = int(branch.upstream_node_id)
            downstream = int(branch.downstream_node_id)
            adjacency[upstream].add(downstream)
            adjacency[downstream].add(upstream)
        pending = [next(iter(adjacency))]
        visited: set[int] = set()
        while pending:
            node_id = pending.pop()
            if node_id in visited:
                continue
            visited.add(node_id)
            pending.extend(adjacency[node_id] - visited)
        if visited != set(adjacency):
            return False
    return True


def _profile_points_ready(points: Iterable[HydraulicCrossSectionPoint]) -> bool:
    """Require at least two finite Station/Elevation points ordered left-to-right."""

    ordered = sorted(points, key=lambda item: item.sequence)
    if len(ordered) < 2:
        return False
    stations = [item.distance for item in ordered]
    elevations = [item.elevation for item in ordered]
    return all(math.isfinite(value) for value in (*stations, *elevations)) and all(
        right > left for left, right in zip(stations, stations[1:])
    )


def _roughness_covers_profile(
    profile: HydraulicCrossSectionProfile,
    points: Iterable[HydraulicCrossSectionPoint],
    zones: Iterable[HydraulicRoughnessZone],
) -> bool:
    """Verify sourced positive Manning zones cover the full raw Station domain."""

    point_rows = sorted(points, key=lambda item: item.distance)
    zone_rows = sorted(zones, key=lambda item: item.offset_start_m)
    if not point_rows or not zone_rows:
        return False
    if not (profile.source_revision or _has_source_reference(profile.metadata_json)):
        return False
    tolerance = 1e-9
    if zone_rows[0].offset_start_m > point_rows[0].distance + tolerance:
        return False
    if zone_rows[-1].offset_end_m < point_rows[-1].distance - tolerance:
        return False
    for zone in zone_rows:
        if not math.isfinite(zone.manning_n) or zone.manning_n <= 0:
            return False
    return all(
        right.offset_start_m <= left.offset_end_m + tolerance
        for left, right in zip(zone_rows, zone_rows[1:])
    )


def _gate_ready(gate: HydraulicStructure, branches: dict[int, HydraulicBranch]) -> bool:
    """Require both Gate geometry and traceable MIKE11-style engineering inputs."""

    branch = branches.get(gate.branch_id)
    hydraulic = gate.hydraulic_parameters if isinstance(gate.hydraulic_parameters, dict) else {}
    operation = gate.operation_parameters if isinstance(gate.operation_parameters, dict) else {}
    metadata = gate.metadata_json if isinstance(gate.metadata_json, dict) else {}
    mike11 = hydraulic.get("mike11_gate_configuration")
    if not isinstance(mike11, dict):
        mike11 = {}
    gate_count = mike11.get("number_of_gates", hydraulic.get("number_of_gates"))
    maximum_opening = mike11.get("maximum_value_m", operation.get("maximum_opening_m"))
    initial_opening = mike11.get("initial_value_m", operation.get("initial_opening_m"))
    opening_speed = mike11.get("maximum_speed_m_per_s", operation.get("opening_rate_limit_m_per_s"))
    coefficient = mike11.get(
        "underflow_discharge_coefficient",
        hydraulic.get("correction_coefficient", hydraulic.get("discharge_coefficient")),
    )
    head_loss = mike11.get("head_loss_factors", hydraulic.get("head_loss_factors"))
    try:
        positive_gate_count = int(gate_count) >= 1
        numeric_values = [
            float(maximum_opening),
            float(initial_opening),
            float(opening_speed),
            float(coefficient),
        ]
    except (TypeError, ValueError):
        return False
    return bool(
        branch
        and branch.start_chainage <= gate.chainage_m <= branch.end_chainage
        and gate.invert_elevation_m is not None
        and gate.width_m is not None
        and positive_gate_count
        and all(math.isfinite(value) for value in numeric_values)
        and numeric_values[0] >= numeric_values[1] >= 0
        and numeric_values[2] >= 0
        and numeric_values[3] > 0
        and isinstance(head_loss, dict)
        and head_loss
        and (
            _has_source_reference(metadata)
            or _has_source_reference(hydraulic)
            or _has_source_reference(operation)
        )
    )


def _time_series_ready(values: dict[str, Any], value_keys: tuple[str, ...]) -> bool:
    """Validate a non-empty, strictly increasing engineering boundary series."""

    series = values.get("series")
    if isinstance(series, list) and len(series) >= 2:
        pairs = [
            (
                item.get("time_seconds"),
                next(
                    (item.get(key) for key in value_keys if item.get(key) is not None),
                    item.get("value"),
                ),
            )
            for item in series
            if isinstance(item, dict)
        ]
    else:
        times = values.get("time_seconds")
        ordinates = next(
            (values.get(key) for key in value_keys if isinstance(values.get(key), list)),
            None,
        )
        if (
            not isinstance(times, list)
            or not isinstance(ordinates, list)
            or len(times) != len(ordinates)
        ):
            return False
        pairs = list(zip(times, ordinates))
    if len(pairs) < 2:
        return False
    try:
        numeric = [(float(time), float(value)) for time, value in pairs]
    except (TypeError, ValueError):
        return False
    return all(math.isfinite(value) for pair in numeric for value in pair) and all(
        right[0] > left[0] for left, right in zip(numeric, numeric[1:])
    )


def _boundary_ready(boundary: BoundaryCondition) -> bool:
    """Require source, time basis, location, units, and valid Q/H data semantics."""

    values = boundary.values if isinstance(boundary.values, dict) else {}
    if not boundary.unit or not _has_source_reference(values):
        return False
    time_basis = values.get("time_basis")
    if time_basis not in {"relative", "absolute"}:
        return False
    if time_basis == "absolute" and not values.get("timezone"):
        return False
    if boundary.boundary_type == "upstream_discharge":
        return boundary.hydraulic_node_id is not None and _time_series_ready(
            values, ("flow_m3_s", "discharge_m3_s")
        )
    if boundary.boundary_type == "downstream_water_level":
        if boundary.hydraulic_node_id is None:
            return False
        if values.get("mode") == "constant":
            value = values.get("value")
            return bool(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                and values.get("applicability")
            )
        if values.get("mode") == "rating_curve":
            curve = values.get("curve")
            return bool(isinstance(curve, list) and len(curve) >= 2)
        return _time_series_ready(values, ("water_level_m", "stage_m"))
    return False


def _qa_matches_graph(run: HydraulicValidationRun, graph_hash: str) -> bool:
    """Accept only a passed QA decision bound to the current graph identity."""

    return bool(
        run.status == "passed"
        and isinstance(run.summary, dict)
        and run.summary.get("engineering_content_hash") == graph_hash
    )


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
            select(HydraulicCrossSection).where(
                HydraulicCrossSection.dataset_version_id == version_id
            )
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
    points = list(
        session.scalars(
            select(HydraulicCrossSectionPoint).where(
                HydraulicCrossSectionPoint.dataset_version_id == version_id
            )
        ).all()
    )
    roughness_zones = list(
        session.scalars(
            select(HydraulicRoughnessZone).where(
                HydraulicRoughnessZone.dataset_version_id == version_id
            )
        ).all()
    )
    observations = list(
        session.scalars(
            select(HydraulicObservationSeries).where(
                HydraulicObservationSeries.dataset_version_id == version_id
            )
        ).all()
    )
    cases = list(
        session.scalars(
            select(SimulationCase).where(SimulationCase.dataset_version_id == version_id)
        ).all()
    )
    validation_runs = list(
        session.scalars(
            select(HydraulicValidationRun).where(
                HydraulicValidationRun.dataset_version_id == version_id,
                HydraulicValidationRun.status == "passed",
            )
        ).all()
    )
    graph_hash = engineering_graph_content_hash(session, version_id)
    current_qa_runs = [item for item in validation_runs if _qa_matches_graph(item, graph_hash)]

    counts = {
        "networks": len(networks),
        "nodes": _count(session, HydraulicNode, version_id),
        "branches": len(branches),
        "cross_sections": len(sections),
        "active_profiles": len(profiles),
        "cross_section_points": len(points),
        "roughness_zones": len(roughness_zones),
        "gates": sum(item.structure_type == "gate" for item in structures),
        "pumps": sum(item.structure_type == "pump" for item in structures),
        "boundary_conditions": len(boundaries),
        "observation_series": len(observations),
        "import_jobs": len(import_jobs),
        "passed_qa_runs": len(validation_runs),
        "current_qa_runs": len(current_qa_runs),
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

    project_ok = bool(version.version and version.name and version.creator and version.description)
    add(
        "PROJECT",
        "AVAILABLE" if project_ok else "PARTIAL",
        "Dataset Version 已记录工程名称、版本、责任人和用途说明。"
        if project_ok
        else "工程名称、版本、责任人或用途/权属说明未完整记录。",
        "REAL01_PROJECT_IDENTITY_REQUIRED",
    )

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

    crs_ok = (
        bool(networks)
        and all(_coordinate_contract_ready(network) for network in networks)
        and bool(profiles)
        and all(
            _known_datum(profile.vertical_datum) and profile.vertical_unit == "m"
            for profile in profiles
        )
    )
    add(
        "CRS_VERTICAL_DATUM",
        "AVAILABLE" if crs_ok else ("PARTIAL" if networks else "MISSING"),
        "所有网络均记录工程 CRS 与高程基准，活动断面剖面也有明确高程基准。"
        if crs_ok
        else "工程 CRS、中央子午线/轴映射证据或 1985 高程等垂直基准尚未完整落库。",
        "REAL01_CRS_OR_VERTICAL_DATUM_REQUIRED",
    )

    river_count = len({item.river_name for item in branches if item.river_name})
    network_ok = (
        counts["nodes"] > 0
        and river_count == REAL01_EXPECTED_RIVER_COUNT
        and _network_topology_ready(branches)
    )
    add(
        "RIVER_NETWORK",
        "AVAILABLE" if network_ok else ("PARTIAL" if branches else "MISSING"),
        f"已识别 {river_count} 条河流；REAL-01 准入要求恰好 {REAL01_EXPECTED_RIVER_COUNT} 条，且每个河网内方向、节点和连通性完整。"
        if not network_ok
        else "五河河网、节点、河段和方向均已存在于统一水力 Domain。",
        "REAL01_NETWORK_REQUIRED",
    )

    branch_by_id = {item.id: item for item in branches}
    profiles_by_section: dict[int, list[HydraulicCrossSectionProfile]] = defaultdict(list)
    points_by_profile: dict[int, list[HydraulicCrossSectionPoint]] = defaultdict(list)
    zones_by_profile: dict[int, list[HydraulicRoughnessZone]] = defaultdict(list)
    for profile in profiles:
        profiles_by_section[profile.cross_section_id].append(profile)
    for point in points:
        points_by_profile[point.profile_id].append(point)
    for zone in roughness_zones:
        zones_by_profile[zone.profile_id].append(zone)
    section_ok = bool(sections) and all(
        len(profiles_by_section.get(section.id, [])) == 1
        and section.branch_id in branch_by_id
        and branch_by_id[section.branch_id].start_chainage
        <= section.chainage
        <= branch_by_id[section.branch_id].end_chainage
        and section.hydraulic_ready
        and section.spatial_geometry_source != "UNAVAILABLE"
        and section.review_status == "REVIEWED"
        and _profile_points_ready(points_by_profile[profiles_by_section[section.id][0].id])
        for section in sections
    )
    add(
        "CROSS_SECTION",
        "AVAILABLE" if section_ok else ("PARTIAL" if sections else "MISSING"),
        "所有断面均位于 Branch 桩号范围内，有一个已审核活动剖面、可用空间定位和严格递增的原始 Station/Elevation 点。"
        if section_ok
        else "断面 Branch/Chainage、活动剖面、空间定位、人工审核或 Station/Elevation 点序存在缺口。",
        "REAL01_CROSS_SECTION_REQUIRED",
    )

    roughness_ok = bool(profiles) and all(
        _roughness_covers_profile(
            profile,
            points_by_profile[profile.id],
            zones_by_profile[profile.id],
        )
        for profile in profiles
    )
    add(
        "ROUGHNESS",
        "AVAILABLE" if roughness_ok else ("PARTIAL" if profiles else "MISSING"),
        "每个活动剖面均有来源证据，且正值糙率分区连续覆盖完整 Station 范围。"
        if roughness_ok
        else "粗糙率可以有数值，但尚无逐剖面来源证据；不得把默认值升级为真实工程参数。",
        "REAL01_ROUGHNESS_PROVENANCE_REQUIRED",
    )

    gates = [item for item in structures if item.structure_type == "gate"]
    gate_ok = len(gates) == REAL01_EXPECTED_GATE_COUNT and all(
        _gate_ready(item, branch_by_id) for item in gates
    )
    add(
        "GATE",
        "AVAILABLE" if gate_ok else ("PARTIAL" if gates else "MISSING"),
        f"已识别 {len(gates)} 座 Gate；REAL-01 需要 {REAL01_EXPECTED_GATE_COUNT} 座具备 Branch/Chainage、底槛、孔数/孔宽、开度/速度、流量与水头损失参数及来源。"
        if not gate_ok
        else "两座 Gate 的统一建筑物参数和位置均已具备。",
        "REAL01_GATE_REQUIRED",
    )

    upstream = [item for item in boundaries if item.boundary_type == "upstream_discharge"]
    downstream = [item for item in boundaries if item.boundary_type == "downstream_water_level"]
    boundary_ok = (
        bool(upstream)
        and bool(downstream)
        and all(_boundary_ready(item) for item in (*upstream, *downstream))
    )
    add(
        "BOUNDARY",
        "AVAILABLE" if boundary_ok else ("PARTIAL" if upstream or downstream else "MISSING"),
        "上游 Q(t) 与下游 H/H(t) 均有单位、值和来源/时间基准证据。"
        if boundary_ok
        else "上游 Q(t)、下游 H/H(t)、单位、时间基准或来源证据尚未完整录入。",
        "REAL01_BOUNDARY_REQUIRED",
    )

    scenario_ok = bool(cases) and all(
        isinstance(item.hydraulic_1d_configuration, dict)
        and isinstance(item.hydraulic_1d_configuration.get("initial_condition"), dict)
        and _has_source_reference(item.hydraulic_1d_configuration.get("initial_condition"))
        and _has_source_reference(item.hydraulic_1d_configuration)
        for item in cases
    )
    add(
        "SCENARIO_INITIAL_CONDITION",
        "AVAILABLE" if scenario_ok else ("PARTIAL" if cases else "MISSING"),
        "计算工况和初始条件均记录来源、适用范围与显式初值。"
        if scenario_ok
        else "计算工况、适用范围、初始水位/流量或其来源证据尚未完整记录。",
        "REAL01_SCENARIO_OR_INITIAL_CONDITION_REQUIRED",
    )

    observation_ok = bool(observations) and all(
        item.unit
        and _known_datum(item.vertical_datum)
        and item.time_basis in {"relative", "absolute"}
        and (item.time_basis != "absolute" or item.timezone)
        and item.source
        and item.source_sha256
        and item.samples_json
        for item in observations
    )
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

    qa_ok = bool(current_qa_runs)
    add(
        "QA_REVIEW",
        "AVAILABLE" if qa_ok else "MISSING",
        "统一水力 QA 通过记录与当前工程图 Hash 一致。"
        if qa_ok
        else "尚无与当前工程图 Hash 一致的通过 QA；历史通过记录在数据变化后不得复用。",
        "REAL01_QA_REQUIRED",
    )

    blocking_statuses = {"MISSING", "PARTIAL"}
    base_domains = {
        "PROJECT",
        "SOURCE_EVIDENCE",
        "CRS_VERTICAL_DATUM",
        "RIVER_NETWORK",
        "CROSS_SECTION",
        "ROUGHNESS",
        "GATE",
        "BOUNDARY",
        "SCENARIO_INITIAL_CONDITION",
        "QA_REVIEW",
    }
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
        engineering_content_hash=graph_hash,
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
