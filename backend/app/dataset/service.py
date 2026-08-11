"""数据集版本、模型配置和 Phase 3 输入快照业务服务。"""

from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.spatial import geometry_json
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
)


Entity = TypeVar("Entity")


def _dump(entity: Any) -> dict[str, Any]:
    """提取非 ORM 内部字段，供简单记录契约复用。"""

    return {column.name: getattr(entity, column.name) for column in entity.__table__.columns}


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

    _apply(entity, payload.model_dump(exclude_unset=True))
    session.flush()
    return DatasetVersionRecord(**_dump(entity))


def list_parameters(session: Session, dataset_version_id: int | None) -> list[ModelParameterRecord]:
    """返回指定版本或全部模型参数。"""

    statement = select(ModelParameter).order_by(ModelParameter.id)
    if dataset_version_id is not None:
        statement = statement.where(ModelParameter.dataset_version_id == dataset_version_id)
    return [ModelParameterRecord(**_dump(item)) for item in session.scalars(statement).all()]


def create_parameter(session: Session, payload: ModelParameterCreate) -> ModelParameterRecord:
    """新增模型参数。"""

    entity = ModelParameter(**payload.model_dump())
    session.add(entity)
    session.flush()
    return ModelParameterRecord(**_dump(entity))


def update_parameter(session: Session, entity: ModelParameter, payload: ModelParameterUpdate) -> ModelParameterRecord:
    """修改模型参数值或说明。"""

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

    entity = BoundaryCondition(**payload.model_dump())
    session.add(entity)
    session.flush()
    return BoundaryConditionRecord(**_dump(entity))


def update_boundary(session: Session, entity: BoundaryCondition, payload: BoundaryConditionUpdate) -> BoundaryConditionRecord:
    """局部修改边界条件。"""

    _apply(entity, payload.model_dump(exclude_unset=True))
    session.flush()
    return BoundaryConditionRecord(**_dump(entity))


def list_cases(session: Session, dataset_version_id: int | None) -> list[SimulationCaseRecord]:
    """返回指定版本或全部计算方案。"""

    statement = select(SimulationCase).order_by(SimulationCase.id)
    if dataset_version_id is not None:
        statement = statement.where(SimulationCase.dataset_version_id == dataset_version_id)
    return [SimulationCaseRecord(**_dump(item)) for item in session.scalars(statement).all()]


def create_case(session: Session, payload: SimulationCaseCreate) -> SimulationCaseRecord:
    """新增计算方案，并要求边界条件属于同一数据版本。"""

    boundary = session.get(BoundaryCondition, payload.boundary_condition_id)
    if boundary is None or boundary.dataset_version_id != payload.dataset_version_id:
        raise ValueError("边界条件必须存在且属于同一数据版本")
    entity = SimulationCase(**payload.model_dump())
    session.add(entity)
    session.flush()
    return SimulationCaseRecord(**_dump(entity))


def update_case(session: Session, entity: SimulationCase, payload: SimulationCaseUpdate) -> SimulationCaseRecord:
    """修改计算方案并保持数据版本与边界条件一致。"""

    values = payload.model_dump(exclude_unset=True)
    boundary_id = values.get("boundary_condition_id")
    if boundary_id is not None:
        boundary = session.get(BoundaryCondition, boundary_id)
        if boundary is None or boundary.dataset_version_id != entity.dataset_version_id:
            raise ValueError("边界条件必须存在且属于同一数据版本")
    _apply(entity, values)
    session.flush()
    return SimulationCaseRecord(**_dump(entity))


def delete_entity(session: Session, entity: Any) -> None:
    """删除版本配置类对象并刷新约束。"""

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
    boundaries = list_boundaries(session, version_id)
    connections = [_dump(item) for item in session.scalars(select(RiverConnection).where(RiverConnection.dataset_version_id == version_id).order_by(RiverConnection.id)).all()]
    return ModelInputSnapshot(
        generated_time=datetime.now(UTC),
        simulation_case=SimulationCaseRecord(**_dump(case)),
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
