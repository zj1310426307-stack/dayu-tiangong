"""Deterministically reconcile one native-v4 result artifact inside storage root."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from os import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.files import configured_storage_root, resolve_within
from app.gis.models import (
    HydraulicTaskArtifact,
    HydraulicTaskControlEvent,
    HydraulicTaskGateResult,
    HydraulicTaskPumpResult,
    HydraulicTaskSectionResult,
    SimulationTask,
)
from app.model_engine.v4_result import (
    ARTIFACT_SCHEMA_VERSION,
    ARTIFACT_TYPE,
    RESULT_SCHEMA_VERSION,
    v4_attempt_staging_storage_key_from_hashes,
)


RECONCILABLE_TASK_ARTIFACT_STATES = frozenset(
    {"prepared", "publishing", "reconciliation_required"}
)
RECONCILABLE_ROW_STATES = frozenset(
    {"prepared", "publishing", "published", "reconciliation_required"}
)
FINALIZATION_PHASES = frozenset(
    {"persisting", "publishing_artifact", "finalizing"}
)


def expected_v4_artifact_storage_key(task_id: int) -> str:
    """Return the only storage key this bounded reconciler will inspect."""

    return f"hydraulic-evidence/task-{task_id}-stage-evidence-v1.jsonl.gz"


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _temporary_files(target: Path) -> list[Path]:
    """Inspect only exact atomic-output siblings for this task's deterministic file."""

    if not target.parent.is_dir():
        return []
    prefix = f".{target.name}."
    return sorted(
        path
        for path in target.parent.iterdir()
        if (
            path.is_file()
            and not path.is_symlink()
            and path.name.startswith(prefix)
            and path.name.endswith(".tmp")
        )
    )


def _attempt_staging_path(
    root: Path,
    task_id: int,
    artifact: HydraulicTaskArtifact,
) -> tuple[Path | None, str | None]:
    """Resolve only a token/hash-derived staging key from trusted row metadata."""

    metadata = artifact.metadata_json
    if not isinstance(metadata, dict):
        return None, "artifact metadata is not an object"
    token_hash = metadata.get("execution_token_sha256")
    staged_key = metadata.get("staged_storage_key")
    if token_hash is None and staged_key is None:
        # Artifacts created before attempt-scoped staging remain reconcilable by
        # their canonical path; never guess or scan a staging path for them.
        return None, None
    if not isinstance(token_hash, str) or not isinstance(staged_key, str):
        return None, "attempt staging metadata is incomplete"
    try:
        expected = v4_attempt_staging_storage_key_from_hashes(
            task_id,
            token_hash,
            artifact.sha256,
        )
    except ValueError as exc:
        return None, str(exc)
    if staged_key != expected:
        return None, "attempt staging metadata is not token/hash-derived"
    try:
        return resolve_within(root, staged_key), None
    except ValueError:
        return None, "attempt staging path escapes configured storage root"


def _quarantine(root: Path, source: Path, task_id: int, label: str) -> str:
    """Move an untrusted file to a recoverable location inside storage root."""

    directory = resolve_within(root, "hydraulic-evidence", "quarantine")
    directory.mkdir(parents=True, exist_ok=True)
    source_fingerprint = sha256(source.name.encode("utf-8")).hexdigest()[:16]
    destination = resolve_within(
        directory,
        f"task-{task_id}-{label}-{uuid4().hex[:16]}-{source_fingerprint}{source.suffix}",
    )
    replace(source, destination)
    return _relative(root, destination)


def _result_row_counts(session: Session, task_id: int) -> dict[str, int]:
    models = {
        "sections": HydraulicTaskSectionResult,
        "gates": HydraulicTaskGateResult,
        "pumps": HydraulicTaskPumpResult,
        "events": HydraulicTaskControlEvent,
    }
    return {
        name: int(
            session.scalar(
                select(func.count()).select_from(model).where(model.task_id == task_id)
            )
            or 0
        )
        for name, model in models.items()
    }


