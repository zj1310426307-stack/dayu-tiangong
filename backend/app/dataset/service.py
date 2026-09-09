"""Dataset Version, model configuration, boundary, and Case services."""

from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dataset.lifecycle import assert_dataset_version_mutable
from app.dataset.schemas import (
    BoundaryRatingCurveGenerateRequest,
    BoundaryRatingCurveGenerateResponse,
    BoundaryConditionCreate,
    BoundaryConditionRecord,
    BoundaryConditionUpdate,
    DatasetVersionCreate,
    DatasetVersionApprovalRequest,
    DatasetVersionRecord,
    DatasetVersionUpdate,
    ModelParameterCreate,
    ModelParameterRecord,
    ModelParameterUpdate,
    SimulationCaseCreate,
    SimulationCaseRecord,
    SimulationCaseUpdate,
)
from app.gis.models import (
    BoundaryCondition,
    DatasetVersion,
    ModelParameter,
    SimulationCase,
    SimulationCaseBoundary,
)
from app.hydraulic.models import (
    HydraulicBranch as HydraulicBranchRow,
    HydraulicCrossSection,
    HydraulicCrossSectionPoint,
    HydraulicCrossSectionProfile,
    HydraulicNode,
    HydraulicRoughnessZone,
)
from app.hydraulic.processing import _roughness_intervals
from app.hydraulic.rating_curve import (
    RATING_CURVE_METHOD,
    generate_manning_rating_curve,
    interpolate_rating_curve,
)
from app.gis_governance.service import dataset_core_content_hash
from app.model_engine.hydraulic_1d_service import build_hydraulic_1d_model
from app.validation.service import run_validation
from model.provenance import snapshot_hash


Entity = TypeVar("Entity")


def _dump(entity: Any) -> dict[str, Any]:
    """提取非 ORM 内部字段，供简单记录契约复用。"""

    return {column.name: getattr(entity, column.name) for column in entity.__table__.columns}


def _case_record(session: Session, entity: SimulationCase) -> SimulationCaseRecord:
    """返回包含旧主边界字段和 Phase 4 显式边界组的计算方案。"""

    boundary_ids = list(
        session.scalars(
            select(SimulationCaseBoundary.boundary_condition_id)
            .where(SimulationCaseBoundary.case_id == entity.id)
            .order_by(SimulationCaseBoundary.boundary_condition_id)
        ).all()
    )
    if not boundary_ids and entity.boundary_condition_id is not None:
        boundary_ids = [entity.boundary_condition_id]
    # Project only fields owned by the public record contract. The ORM still keeps
    # historical columns such as v4_configuration for audit compatibility; leaking
    # them through a blanket table dump breaks this strict response model.
    record_values = {
        field: getattr(entity, field)
        for field in SimulationCaseRecord.model_fields
        if field != "boundary_condition_ids"
    }
    return SimulationCaseRecord(**record_values, boundary_condition_ids=boundary_ids)


def list_dataset_versions(session: Session) -> list[DatasetVersionRecord]:
    """按创建顺序返回全部数据集版本。"""

    return [DatasetVersionRecord(**_dump(item)) for item in session.scalars(select(DatasetVersion).order_by(DatasetVersion.id)).all()]


def create_dataset_version(session: Session, payload: DatasetVersionCreate) -> DatasetVersionRecord:
    """新增数据集版本。"""

    entity = DatasetVersion(**payload.model_dump())
    session.add(entity)
    session.flush()
    return DatasetVersionRecord(**_dump(entity))


def update_dataset_version(session: Session, entity: DatasetVersion, payload: DatasetVersionUpdate) -> DatasetVersionRecord:
    """修改数据集版本说明性字段。"""

    mutable = assert_dataset_version_mutable(session, entity.id)
    _apply(mutable, payload.model_dump(exclude_unset=True))
    session.flush()
    return DatasetVersionRecord(**_dump(mutable))


