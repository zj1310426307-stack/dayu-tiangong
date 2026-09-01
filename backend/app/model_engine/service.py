"""Persist Standard 1D tasks while delegating numerics to external engines."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from hmac import compare_digest
from math import isclose, isfinite
from time import monotonic
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.gis.models import (
    HydraulicTaskSectionResult,
    SimulationCase,
    SimulationTask,
)
from app.hydraulic.models import HydraulicCrossSection, HydraulicProductionRun
from app.hydraulic.production.gate import assert_production_gate
from app.model_engine.hydraulic_1d_service import (
    build_hydraulic_1d_model,
    freeze_hydraulic_1d_input,
)
from app.model_engine.schemas import (
    Hydraulic1DPreviewResponse,
    Hydraulic1DReadinessResponse,
    ResultSectionOption,
    SimulationResultResponse,
    SimulationTaskCreate,
    SimulationTaskRecord,
)
from model.build_identity import (
    BuildIdentityError,
    RuntimeBuildIdentity,
    assert_runtime_build_matches,
    current_runtime_build_identity,
)
from model.hydraulic_1d.contracts import (
    HYDRAULIC_1D_INPUT_SCHEMA,
    Hydraulic1DModel,
    HydraulicResult,
)
from model.hydraulic_1d import (
    DEFAULT_HYDRAULIC_1D_ENGINE_ID,
    DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
)
from model.hydraulic_1d.engine import Hydraulic1DExecutionContext
from model.hydraulic_1d.errors import (
    Hydraulic1DCancelled,
    Hydraulic1DError,
    Hydraulic1DValidationError,
)
from model.hydraulic_1d.factory import create_hydraulic_1d_engine
from model.hydraulic_1d.registry import task_engine_provenance
from model.provenance import snapshot_hash


class TaskNotFoundError(LookupError):
    """Raised when a task or referenced Simulation Case does not exist."""


class TaskStateError(RuntimeError):
    """Raised when a request conflicts with immutable task lifecycle state."""


def parse_frozen_task_model(task: SimulationTask) -> Hydraulic1DModel:
    """Verify the persisted snapshot digest before exposing it to any runtime."""

    if not isinstance(task.input_snapshot, Mapping) or not isinstance(
        task.input_snapshot_hash, str
    ):
        raise Hydraulic1DValidationError(
            "DAYU_HYDRAULIC_1D_SNAPSHOT_INTEGRITY_ERROR",
            "task snapshot or digest is missing",
            field_path="simulation_task.input_snapshot",
        )
    observed = snapshot_hash(task.input_snapshot)
    if not compare_digest(observed, task.input_snapshot_hash):
        raise Hydraulic1DValidationError(
            "DAYU_HYDRAULIC_1D_SNAPSHOT_INTEGRITY_ERROR",
            "task snapshot digest does not match its frozen input",
            field_path="simulation_task.input_snapshot_hash",
        )
    return Hydraulic1DModel.parse_snapshot(task.input_snapshot)


def _snapshot_summary(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return a compact solver-neutral summary safe for task listings."""

    metadata = snapshot.get("metadata")
    return {
        "schema_version": snapshot.get("schema_version"),
        "simulation_id": snapshot.get("simulation_id"),
        "scenario_id": snapshot.get("scenario_id"),
        "dataset_version_id": (
            metadata.get("dataset_version_id") if isinstance(metadata, Mapping) else None
        ),
        "branch_count": len(snapshot.get("branches", [])),
        "section_count": len(snapshot.get("cross_sections", [])),
        "boundary_count": len(snapshot.get("boundaries", [])),
        "structure_count": len(snapshot.get("structures", [])),
    }


def retry_block_reason(task: SimulationTask) -> str | None:
    """Explain why an immutable task may or may not enter a manual retry."""

    if task.input_schema_version != HYDRAULIC_1D_INPUT_SCHEMA:
        return "LEGACY_ENGINE_RETIRED: historical custom-solver tasks cannot be retried"
    if task.status == "success":
        return "successful tasks are immutable; create a new task to recompute"
    if task.status not in {"failed", "cancelled"}:
        return "only failed or cancelled tasks can be retried"
    if task.active_execution_token is not None:
        return "an execution lease is still active"
    return None