def _prepared_scientific_result_is_complete(
    task: SimulationTask,
    artifact: HydraulicTaskArtifact,
    row_counts: dict[str, int],
) -> bool:
    """Fail closed: reconciliation may publish only an already-prepared result."""

    diagnostics = task.diagnostics
    if not isinstance(diagnostics, dict):
        return False
    manifest = diagnostics.get("artifact_manifest")
    return bool(
        task.status in {"failed", "success"}
        and task.active_execution_token is None
        and not task.cancel_requested
        and task.execution_phase in FINALIZATION_PHASES
        and task.artifact_status in (
            RECONCILABLE_TASK_ARTIFACT_STATES | {"published"}
        )
        and task.result_schema_version == RESULT_SCHEMA_VERSION
        and task.result_path
        and diagnostics.get("result_schema_version") == RESULT_SCHEMA_VERSION
        and isinstance(manifest, dict)
        and manifest.get("storage_key") == artifact.storage_key
        and manifest.get("sha256") == artifact.sha256
        and row_counts["sections"] > 0
        and row_counts["gates"] > 0
        and row_counts["pumps"] > 0
    )


def _published_diagnostics(
    task: SimulationTask, artifact: HydraulicTaskArtifact, action: str
) -> dict[str, Any]:
    diagnostics = deepcopy(task.diagnostics) if isinstance(task.diagnostics, dict) else {}
    manifest = dict(diagnostics.get("artifact_manifest") or {})
    manifest.update(
        {
            "artifact_type": artifact.artifact_type,
            "storage_key": artifact.storage_key,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "record_count": artifact.record_count,
            "media_type": artifact.media_type,
            "schema_version": artifact.schema_version,
            "status": "published",
        }
    )
    diagnostics["artifact_manifest"] = manifest
    diagnostics["reconciliation"] = {
        "action": action,
        "time": datetime.now(UTC).isoformat(),
    }
    return diagnostics


def _mark_integrity_failure(
    task: SimulationTask,
    artifact: HydraulicTaskArtifact,
    message: str,
) -> None:
    artifact.status = "failed"
    artifact.published_time = None
    task.artifact_status = "failed"
    task.error_message = message[:4000]