def approve_dataset_version_for_calculation(
    session: Session,
    entity: DatasetVersion,
    payload: DatasetVersionApprovalRequest,
) -> DatasetVersionRecord:
    """Validate and freeze one draft for traceable Standard 1D calculations."""

    if entity.status in {"approved", "published"}:
        return DatasetVersionRecord(**_dump(entity))
    mutable = assert_dataset_version_mutable(session, entity.id)
    report = run_validation(session, mutable.id)
    if report.summary.errors or report.summary.warnings or not report.summary.is_model_ready:
        raise ValueError(
            "数据版本校核未通过：批准前必须为 0 个错误、0 个警告且模型已就绪"
        )
    case_ids = list(
        session.scalars(
            select(SimulationCase.id)
            .where(SimulationCase.dataset_version_id == mutable.id)
            .order_by(SimulationCase.id)
        ).all()
    )
    if not case_ids:
        raise ValueError("数据版本没有可校核的计算方案")
    approval_defaults = {
        "duration_seconds": 3600.0,
        "time_step_seconds": 10.0,
        "output_interval_seconds": 60.0,
    }
    for case_id in case_ids:
        build_hydraulic_1d_model(
            session,
            case_id,
            approval_defaults,
            allow_draft_for_approval=True,
        )
    now = datetime.now(UTC)
    mutable.content_hash = dataset_core_content_hash(session, mutable.id)
    mutable.change_summary = payload.reason
    mutable.reviewed_by = payload.reviewer
    mutable.reviewed_at = now
    mutable.approved_by = payload.reviewer
    mutable.approved_at = now
    mutable.status = "approved"
    session.flush()
    return DatasetVersionRecord(**_dump(mutable))


def list_parameters(session: Session, dataset_version_id: int | None) -> list[ModelParameterRecord]:
    """返回指定版本或全部模型参数。"""

    statement = select(ModelParameter).order_by(ModelParameter.id)
    if dataset_version_id is not None:
        statement = statement.where(ModelParameter.dataset_version_id == dataset_version_id)
    return [ModelParameterRecord(**_dump(item)) for item in session.scalars(statement).all()]


def create_parameter(session: Session, payload: ModelParameterCreate) -> ModelParameterRecord:
    """新增模型参数。"""

    assert_dataset_version_mutable(session, payload.dataset_version_id)
    entity = ModelParameter(**payload.model_dump())
    session.add(entity)
    session.flush()
    return ModelParameterRecord(**_dump(entity))


def update_parameter(session: Session, entity: ModelParameter, payload: ModelParameterUpdate) -> ModelParameterRecord:
    """修改模型参数值或说明。"""

    assert_dataset_version_mutable(session, entity.dataset_version_id)
    _apply(entity, payload.model_dump(exclude_unset=True))
    session.flush()
    return ModelParameterRecord(**_dump(entity))


def list_boundaries(session: Session, dataset_version_id: int | None) -> list[BoundaryConditionRecord]:
    """返回指定版本或全部边界条件。"""

    statement = select(BoundaryCondition).order_by(BoundaryCondition.id)
    if dataset_version_id is not None:
        statement = statement.where(BoundaryCondition.dataset_version_id == dataset_version_id)
    return [BoundaryConditionRecord(**_dump(item)) for item in session.scalars(statement).all()]


