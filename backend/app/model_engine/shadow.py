"""Create and compare independent legacy-v3/native-v4 diagnostic task pairs."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.gis.models import (
    HydraulicTaskSectionResult,
    SimulationResult,
    SimulationTask,
    SimulationTaskGroup,
)
from app.hydraulic.model_input import build_model_input_v3
from app.model_engine import service
from app.model_engine.schemas import SimulationTaskCreate
from app.model_engine.v4_schemas import (
    V4ShadowComparison,
    V4ShadowCreate,
    V4ShadowPair,
    V4ShadowSectionDelta,
)
from app.model_engine.v4_service import assess_database_case
from model.solver.registry import D1_CAPABILITY_ID, D1_SOLVER_ID, LEGACY_NETWORK_SOLVER


_DISCLAIMER = (
    "Diagnostic shadow only: legacy v3 is not truth for native v4, and neither "
    "result is approved for production water decisions."
)


def create_shadow_pair(session: Session, payload: V4ShadowCreate) -> V4ShadowPair:
    """Freeze two independent inputs only when both platform builders are ready."""

    try:
        try:
            v3_snapshot = build_model_input_v3(session, payload.case_id)
        except ValueError as exc:
            raise ValueError(f"shadow not_ready: v3: {exc}") from exc
        if v3_snapshot is None:
            raise LookupError("simulation case does not exist")
        assessment = assess_database_case(
            session, payload.case_id, payload.dispatch_plan_id
        )
        if not assessment.readiness.ready:
            detail = "; ".join(
                f"{item.code}: {item.message}" for item in assessment.readiness.errors
            )
            raise ValueError(f"shadow not_ready: v4: {detail}")

        group = SimulationTaskGroup(
            case_id=payload.case_id,
            group_type="shadow",
            status="pending",
        )
        session.add(group)
        session.flush()
        v3_task = service.build_task_entity(
            session,
            SimulationTaskCreate(
                case_id=payload.case_id,
                input_schema_version="dayu.model-input.v3",
                solver_id=LEGACY_NETWORK_SOLVER,
                storage_level="full",
            ),
        )
        v4_task = service.build_task_entity(
            session,
            SimulationTaskCreate(
                case_id=payload.case_id,
                input_schema_version="dayu.model-input.v4",
                solver_id=D1_SOLVER_ID,
                capability_id=D1_CAPABILITY_ID,
                dispatch_plan_id=payload.dispatch_plan_id,
                execution_mode="shadow",
                storage_level="full",
            ),
        )
        v3_task.comparison_group_id = group.id
        v3_task.group_role = "legacy-v3"
        v3_task.execution_mode = "shadow"
        v4_task.comparison_group_id = group.id
        v4_task.group_role = "native-v4"
        group_id = int(group.id)
        v3_task_id = int(v3_task.id)
        v4_task_id = int(v4_task.id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return V4ShadowPair(
        group_id=group_id,
        status="pending",
        v3_task_id=v3_task_id,
        v4_task_id=v4_task_id,
    )


def _tasks(
    session: Session, group_id: int
) -> tuple[SimulationTaskGroup, SimulationTask | None, SimulationTask | None]:
    group = session.get(SimulationTaskGroup, group_id)
    if group is None:
        raise LookupError("shadow task group does not exist")
    tasks = session.scalars(
        select(SimulationTask).where(SimulationTask.comparison_group_id == group_id)
    ).all()
    v3 = next((item for item in tasks if item.group_role == "legacy-v3"), None)
    v4 = next((item for item in tasks if item.group_role == "native-v4"), None)
    return group, v3, v4


def _persist_group_status(
    session: Session, group: SimulationTaskGroup, status: str
) -> None:
    """Persist a derived group lifecycle state without rewriting unchanged rows."""

    if group.status == status:
        return
    group.status = status
    session.commit()


def compare_shadow_pair(session: Session, group_id: int) -> V4ShadowComparison:
    """Compare common Section codes/times after both independent tasks succeed."""

    group, v3, v4 = _tasks(session, group_id)
    if v3 is None or v4 is None:
        status = "not_ready"
        group_status = "failed"
        rows: list[V4ShadowSectionDelta] = []
    elif v3.status == "failed" or v4.status == "failed":
        status = "failed"
        group_status = "failed"
        rows = []
    elif v3.status == "cancelled" or v4.status == "cancelled":
        status = "cancelled"
        group_status = "cancelled"
        rows = []
    elif v3.status != "success" or v4.status != "success":
        status = "pending" if v3.status == v4.status == "pending" else "running"
        group_status = status
        rows = []
    else:
        legacy = session.scalars(
            select(SimulationResult)
            .where(SimulationResult.task_id == v3.id)
            .order_by(SimulationResult.section_code, SimulationResult.time_seconds)
        ).all()
        native = session.scalars(
            select(HydraulicTaskSectionResult)
            .where(HydraulicTaskSectionResult.task_id == v4.id)
            .order_by(
                HydraulicTaskSectionResult.section_code,
                HydraulicTaskSectionResult.time_seconds,
            )
        ).all()
        legacy_by_code: dict[str, dict[float, SimulationResult]] = defaultdict(dict)
        native_by_code: dict[str, dict[float, HydraulicTaskSectionResult]] = defaultdict(dict)
        for item in legacy:
            legacy_by_code[item.section_code][item.time_seconds] = item
        for item in native:
            native_by_code[item.section_code][item.time_seconds] = item
        rows = []
        for code in sorted(legacy_by_code.keys() & native_by_code.keys()):
            legacy_rows = legacy_by_code[code]
            native_rows = native_by_code[code]
            times = sorted(legacy_rows.keys() & native_rows.keys())
            if not times:
                continue
            h_delta = [
                native_rows[time].water_level_m - legacy_rows[time].water_level
                for time in times
            ]
            q_delta = [
                native_rows[time].flow_m3s - legacy_rows[time].flow for time in times
            ]
            legacy_peak = max(times, key=lambda time: legacy_rows[time].flow)
            native_peak = max(times, key=lambda time: native_rows[time].flow_m3s)
            rows.append(
                V4ShadowSectionDelta(
                    section_code=code,
                    time_seconds=times,
                    water_level_delta_m=h_delta,
                    flow_delta_m3s=q_delta,
                    maximum_absolute_water_level_delta_m=max(map(abs, h_delta)),
                    maximum_absolute_flow_delta_m3s=max(map(abs, q_delta)),
                    peak_flow_time_delta_seconds=native_peak - legacy_peak,
                )
            )
        status = "ready" if rows else "not_ready"
        group_status = "ready" if rows else "failed"
    _persist_group_status(session, group, group_status)
    return V4ShadowComparison(
        group_id=group.id,
        status=status,
        diagnostic_disclaimer=_DISCLAIMER,
        v3_task_id=v3.id if v3 is not None else None,
        v4_task_id=v4.id if v4 is not None else None,
        sections=rows,
    )


__all__ = ["compare_shadow_pair", "create_shadow_pair"]
