"""数据集版本、模型配置和 Phase 3 输入快照业务服务。"""

from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.spatial import geometry_json
from app.dataset.lifecycle import assert_dataset_version_mutable
from app.dataset.schemas import (
    BoundaryConditionCreate,
    BoundaryConditionRecord,
    BoundaryConditionUpdate,
    DatasetVersionCreate,
    DatasetVersionRecord,
    DatasetVersionUpdate,
    ModelInputSnapshot,
    ModelParameterCreate,
    ModelParameterRecord,
    ModelParameterUpdate,
    SimulationCaseCreate,
    SimulationCaseRecord,
    SimulationCaseUpdate,
)
from app.gis.models import (
    BoundaryCondition,
    CrossSection,
    DatasetVersion,
    Gate,
    ModelParameter,
    Pump,
    River,
    RiverConnection,
    RiverNode,
    RiverSegment,
    SimulationCase,
    SimulationCaseBoundary,
)


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
    return SimulationCaseRecord(**_dump(entity), boundary_condition_ids=boundary_ids)


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


def create_boundary(session: Session, payload: BoundaryConditionCreate) -> BoundaryConditionRecord:
    """新增边界条件。"""

    assert_dataset_version_mutable(session, payload.dataset_version_id)
    entity = BoundaryCondition(**payload.model_dump())
    session.add(entity)
    session.flush()
    return BoundaryConditionRecord(**_dump(entity))


def update_boundary(session: Session, entity: BoundaryCondition, payload: BoundaryConditionUpdate) -> BoundaryConditionRecord:
    """局部修改边界条件。"""

    assert_dataset_version_mutable(session, entity.dataset_version_id)
    _apply(entity, payload.model_dump(exclude_unset=True))
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
    """验证边界存在、同版本且没有同节点同类型冲突。"""

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
    keys: set[tuple[int | None, str]] = set()
    for boundary in boundaries:
        key = (boundary.target_node_id, boundary.boundary_type)
        if key in keys:
            raise ValueError("同一节点不可关联多个同类型边界")
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


def build_model_input(session: Session, case_id: int) -> ModelInputSnapshot | None:
    """汇总指定方案对应版本的全部静态水动力输入，绝不写入计算结果。"""

    case = session.get(SimulationCase, case_id)
    if case is None:
        return None
    version_id = case.dataset_version_id
    dataset_version = session.get(DatasetVersion, version_id)
    if dataset_version is None:
        return None

    def spatial_rows(model: Any) -> list[dict[str, Any]]:
        """序列化指定版本内某类空间表。"""

        entities = session.scalars(select(model).where(model.dataset_version_id == version_id).order_by(model.id)).all()
        rows: list[dict[str, Any]] = []
        for entity in entities:
            row = _dump(entity)
            row["geometry"] = geometry_json(session, entity.geometry)
            rows.append(row)
        return rows

    parameters = list_parameters(session, version_id)
    boundary_ids = list(
        session.scalars(
            select(SimulationCaseBoundary.boundary_condition_id).where(
                SimulationCaseBoundary.case_id == case.id
            )
        ).all()
    )
    if not boundary_ids:
        boundary_ids = [case.boundary_condition_id]
    boundaries = [
        BoundaryConditionRecord(**_dump(item))
        for item in session.scalars(
            select(BoundaryCondition)
            .where(BoundaryCondition.id.in_(boundary_ids))
            .order_by(BoundaryCondition.id)
        ).all()
    ]
    connections = [_dump(item) for item in session.scalars(select(RiverConnection).where(RiverConnection.dataset_version_id == version_id).order_by(RiverConnection.id)).all()]
    return ModelInputSnapshot(
        generated_time=datetime.now(UTC),
        simulation_case=_case_record(session, case),
        dataset_version=DatasetVersionRecord(**_dump(dataset_version)),
        rivers=spatial_rows(River),
        nodes=spatial_rows(RiverNode),
        segments=spatial_rows(RiverSegment),
        connections=connections,
        cross_sections=spatial_rows(CrossSection),
        gates=spatial_rows(Gate),
        pumps=spatial_rows(Pump),
        parameters=parameters,
        boundary_conditions=boundaries,
    )


def build_model_input_v2(
    session: Session,
    case_id: int,
    *,
    controls: dict[str, Any] | None = None,
    dispatch_plan: dict[str, Any] | None = None,
    engine_version: str = "dayu-hydraulic-4.0.0",
) -> dict[str, Any] | None:
    """构建可冻结的 v2 输入，显式声明几何、边界、单位和来源。"""

    legacy = build_model_input(session, case_id)
    if legacy is None:
        return None
    payload = legacy.model_dump(mode="json")
    payload.pop("generated_time", None)
    payload["schema_version"] = "dayu.model-input.v2"
    geometry_mode = str((controls or {}).get("section_geometry", "rectangular"))
    payload["cross_sections"] = [
        {**item, "geometry_type": geometry_mode} for item in payload["cross_sections"]
    ]
    payload["controls"] = {
        "allow_fallback_boundary": False,
        "section_geometry": geometry_mode,
        **(controls or {}),
    }
    payload["dispatch_plan"] = dispatch_plan
    payload["units"] = {
        "length": "m",
        "time": "s",
        "flow": "m3/s",
        "water_level": "m",
        "power": "kW",
        "energy": "kWh",
    }
    payload["coordinate_system"] = "CGCS2000 (EPSG:4490)"
    payload["distance_basis"] = "section station and segment length in metres"
    payload["engine_version"] = engine_version
    return payload