def _validate_boundary_binding(session: Session, state: dict[str, Any]) -> None:
    """Validate the persisted Standard 1D location against HYDRO-DATA."""

    boundary_type = state.get("boundary_type")
    dataset_version_id = state.get("dataset_version_id")
    hydraulic_node_id = state.get("hydraulic_node_id")
    branch_id = state.get("branch_id")
    chainage_m = state.get("chainage_m")
    endpoint_columns = {
        "upstream_discharge": HydraulicBranchRow.upstream_node_id,
        "downstream_water_level": HydraulicBranchRow.downstream_node_id,
    }
    endpoint_column = endpoint_columns.get(boundary_type)
    if endpoint_column is not None:
        if hydraulic_node_id is None:
            raise ValueError(f"{boundary_type} requires hydraulic_node_id")
        if branch_id is not None or chainage_m is not None:
            raise ValueError(
                "端点边界只允许 hydraulic_node_id，不得设置 branch_id 或 chainage_m"
            )
        node = session.scalar(
            select(HydraulicNode).where(
                HydraulicNode.id == hydraulic_node_id,
                HydraulicNode.dataset_version_id == dataset_version_id,
            )
        )
        if node is None:
            raise ValueError("hydraulic_node_id 必须属于边界条件的数据版本")
        matching_branches = list(
            session.scalars(
                select(HydraulicBranchRow).where(
                    HydraulicBranchRow.dataset_version_id == dataset_version_id,
                    endpoint_column == hydraulic_node_id,
                )
            ).all()
        )
        if len(matching_branches) != 1:
            raise ValueError(
                f"{boundary_type} 的 hydraulic_node_id 必须唯一绑定一个定向河段端点"
            )
        return
    if boundary_type != "lateral_inflow":
        raise ValueError(f"不支持的边界类型：{boundary_type}")
    if hydraulic_node_id is not None:
        raise ValueError("lateral_inflow 不得设置 hydraulic_node_id")
    if branch_id is None or chainage_m is None:
        raise ValueError("lateral_inflow requires branch_id and chainage_m")
    branch = session.scalar(
        select(HydraulicBranchRow).where(
            HydraulicBranchRow.id == branch_id,
            HydraulicBranchRow.dataset_version_id == dataset_version_id,
        )
    )
    if branch is None:
        raise ValueError("branch_id 必须属于边界条件的数据版本")
    if isinstance(chainage_m, bool) or not isinstance(chainage_m, (int, float)):
        raise ValueError("chainage_m 必须是非负米制数值")
    if not branch.start_chainage <= float(chainage_m) <= branch.end_chainage:
        raise ValueError("chainage_m 必须位于 branch_id 的定向桩号范围内")


def _boundary_numeric_series(values: Any, *, variable_key: str) -> list[tuple[float, float]]:
    """Read one constant or time series without guessing missing ordinates."""

    if not isinstance(values, dict):
        raise ValueError("边界 values 必须是 JSON 对象")
    mode = str(values.get("mode", "")).lower()
    if mode == "constant" or (
        "value" in values and "series" not in values and "time_seconds" not in values
    ):
        raw_value = values.get("value")
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise ValueError("定值边界必须提供数值 value")
        return [(0.0, float(raw_value))]
    raw_series = values.get("series")
    if isinstance(raw_series, list):
        result: list[tuple[float, float]] = []
        for index, sample in enumerate(raw_series):
            if not isinstance(sample, dict):
                raise ValueError(f"边界 series[{index}] 必须是对象")
            raw_time = sample.get("time_seconds")
            raw_value = sample.get("value", sample.get(variable_key))
            if (
                isinstance(raw_time, bool)
                or not isinstance(raw_time, (int, float))
                or isinstance(raw_value, bool)
                or not isinstance(raw_value, (int, float))
            ):
                raise ValueError(f"边界 series[{index}] 缺少有效时间或数值")
            result.append((float(raw_time), float(raw_value)))
    else:
        times = values.get("time_seconds")
        ordinates = values.get(variable_key)
        if (
            not isinstance(times, list)
            or not isinstance(ordinates, list)
            or len(times) != len(ordinates)
            or not times
        ):
            raise ValueError("边界必须提供对齐的非空时间和数值序列")
        result = [(float(time), float(value)) for time, value in zip(times, ordinates)]
    if any(right[0] <= left[0] for left, right in zip(result, result[1:])):
        raise ValueError("边界时间必须严格递增")
    return result


def _validate_rating_curve_values(session: Session, state: dict[str, Any]) -> None:
    """Validate rating-curve lineage and range against its discharge source."""

    values = state.get("values")
    if not isinstance(values, dict) or str(values.get("mode", "")).lower() != "rating_curve":
        return
    if state.get("boundary_type") != "downstream_water_level":
        raise ValueError("水位流量关系曲线只能用于下游水位边界")
    source_id = values.get("source_discharge_boundary_id")
    curve = values.get("curve")
    if not isinstance(curve, list):
        raise ValueError("关系曲线 curve 必须是数组")
    if source_id is None:
        reference = values.get("reference_discharge_m3_s")
        if isinstance(reference, bool) or not isinstance(reference, (int, float)):
            raise ValueError("关系曲线必须引用上游流量边界或固定参考流量")
        interpolate_rating_curve(curve, float(reference))
        return
    if isinstance(source_id, bool) or not isinstance(source_id, int):
        raise ValueError("关系曲线引用的上游流量边界 ID 无效")
    source = session.get(BoundaryCondition, source_id)
    if (
        source is None
        or source.dataset_version_id != state.get("dataset_version_id")
        or source.boundary_type != "upstream_discharge"
    ):
        raise ValueError("关系曲线引用的上游流量边界无效")
    expected_hash = snapshot_hash(source.values)
    if values.get("source_discharge_values_hash") != expected_hash:
        raise ValueError("上游流量边界已变更，请重新生成水位流量关系曲线")
    for _, discharge in _boundary_numeric_series(source.values, variable_key="flow_m3_s"):
        interpolate_rating_curve(curve, discharge)


