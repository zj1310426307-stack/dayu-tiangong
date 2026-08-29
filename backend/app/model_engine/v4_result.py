"""Validate and atomically publish native-v4 result rows and stage evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from gzip import GzipFile
from hashlib import sha256
from io import BytesIO
import math
from os import fsync, replace
from pathlib import Path
from typing import Any, Callable, Mapping

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.files import (
    atomic_output_path,
    configured_storage_root,
    resolve_within,
    storage_directory,
)
from app.gis.models import (
    HydraulicTaskArtifact,
    HydraulicTaskControlEvent,
    HydraulicTaskGateResult,
    HydraulicTaskPumpResult,
    HydraulicTaskSectionResult,
    SimulationTask,
)
from app.model_engine.v4_schemas import (
    V4ArtifactManifest,
    V4ResultSummary,
    V4SectionOption,
    V4SectionResultResponse,
)
from app.worker.lifecycle import StaleExecutionError
from model.adapters.v4 import V4RuntimeProjection
from model.build_identity import RuntimeBuildIdentity, current_runtime_build_identity
from model.core.callbacks import check_cancellation
from model.provenance import CANONICALIZATION_ID, canonical_json
from model.solver.registry import D3A_1_CAPABILITY_ID, D3A_2_CAPABILITY_ID


RESULT_SCHEMA_VERSION = "dayu.hydraulic-result.v3"
ARTIFACT_SCHEMA_VERSION = "dayu.hydraulic-stage-evidence.v1"
ARTIFACT_TYPE = "stage-evidence"
ARTIFACT_MEDIA_TYPE = "application/x-ndjson+gzip"


def v4_attempt_staging_storage_key(
    task_id: int,
    execution_token: str,
    artifact_sha256: str,
) -> str:
    """Return the exact token/hash-bound staging key for one execution attempt."""

    if task_id <= 0:
        raise ValueError("native-v4 task id must be positive")
    if not execution_token or len(execution_token) > 64:
        raise ValueError("native-v4 execution token is invalid")
    token_hash = sha256(execution_token.encode("utf-8")).hexdigest()
    return v4_attempt_staging_storage_key_from_hashes(
        task_id,
        token_hash,
        artifact_sha256,
    )


def v4_attempt_staging_storage_key_from_hashes(
    task_id: int,
    execution_token_sha256: str,
    artifact_sha256: str,
) -> str:
    """Rebuild a staging key without retaining or exposing the lease token."""

    if task_id <= 0:
        raise ValueError("native-v4 task id must be positive")
    for value, label in (
        (execution_token_sha256, "execution token"),
        (artifact_sha256, "artifact"),
    ):
        if (
            len(value) != 64
            or value != value.lower()
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError(f"native-v4 {label} sha256 is invalid")
    return (
        "hydraulic-evidence/staging/"
        f"task-{task_id}-attempt-{execution_token_sha256[:24]}-"
        f"{artifact_sha256[:24]}.jsonl.gz"
    )


def _finite_tree(value: Any, path: str = "result") -> None:
    """Reject non-finite numbers anywhere in the numerical result."""

    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ValueError(f"non-finite numerical result at {path}")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _finite_tree(child, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _finite_tree(child, f"{path}[{index}]")


def _strictly_increasing(values: list[float], label: str) -> None:
    """Require an ordered, duplicate-free output axis."""

    if not values or any(right <= left for left, right in zip(values, values[1:])):
        raise ValueError(f"{label} times must be strictly increasing")


def validate_v4_result(
    result: Mapping[str, Any], projection: V4RuntimeProjection
) -> None:
    """Apply D2 quality gates before any previous rows can be replaced."""

    _finite_tree(result)
    if result.get("schema_version") != "dayu.hydraulic-result.mvp":
        raise ValueError("native v4 runtime returned an unexpected result schema")
    water = result.get("water_balance")
    if not isinstance(water, Mapping) or water.get("status") != "pass":
        raise ValueError("native v4 water balance did not pass")
    relative = float(water.get("relative_water_balance_error", math.inf))
    tolerance = float(water.get("tolerance", -math.inf))
    if relative > tolerance:
        raise ValueError("native v4 water-balance error exceeds frozen tolerance")
    sections = result.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("native v4 result has no Section series")
    for section in sections:
        times = [float(item) for item in section.get("time", [])]
        _strictly_increasing(times, f"Section {section.get('section_id')}")
        volumes = section.get("volume_m3")
        if not isinstance(volumes, list) or any(float(item) <= 0.0 for item in volumes):
            raise ValueError("native v4 control volumes must remain positive")
    pumps = result.get("pumps")
    if not isinstance(pumps, list) or len(pumps) != 1:
        raise ValueError("native v4 result requires exactly one Pump series")
    pump = pumps[0]
    pump_times = [float(item) for item in pump.get("time", [])]
    _strictly_increasing(pump_times, "Pump")
    energy = [float(item) for item in pump.get("cumulative_energy_kwh", [])]
    if any(right < left for left, right in zip(energy, energy[1:])):
        raise ValueError("Pump cumulative energy must be monotonic")
    events = result.get("control_events")
    if not isinstance(events, list):
        raise ValueError("native v4 control_events must be an array")
    event_times = [float(item["time"]) for item in events]
    if event_times != sorted(event_times):
        raise ValueError("native v4 event times must be monotonic")
    diagnostics = result.get("diagnostics")
    step_count = int(diagnostics.get("step_count", -1)) if isinstance(diagnostics, Mapping) else -1
    if projection.source.solver_selection.capability_id in {
        D3A_1_CAPABILITY_ID,
        D3A_2_CAPABILITY_ID,
    }:
        maximum_friction = (
            float(diagnostics.get("maximum_friction_number", math.inf))
            if isinstance(diagnostics, Mapping)
            else math.inf
        )
        friction_retries = (
            diagnostics.get("friction_retry_count")
            if isinstance(diagnostics, Mapping)
            else None
        )
        if (
            not 0.0 < maximum_friction <= 0.1 + 1.0e-12
            or not isinstance(friction_retries, int)
            or friction_retries < 0
        ):
            raise ValueError("D3A-1 Manning diagnostics failed their frozen gate")
    gate_evidence = result.get("controlled_gate_coupling_evidence")
    pump_evidence = result.get("pump_coupling_evidence")
    if not isinstance(gate_evidence, list) or len(gate_evidence) != 1:
        raise ValueError("native v4 requires one completed-Gate evidence collection")
    if not isinstance(pump_evidence, list) or len(pump_evidence) != 1:
        raise ValueError("native v4 requires one Pump evidence collection")
    if len(gate_evidence[0].get("stage_evaluations", [])) != 2 * step_count:
        raise ValueError("Gate stage evidence does not align with accepted steps")
    if len(pump_evidence[0].get("stage_evaluations", [])) != 2 * step_count:
        raise ValueError("Pump stage evidence does not align with accepted steps")
    if float(pump_evidence[0].get("maximum_absolute_head_residual_m", math.inf)) > float(
        pump_evidence[0].get("head_residual_tolerance_m", -math.inf)
    ):
        raise ValueError("Pump operating-point residual exceeds its frozen tolerance")
    provenance = result.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("native v4 runtime result has no provenance")
    if provenance.get("input_snapshot_hash") != projection.manifest["runtime_projection_hash"]:
        # The MVP provenance hashes canonical runtime input while the manifest uses
        # its explicit runtime-projection domain. Verify both independently below.
        from model.provenance import snapshot_hash

        if provenance.get("input_snapshot_hash") != snapshot_hash(
            projection.runtime.model_dump(mode="json")
        ):
            raise ValueError("runtime result input hash does not match the projection")
    if provenance.get("mesh_hash") != projection.manifest["mesh_hash"]:
        raise ValueError("runtime result mesh hash does not match the frozen task")
    if provenance.get("solver_policy_hash") != projection.manifest["solver_policy_hash"]:
        raise ValueError("runtime result solver-policy hash does not match the task")


def build_stage_evidence_artifact(
    result: Mapping[str, Any],
    projection: V4RuntimeProjection,
    *,
    cancel_check: object | None = None,
) -> tuple[bytes, int]:
    """Return deterministic canonical JSONL.GZ and its exact record count."""

    records: list[dict[str, Any]] = []
    gate = result["controlled_gate_coupling_evidence"][0]
    for row in gate["stage_evaluations"]:
        check_cancellation(cancel_check, "artifact_gate_stage")
        records.append({"record_type": "gate_stage", "evidence": row})
    pump = result["pump_coupling_evidence"][0]
    for row in pump["stage_evaluations"]:
        check_cancellation(cancel_check, "artifact_pump_stage")
        records.append({"record_type": "pump_stage", "evidence": row})
    for row in result["control_events"]:
        records.append({"record_type": "control_event", "evidence": row})
    records.extend(
        [
            {
                "record_type": "retry_summary",
                "evidence": result["diagnostics"],
            },
            {
                "record_type": "water_balance",
                "evidence": result["water_balance"],
            },
            {
                "record_type": "projection_manifest",
                "evidence": projection.manifest,
            },
        ]
    )
    uncompressed = "".join(canonical_json(record) + "\n" for record in records).encode(
        "utf-8"
    )
    buffer = BytesIO()
    with GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as archive:
        archive.write(uncompressed)
    return buffer.getvalue(), len(records)


def _phase(callback: Callable[[str], None] | None, value: str) -> None:
    if callback is not None:
        callback(value)


def _fault(callback: Callable[[str], None] | None, value: str) -> None:
    """仅供确定性故障注入测试使用；生产调用方不传入。"""

    if callback is not None:
        callback(value)


def _task_diagnostics(
    task: SimulationTask,
    result: Mapping[str, Any],
    projection: V4RuntimeProjection,
    artifact: HydraulicTaskArtifact,
    executed_build_identity: RuntimeBuildIdentity,
    *,
    artifact_status: str,
) -> dict[str, Any]:
    """构造 prepared/published 两阶段共用的完整科学来源。"""

    return {
        "input_schema_version": "dayu.model-input.v4",
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "solver_id": task.solver_id,
        "capability_id": task.capability_id,
        "runtime_adapter_id": task.runtime_adapter_id,
        "input_snapshot_hash": task.input_snapshot_hash,
        "runtime_projection_hash": task.runtime_projection_hash,
        "mesh_hash": task.mesh_hash,
        "solver_policy_hash": task.solver_policy_hash,
        "validation_policy_hash": task.validation_policy_hash,
        "canonicalization_id": CANONICALIZATION_ID,
        "engine_version": task.engine_version,
        "engine_commit": task.engine_commit,
        "solver_build_id": task.solver_build_id,
        "build_mode": task.build_mode,
        "build_verified": task.build_verified,
        "unverified_build": not task.build_verified,
        "runtime_build_identity": {
            "task_requested": {
                "engine_version": task.engine_version,
                "engine_commit": task.engine_commit,
                "solver_build_id": task.solver_build_id,
                "build_mode": task.build_mode,
                "build_verified": task.build_verified,
                "unverified_build": not task.build_verified,
                "registry_hash": task.registry_hash,
            },
            "worker_executed": {
                **executed_build_identity.provenance(),
                "registry_hash": task.registry_hash,
            },
        },
        "numeric_platform": result["provenance"],
        "water_balance": result["water_balance"],
        "diagnostics": result["diagnostics"],
        "capability_scope": list(projection.source.capability_scope),
        "capability_exclusions": list(projection.source.capability_exclusions),
        "case_notes": list(projection.source.case_notes),
        "known_limitations": list(projection.source.known_limitations),
        "artifact_manifest": {
            "artifact_type": artifact.artifact_type,
            "storage_key": artifact.storage_key,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "record_count": artifact.record_count,
            "media_type": artifact.media_type,
            "schema_version": artifact.schema_version,
            "status": artifact_status,
        },
    }


def persist_v4_result(
    session: Session,
    task: SimulationTask,
    engine_result: Any,
    projection: V4RuntimeProjection,
    *,
    execution_token: str,
    executed_build_identity: RuntimeBuildIdentity | None = None,
    cancel_check: object | None = None,
    phase_callback: Callable[[str], None] | None = None,
    fault_hook: Callable[[str], None] | None = None,
) -> SimulationTask:
    """Persist prepared rows, atomically publish the file, then CAS final success."""

    worker_build = executed_build_identity or current_runtime_build_identity()
    if task.status == "success":
        raise ValueError("a successful v4 task cannot be overwritten")
    if (
        task.status != "running"
        or task.cancel_requested
        or task.active_execution_token != execution_token
    ):
        raise StaleExecutionError("native-v4 attempt is not eligible for persistence")
    task_id = int(task.id)
    result = engine_result.to_dict()
    _phase(phase_callback, "serializing")
    validate_v4_result(result, projection)
    artifact_bytes, record_count = build_stage_evidence_artifact(
        result, projection, cancel_check=cancel_check
    )
    artifact_hash = sha256(artifact_bytes).hexdigest()
    dataset_id = int(projection.source.dataset_version.id)
    section_source = {
        int(item.section_id): item for item in projection.source.cross_sections
    }
    gate_source = projection.source.structures.gates[0]
    pump_source = projection.source.structures.pumps[0]
    gate_id = int(gate_source.identity.id)
    pump_id = int(pump_source.identity.id)
    gate_evidence = result["controlled_gate_coupling_evidence"][0][
        "stage_evaluations"
    ]
    gate_by_time: dict[float, Mapping[str, Any]] = {}
    for item in gate_evidence:
        gate_by_time[float(item["evaluation_time"])] = item
    storage_root = storage_directory("hydraulic-evidence")
    filename = f"task-{task.id}-stage-evidence-v1.jsonl.gz"
    storage_key = f"hydraulic-evidence/{filename}"
    staging_key = v4_attempt_staging_storage_key(
        task_id,
        execution_token,
        artifact_hash,
    )
    execution_token_hash = sha256(execution_token.encode("utf-8")).hexdigest()
    staging_root = resolve_within(storage_root, "staging")
    staging_filename = Path(staging_key).name
    staging_target = resolve_within(configured_storage_root(), staging_key)
    canonical_target = resolve_within(configured_storage_root(), storage_key)
    _phase(phase_callback, "persisting")
    with atomic_output_path(staging_root, staging_filename) as (temporary, _target):
        with temporary.open("wb") as handle:
            handle.write(artifact_bytes)
            handle.flush()
            fsync(handle.fileno())
        if sha256(temporary.read_bytes()).hexdigest() != artifact_hash:
            raise ValueError("temporary stage-evidence artifact failed hash verification")
        _fault(fault_hook, "after_artifact_temp_ready")
        check_cancellation(cancel_check, "artifact_pre_persistence")
        for model in (
            HydraulicTaskSectionResult,
            HydraulicTaskGateResult,
            HydraulicTaskPumpResult,
            HydraulicTaskControlEvent,
            HydraulicTaskArtifact,
        ):
            session.query(model).filter(model.task_id == task.id).delete(
                synchronize_session=False
            )
        for section in result["sections"]:
            source = section_source.get(int(section["section_id"]))
            if source is None:
                raise ValueError("result Section has no authoritative v4 identity")
            arrays = (
                section["time"],
                section["water_level"],
                section["flow"],
                section["velocity"],
                section["volume_m3"],
            )
            if len({len(values) for values in arrays}) != 1:
                raise ValueError("result Section arrays are not aligned")
            for index, time_seconds in enumerate(section["time"]):
                check_cancellation(cancel_check, "section_result_batch")
                session.add(
                    HydraulicTaskSectionResult(
                        task_id=task.id,
                        dataset_version_id=dataset_id,
                        hydraulic_cross_section_id=int(source.section_id),
                        section_code=source.section_code,
                        branch_id=int(source.branch_id),
                        chainage_m=float(source.chainage_m),
                        time_seconds=float(time_seconds),
                        water_level_m=float(section["water_level"][index]),
                        flow_m3s=float(section["flow"][index]),
                        velocity_m_s=float(section["velocity"][index]),
                        control_volume_m3=float(section["volume_m3"][index]),
                    )
                )
        gate_series = result["gates"][0]
        for index, time_seconds in enumerate(gate_series["time"]):
            evidence = gate_by_time.get(float(time_seconds))
            if evidence is None:
                raise ValueError("Gate output time has no stage evidence")
            session.add(
                HydraulicTaskGateResult(
                    task_id=task.id,
                    dataset_version_id=dataset_id,
                    canonical_gate_id=gate_id,
                    time_seconds=float(time_seconds),
                    opening_m=float(gate_series["opening"][index]),
                    flow_m3s=float(gate_series["flow"][index]),
                    upstream_stage_m=float(evidence["upstream_stage"]),
                    downstream_stage_m=float(evidence["downstream_stage"]),
                    head_loss_m=float(evidence["head_loss"]),
                    reaction_force_per_density=float(
                        evidence["reaction_force_per_density"]
                    ),
                    regime=str(evidence["regime"]),
                )
            )
        pump_series = result["pumps"][0]
        pump_fields = (
            "time",
            "control_state",
            "running_units",
            "flow_m3s",
            "source_stage_m",
            "outlet_or_target_stage_m",
            "pump_head_m",
            "system_head_m",
            "efficiency",
            "input_power_kw",
            "cumulative_energy_kwh",
            "iterations",
            "regime",
        )
        if len({len(pump_series[field]) for field in pump_fields}) != 1:
            raise ValueError("Pump result arrays are not aligned")
        for index, time_seconds in enumerate(pump_series["time"]):
            session.add(
                HydraulicTaskPumpResult(
                    task_id=task.id,
                    dataset_version_id=dataset_id,
                    canonical_pump_id=pump_id,
                    time_seconds=float(time_seconds),
                    control_state=str(pump_series["control_state"][index]),
                    running_units=int(pump_series["running_units"][index]),
                    flow_m3s=float(pump_series["flow_m3s"][index]),
                    source_stage_m=float(pump_series["source_stage_m"][index]),
                    outlet_stage_m=float(
                        pump_series["outlet_or_target_stage_m"][index]
                    ),
                    pump_head_m=float(pump_series["pump_head_m"][index]),
                    system_head_m=float(pump_series["system_head_m"][index]),
                    efficiency=float(pump_series["efficiency"][index]),
                    input_power_kw=float(pump_series["input_power_kw"][index]),
                    cumulative_energy_kwh=float(
                        pump_series["cumulative_energy_kwh"][index]
                    ),
                    iterations=int(pump_series["iterations"][index]),
                    regime=str(pump_series["regime"][index]),
                )
            )
        for event in result["control_events"]:
            structure_id = int(event["structure_id"])
            if (event["structure_type"], structure_id) not in {
                ("gate", gate_id),
                ("pump", pump_id),
            }:
                raise ValueError("control event has no authoritative structure identity")
            session.add(
                HydraulicTaskControlEvent(
                    task_id=task.id,
                    dataset_version_id=dataset_id,
                    time_seconds=float(event["time"]),
                    structure_type=str(event["structure_type"]),
                    canonical_structure_id=structure_id,
                    canonical_gate_id=(
                        structure_id if event["structure_type"] == "gate" else None
                    ),
                    canonical_pump_id=(
                        structure_id if event["structure_type"] == "pump" else None
                    ),
                    event_type=str(event["action"]),
                    reason=event.get("reason"),
                    pre_state_json={
                        key: event.get(key)
                        for key in (
                            "previous_time",
                            "previous_observed_water_level",
                            "observed_water_level",
                        )
                        if event.get(key) is not None
                    }
                    or None,
                    post_command_json={"action": event["action"]},
                )
            )
        artifact = HydraulicTaskArtifact(
            task_id=task.id,
            artifact_type=ARTIFACT_TYPE,
            storage_key=storage_key,
            sha256=artifact_hash,
            size_bytes=len(artifact_bytes),
            record_count=record_count,
            media_type=ARTIFACT_MEDIA_TYPE,
            schema_version=ARTIFACT_SCHEMA_VERSION,
            status="prepared",
            metadata_json={
                "canonicalization_id": CANONICALIZATION_ID,
                "input_snapshot_hash": task.input_snapshot_hash,
                "runtime_projection_hash": task.runtime_projection_hash,
                "engine_version": task.engine_version,
                "engine_commit": task.engine_commit,
                "solver_build_id": task.solver_build_id,
                "build_mode": task.build_mode,
                "build_verified": task.build_verified,
                "unverified_build": not task.build_verified,
                "worker_executed_build": {
                    **worker_build.provenance(),
                    "registry_hash": task.registry_hash,
                },
                "execution_token_sha256": execution_token_hash,
                "staged_storage_key": staging_key,
                "capability_scope": list(projection.source.capability_scope),
                "capability_exclusions": list(
                    projection.source.capability_exclusions
                ),
                "case_notes": list(projection.source.case_notes),
                "known_limitations": list(projection.source.known_limitations),
            },
        )
        session.add(artifact)
        session.flush()
        prepared_diagnostics = _task_diagnostics(
            task,
            result,
            projection,
            artifact,
            worker_build,
            artifact_status="prepared",
        )
        prepared = session.execute(
            update(SimulationTask)
            .where(
                SimulationTask.id == task_id,
                SimulationTask.status == "running",
                SimulationTask.cancel_requested.is_(False),
                SimulationTask.active_execution_token == execution_token,
            )
            .values(
                artifact_status="prepared",
                execution_phase="publishing_artifact",
                heartbeat_time=datetime.now(UTC),
                result_schema_version=RESULT_SCHEMA_VERSION,
                result_path=f"api://model/v4/tasks/{task_id}/summary",
                diagnostics=prepared_diagnostics,
            )
            .execution_options(synchronize_session=False)
        )
        if prepared.rowcount != 1:
            session.rollback()
            raise StaleExecutionError(
                "native-v4 prepared commit rejected for stale/cancelled attempt"
            )
        session.commit()
        _fault(fault_hook, "after_db_prepared_commit")
        _phase(phase_callback, "publishing_artifact")
        check_cancellation(cancel_check, "artifact_publish")
        staging_lease = session.scalar(
            select(SimulationTask.id)
            .where(
                SimulationTask.id == task_id,
                SimulationTask.status == "running",
                SimulationTask.cancel_requested.is_(False),
                SimulationTask.active_execution_token == execution_token,
            )
            .with_for_update()
        )
        if staging_lease is None:
            session.rollback()
            raise StaleExecutionError(
                "native-v4 attempt staging rejected for stale/cancelled attempt"
            )
    # Release the short staging lease only after the atomic attempt rename.  A
    # stale recovery that wins before this lock prevents the rename entirely.
    session.commit()
    _fault(fault_hook, "after_atomic_rename")
    _phase(phase_callback, "finalizing")
    check_cancellation(cancel_check, "artifact_final_cas")
    _fault(fault_hook, "before_final_cas")

    # The attempt-specific stage may exist after a process crash without ever
    # touching the canonical download path.  Hold the task row lock from the
    # token check through file promotion and the final DB CAS so stale recovery,
    # cancellation, and a newer attempt cannot cross this publication window.
    locked_task = session.scalar(
        select(SimulationTask)
        .where(
            SimulationTask.id == task_id,
            SimulationTask.status == "running",
            SimulationTask.cancel_requested.is_(False),
            SimulationTask.active_execution_token == execution_token,
        )
        .with_for_update()
    )
    if locked_task is None:
        session.rollback()
        raise StaleExecutionError(
            "native-v4 final publication rejected for stale/cancelled attempt"
        )
    artifact = session.scalar(
        select(HydraulicTaskArtifact).where(
            HydraulicTaskArtifact.task_id == task_id,
            HydraulicTaskArtifact.artifact_type == ARTIFACT_TYPE,
            HydraulicTaskArtifact.schema_version == ARTIFACT_SCHEMA_VERSION,
        ).with_for_update()
    )
    if artifact is None:
        raise ValueError("published artifact metadata disappeared")
    metadata = artifact.metadata_json if isinstance(artifact.metadata_json, dict) else {}
    if (
        artifact.status not in {"prepared", "publishing"}
        or artifact.storage_key != storage_key
        or artifact.sha256 != artifact_hash
        or metadata.get("execution_token_sha256") != execution_token_hash
        or metadata.get("staged_storage_key") != staging_key
    ):
        raise StaleExecutionError(
            "native-v4 artifact metadata no longer belongs to this execution attempt"
        )
    if not staging_target.is_file():
        raise ValueError("native-v4 attempt staging artifact disappeared")
    if (
        staging_target.stat().st_size != len(artifact_bytes)
        or sha256(staging_target.read_bytes()).hexdigest() != artifact_hash
    ):
        raise ValueError("native-v4 attempt staging artifact failed final verification")
    if canonical_target.exists():
        raise ValueError(
            "native-v4 canonical artifact already exists; reconciliation required"
        )
    replace(staging_target, canonical_target)
    _fault(fault_hook, "after_final_publish_rename")
    now = datetime.now(UTC)
    published_diagnostics = _task_diagnostics(
        locked_task,
        result,
        projection,
        artifact,
        worker_build,
        artifact_status="published",
    )
    finalized = session.execute(
        update(SimulationTask)
        .where(
            SimulationTask.id == task_id,
            SimulationTask.status == "running",
            SimulationTask.cancel_requested.is_(False),
            SimulationTask.active_execution_token == execution_token,
        )
        .values(
            status="success",
            progress=100,
            result_schema_version=RESULT_SCHEMA_VERSION,
            result_path=f"api://model/v4/tasks/{task_id}/summary",
            artifact_status="published",
            execution_phase="finalizing",
            heartbeat_time=now,
            end_time=now,
            error_message=None,
            diagnostics=published_diagnostics,
            last_execution_token=execution_token,
            active_execution_token=None,
        )
        .execution_options(synchronize_session=False)
    )
    if finalized.rowcount != 1:
        session.rollback()
        raise StaleExecutionError(
            "native-v4 final success rejected for stale/cancelled attempt"
        )
    published = session.execute(
        update(HydraulicTaskArtifact)
        .where(
            HydraulicTaskArtifact.id == artifact.id,
            HydraulicTaskArtifact.status.in_(("prepared", "publishing")),
        )
        .values(status="published", published_time=now)
        .execution_options(synchronize_session=False)
    )
    if published.rowcount != 1:
        session.rollback()
        raise StaleExecutionError("native-v4 artifact publication CAS was rejected")
    session.commit()
    session.expire_all()
    task = session.get(SimulationTask, task_id)
    if task is None:
        raise LookupError("native-v4 task disappeared after successful finalization")
    return task


def require_successful_v4_task(session: Session, task_id: int) -> SimulationTask:
    """Resolve one published native-v4 task or return a stable application error."""

    task = session.get(SimulationTask, task_id)
    if task is None:
        raise LookupError("simulation task does not exist")
    if task.input_schema_version != "dayu.model-input.v4":
        raise ValueError("requested task is not native v4")
    if task.status != "success" or task.artifact_status != "published":
        raise ValueError(
            "native-v4 results are available only after result/artifact publication"
        )
    published_artifact = session.scalar(
        select(HydraulicTaskArtifact.id).where(
            HydraulicTaskArtifact.task_id == task_id,
            HydraulicTaskArtifact.artifact_type == ARTIFACT_TYPE,
            HydraulicTaskArtifact.schema_version == ARTIFACT_SCHEMA_VERSION,
            HydraulicTaskArtifact.status == "published",
        )
    )
    if published_artifact is None:
        raise ValueError("native-v4 published task has no published artifact metadata")
    return task


def list_v4_section_options(session: Session, task_id: int) -> list[V4SectionOption]:
    """List one row per persisted authoritative hydraulic Section."""

    require_successful_v4_task(session, task_id)
    rows = session.execute(
        select(
            HydraulicTaskSectionResult.hydraulic_cross_section_id,
            HydraulicTaskSectionResult.section_code,
            HydraulicTaskSectionResult.branch_id,
            HydraulicTaskSectionResult.chainage_m,
        )
        .where(HydraulicTaskSectionResult.task_id == task_id)
        .distinct()
        .order_by(HydraulicTaskSectionResult.chainage_m)
    ).all()
    return [V4SectionOption.model_validate(row._mapping) for row in rows]


def read_v4_section_result(
    session: Session, task_id: int, section_id: int
) -> V4SectionResultResponse:
    """Return aligned output-interval Section arrays for one authoritative ID."""

    options = list_v4_section_options(session, task_id)
    selected = next(
        (item for item in options if item.hydraulic_cross_section_id == section_id),
        None,
    )
    if selected is None:
        raise LookupError("hydraulic Section result does not exist in this task")
    rows = list(
        session.scalars(
            select(HydraulicTaskSectionResult)
            .where(
                HydraulicTaskSectionResult.task_id == task_id,
                HydraulicTaskSectionResult.hydraulic_cross_section_id == section_id,
            )
            .order_by(HydraulicTaskSectionResult.time_seconds)
        ).all()
    )
    return V4SectionResultResponse(
        **selected.model_dump(),
        task_id=task_id,
        time_seconds=[row.time_seconds for row in rows],
        water_level_m=[row.water_level_m for row in rows],
        flow_m3s=[row.flow_m3s for row in rows],
        velocity_m_s=[row.velocity_m_s for row in rows],
        control_volume_m3=[row.control_volume_m3 for row in rows],
        available_sections=options,
    )


def artifact_manifest(artifact: HydraulicTaskArtifact) -> V4ArtifactManifest:
    """Convert persisted metadata without resolving or leaking an absolute path."""

    metadata = dict(artifact.metadata_json)
    metadata.pop("execution_token_sha256", None)
    metadata.pop("staged_storage_key", None)
    return V4ArtifactManifest(
        id=artifact.id,
        artifact_type=artifact.artifact_type,
        storage_key=artifact.storage_key,
        sha256=artifact.sha256,
        size_bytes=artifact.size_bytes,
        record_count=artifact.record_count,
        media_type=artifact.media_type,
        schema_version=artifact.schema_version,
        status=artifact.status,
        metadata=metadata,
        created_time=artifact.created_time,
        published_time=artifact.published_time,
    )


def list_v4_artifacts(session: Session, task_id: int) -> list[V4ArtifactManifest]:
    """List only published artifacts belonging to one successful task."""

    require_successful_v4_task(session, task_id)
    rows = session.scalars(
        select(HydraulicTaskArtifact)
        .where(
            HydraulicTaskArtifact.task_id == task_id,
            HydraulicTaskArtifact.status == "published",
        )
        .order_by(HydraulicTaskArtifact.id)
    ).all()
    return [artifact_manifest(row) for row in rows]


def resolve_v4_artifact_download(
    session: Session, task_id: int, artifact_id: int
) -> tuple[HydraulicTaskArtifact, Any]:
    """Resolve, verify, and return a published artifact inside DAYU_STORAGE_ROOT."""

    require_successful_v4_task(session, task_id)
    artifact = session.get(HydraulicTaskArtifact, artifact_id)
    if (
        artifact is None
        or artifact.task_id != task_id
        or artifact.status != "published"
    ):
        raise LookupError("published task artifact does not exist")
    path = resolve_within(configured_storage_root(), artifact.storage_key)
    if not path.is_file():
        raise ValueError("published task artifact file is missing")
    content = path.read_bytes()
    if len(content) != artifact.size_bytes or sha256(content).hexdigest() != artifact.sha256:
        raise ValueError("published task artifact failed integrity verification")
    return artifact, path


def v4_result_summary(session: Session, task_id: int) -> V4ResultSummary:
    """Return bounded result-v3 provenance and row counts."""

    task = require_successful_v4_task(session, task_id)
    provenance = task.diagnostics or {}
    artifacts = list_v4_artifacts(session, task_id)
    return V4ResultSummary(
        task_id=task.id,
        result_schema_version="dayu.hydraulic-result.v3",
        provenance=provenance,
        section_count=len(list_v4_section_options(session, task_id)),
        gate_row_count=session.query(HydraulicTaskGateResult)
        .filter(HydraulicTaskGateResult.task_id == task_id)
        .count(),
        pump_row_count=session.query(HydraulicTaskPumpResult)
        .filter(HydraulicTaskPumpResult.task_id == task_id)
        .count(),
        event_count=session.query(HydraulicTaskControlEvent)
        .filter(HydraulicTaskControlEvent.task_id == task_id)
        .count(),
        artifacts=artifacts,
    )


__all__ = [
    "ARTIFACT_MEDIA_TYPE",
    "ARTIFACT_SCHEMA_VERSION",
    "ARTIFACT_TYPE",
    "RESULT_SCHEMA_VERSION",
    "build_stage_evidence_artifact",
    "persist_v4_result",
    "artifact_manifest",
    "list_v4_artifacts",
    "list_v4_section_options",
    "read_v4_section_result",
    "require_successful_v4_task",
    "resolve_v4_artifact_download",
    "validate_v4_result",
    "v4_attempt_staging_storage_key",
    "v4_attempt_staging_storage_key_from_hashes",
    "v4_result_summary",
]