def _record(task: SimulationTask) -> SimulationTaskRecord:
    """Convert one ORM entity to the public task contract."""

    record = SimulationTaskRecord.model_validate(task)
    if isinstance(task.input_snapshot, Mapping):
        record.snapshot_summary = _snapshot_summary(task.input_snapshot)
    record.retry_block_reason = retry_block_reason(task)
    record.retry_eligible = record.retry_block_reason is None
    return record


def _task_config(payload: SimulationTaskCreate) -> dict[str, Any]:
    """Keep only execution-neutral overrides in the immutable model builder input."""

    return payload.model_dump(
        exclude={"case_id", "engine", "input_schema_version"},
        exclude_none=True,
    )


def build_task_entity(session: Session, payload: SimulationTaskCreate) -> SimulationTask:
    """Freeze and stage one Standard 1D task without committing the transaction."""

    simulation_case = session.get(SimulationCase, payload.case_id)
    if simulation_case is None:
        raise TaskNotFoundError("simulation case does not exist")
    config = _task_config(payload)
    try:
        build_identity = current_runtime_build_identity()
        snapshot, digest = freeze_hydraulic_1d_input(session, payload.case_id, config)
    except LookupError as exc:
        raise TaskNotFoundError(str(exc)) from exc
    except (BuildIdentityError, Hydraulic1DError, ValueError) as exc:
        raise TaskStateError(f"model input is not ready: {exc}") from exc
    task = SimulationTask(
        case_id=payload.case_id,
        dataset_version_id=simulation_case.dataset_version_id,
        config=config,
        input_schema_version=HYDRAULIC_1D_INPUT_SCHEMA,
        input_snapshot=snapshot,
        input_snapshot_hash=digest,
        engine_version=build_identity.engine_version,
        engine_commit=build_identity.engine_commit,
        solver_build_id=build_identity.solver_build_id,
        build_mode=build_identity.build_mode,
        build_verified=build_identity.verified,
        execution_phase="validating_snapshot",
        artifact_status="none",
        **task_engine_provenance(),
    )
    session.add(task)
    session.flush()
    return task


def create_task(session: Session, payload: SimulationTaskCreate) -> SimulationTaskRecord:
    """Create a pending task whose physical input is already immutable."""

    task = build_task_entity(session, payload)
    session.commit()
    session.refresh(task)
    return _record(task)


def list_tasks(
    session: Session, dataset_version_id: int | None = None
) -> list[SimulationTaskRecord]:
    """Return newest task records, optionally scoped to one Dataset Version."""

    statement = select(SimulationTask)
    if dataset_version_id is not None:
        statement = statement.where(SimulationTask.dataset_version_id == dataset_version_id)
    tasks = session.scalars(statement.order_by(SimulationTask.id.desc())).all()
    return [_record(task) for task in tasks]


def get_task(session: Session, task_id: int) -> SimulationTaskRecord | None:
    """Read a task without mutating lifecycle state."""

    task = session.get(SimulationTask, task_id)
    return _record(task) if task is not None else None


def manual_retry_reset_values(task: SimulationTask) -> dict[str, object]:
    """Reset mutable runtime state while preserving frozen model/build identity."""

    return {
        "status": "queued",
        "progress": 0,
        "cancel_requested": False,
        "worker_id": None,
        "queue_job_id": None,
        "delivery_attempt_count": 0,
        "last_delivery_time": None,
        "queued_time": datetime.now(UTC),
        "start_time": None,
        "end_time": None,
        "heartbeat_time": None,
        "execution_phase": None,
        "active_execution_token": None,
        "last_execution_token": None,
        "artifact_status": "none",
        "error_message": None,
        "diagnostics": None,
        "result_path": None,
        "last_infrastructure_error": None,
        "manual_retry_count": task.manual_retry_count + 1,
        "retry_reason": task.error_message,
    }


def reset_task_for_manual_retry(session: Session, task: SimulationTask) -> SimulationTask:
    """CAS-reset one failed/cancelled Standard 1D task for redelivery."""

    reason = retry_block_reason(task)
    if reason is not None:
        raise TaskStateError(reason)
    result = session.execute(
        update(SimulationTask)
        .where(
            SimulationTask.id == task.id,
            SimulationTask.status == task.status,
            SimulationTask.active_execution_token.is_(None),
            SimulationTask.input_schema_version == HYDRAULIC_1D_INPUT_SCHEMA,
        )
        .values(**manual_retry_reset_values(task))
    )
    if result.rowcount != 1:
        session.rollback()
        raise TaskStateError("task state changed while preparing manual retry")
    session.commit()
    session.expire_all()
    current = session.get(SimulationTask, task.id)
    if current is None:
        raise TaskNotFoundError("simulation task does not exist")
    return current


