"""Persist hydraulic task state while delegating all numerics to ``model/``."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import math
from os import getenv
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.gis.models import (
    DispatchEvent,
    DispatchRun,
    JunctionResult,
    SimulationCase,
    SimulationResult,
    SimulationTask,
    StructureResult,
)
from app.model_engine.schemas import (
    ResultSectionOption,
    SimulationResultResponse,
    SimulationTaskCreate,
    SimulationTaskRecord,
)
from app.model_engine.provenance import ENGINE_VERSION, freeze_task_input, snapshot_summary
from model import HydraulicEngine
from model.core.errors import HydraulicCancelledError


class TaskNotFoundError(LookupError):
    """Raised when a task or its referenced simulation case does not exist."""


class TaskStateError(RuntimeError):
    """Raised when the requested operation is incompatible with task state."""


def _v3_result_identity_maps(
    task: SimulationTask,
) -> tuple[dict[int, int] | None, dict[int, int] | None, set[int] | None]:
    """Return hydraulic-to-public result identities from the frozen v3 evidence.

    The solver intentionally uses authoritative hydraulic node and section IDs.
    Existing result tables still reference the public compatibility projection,
    so persistence must use the verified bridge frozen with the task instead of
    assuming that independently allocated integer IDs happen to match.
    """

    snapshot = task.input_snapshot
    schema_version = (
        snapshot.get("schema_version") if isinstance(snapshot, Mapping) else None
    ) or task.input_schema_version
    if schema_version != "dayu.model-input.v3":
        return None, None, None
    if not isinstance(snapshot, Mapping):
        raise ValueError("model-input.v3 task has no frozen object snapshot")
    compatibility = snapshot.get("compatibility_mapping")
    if not isinstance(compatibility, Mapping):
        raise ValueError(
            "model-input.v3 result persistence requires compatibility_mapping"
        )

    def reverse_mapping(
        collection_name: str,
        legacy_field: str,
        hydraulic_field: str,
    ) -> dict[int, int]:
        rows = compatibility.get(collection_name)
        if not isinstance(rows, list):
            raise ValueError(
                f"model-input.v3 compatibility_mapping.{collection_name} must be an array"
            )
        result: dict[int, int] = {}
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise ValueError(
                    f"compatibility_mapping.{collection_name}[{index}] must be an object"
                )
            legacy_id = row.get(legacy_field)
            hydraulic_id = row.get(hydraulic_field)
            if (
                isinstance(legacy_id, bool)
                or not isinstance(legacy_id, int)
                or legacy_id <= 0
                or isinstance(hydraulic_id, bool)
                or not isinstance(hydraulic_id, int)
                or hydraulic_id <= 0
            ):
                raise ValueError(
                    f"compatibility_mapping.{collection_name}[{index}] has invalid IDs"
                )
            previous = result.get(hydraulic_id)
            if previous is not None and previous != legacy_id:
                raise ValueError(
                    f"hydraulic {collection_name} identity {hydraulic_id} maps to "
                    "multiple public IDs"
                )
            result[hydraulic_id] = legacy_id
        return result

    node_ids = reverse_mapping(
        "river_nodes", "legacy_river_node_id", "hydraulic_node_id"
    )
    section_ids = reverse_mapping(
        "cross_sections",
        "legacy_cross_section_id",
        "hydraulic_cross_section_id",
    )
    branches = snapshot.get("branches")
    if not isinstance(branches, list):
        raise ValueError("model-input.v3 branches must be an array for result persistence")
    legacy_river_ids: set[int] = set()
    for index, branch in enumerate(branches):
        legacy_id = branch.get("legacy_river_id") if isinstance(branch, Mapping) else None
        if isinstance(legacy_id, bool) or not isinstance(legacy_id, int) or legacy_id <= 0:
            raise ValueError(
                f"model-input.v3 branch {index} has no public river identity for results"
            )
        legacy_river_ids.add(legacy_id)
    return section_ids, node_ids, legacy_river_ids


def _public_result_id(
    hydraulic_id: int,
    identities: dict[int, int] | None,
    label: str,
) -> int:
    """Resolve one v3 result identity or retain the established v1/v2 ID."""

    if identities is None:
        return hydraulic_id
    public_id = identities.get(hydraulic_id)
    if public_id is None:
        raise ValueError(
            f"model-input.v3 result {label} {hydraulic_id} has no verified public mapping"
        )
    return public_id


def _validate_engine_result_for_persistence(engine_result: Any) -> None:
    """Reject non-finite or materially unbalanced results before marking success."""

    payload = engine_result.to_dict()

    def require_finite(value: Any, path: str) -> None:
        if isinstance(value, bool) or value is None or isinstance(value, str):
            return
        if isinstance(value, (int, float)):
            if not math.isfinite(float(value)):
                raise ValueError(f"engine result contains non-finite value at {path}")
            return
        if isinstance(value, Mapping):
            for key, child in value.items():
                require_finite(child, f"{path}.{key}")
            return
        if isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                require_finite(child, f"{path}[{index}]")

    require_finite(payload, "result")
    if engine_result.schema_version != "dayu.hydraulic-result.v2":
        return
    balance = engine_result.water_balance
    if not isinstance(balance, Mapping):
        raise ValueError("hydraulic-result.v2 requires a water_balance object")
    status = balance.get("status")
    relative = balance.get("relative_balance_residual")
    if isinstance(relative, bool) or not isinstance(relative, (int, float)):
        raise ValueError("water_balance.relative_balance_residual must be numeric")
    if status not in {"pass", "warning", "fail"}:
        raise ValueError("water_balance.status is invalid")
    if status == "fail" or float(relative) >= 0.01:
        raise ValueError(
            "engine result failed the water-balance persistence gate: "
            f"status={status}, relative_residual={float(relative):.6g}"
        )


def _record(task: SimulationTask) -> SimulationTaskRecord:
    """Convert one ORM entity to the public Pydantic record."""

    record = SimulationTaskRecord.model_validate(task)
    record.snapshot_summary = (
        snapshot_summary(task.input_snapshot) if task.input_snapshot is not None else None
    )
    return record


def create_task(session: Session, payload: SimulationTaskCreate) -> SimulationTaskRecord:
    """创建任务时立即冻结全部输入，后续业务数据修改不再影响本任务。"""

    if session.get(SimulationCase, payload.case_id) is None:
        raise TaskNotFoundError("simulation case does not exist")
    config = payload.model_dump(
        exclude={"case_id", "input_schema_version"}, exclude_none=True
    )
    engine_commit = getenv("ENGINE_COMMIT", "uncommitted")
    try:
        snapshot, digest = freeze_task_input(
            session,
            payload.case_id,
            config,
            schema_version=payload.input_schema_version,
            engine_commit=engine_commit,
        )
    except LookupError as exc:
        raise TaskNotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise TaskStateError(f"model input is not ready: {exc}") from exc
    task = SimulationTask(
        case_id=payload.case_id,
        config=config,
        input_schema_version=payload.input_schema_version,
        input_snapshot=snapshot,
        input_snapshot_hash=digest,
        engine_version=ENGINE_VERSION,
        engine_commit=engine_commit,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return _record(task)


def list_tasks(
    session: Session, dataset_version_id: int | None = None
) -> list[SimulationTaskRecord]:
    """Return newest tasks, optionally restricted to one Dataset Version."""

    statement = select(SimulationTask)
    if dataset_version_id is not None:
        statement = statement.join(
            SimulationCase, SimulationTask.case_id == SimulationCase.id
        ).where(SimulationCase.dataset_version_id == dataset_version_id)
    tasks = session.scalars(statement.order_by(SimulationTask.id.desc())).all()
    return [_record(task) for task in tasks]


def get_task(session: Session, task_id: int) -> SimulationTaskRecord | None:
    """Return a task without changing its lifecycle."""

    task = session.get(SimulationTask, task_id)
    return _record(task) if task is not None else None


def run_task(session: Session, task_id: int) -> SimulationTaskRecord:
    """兼容同步执行冻结输入；生产前端必须使用异步入队接口。"""

    task = session.get(SimulationTask, task_id)
    if task is None:
        raise TaskNotFoundError("simulation task does not exist")
    if task.status != "pending":
        raise TaskStateError("only a pending task can be run")

    task.status = "running"
    task.progress = 10
    task.start_time = datetime.now(UTC)
    task.error_message = None
    session.commit()

    try:
        snapshot = task.input_snapshot
        if snapshot is None:
            raise TaskStateError("legacy task has no frozen input snapshot")
        task.progress = 30
        session.commit()

        engine_result = HydraulicEngine().run(snapshot, task.config)
        task.progress = 80
        session.flush()

        return persist_engine_result(session, task, engine_result)
    except HydraulicCancelledError as exc:
        session.rollback()
        cancelled = session.get(SimulationTask, task_id)
        if cancelled is None:
            raise
        cancelled.status = "cancelled"
        cancelled.progress = 100
        cancelled.error_message = str(exc)
        cancelled.end_time = datetime.now(UTC)
        session.commit()
        return _record(cancelled)
    except Exception as exc:
        # The state transition is itself valuable evidence, so keep failures
        # durable while leaving the numerical engine free to raise rich errors.
        session.rollback()
        failed_task = session.get(SimulationTask, task_id)
        if failed_task is None:
            raise
        failed_task.status = "failed"
        failed_task.progress = 100
        failed_task.error_message = str(exc)[:4000]
        failed_task.end_time = datetime.now(UTC)
        session.commit()
        session.refresh(failed_task)
        return _record(failed_task)


def persist_engine_result(
    session: Session, task: SimulationTask, engine_result: Any
) -> SimulationTaskRecord:
    """通过唯一入口持久化 v1/v2/v3 结果并完成 success 状态。"""

    _validate_engine_result_for_persistence(engine_result)
    section_identities, node_identities, legacy_river_ids = (
        _v3_result_identity_maps(task)
    )
    # Resolve every foreign-key identity before deleting or adding result rows.
    # This preserves the previous durable result if a frozen v3 bridge is incomplete.
    resolved_section_ids = {
        series.section.id: _public_result_id(
            int(series.section.id), section_identities, "cross-section"
        )
        for series in engine_result.series
    }
    resolved_node_ids = {
        int(item["node_id"]): _public_result_id(
            int(item["node_id"]), node_identities, "river-node"
        )
        for item in engine_result.node_series
    }
    if legacy_river_ids is not None:
        unknown_river_ids = {
            int(series.section.river_id)
            for series in engine_result.series
            if int(series.section.river_id) not in legacy_river_ids
        }
        if unknown_river_ids:
            raise ValueError(
                "model-input.v3 results reference unverified public river IDs: "
                + ", ".join(str(value) for value in sorted(unknown_river_ids))
            )

    session.query(SimulationResult).filter(SimulationResult.task_id == task.id).delete()
    session.query(JunctionResult).filter(JunctionResult.task_id == task.id).delete()
    session.query(StructureResult).filter(StructureResult.task_id == task.id).delete()
    dispatch_run = session.scalar(
        select(DispatchRun).where(DispatchRun.controlled_task_id == task.id)
    )
    if dispatch_run is not None:
        session.query(DispatchEvent).filter(
            DispatchEvent.run_id == dispatch_run.id
        ).delete()
    storage_level = str(task.config.get("storage_level", "full"))
    selected_ids: set[int] = set()
    grouped_series: dict[int, list[Any]] = {}
    for series in engine_result.series:
        grouped_series.setdefault(series.section.river_id, []).append(series)
    for river_series in grouped_series.values():
        ordered = sorted(river_series, key=lambda item: item.section.station)
        if storage_level == "full":
            selected_ids.update(item.section.id for item in ordered)
        elif storage_level == "key_sections":
            selected_ids.update(
                item.section.id
                for item in (ordered[0], ordered[len(ordered) // 2], ordered[-1])
            )
        else:
            selected_ids.add(ordered[0].section.id)
    for series in engine_result.series:
        if series.section.id not in selected_ids:
            continue
        for index, time_seconds in enumerate(series.time):
            session.add(
                SimulationResult(
                    task_id=task.id,
                    section_id=resolved_section_ids[series.section.id],
                    river_id=series.section.river_id, section_code=series.section.code,
                    station=series.section.station, time_seconds=time_seconds,
                    water_level=series.water_level[index], flow=series.flow[index],
                    velocity=series.velocity[index],
                )
            )
    for item in engine_result.node_series:
        session.add(
            JunctionResult(
                task_id=task.id,
                node_id=resolved_node_ids[int(item["node_id"])],
                time_seconds=float(item["time_seconds"]), water_level=float(item["water_level"]),
                inflow=float(item["inflow"]), outflow=float(item["outflow"]),
                source_sink=float(item["source_sink"]),
                balance_residual=float(item["balance_residual"]),
            )
        )
    for item in engine_result.structure_series:
        session.add(
            StructureResult(
                task_id=task.id,
                dispatch_run_id=dispatch_run.id if dispatch_run is not None else None,
                time_seconds=float(item["time_seconds"]),
                structure_type=str(item["structure_type"]), structure_id=int(item["structure_id"]),
                requested_value=item.get("requested_value"), actual_value=item.get("actual_value"),
                flow=float(item["flow"]), upstream_level=item.get("upstream_level"),
                downstream_level=item.get("downstream_level"),
                head_difference=item.get("head_difference"),
                transfer_type=item.get("transfer_type"), power_kw=item.get("power_kw"),
                energy_kwh=item.get("energy_kwh"), regime=item.get("regime"),
                constraint_flags=list(item.get("constraint_flags", [])),
            )
        )
    if dispatch_run is not None:
        for item in engine_result.dispatch_events:
            session.add(
                DispatchEvent(
                    run_id=dispatch_run.id,
                    time_seconds=float(item["time_seconds"]),
                    source_type=str(item["source_type"]),
                    source_id=item.get("source_id"),
                    structure_type=str(item["structure_type"]),
                    structure_id=int(item["structure_id"]),
                    requested_command=dict(item["requested_command"]),
                    applied_command=item.get("applied_command"),
                    outcome=str(item["outcome"]),
                    reason=item.get("reason"),
                )
            )
    task.status = "success"
    task.progress = 100
    task.diagnostics = engine_result.diagnostics
    task.result_path = f"database://simulation_result?task_id={task.id}"
    task.end_time = datetime.now(UTC)
    task.heartbeat_time = datetime.now(UTC)
    session.commit()
    session.refresh(task)
    return _record(task)


def get_result(
    session: Session, task_id: int, section_id: int | None = None
) -> SimulationResultResponse:
    """Return one section series plus all available section choices."""

    task = session.get(SimulationTask, task_id)
    if task is None:
        raise TaskNotFoundError("simulation task does not exist")
    if task.status != "success":
        raise TaskStateError("results are available only for successful tasks")

    option_rows = session.execute(
        select(
            SimulationResult.section_id,
            SimulationResult.section_code,
            SimulationResult.river_id,
            SimulationResult.station,
        )
        .where(SimulationResult.task_id == task_id)
        .distinct()
        .order_by(SimulationResult.river_id, SimulationResult.station)
    ).all()
    options = [
        ResultSectionOption(
            section_id=row.section_id,
            section_code=row.section_code,
            river_id=row.river_id,
            station=row.station,
        )
        for row in option_rows
    ]
    if not options:
        raise TaskStateError("the successful task has no persisted section results")

    selected = next(
        (item for item in options if item.section_id == section_id),
        options[0] if section_id is None else None,
    )
    if selected is None:
        raise TaskNotFoundError("section result does not exist in this task")

    conditions: list[Any] = [
        SimulationResult.task_id == task_id,
        SimulationResult.section_code == selected.section_code,
    ]
    rows = session.scalars(
        select(SimulationResult)
        .where(*conditions)
        .order_by(SimulationResult.time_seconds)
    ).all()
    return SimulationResultResponse(
        task_id=task.id,
        status=task.status,
        section_id=selected.section_id,
        section_code=selected.section_code,
        river_id=selected.river_id,
        station=selected.station,
        time=[row.time_seconds for row in rows],
        water_level=[row.water_level for row in rows],
        flow=[row.flow for row in rows],
        velocity=[row.velocity for row in rows],
        available_sections=options,
        diagnostics=task.diagnostics,
    )