def generate_boundary_rating_curve(
    session: Session, payload: BoundaryRatingCurveGenerateRequest
) -> BoundaryRatingCurveGenerateResponse:
    """Generate a derived Q-H boundary from the terminal active Section profile."""

    branch_rows = list(
        session.scalars(
            select(HydraulicBranchRow).where(
                HydraulicBranchRow.dataset_version_id == payload.dataset_version_id,
                HydraulicBranchRow.downstream_node_id == payload.hydraulic_node_id,
            )
        ).all()
    )
    if len(branch_rows) != 1:
        raise ValueError("下游节点必须唯一对应一条定向水力河段")
    branch = branch_rows[0]
    sections = list(
        session.scalars(
            select(HydraulicCrossSection)
            .where(
                HydraulicCrossSection.dataset_version_id == payload.dataset_version_id,
                HydraulicCrossSection.branch_id == branch.id,
            )
            .order_by(HydraulicCrossSection.chainage.desc())
        ).all()
    )
    if len(sections) < 2:
        raise ValueError("自动生成关系曲线至少需要下游末两个断面")
    terminal, upstream = sections[0], sections[1]
    endpoint_tolerance = max(0.001, abs(branch.end_chainage - branch.start_chainage) * 1e-9)
    if abs(float(terminal.chainage) - float(branch.end_chainage)) > endpoint_tolerance:
        raise ValueError("最下游断面必须与河段下游端点重合")

    def profile_and_points(section: HydraulicCrossSection):
        """Load one active profile and its immutable ordered survey points."""

        profile = session.scalar(
            select(HydraulicCrossSectionProfile).where(
                HydraulicCrossSectionProfile.cross_section_id == section.id,
                HydraulicCrossSectionProfile.is_active.is_(True),
            )
        )
        if profile is None:
            raise ValueError(f"断面 {section.section_code} 没有活动横断面剖面")
        points = list(
            session.scalars(
                select(HydraulicCrossSectionPoint)
                .where(HydraulicCrossSectionPoint.profile_id == profile.id)
                .order_by(HydraulicCrossSectionPoint.sequence)
            ).all()
        )
        if len(points) < 2:
            raise ValueError(f"断面 {section.section_code} 测点不足")
        return profile, points

    profile, terminal_points = profile_and_points(terminal)
    _, upstream_points = profile_and_points(upstream)
    source_profile_points = [
        (float(point.distance), float(point.elevation)) for point in terminal_points
    ]
    processed_rows = (profile.processed_geometry_json or {}).get("points", [])
    profile_points = (
        [(float(item["offset"]), float(item["elevation"])) for item in processed_rows]
        if processed_rows
        else source_profile_points
    )
    zones = list(
        session.scalars(
            select(HydraulicRoughnessZone)
            .where(HydraulicRoughnessZone.profile_id == profile.id)
            .order_by(HydraulicRoughnessZone.zone_order)
        ).all()
    )
    intervals = _roughness_intervals(source_profile_points, zones, profile.default_manning_n)

    warnings = [
        "自动关系曲线采用 Manning 均匀流假定，不代替实测率定曲线。"
    ]
    if payload.friction_slope is None:
        distance = float(terminal.chainage) - float(upstream.chainage)
        if distance <= 0:
            raise ValueError("末两断面桩号必须严格递增")
        slope = (
            min(float(point.elevation) for point in upstream_points)
            - min(float(point.elevation) for point in terminal_points)
        ) / distance
        if slope <= 0:
            raise ValueError("末两断面无法推导正坡降，请人工输入摩阻坡降")
        slope_source = "DERIVED_TERMINAL_THALWEG"
        warnings.append("摩阻坡降由末两断面深泓高程差自动推导，需要工程复核。")
    else:
        slope = float(payload.friction_slope)
        slope_source = "MANUAL"

    if payload.source_discharge_boundary_id is not None:
        source = session.get(BoundaryCondition, payload.source_discharge_boundary_id)
        if (
            source is None
            or source.dataset_version_id != payload.dataset_version_id
            or source.boundary_type != "upstream_discharge"
            or source.hydraulic_node_id != branch.upstream_node_id
        ):
            raise ValueError("流量来源必须是同版本、同河段上游端的流量边界")
        discharge_series = _boundary_numeric_series(source.values, variable_key="flow_m3_s")
        source_id = source.id
        source_hash = snapshot_hash(source.values)
    else:
        discharge_series = [(0.0, float(payload.reference_discharge_m3s))]
        source_id = None
        source_hash = None
    reference_discharge = max(value for _, value in discharge_series)
    curve = generate_manning_rating_curve(
        points=profile_points,
        roughness_intervals=intervals,
        friction_slope=slope,
        reference_discharge_m3s=reference_discharge,
        vertical_step_m=payload.vertical_step_m,
        maximum_depth_m=payload.maximum_depth_m,
    )
    resolved = [
        {
            "time_seconds": time,
            "water_level_m": interpolate_rating_curve(curve, discharge),
        }
        for time, discharge in discharge_series
    ]
    values: dict[str, Any] = {
        "mode": "rating_curve",
        "method": RATING_CURVE_METHOD,
        "curve": curve,
        "series": resolved,
        "friction_slope": slope,
        "friction_slope_source": slope_source,
        "cross_section_id": terminal.id,
        "profile_id": profile.id,
        "reference_discharge_m3_s": reference_discharge,
        "raw_profile_immutable": True,
    }
    if source_id is not None:
        values.update(
            {
                "source_discharge_boundary_id": source_id,
                "source_discharge_values_hash": source_hash,
            }
        )
    return BoundaryRatingCurveGenerateResponse(
        dataset_version_id=payload.dataset_version_id,
        hydraulic_node_id=payload.hydraulic_node_id,
        branch_id=branch.id,
        cross_section_id=terminal.id,
        cross_section_code=terminal.section_code,
        profile_id=profile.id,
        vertical_datum=profile.vertical_datum,
        friction_slope=slope,
        friction_slope_source=slope_source,
        reference_discharge_m3s=reference_discharge,
        resolved_water_level_m=resolved[-1]["water_level_m"],
        curve=curve,
        values=values,
        warnings=warnings,
    )