def _runtime_readiness(case_id: int) -> tuple[bool, str, dict[str, object]]:
    """Return the configured external runtime status without doing work."""

    del case_id
    engine = create_hydraulic_1d_engine()
    available, detail = engine.availability()
    return available, detail, engine.runtime_provenance()


def _blocker(exc: Exception) -> dict[str, Any]:
    """Normalize mapping failures into stable API diagnostics."""

    if isinstance(exc, Hydraulic1DValidationError):
        return {"code": exc.code, "field_path": exc.field_path, "message": str(exc)}
    return {
        "code": "DAYU_HYDRAULIC_1D_NOT_READY",
        "field_path": "simulation_case",
        "message": str(exc),
    }


def assess_readiness(
    session: Session,
    case_id: int,
    task_config: Mapping[str, Any] | None = None,
) -> Hydraulic1DReadinessResponse:
    """Validate authoritative mapping and report runtime availability independently."""

    runtime_available, runtime_detail, runtime_identity = _runtime_readiness(case_id)
    blockers: list[dict[str, Any]] = []
    model: Hydraulic1DModel | None = None
    try:
        model = build_hydraulic_1d_model(session, case_id, task_config or {})
    except (LookupError, Hydraulic1DError, ValueError) as exc:
        blockers.append(_blocker(exc))
    if not runtime_available:
        blockers.append(
            {
                "code": "MASCARET_RUNTIME_NOT_AVAILABLE",
                "field_path": "runtime",
                "message": runtime_detail,
            }
        )
    summary = None
    if model is not None:
        summary = _snapshot_summary(model.model_dump(mode="json"))
    return Hydraulic1DReadinessResponse(
        case_id=case_id,
        ready=model is not None and runtime_available,
        runtime_available=runtime_available,
        runtime_detail=runtime_detail,
        runtime_identity=runtime_identity,
        blockers=blockers,
        warnings=(
            [
                {
                    "code": "MASCARET_STRUCTURES_UNSUPPORTED",
                    "message": (
                        "Gates and pumps are rejected until their business semantics "
                        "and MASCARET mapping have passed real-runtime benchmarks."
                    ),
                }
            ]
            if model is not None
            else []
        ),
        input_summary=summary,
    )


def preview_model(session: Session, payload: SimulationTaskCreate) -> Hydraulic1DPreviewResponse:
    """Return the exact unified snapshot without creating a task or workspace."""

    config = _task_config(payload)
    readiness = assess_readiness(session, payload.case_id, config)
    try:
        snapshot, digest = freeze_hydraulic_1d_input(session, payload.case_id, config)
    except (LookupError, Hydraulic1DError, ValueError):
        return Hydraulic1DPreviewResponse(readiness=readiness)
    return Hydraulic1DPreviewResponse(
        readiness=readiness,
        snapshot_hash=digest,
        snapshot=snapshot,
    )