def reconcile_v4_task(
    session: Session,
    task_id: int,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Inspect one task; mutate only with explicit ``apply=True``.

    The command never scans outside the deterministic task path and never promotes
    an active, cancelled, or scientifically failed task to success.
    """

    statement = select(SimulationTask).where(SimulationTask.id == task_id)
    if apply:
        statement = statement.with_for_update()
    task = session.scalar(statement)
    if task is None:
        raise LookupError("simulation task does not exist")
    if task.input_schema_version != "dayu.model-input.v4":
        raise ValueError("reconciliation is restricted to native-v4 tasks")

    root = configured_storage_root().resolve()
    expected_key = expected_v4_artifact_storage_key(task_id)
    target = resolve_within(root, expected_key)
    artifact_statement = select(HydraulicTaskArtifact).where(
        HydraulicTaskArtifact.task_id == task_id,
        HydraulicTaskArtifact.artifact_type == ARTIFACT_TYPE,
        HydraulicTaskArtifact.schema_version == ARTIFACT_SCHEMA_VERSION,
    )
    if apply:
        artifact_statement = artifact_statement.with_for_update()
    artifact = session.scalar(artifact_statement)
    staging_target: Path | None = None
    staging_error: str | None = None
    if artifact is not None:
        staging_target, staging_error = _attempt_staging_path(
            root,
            task_id,
            artifact,
        )
    temporary = _temporary_files(target)
    if staging_target is not None:
        temporary.extend(_temporary_files(staging_target))
        temporary = sorted(set(temporary))
    report: dict[str, Any] = {
        "task_id": task_id,
        "mode": "apply" if apply else "dry-run",
        "task_status_before": task.status,
        "task_artifact_status_before": task.artifact_status,
        "expected_storage_key": expected_key,
        "metadata_status": artifact.status if artifact is not None else None,
        "final_file_exists": target.is_file(),
        "staged_storage_key": (
            _relative(root, staging_target) if staging_target is not None else None
        ),
        "staged_file_exists": bool(
            staging_target is not None and staging_target.is_file()
        ),
        "staging_metadata_error": staging_error,
        "temporary_files": [_relative(root, path) for path in temporary],
        "actions": [],
        "outcome": "inspection_required",
    }

    if task.active_execution_token is not None or task.status in {
        "running",
        "cancel_requested",
    }:
        report["outcome"] = "active_attempt_not_reconciled"
        report["actions"].append("run stale recovery or complete cancellation first")
        if apply:
            session.rollback()
        return report

    if artifact is None:
        if target.is_file():
            report["outcome"] = "orphan_final_file"
            report["actions"].append("quarantine orphan final file")
            if apply:
                report["quarantined_files"] = [
                    _quarantine(root, target, task_id, "orphan-final")
                ]
                task.artifact_status = (
                    "failed" if task.status == "success" else "none"
                )
                if task.status == "success":
                    task.error_message = (
                        "artifact integrity incident: final file had no metadata"
                    )
        else:
            if task.status == "success":
                report["outcome"] = "successful_task_metadata_missing"
                report["actions"].append("mark operational integrity incident")
                if apply:
                    task.artifact_status = "failed"
                    task.error_message = (
                        "artifact integrity incident: successful task has no metadata"
                    )
            else:
                report["outcome"] = "clean_no_artifact"
                if apply and task.status in {"failed", "cancelled"}:
                    task.artifact_status = "none"
        if temporary:
            report["outcome"] = "orphan_temporary_files"
            report["actions"].append("quarantine orphan temporary files")
            if apply:
                report.setdefault("quarantined_files", []).extend(
                    _quarantine(root, path, task_id, "orphan-temp")
                    for path in temporary
                )
                if task.status != "success":
                    task.artifact_status = "none"
        if apply:
            session.commit()
        report["task_status_after"] = task.status
        report["task_artifact_status_after"] = task.artifact_status
        return report

    if artifact.storage_key != expected_key:
        report["outcome"] = "invalid_metadata_path"
        report["actions"].append("mark artifact failed; no file path inspected")
        if apply:
            _mark_integrity_failure(
                task,
                artifact,
                "artifact reconciliation rejected a non-deterministic storage key",
            )
            session.commit()
        report["task_status_after"] = task.status
        report["task_artifact_status_after"] = task.artifact_status
        return report

    if staging_error is not None:
        report["outcome"] = "invalid_attempt_staging_metadata"
        report["actions"].append(
            "quarantine deterministic canonical files and mark artifact failed"
        )
        if apply:
            quarantined: list[str] = []
            if target.is_file():
                quarantined.append(
                    _quarantine(root, target, task_id, "invalid-staging-metadata")
                )
            quarantined.extend(
                _quarantine(root, path, task_id, "invalid-staging-temp")
                for path in temporary
            )
            if quarantined:
                report["quarantined_files"] = quarantined
            _mark_integrity_failure(
                task,
                artifact,
                f"artifact reconciliation rejected staging metadata: {staging_error}",
            )
            session.commit()
        report["task_status_after"] = task.status
        report["task_artifact_status_after"] = task.artifact_status
        return report

    row_counts = _result_row_counts(session, task_id)
    report["result_row_counts"] = row_counts
    if not target.is_file():
        if staging_target is not None and staging_target.is_file():
            staged_size = staging_target.stat().st_size
            staged_hash = _file_sha256(staging_target)
            staged_integrity_matches = (
                staged_size == artifact.size_bytes and staged_hash == artifact.sha256
            )
            report.update(
                {
                    "staged_size_bytes": staged_size,
                    "staged_sha256": staged_hash,
                    "staged_integrity_matches": staged_integrity_matches,
                }
            )
            report["outcome"] = (
                "staged_attempt_requires_quarantine"
                if staged_integrity_matches
                else "staged_attempt_integrity_mismatch"
            )
            report["actions"].append(
                "quarantine attempt-scoped staging file; do not publish it"
            )
            if temporary:
                report["actions"].append("quarantine attempt temporary files")
            if apply:
                report["quarantined_files"] = [
                    _quarantine(root, staging_target, task_id, "stale-attempt-stage")
                ]
                report["quarantined_files"].extend(
                    _quarantine(root, path, task_id, "stale-attempt-temp")
                    for path in temporary
                )
                _mark_integrity_failure(
                    task,
                    artifact,
                    (
                        "attempt-scoped staging artifact was never token-authorized "
                        "for canonical publication"
                        if staged_integrity_matches
                        else "attempt-scoped staging artifact failed size/hash verification"
                    ),
                )
                session.commit()
            report["task_status_after"] = task.status
            report["task_artifact_status_after"] = task.artifact_status
            return report
        report["outcome"] = (
            "published_artifact_missing"
            if task.status == "success" or artifact.status == "published"
            else "prepared_artifact_missing"
        )
        report["actions"].append("mark artifact failed")
        if temporary:
            report["actions"].append("quarantine orphan temporary files")
        if apply:
            if temporary:
                report["quarantined_files"] = [
                    _quarantine(root, path, task_id, "missing-final-temp")
                    for path in temporary
                ]
            _mark_integrity_failure(
                task,
                artifact,
                "artifact integrity incident: prepared/published file is missing",
            )
            session.commit()
        report["task_status_after"] = task.status
        report["task_artifact_status_after"] = task.artifact_status
        return report

    actual_size = target.stat().st_size
    actual_hash = _file_sha256(target)
    integrity_matches = (
        actual_size == artifact.size_bytes and actual_hash == artifact.sha256
    )
    report.update(
        {
            "actual_size_bytes": actual_size,
            "actual_sha256": actual_hash,
            "integrity_matches": integrity_matches,
        }
    )
    if not integrity_matches:
        report["outcome"] = "artifact_integrity_mismatch"
        report["actions"].extend(["quarantine corrupt final file", "mark artifact failed"])
        if staging_target is not None and staging_target.is_file():
            report["actions"].append("quarantine attempt staging file")
        if temporary:
            report["actions"].append("quarantine attempt temporary files")
        if apply:
            report["quarantined_files"] = [
                _quarantine(root, target, task_id, "hash-mismatch")
            ]
            if staging_target is not None and staging_target.is_file():
                report["quarantined_files"].append(
                    _quarantine(root, staging_target, task_id, "hash-mismatch-stage")
                )
            report["quarantined_files"].extend(
                _quarantine(root, path, task_id, "hash-mismatch-temp")
                for path in temporary
            )
            _mark_integrity_failure(
                task,
                artifact,
                "artifact integrity incident: size/hash mismatch",
            )
            session.commit()
        report["task_status_after"] = task.status
        report["task_artifact_status_after"] = task.artifact_status
        return report

    if task.status == "cancelled" or task.cancel_requested:
        report["outcome"] = "cancelled_task_artifact_quarantine"
        report["actions"].extend(["quarantine final file", "mark artifact failed"])
        if staging_target is not None and staging_target.is_file():
            report["actions"].append("quarantine attempt staging file")
        if temporary:
            report["actions"].append("quarantine attempt temporary files")
        if apply:
            report["quarantined_files"] = [
                _quarantine(root, target, task_id, "cancelled")
            ]
            if staging_target is not None and staging_target.is_file():
                report["quarantined_files"].append(
                    _quarantine(root, staging_target, task_id, "cancelled-stage")
                )
            report["quarantined_files"].extend(
                _quarantine(root, path, task_id, "cancelled-temp")
                for path in temporary
            )
            _mark_integrity_failure(
                task,
                artifact,
                "artifact discarded because cancellation reached a terminal state",
            )
            session.commit()
        report["task_status_after"] = task.status
        report["task_artifact_status_after"] = task.artifact_status
        return report

    if task.status == "success" and artifact.status == "published":
        orphan_staging = bool(
            (staging_target is not None and staging_target.is_file()) or temporary
        )
        report["outcome"] = (
            "published_artifact_with_orphan_staging"
            if orphan_staging
            else "published_artifact_consistent"
        )
        if orphan_staging:
            report["actions"].append("quarantine orphan attempt staging files")
            if apply:
                quarantined: list[str] = []
                if staging_target is not None and staging_target.is_file():
                    quarantined.append(
                        _quarantine(root, staging_target, task_id, "published-stage")
                    )
                quarantined.extend(
                    _quarantine(root, path, task_id, "published-temp")
                    for path in temporary
                )
                report["quarantined_files"] = quarantined
                session.commit()
        report["scientific_result_complete"] = True
        report["task_status_after"] = task.status
        report["task_artifact_status_after"] = task.artifact_status
        return report

    eligible = (
        artifact.status in RECONCILABLE_ROW_STATES
        and _prepared_scientific_result_is_complete(task, artifact, row_counts)
    )
    report["scientific_result_complete"] = eligible
    if eligible:
        report["outcome"] = "publishable_prepared_artifact"
        report["actions"].append("complete task/artifact publication")
        if staging_target is not None and staging_target.is_file():
            report["actions"].append("quarantine redundant attempt staging file")
        if temporary:
            report["actions"].append("quarantine attempt temporary files")
        if apply:
            quarantined: list[str] = []
            if staging_target is not None and staging_target.is_file():
                quarantined.append(
                    _quarantine(root, staging_target, task_id, "published-redundant-stage")
                )
            quarantined.extend(
                _quarantine(root, path, task_id, "published-redundant-temp")
                for path in temporary
            )
            if quarantined:
                report["quarantined_files"] = quarantined
            now = datetime.now(UTC)
            artifact.status = "published"
            artifact.published_time = now
            task.status = "success"
            task.progress = 100
            task.artifact_status = "published"
            task.execution_phase = "finalizing"
            task.heartbeat_time = now
            task.end_time = task.end_time or now
            task.error_message = None
            task.active_execution_token = None
            task.diagnostics = _published_diagnostics(
                task, artifact, "complete_prepared_publication"
            )
            session.commit()
    else:
        report["outcome"] = "scientific_failure_not_auto_recovered"
        report["actions"].append(
            "quarantine unpublishable final file; task will not be promoted"
        )
        if staging_target is not None and staging_target.is_file():
            report["actions"].append("quarantine attempt staging file")
        if temporary:
            report["actions"].append("quarantine attempt temporary files")
        if apply:
            report["quarantined_files"] = [
                _quarantine(root, target, task_id, "unpublishable")
            ]
            if staging_target is not None and staging_target.is_file():
                report["quarantined_files"].append(
                    _quarantine(root, staging_target, task_id, "unpublishable-stage")
                )
            report["quarantined_files"].extend(
                _quarantine(root, path, task_id, "unpublishable-temp")
                for path in temporary
            )
            _mark_integrity_failure(
                task,
                artifact,
                "artifact was not backed by a complete prepared scientific result",
            )
            session.commit()

    report["task_status_after"] = task.status
    report["task_artifact_status_after"] = task.artifact_status
    return report


__all__ = [
    "FINALIZATION_PHASES",
    "RECONCILABLE_ROW_STATES",
    "RECONCILABLE_TASK_ARTIFACT_STATES",
    "expected_v4_artifact_storage_key",
    "reconcile_v4_task",
]
