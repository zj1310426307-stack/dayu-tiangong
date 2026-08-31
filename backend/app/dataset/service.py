"""Dataset Version, model configuration, boundary, and Case services."""

from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dataset.lifecycle import assert_dataset_version_mutable
from app.dataset.schemas import (
    BoundaryConditionCreate,
    BoundaryConditionRecord,
    BoundaryConditionUpdate,
    DatasetVersionCreate,
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
    HydraulicNode,
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


def create_boundary(session: Session, payload: BoundaryConditionCreate) -> BoundaryConditionRecord:
    """新增边界条件。"""

    assert_dataset_version_mutable(session, payload.dataset_version_id)
    values = payload.model_dump()
    _validate_boundary_binding(session, values)
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
    }
    state.update(values)
    _validate_boundary_binding(session, state)
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
