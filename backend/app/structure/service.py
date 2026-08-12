"""闸门与泵站 CRUD、筛选及空间序列化业务服务。"""

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.common.spatial import geometry_expression, geometry_json
from app.gis.models import Gate, Pump
from app.structure.schemas import (
    GateCreate,
    GateListResponse,
    GateRecord,
    GateUpdate,
    PumpCreate,
    PumpListResponse,
    PumpRecord,
    PumpUpdate,
)


def _gate_record(session: Session, gate: Gate) -> GateRecord:
    """把闸门 ORM 对象转换为响应记录。"""

    return GateRecord(
        id=gate.id,
        dataset_version_id=gate.dataset_version_id,
        name=gate.name,
        gate_code=gate.gate_code,
        river_id=gate.river_id,
        gate_type=gate.gate_type,
        opening_direction=gate.opening_direction,
        control_mode=gate.control_mode,
        width=gate.width,
        height=gate.height,
        max_flow=gate.max_flow,
        bottom_elevation=gate.bottom_elevation,
        river_segment_id=gate.river_segment_id,
        station=gate.station,
        upstream_node_id=gate.upstream_node_id,
        downstream_node_id=gate.downstream_node_id,
        crest_elevation=gate.crest_elevation,
        discharge_coefficient=gate.discharge_coefficient,
        minimum_opening=gate.minimum_opening,
        maximum_opening=gate.maximum_opening,
        opening_rate_limit=gate.opening_rate_limit,
        minimum_hold_seconds=gate.minimum_hold_seconds,
        allow_reverse_flow=gate.allow_reverse_flow,
        status=gate.status,
        geometry=geometry_json(session, gate.geometry),
        created_time=gate.created_time,
    )


def _pump_record(session: Session, pump: Pump) -> PumpRecord:
    """把泵站 ORM 对象转换为响应记录。"""

    return PumpRecord(
        id=pump.id,
        dataset_version_id=pump.dataset_version_id,
        name=pump.name,
        pump_code=pump.pump_code,
        river_id=pump.river_id,
        design_flow=pump.design_flow,
        head=pump.head,
        power=pump.power,
        efficiency_curve=pump.efficiency_curve,
        head_curve=pump.head_curve,
        intake_node_id=pump.intake_node_id,
        outlet_node_id=pump.outlet_node_id,
        transfer_type=pump.transfer_type,
        unit_count=pump.unit_count,
        minimum_running_units=pump.minimum_running_units,
        maximum_running_units=pump.maximum_running_units,
        minimum_run_seconds=pump.minimum_run_seconds,
        minimum_stop_seconds=pump.minimum_stop_seconds,
        maximum_starts_per_run=pump.maximum_starts_per_run,
        minimum_operating_head=pump.minimum_operating_head,
        maximum_operating_head=pump.maximum_operating_head,
        reverse_flow_protection=pump.reverse_flow_protection,
        control_mode=pump.control_mode,
        status=pump.status,
        geometry=geometry_json(session, pump.geometry),
        created_time=pump.created_time,
    )


def _conditions(model: Any, dataset_version_id: int | None, river_id: int | None, search: str | None) -> list[Any]:
    """构造闸泵列表共用筛选条件。"""

    values: list[Any] = []
    if dataset_version_id is not None:
        values.append(model.dataset_version_id == dataset_version_id)
    if river_id is not None:
        values.append(model.river_id == river_id)
    if search:
        token = f"%{search.strip()}%"
        code_column = model.gate_code if model is Gate else model.pump_code
        values.append(or_(model.name.ilike(token), code_column.ilike(token)))
    return values


def list_gates(session: Session, dataset_version_id: int | None, river_id: int | None, search: str | None, limit: int, offset: int) -> GateListResponse:
    """分页查询闸门。"""

    conditions = _conditions(Gate, dataset_version_id, river_id, search)
    total = session.scalar(select(func.count(Gate.id)).where(*conditions)) or 0
    entities = session.scalars(select(Gate).where(*conditions).order_by(Gate.id).limit(limit).offset(offset)).all()
    return GateListResponse(items=[_gate_record(session, item) for item in entities], total=total, limit=limit, offset=offset)


def list_pumps(session: Session, dataset_version_id: int | None, river_id: int | None, search: str | None, limit: int, offset: int) -> PumpListResponse:
    """分页查询泵站。"""

    conditions = _conditions(Pump, dataset_version_id, river_id, search)
    total = session.scalar(select(func.count(Pump.id)).where(*conditions)) or 0
    entities = session.scalars(select(Pump).where(*conditions).order_by(Pump.id).limit(limit).offset(offset)).all()
    return PumpListResponse(items=[_pump_record(session, item) for item in entities], total=total, limit=limit, offset=offset)


def get_gate(session: Session, entity_id: int) -> GateRecord | None:
    """按主键读取闸门。"""

    entity = session.get(Gate, entity_id)
    return _gate_record(session, entity) if entity else None


def get_pump(session: Session, entity_id: int) -> PumpRecord | None:
    """按主键读取泵站。"""

    entity = session.get(Pump, entity_id)
    return _pump_record(session, entity) if entity else None


def create_gate(session: Session, payload: GateCreate) -> GateRecord:
    """新增闸门。"""

    values = payload.model_dump(exclude={"geometry"})
    entity = Gate(**values, geometry=geometry_expression(payload.geometry, "Point"))
    session.add(entity)
    session.flush()
    return _gate_record(session, entity)


def create_pump(session: Session, payload: PumpCreate) -> PumpRecord:
    """新增泵站。"""

    values = payload.model_dump(exclude={"geometry"})
    entity = Pump(**values, geometry=geometry_expression(payload.geometry, "Point"))
    session.add(entity)
    session.flush()
    return _pump_record(session, entity)


def update_gate(session: Session, entity: Gate, payload: GateUpdate) -> GateRecord:
    """局部更新闸门。"""

    values = payload.model_dump(exclude_unset=True)
    geometry = values.pop("geometry", None)
    for key, value in values.items():
        setattr(entity, key, value)
    if geometry is not None:
        entity.geometry = geometry_expression(geometry, "Point")
    session.flush()
    return _gate_record(session, entity)


def update_pump(session: Session, entity: Pump, payload: PumpUpdate) -> PumpRecord:
    """局部更新泵站。"""

    values = payload.model_dump(exclude_unset=True)
    geometry = values.pop("geometry", None)
    for key, value in values.items():
        setattr(entity, key, value)
    if geometry is not None:
        entity.geometry = geometry_expression(geometry, "Point")
    session.flush()
    return _pump_record(session, entity)


def delete_structure(session: Session, entity: Gate | Pump) -> None:
    """删除指定闸门或泵站。"""

    session.delete(entity)
    session.flush()