def _validate_result(task: SimulationTask, result: HydraulicResult) -> None:
    """Reject cross-task, wrong-engine, empty, duplicate, or non-finite output."""

    snapshot = parse_frozen_task_model(task)
    expected = {
        "simulation_id": snapshot.simulation_id,
        "scenario_id": snapshot.scenario_id,
        "engine": DEFAULT_HYDRAULIC_1D_ENGINE_ID,
        "engine_version": DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
    }
    observed = {
        "simulation_id": result.simulation_id,
        "scenario_id": result.scenario_id,
        "engine": result.engine,
        "engine_version": result.engine_version,
    }
    mismatches = [
        f"{key}: expected={value!r}, actual={observed[key]!r}"
        for key, value in expected.items()
        if observed[key] != value
    ]
    if mismatches:
        raise ValueError("hydraulic result identity mismatch: " + "; ".join(mismatches))
    if not result.records:
        raise ValueError("hydraulic result contains no records")
    section_by_id = {item.id: item for item in snapshot.cross_sections}
    branch_ids = {item.id for item in snapshot.branches}
    seen: set[tuple[str, float]] = set()
    times_by_section: dict[str, set[float]] = {item.id: set() for item in snapshot.cross_sections}
    for record in result.records:
        section = section_by_id.get(record.cross_section_id)
        if section is None or record.branch_id not in branch_ids:
            raise ValueError("hydraulic result references an unknown section or branch")
        record_identity = {
            "simulation_id": record.simulation_id,
            "scenario_id": record.scenario_id,
            "engine": record.engine,
            "engine_version": record.engine_version,
        }
        if record_identity != expected:
            raise ValueError("hydraulic result record identity differs from its result envelope")
        if record.branch_id != section.branch_id or not isclose(
            record.chainage_m,
            section.chainage_m,
            rel_tol=0.0,
            abs_tol=max(1e-6, abs(section.chainage_m) * 1e-10),
        ):
            raise ValueError("hydraulic result Section branch/chainage identity mismatch")
        if isinstance(record.timestamp, datetime):
            raise ValueError("MASCARET result timestamps must be simulation seconds")
        timestamp = float(record.timestamp)
        if timestamp < 0.0 or timestamp > snapshot.settings.duration_seconds + 1e-9:
            raise ValueError("hydraulic result timestamp lies outside the frozen duration")
        key = (record.cross_section_id, timestamp)
        if key in seen:
            raise ValueError("hydraulic result contains a duplicate section/timestamp")
        seen.add(key)
        times_by_section[record.cross_section_id].add(timestamp)
        numeric = (
            timestamp,
            record.chainage_m,
            record.water_level_m,
            record.depth_m,
            record.discharge_m3s,
            record.velocity_m_s,
            record.flow_area_m2,
        )
        if not all(isfinite(float(value)) for value in numeric):
            raise ValueError("hydraulic result contains a non-finite required value")
    reference_times = next(iter(times_by_section.values()))
    if not reference_times or any(times != reference_times for times in times_by_section.values()):
        raise ValueError("hydraulic result does not cover every Section on one time axis")
    observed_times = sorted(reference_times)
    expected_times = snapshot.settings.expected_output_times()
    time_tolerance = max(1e-6, snapshot.settings.output_interval_seconds * 1e-9)
    if len(observed_times) != len(expected_times) or any(
        not isclose(observed, expected, rel_tol=0.0, abs_tol=time_tolerance)
        for observed, expected in zip(observed_times, expected_times)
    ):
        raise ValueError("hydraulic result has a truncated or irregular output time axis")