def create_boundary(session: Session, payload: BoundaryConditionCreate) -> BoundaryConditionRecord:
    """新增边界条件。"""

    assert_dataset_version_mutable(session, payload.dataset_version_id)
    values = payload.model_dump()
    _validate_boundary_binding(session, values)
    _validate_rating_curve_values(session, values)
    entity = BoundaryCondition(**values)
    session.add(entity)
    session.flush()
    return BoundaryConditionRecord(**_dump(entity))


def update_boundary(session: Session, entity: BoundaryCondition, payload: BoundaryConditionUpdate) -> BoundaryConditionRecord:
    """局部修改边界条件。"""

    assert_dataset_version_mutable(session, entity.dataset_version_id)
    values = payload.model_dump(exclude_unset=True)
    state = {
        "dataset_version_id": entity.dataset_version_id,
        "boundary_type": entity.boundary_type,
        "hydraulic_node_id": entity.hydraulic_node_id,
        "branch_id": entity.branch_id,
        "chainage_m": entity.chainage_m,
        "values": entity.values,
        "unit": entity.unit,
    }
    state.update(values)
    _validate_boundary_binding(session, state)
    _validate_rating_curve_values(session, state)
    _apply(entity, values)
    session.flush()
    return BoundaryConditionRecord(**_dump(entity))


def list_cases(session: Session, dataset_version_id: int | None) -> list[SimulationCaseRecord]:
    """返回指定版本或全部计算方案。"""

    statement = select(SimulationCase).order_by(SimulationCase.id)
    if dataset_version_id is not None:
        statement = statement.where(SimulationCase.dataset_version_id == dataset_version_id)
    return [_case_record(session, item) for item in session.scalars(statement).all()]


