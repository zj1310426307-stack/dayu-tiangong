"""执行空间、水力、建筑物、拓扑与模型输入完整性规则。"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
    SimulationCase,
)
from app.validation.schemas import ValidationItem, ValidationReport, ValidationSummary


def _ids(session: Session, statement: Any) -> list[int]:
    """执行规则查询并最多保留五个样例主键。"""

    return list(session.scalars(statement.limit(5)).all())


def _item(code: str, category: str, message: str, sample_ids: list[int], severity: str = "error") -> ValidationItem:
    """根据命中结果构造通过或失败规则项。"""

    return ValidationItem(
        code=code,
        category=category,
        severity=severity if sample_ids else "passed",
        message=f"不通过：{message}" if sample_ids else f"通过：{message}",
        count=len(sample_ids),
        sample_ids=sample_ids,
    )


def run_validation(session: Session, dataset_version_id: int) -> ValidationReport:
    """对一个版本运行可直接阻断模型输入的核心规则集。"""

    if session.get(DatasetVersion, dataset_version_id) is None:
        raise ValueError("数据集版本不存在")

    items: list[ValidationItem] = []
    for model, label in ((River, "河道"), (CrossSection, "横断面"), (Gate, "闸门"), (Pump, "泵站"), (RiverNode, "河网节点")):
        invalid = _ids(
            session,
            select(model.id).where(
                model.dataset_version_id == dataset_version_id,
                ~func.ST_IsValid(model.geometry),
            ),
        )
        items.append(_item(f"SPATIAL_{model.__tablename__.upper()}_VALID", "spatial", f"{label}空间几何有效", invalid))

    no_sections = _ids(
        session,
        select(River.id).where(
            River.dataset_version_id == dataset_version_id,
            ~select(CrossSection.id).where(CrossSection.river_id == River.id).exists(),
        ),
    )
    items.append(_item("HYDRAULIC_RIVER_SECTION_REQUIRED", "hydraulic", "每条河道至少包含一个横断面", no_sections))

    out_of_range = _ids(
        session,
        select(CrossSection.id).join(River, River.id == CrossSection.river_id).where(
            CrossSection.dataset_version_id == dataset_version_id,
            CrossSection.station > River.length,
        ),
    )
    items.append(_item("HYDRAULIC_STATION_RANGE", "hydraulic", "断面桩号位于所属河道长度范围内", out_of_range))

    elevation_mismatch = []
    for section in session.scalars(
        select(CrossSection).where(CrossSection.dataset_version_id == dataset_version_id)
    ).all():
        profile = section.points.get("points", []) if isinstance(section.points, dict) else []
        if not profile or abs(section.elevation_min - min(float(point[1]) for point in profile)) > 0.01:
            elevation_mismatch.append(section.id)
        if len(elevation_mismatch) == 5:
            break
    items.append(_item("HYDRAULIC_ELEVATION_MIN", "hydraulic", "断面最低高程与剖面点一致", elevation_mismatch, "warning"))

    gate_invalid = _ids(
        session,
        select(Gate.id).where(
            Gate.dataset_version_id == dataset_version_id,
            (Gate.max_flow <= 0) | (Gate.width <= 0) | (Gate.height <= 0),
        ),
    )
    items.append(_item("STRUCTURE_GATE_PARAMETERS", "structure", "闸门宽高和最大过流能力有效", gate_invalid))

    pump_invalid = _ids(
        session,
        select(Pump.id).where(
            Pump.dataset_version_id == dataset_version_id,
            (Pump.design_flow <= 0) | (Pump.head <= 0) | (Pump.power <= 0),
        ),
    )
    items.append(_item("STRUCTURE_PUMP_PARAMETERS", "structure", "泵站设计流量、扬程和功率有效", pump_invalid))

    pump_curve = _ids(
        session,
        select(Pump.id).where(
            Pump.dataset_version_id == dataset_version_id,
            func.json_array_length(Pump.efficiency_curve["points"]) < 2,
        ),
    )
    items.append(_item("STRUCTURE_PUMP_CURVE", "structure", "泵站效率曲线至少包含两个点", pump_curve))

    river_count = session.scalar(select(func.count(River.id)).where(River.dataset_version_id == dataset_version_id)) or 0
    from app.gis.models import RiverSegment

    segment_count = session.scalar(select(func.count(RiverSegment.id)).where(RiverSegment.dataset_version_id == dataset_version_id)) or 0
    connection_count = session.scalar(select(func.count(RiverConnection.id)).where(RiverConnection.dataset_version_id == dataset_version_id)) or 0
    topology_missing = [dataset_version_id] if river_count > 0 and (segment_count == 0 or connection_count != segment_count) else []
    items.append(_item("TOPOLOGY_CONNECTION_COMPLETE", "topology", "每个计算河段均有一条有向拓扑连接", topology_missing))

    boundary_missing = [dataset_version_id] if not session.scalar(select(BoundaryCondition.id).where(BoundaryCondition.dataset_version_id == dataset_version_id).limit(1)) else []
    items.append(_item("MODEL_BOUNDARY_REQUIRED", "model", "数据版本至少包含一个边界条件", boundary_missing))

    parameter_missing = [dataset_version_id] if not session.scalar(select(ModelParameter.id).where(ModelParameter.dataset_version_id == dataset_version_id).limit(1)) else []
    items.append(_item("MODEL_PARAMETER_REQUIRED", "model", "数据版本至少包含一个模型参数", parameter_missing, "warning"))

    case_missing = [dataset_version_id] if not session.scalar(select(SimulationCase.id).where(SimulationCase.dataset_version_id == dataset_version_id).limit(1)) else []
    items.append(_item("MODEL_CASE_REQUIRED", "model", "数据版本至少包含一个计算方案", case_missing, "warning"))

    errors = sum(1 for item in items if item.severity == "error")
    warnings = sum(1 for item in items if item.severity == "warning")
    passed = sum(1 for item in items if item.severity == "passed")
    return ValidationReport(
        dataset_version_id=dataset_version_id,
        checked_time=datetime.now(UTC),
        summary=ValidationSummary(errors=errors, warnings=warnings, passed=passed, is_model_ready=errors == 0),
        items=items,
    )