def persist_hydraulic_1d_result(
    session: Session,
    task: SimulationTask,
    result: HydraulicResult,
    *,
    executed_build_identity: RuntimeBuildIdentity | None = None,
) -> SimulationTaskRecord:
    """Atomically replace authoritative Section rows and mark one task successful."""

    persistence_started = monotonic()
    if task.status not in {"running", "pending"}:
        raise TaskStateError("only an active task can persist a result")
    if task.input_schema_version != HYDRAULIC_1D_INPUT_SCHEMA:
        raise TaskStateError("LEGACY_ENGINE_RETIRED")
    _validate_result(task, result)
    build_identity = executed_build_identity or assert_runtime_build_matches(
        expected_engine_version=task.engine_version,
        expected_engine_commit=task.engine_commit,
        expected_solver_build_id=task.solver_build_id,
        expected_build_mode=task.build_mode,
        expected_verified=task.build_verified,
        expected_registry_hash=task.registry_hash,
    )
    section_rows = session.scalars(
        select(HydraulicCrossSection).where(
            HydraulicCrossSection.dataset_version_id == task.dataset_version_id
        )
    ).all()
    sections = {str(item.id): item for item in section_rows}
    session.execute(
        delete(HydraulicTaskSectionResult).where(HydraulicTaskSectionResult.task_id == task.id)
    )
    for record in result.records:
        section = sections.get(record.cross_section_id)
        if section is None or str(section.branch_id) != record.branch_id:
            raise ValueError("result Section identity is absent from the task Dataset Version")
        assert not isinstance(record.timestamp, datetime)
        session.add(
            HydraulicTaskSectionResult(
                task_id=task.id,
                dataset_version_id=task.dataset_version_id,
                hydraulic_cross_section_id=section.id,
                section_code=section.section_code,
                branch_id=section.branch_id,
                chainage_m=float(record.chainage_m),
                time_seconds=float(record.timestamp),
                water_level_m=float(record.water_level_m),
                depth_m=float(record.depth_m),
                flow_m3s=float(record.discharge_m3s),
                velocity_m_s=float(record.velocity_m_s),
                flow_area_m2=float(record.flow_area_m2),
                wet_area_m2=(float(record.wet_area_m2) if record.wet_area_m2 is not None else None),
                hydraulic_radius_m=(
                    float(record.hydraulic_radius_m)
                    if record.hydraulic_radius_m is not None
                    else None
                ),
                top_width_m=(float(record.top_width_m) if record.top_width_m is not None else None),
                froude_number=(
                    float(record.froude_number) if record.froude_number is not None else None
                ),
                control_volume_m3=None,
            )
        )
    task.status = "success"
    task.progress = 100
    task.execution_phase = "complete"
    task.error_message = None
    task.end_time = datetime.now(UTC)
    task.heartbeat_time = task.end_time
    task.result_path = f"database://hydraulic_task_section_result/{task.id}"
    # Flush the authoritative result rows so the diagnostic includes database
    # serialization and insert work, while the surrounding commit stays atomic.
    session.flush()
    persistence_seconds = monotonic() - persistence_started
    task.diagnostics = {
        **result.diagnostics,
        "persistence_seconds": persistence_seconds,
        "engine": result.engine,
        "engine_version": result.engine_version,
        "result_schema_version": result.schema_version,
        "record_count": len(result.records),
        "build_identity": build_identity.provenance(),
    }
    production_runs = session.scalars(
        select(HydraulicProductionRun).where(HydraulicProductionRun.task_id == task.id)
    ).all()
    water_balance = result.diagnostics.get("water_balance")
    nested_balance = water_balance if isinstance(water_balance, Mapping) else {}
    mass_balance = result.diagnostics.get(
        "network_mass_balance_residual",
        nested_balance.get("relative_balance_residual"),
    )
    normalized_mass_balance = (
        abs(float(mass_balance))
        if isinstance(mass_balance, (int, float))
        and not isinstance(mass_balance, bool)
        and isfinite(float(mass_balance))
        else None
    )
    for production_run in production_runs:
        production_run.runtime_provenance_json = {
            "task_id": task.id,
            "result_schema_version": result.schema_version,
            "engine": result.engine,
            "engine_version": result.engine_version,
            "record_count": len(result.records),
            "build_identity": build_identity.provenance(),
        }
        production_run.mass_balance_relative_error = normalized_mass_balance
    session.commit()
    session.refresh(task)
    return _record(task)


def _fail_sync_task(session: Session, task_id: int, exc: Exception) -> SimulationTaskRecord:
    """Persist a synchronous terminal error as durable evidence."""

    session.rollback()
    task = session.get(SimulationTask, task_id)
    if task is None:
        raise TaskNotFoundError("simulation task does not exist") from exc
    task.status = "cancelled" if isinstance(exc, Hydraulic1DCancelled) else "failed"
    task.progress = 100
    task.execution_phase = "finalizing"
    task.error_message = str(exc)[:4000]
    task.end_time = datetime.now(UTC)
    session.commit()
    session.refresh(task)
    return _record(task)