def _validate_case_boundaries(
    session: Session, dataset_version_id: int, boundary_ids: list[int]
) -> list[BoundaryCondition]:
    """Require current authoritative bindings and reject duplicate locations."""

    unique_ids = list(dict.fromkeys(boundary_ids))
    if not unique_ids:
        raise ValueError("计算方案至少需要一个明确关联边界")
    boundaries = list(
        session.scalars(
            select(BoundaryCondition)
            .where(BoundaryCondition.id.in_(unique_ids))
            .order_by(BoundaryCondition.id)
        ).all()
    )
    if len(boundaries) != len(unique_ids) or any(
        item.dataset_version_id != dataset_version_id for item in boundaries
    ):
        raise ValueError("全部边界条件必须存在且属于计算方案的数据版本")
    keys: set[tuple[Any, ...]] = set()
    for boundary in boundaries:
        state = {
            "dataset_version_id": boundary.dataset_version_id,
            "boundary_type": boundary.boundary_type,
            "hydraulic_node_id": boundary.hydraulic_node_id,
            "branch_id": boundary.branch_id,
            "chainage_m": boundary.chainage_m,
        }
        _validate_boundary_binding(session, state)
        if boundary.boundary_type == "lateral_inflow":
            key = (boundary.boundary_type, boundary.branch_id, boundary.chainage_m)
        else:
            key = (boundary.boundary_type, boundary.hydraulic_node_id)
        if key in keys:
            raise ValueError("同一水力位置不可关联多个同类型边界")
        keys.add(key)
    return boundaries


def _replace_case_boundary_links(
    session: Session, case: SimulationCase, boundaries: list[BoundaryCondition]
) -> None:
    """原子替换计算方案的边界组，旧主边界字段保留兼容。"""

    session.query(SimulationCaseBoundary).filter(
        SimulationCaseBoundary.case_id == case.id
    ).delete(synchronize_session=False)
    for boundary in boundaries:
        session.add(
            SimulationCaseBoundary(
                case_id=case.id,
                boundary_condition_id=boundary.id,
                role=boundary.boundary_type,
            )
        )


def create_case(session: Session, payload: SimulationCaseCreate) -> SimulationCaseRecord:
    """新增计算方案，并要求边界条件属于同一数据版本。"""

    assert_dataset_version_mutable(session, payload.dataset_version_id)
    boundary_ids = payload.boundary_condition_ids or [payload.boundary_condition_id]
    boundaries = _validate_case_boundaries(session, payload.dataset_version_id, boundary_ids)
    values = payload.model_dump(exclude={"boundary_condition_ids"})
    values["boundary_condition_id"] = boundaries[0].id
    entity = SimulationCase(**values)
    session.add(entity)
    session.flush()
    _replace_case_boundary_links(session, entity, boundaries)
    session.flush()
    return _case_record(session, entity)


def update_case(session: Session, entity: SimulationCase, payload: SimulationCaseUpdate) -> SimulationCaseRecord:
    """修改计算方案并保持数据版本与边界条件一致。"""

    assert_dataset_version_mutable(session, entity.dataset_version_id)
    values = payload.model_dump(exclude_unset=True)
    boundary_ids = values.pop("boundary_condition_ids", None)
    boundary_id = values.get("boundary_condition_id")
    if boundary_ids is not None or boundary_id is not None:
        selected_ids = boundary_ids if boundary_ids is not None else [boundary_id]
        boundaries = _validate_case_boundaries(
            session, entity.dataset_version_id, [int(item) for item in selected_ids]
        )
        values["boundary_condition_id"] = boundaries[0].id
        _replace_case_boundary_links(session, entity, boundaries)
    _apply(entity, values)
    session.flush()
    return _case_record(session, entity)


def delete_entity(session: Session, entity: Any) -> None:
    """删除版本配置类对象并刷新约束。"""

    if isinstance(entity, DatasetVersion):
        assert_dataset_version_mutable(session, entity.id)
    elif isinstance(entity, (ModelParameter, BoundaryCondition, SimulationCase)):
        assert_dataset_version_mutable(session, entity.dataset_version_id)
    session.delete(entity)
    session.flush()


def _apply(entity: Any, values: dict[str, Any]) -> None:
    """把显式提供的字段应用到 ORM 实体。"""

    for key, value in values.items():
        setattr(entity, key, value)