def run_task(session: Session, task_id: int) -> SimulationTaskRecord:
    """Run a pending task synchronously only for explicitly enabled diagnostics."""

    task = session.get(SimulationTask, task_id)
    if task is None:
        raise TaskNotFoundError("simulation task does not exist")
    if task.status != "pending":
        raise TaskStateError("only a pending task can be run")
    if task.input_schema_version != HYDRAULIC_1D_INPUT_SCHEMA:
        raise TaskStateError("LEGACY_ENGINE_RETIRED")
    task.status = "running"
    task.progress = 5
    task.start_time = datetime.now(UTC)
    task.execution_phase = "validating_snapshot"
    session.commit()
    try:
        identity = assert_runtime_build_matches(
            expected_engine_version=task.engine_version,
            expected_engine_commit=task.engine_commit,
            expected_solver_build_id=task.solver_build_id,
            expected_build_mode=task.build_mode,
            expected_verified=task.build_verified,
            expected_registry_hash=task.registry_hash,
        )
        model = parse_frozen_task_model(task)
        assert_production_gate(task.config, model, str(task.input_snapshot_hash or ""))
        engine = create_hydraulic_1d_engine()

        def progress(value: float, details: dict[str, Any]) -> None:
            task.progress = min(99, max(task.progress, int(value)))
            task.execution_phase = str(details.get("phase", "running"))[:32]
            task.heartbeat_time = datetime.now(UTC)
            session.commit()

        result = engine.run(
            model,
            Hydraulic1DExecutionContext(
                job_id=f"sync-{task.id}",
                cancel_check=lambda: bool(task.cancel_requested),
                progress_callback=progress,
            ),
        )
        return persist_hydraulic_1d_result(session, task, result, executed_build_identity=identity)
    except Exception as exc:
        return _fail_sync_task(session, task_id, exc)


def get_result(
    session: Session,
    task_id: int,
    section_id: int | None = None,
) -> SimulationResultResponse:
    """Read aligned unified Section series from the authoritative result table."""

    task = session.get(SimulationTask, task_id)
    if task is None:
        raise TaskNotFoundError("simulation task does not exist")
    if task.status != "success":
        raise TaskStateError("task result is available only after success")
    if task.input_schema_version != HYDRAULIC_1D_INPUT_SCHEMA:
        raise TaskStateError("LEGACY_ENGINE_RETIRED")
    options_query = (
        select(HydraulicTaskSectionResult)
        .where(HydraulicTaskSectionResult.task_id == task_id)
        .order_by(
            HydraulicTaskSectionResult.chainage_m,
            HydraulicTaskSectionResult.hydraulic_cross_section_id,
            HydraulicTaskSectionResult.time_seconds,
        )
    )
    all_rows = list(session.scalars(options_query).all())
    if not all_rows:
        raise TaskStateError("successful task has no authoritative Section result")
    option_by_id: dict[int, ResultSectionOption] = {}
    for row in all_rows:
        option_by_id.setdefault(
            row.hydraulic_cross_section_id,
            ResultSectionOption(
                section_id=row.hydraulic_cross_section_id,
                section_code=row.section_code,
                branch_id=row.branch_id,
                chainage_m=row.chainage_m,
            ),
        )
    selected_id = section_id if section_id is not None else next(iter(option_by_id))
    if selected_id not in option_by_id:
        raise TaskNotFoundError("selected Cross Section has no result for this task")
    rows = [row for row in all_rows if row.hydraulic_cross_section_id == selected_id]
    rows.sort(key=lambda item: item.time_seconds)
    snapshot = parse_frozen_task_model(task)
    option = option_by_id[selected_id]
    return SimulationResultResponse(
        task_id=task.id,
        status=task.status,
        simulation_id=snapshot.simulation_id,
        scenario_id=snapshot.scenario_id,
        engine=DEFAULT_HYDRAULIC_1D_ENGINE_ID,
        engine_version=DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
        section_id=option.section_id,
        section_code=option.section_code,
        branch_id=option.branch_id,
        chainage_m=option.chainage_m,
        time=[row.time_seconds for row in rows],
        water_level=[row.water_level_m for row in rows],
        depth=[row.depth_m for row in rows],
        flow=[row.flow_m3s for row in rows],
        velocity=[row.velocity_m_s for row in rows],
        flow_area=[row.flow_area_m2 for row in rows],
        wet_area=[row.wet_area_m2 for row in rows],
        hydraulic_radius=[row.hydraulic_radius_m for row in rows],
        top_width=[row.top_width_m for row in rows],
        froude_number=[row.froude_number for row in rows],
        available_sections=list(option_by_id.values()),
        diagnostics=task.diagnostics,
    )


__all__ = [
    "SimulationTask",
    "TaskNotFoundError",
    "TaskStateError",
    "_record",
    "assess_readiness",
    "build_task_entity",
    "create_task",
    "get_result",
    "get_task",
    "list_tasks",
    "persist_hydraulic_1d_result",
    "parse_frozen_task_model",
    "preview_model",
    "reset_task_for_manual_retry",
    "retry_block_reason",
    "run_task",
]
