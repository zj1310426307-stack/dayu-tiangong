"""Transactional persistence for Production-04 evidence and task gates."""

from __future__ import annotations

from datetime import UTC, datetime
from math import isclose, isfinite
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.gis.models import DatasetVersion, SimulationCase, SimulationTask
from app.hydraulic.models import (
    HydraulicCalibrationRun,
    HydraulicExternalResult,
    HydraulicModelValidationAssessment,
    HydraulicObservationSeries,
    HydraulicProductionAuditEvent,
    HydraulicProductionRun,
    HydraulicResultProduct,
)
from app.hydraulic.production.gate import build_production_gate
from app.hydraulic.production.calibration import (
    build_parameter_sweep,
    evaluate_acceptance,
    evaluate_project_metric_criteria,
    evaluate_validation_independence,
    rank_calibration_candidates,
)
from app.hydraulic.production.contracts import (
    AcceptanceEvaluationRequest,
    CalibrationCandidate,
    CalibrationPromotionRequest,
    CalibrationRankingRequest,
    HydraulicModelQARequest,
    HydraulicModelQAResult,
)
from app.hydraulic.production.products import build_result_products
from app.hydraulic.production.qa import HydraulicModelQA
from app.hydraulic.production.records import (
    AuditEventRecord,
    CalibrationRunCommitRequest,
    CalibrationPromotionResponse,
    CalibrationRunRecord,
    CalibrationSweepCreateRequest,
    CalibrationSweepRunResponse,
    ExternalResultCommitRequest,
    ExternalResultRecord,
    ObservationCommitRequest,
    ObservationRecord,
    ProductionRunRecord,
    ProductionApprovalRequest,
    ProductionTaskCreateRequest,
    ResultProductCommitRequest,
    ResultProductRecord,
    ValidationRunCommitRequest,
    ValidationRunRecord,
)
from app.model_engine.service import build_task_entity, parse_frozen_task_model
from app.model_engine.schemas import SimulationTaskCreate
from model.provenance import snapshot_hash


def _require_dataset(session: Session, dataset_version_id: int) -> DatasetVersion:
    dataset = session.get(DatasetVersion, dataset_version_id)
    if dataset is None:
        raise ValueError("Dataset Version does not exist")
    return dataset


def _require_case(session: Session, case_id: int, dataset_version_id: int) -> SimulationCase:
    case = session.get(SimulationCase, case_id)
    if case is None or case.dataset_version_id != dataset_version_id:
        raise ValueError("Simulation Case does not belong to the Dataset Version")
    return case


def _require_production_run(
    session: Session, run_id: int, dataset_version_id: int, case_id: int
) -> HydraulicProductionRun:
    run = session.get(HydraulicProductionRun, run_id)
    if (
        run is None
        or run.dataset_version_id != dataset_version_id
        or run.case_id != case_id
    ):
        raise ValueError("Production Run does not belong to the Dataset Version and Case")
    return run


def _audit(
    session: Session,
    *,
    dataset_version_id: int,
    action: str,
    actor: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
) -> HydraulicProductionAuditEvent:
    content_hash = snapshot_hash(payload)
    event = HydraulicProductionAuditEvent(
        dataset_version_id=dataset_version_id,
        action=action,
        actor=actor,
        entity_type=entity_type,
        entity_id=entity_id,
        content_hash=content_hash,
        details_json=payload,
    )
    session.add(event)
    session.flush()
    return event


def _task_mass_balance(task: SimulationTask) -> float | None:
    """Read a finite relative mass diagnostic without trusting an API payload."""

    diagnostics = task.diagnostics if isinstance(task.diagnostics, dict) else {}
    water_balance = diagnostics.get("water_balance")
    nested = water_balance if isinstance(water_balance, dict) else {}
    value = diagnostics.get(
        "network_mass_balance_residual", nested.get("relative_balance_residual")
    )
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not isfinite(float(value))
    ):
        return None
    return abs(float(value))


def create_production_run(
    session: Session, payload: ProductionTaskCreateRequest
) -> ProductionRunRecord:
    """Create one task, bind QA evidence, and stage both in one transaction."""

    qa_result = HydraulicModelQA().validate(payload.qa)
    if not qa_result.run_allowed:
        raise ValueError("Production Simulation is blocked by centralized model QA")
    task = build_task_entity(session, payload.task)
    model = parse_frozen_task_model(task)
    digest = str(task.input_snapshot_hash or "")
    gate = build_production_gate(payload.qa, qa_result, model, digest)
    task.config = {**task.config, "production_mode": True, "production_gate": gate}
    run = HydraulicProductionRun(
        run_code=payload.run_code,
        dataset_version_id=task.dataset_version_id,
        case_id=task.case_id,
        task_id=task.id,
        qa_run_code=payload.qa_run_code,
        model_state="QA_PASSED",
        input_snapshot_hash=digest,
        input_snapshot_json={
            "model": task.input_snapshot,
            "qa_request": payload.qa.model_dump(mode="json"),
            "qa_result": qa_result.model_dump(mode="json"),
            "production_gate_hash": gate["gate_hash"],
        },
        engine_provenance_json={
            "engine_version": task.engine_version,
            "engine_commit": task.engine_commit,
            "solver_build_id": task.solver_build_id,
            "solver_id": task.solver_id,
            "capability_id": task.capability_id,
            "registry_hash": task.registry_hash,
        },
        runtime_provenance_json={},
    )
    session.add(run)
    session.flush()
    _audit(
        session,
        dataset_version_id=task.dataset_version_id,
        action="RUN_CREATION",
        actor=payload.actor,
        entity_type="production_run",
        entity_id=str(run.id),
        payload={
            "run_code": run.run_code,
            "task_id": task.id,
            "input_snapshot_hash": digest,
            "qa_run_code": payload.qa_run_code,
            "production_gate_hash": gate["gate_hash"],
        },
    )
    return ProductionRunRecord.model_validate(run, from_attributes=True)


def list_production_runs(
    session: Session, dataset_version_id: int | None = None
) -> list[ProductionRunRecord]:
    statement = select(HydraulicProductionRun)
    if dataset_version_id is not None:
        statement = statement.where(
            HydraulicProductionRun.dataset_version_id == dataset_version_id
        )
    rows = session.scalars(statement.order_by(HydraulicProductionRun.id.desc())).all()
    return [ProductionRunRecord.model_validate(row, from_attributes=True) for row in rows]


def commit_observation(
    session: Session, payload: ObservationCommitRequest
) -> ObservationRecord:
    _require_dataset(session, payload.dataset_version_id)
    series = payload.preview.series
    if not series.station_id or series.branch_id is None or series.chainage_m is None:
        raise ValueError("Observation requires station, Branch, and chainage identities")
    try:
        branch_id = int(series.branch_id)
    except ValueError as exc:
        raise ValueError("Production observation Branch identity must be an integer") from exc
    row = HydraulicObservationSeries(
        dataset_version_id=payload.dataset_version_id,
        series_code=series.series_id,
        station_id=series.station_id,
        branch_id=branch_id,
        chainage_m=series.chainage_m,
        variable=series.variable,
        unit=series.unit,
        vertical_datum=series.vertical_datum,
        time_basis=series.time_basis,
        timezone=series.timezone,
        source=series.source,
        source_filename=payload.preview.source_filename,
        source_sha256=payload.preview.source_sha256,
        samples_json=[item.model_dump(mode="json") for item in series.samples],
        mapping_profile_id=payload.mapping_profile_id,
    )
    session.add(row)
    session.flush()
    _audit(
        session,
        dataset_version_id=payload.dataset_version_id,
        action="IMPORT",
        actor=payload.actor,
        entity_type="observation_series",
        entity_id=str(row.id),
        payload={
            "series_code": row.series_code,
            "source_filename": row.source_filename,
            "source_sha256": row.source_sha256,
            "sample_count": len(row.samples_json),
        },
    )
    return ObservationRecord.model_validate(row, from_attributes=True)


def commit_external_result(
    session: Session, payload: ExternalResultCommitRequest
) -> ExternalResultRecord:
    _require_dataset(session, payload.dataset_version_id)
    if payload.preview.row_count != len(payload.preview.points):
        raise ValueError(
            "External result commit requires every source row; use the multipart import endpoint"
        )
    provenance = payload.preview.provenance
    row = HydraulicExternalResult(
        dataset_version_id=payload.dataset_version_id,
        result_code=payload.result_code,
        external_model_name=str(provenance.get("external_model_name", "UNKNOWN")),
        external_model_version=str(provenance.get("external_model_version", "UNKNOWN")),
        scenario=str(provenance.get("scenario", "UNKNOWN")),
        vertical_datum=str(provenance.get("vertical_datum", "UNKNOWN")),
        source_filename=payload.preview.source_filename,
        source_sha256=payload.preview.source_sha256,
        mapping_json={
            "column_mapping": provenance.get("column_mapping"),
            "branch_mappings": provenance.get("branch_mappings"),
        },
        points_json=[item.model_dump(mode="json") for item in payload.preview.points],
        provenance_json=provenance,
    )
    session.add(row)
    session.flush()
    _audit(
        session,
        dataset_version_id=payload.dataset_version_id,
        action="IMPORT",
        actor=payload.actor,
        entity_type="external_result",
        entity_id=str(row.id),
        payload={
            "result_code": row.result_code,
            "source_filename": row.source_filename,
            "source_sha256": row.source_sha256,
            "row_count": payload.preview.row_count,
        },
    )
    return ExternalResultRecord.model_validate(row, from_attributes=True)


def commit_calibration_run(
    session: Session, payload: CalibrationRunCommitRequest
) -> CalibrationRunRecord:
    _require_dataset(session, payload.dataset_version_id)
    _require_case(session, payload.case_id, payload.dataset_version_id)
    run = _require_production_run(
        session, payload.production_run_id, payload.dataset_version_id, payload.case_id
    )
    if run.model_state not in {"QA_PASSED", "CALIBRATED"}:
        raise ValueError("Calibration requires a QA_PASSED Production Run")
    base_task = session.get(SimulationTask, run.task_id)
    if base_task is None or base_task.status != "success":
        raise ValueError("Calibration requires a successful bound Production task")
    plan = build_parameter_sweep(payload.sweep)
    planned = {item.candidate_id: item for item in plan.candidates}
    if len(payload.candidates) != len(plan.candidates):
        raise ValueError("Calibration results must cover every planned candidate")
    for candidate in payload.candidates:
        expected = planned.get(candidate.candidate_id)
        if expected is None or expected.overrides != candidate.overrides:
            raise ValueError("Calibration candidate does not match the server-generated sweep")
        if candidate.task_id is None:
            raise ValueError("Every calibration candidate must reference an immutable task")
        candidate_task = session.get(SimulationTask, candidate.task_id)
        expected_task_status = {
            "planned": "pending",
            "queued": "queued",
            "running": "running",
            "completed": "success",
            "failed": "failed",
            "cancelled": "cancelled",
        }[candidate.status]
        if (
            candidate_task is None
            or candidate_task.dataset_version_id != payload.dataset_version_id
            or candidate_task.case_id != payload.case_id
            or candidate_task.status != expected_task_status
        ):
            raise ValueError("Calibration candidate task identity or status is inconsistent")
        expected_overrides = [
            {
                "group_id": parameter.group_id,
                "cross_section_ids": [int(value) for value in parameter.target_ids],
                "manning_n": candidate.overrides[f"manning_n:{parameter.group_id}"],
            }
            for parameter in payload.sweep.parameters
        ]
        if candidate_task.config.get("roughness_overrides") != expected_overrides:
            raise ValueError("Calibration task roughness overrides do not match its candidate")
    ranked = rank_calibration_candidates(
        CalibrationRankingRequest(candidates=payload.candidates, objective=payload.objective)
    )
    terminal = {"completed", "failed", "cancelled"}
    row = (
        session.get(HydraulicCalibrationRun, payload.calibration_run_id)
        if payload.calibration_run_id is not None
        else None
    )
    if payload.calibration_run_id is not None and (
        row is None
        or row.production_run_id != run.id
        or row.run_code != payload.run_code
        or row.status not in {"planned", "queued", "running", "completed"}
    ):
        raise ValueError("Calibration Run identity or lifecycle state is inconsistent")
    status = (
        "completed"
        if ranked and all(candidate.status in terminal for candidate in ranked)
        else "planned"
    )
    values = {
        "status": status,
        "calibration_dataset_json": payload.dataset.model_dump(mode="json"),
        "parameter_groups_json": [
            item.model_dump(mode="json") for item in payload.sweep.parameters
        ],
        "candidates_json": [item.model_dump(mode="json") for item in ranked],
        "objective_json": payload.objective.model_dump(mode="json"),
    }
    if row is None:
        row = HydraulicCalibrationRun(
            production_run_id=run.id,
            run_code=payload.run_code,
            dataset_version_id=payload.dataset_version_id,
            case_id=payload.case_id,
            **values,
        )
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()
    return CalibrationRunRecord.model_validate(row, from_attributes=True)


def create_calibration_sweep(
    session: Session, payload: CalibrationSweepCreateRequest
) -> CalibrationSweepRunResponse:
    """Create every bounded candidate as an ordinary immutable Job Manager task."""

    run = session.get(HydraulicProductionRun, payload.production_run_id)
    if run is None:
        raise ValueError("Production Run does not exist")
    if run.model_state not in {"QA_PASSED", "CALIBRATED"}:
        raise ValueError("Calibration sweep requires a QA_PASSED Production Run")
    base_task = session.get(SimulationTask, run.task_id)
    if base_task is None or base_task.status != "success":
        raise ValueError("Calibration sweep requires a successful bound Production task")
    plan = build_parameter_sweep(payload.sweep)
    allowed_config = {
        key: value
        for key, value in base_task.config.items()
        if key
        in {
            "duration_seconds",
            "time_step_seconds",
            "output_interval_seconds",
            "initial_water_level",
            "initial_flow",
            "storage_level",
        }
    }
    candidates = []
    for candidate in plan.candidates:
        overrides = [
            {
                "group_id": parameter.group_id,
                "cross_section_ids": [int(value) for value in parameter.target_ids],
                "manning_n": candidate.overrides[f"manning_n:{parameter.group_id}"],
            }
            for parameter in payload.sweep.parameters
        ]
        task_payload = {
            "case_id": run.case_id,
            **allowed_config,
            "roughness_overrides": overrides,
        }
        task = build_task_entity(
            session, SimulationTaskCreate.model_validate(task_payload)
        )
        candidates.append(candidate.model_copy(update={"task_id": task.id}))
    calibration = HydraulicCalibrationRun(
        production_run_id=run.id,
        run_code=payload.run_code,
        dataset_version_id=run.dataset_version_id,
        case_id=run.case_id,
        status="planned",
        calibration_dataset_json=payload.dataset.model_dump(mode="json"),
        parameter_groups_json=[
            item.model_dump(mode="json") for item in payload.sweep.parameters
        ],
        candidates_json=[item.model_dump(mode="json") for item in candidates],
        objective_json=payload.objective.model_dump(mode="json"),
    )
    session.add(calibration)
    session.flush()
    _audit(
        session,
        dataset_version_id=run.dataset_version_id,
        action="RUN_CREATION",
        actor=payload.actor,
        entity_type="calibration_run",
        entity_id=str(calibration.id),
        payload={
            "run_code": calibration.run_code,
            "production_run_id": run.id,
            "candidate_task_ids": [item.task_id for item in candidates],
        },
    )
    return CalibrationSweepRunResponse(
        run=CalibrationRunRecord.model_validate(calibration, from_attributes=True),
        candidates=candidates,
    )


def promote_calibration_candidate(
    session: Session, calibration_run_id: int, payload: CalibrationPromotionRequest
) -> CalibrationPromotionResponse:
    """Accept one qualified candidate and advance only its bound production run."""

    calibration = session.get(HydraulicCalibrationRun, calibration_run_id)
    if calibration is None:
        raise ValueError("Calibration Run does not exist")
    if calibration.status != "completed":
        raise ValueError("Calibration candidate promotion requires a completed run")
    matches = [
        item
        for item in calibration.candidates_json
        if item.get("candidate_id") == payload.candidate_id and item.get("qualified") is True
    ]
    if len(matches) != 1:
        raise ValueError("Calibration candidate is missing, duplicated, or unqualified")
    selected_task_id = matches[0].get("task_id")
    selected_task = (
        session.get(SimulationTask, selected_task_id)
        if isinstance(selected_task_id, int)
        else None
    )
    if selected_task is None or selected_task.status != "success":
        raise ValueError("Accepted calibration candidate has no successful immutable task")
    selected_candidate = CalibrationCandidate.model_validate(matches[0])
    criteria_passed, criteria_checks = evaluate_project_metric_criteria(
        selected_candidate.metrics,
        payload.acceptance_criteria,
        _task_mass_balance(selected_task),
    )
    if not criteria_passed:
        raise ValueError("Calibration candidate did not pass the declared acceptance criteria")
    now = datetime.now(UTC)
    calibration.status = "accepted"
    calibration.selected_candidate_id = payload.candidate_id
    calibration.accepted_by = payload.accepted_by
    calibration.accepted_at = now
    run = session.get(HydraulicProductionRun, calibration.production_run_id)
    if run is None or run.model_state not in {"QA_PASSED", "CALIBRATED"}:
        raise ValueError("Bound Production Run cannot enter CALIBRATED state")
    formal_task_payload = {
        "case_id": run.case_id,
        **{
            key: value
            for key, value in selected_task.config.items()
            if key
            in {
                "duration_seconds",
                "time_step_seconds",
                "output_interval_seconds",
                "initial_water_level",
                "initial_flow",
                "storage_level",
                "roughness_overrides",
            }
        },
    }
    formal_task = build_task_entity(
        session, SimulationTaskCreate.model_validate(formal_task_payload)
    )
    qa_request = HydraulicModelQARequest.model_validate(
        run.input_snapshot_json.get("qa_request")
    )
    qa_result = HydraulicModelQAResult.model_validate(
        run.input_snapshot_json.get("qa_result")
    )
    formal_model = parse_frozen_task_model(formal_task)
    formal_digest = str(formal_task.input_snapshot_hash or "")
    formal_gate = build_production_gate(
        qa_request, qa_result, formal_model, formal_digest
    )
    formal_task.config = {
        **formal_task.config,
        "production_mode": True,
        "production_gate": formal_gate,
    }
    run.task_id = formal_task.id
    run.model_state = "CALIBRATED"
    run.input_snapshot_hash = formal_digest
    run.input_snapshot_json = {
        "model": formal_task.input_snapshot,
        "qa_request": qa_request.model_dump(mode="json"),
        "qa_result": qa_result.model_dump(mode="json"),
        "production_gate_hash": formal_gate["gate_hash"],
        "promoted_from_candidate_task_id": selected_task.id,
    }
    run.engine_provenance_json = {
        "engine_version": formal_task.engine_version,
        "engine_commit": formal_task.engine_commit,
        "solver_build_id": formal_task.solver_build_id,
        "solver_id": formal_task.solver_id,
        "capability_id": formal_task.capability_id,
        "registry_hash": formal_task.registry_hash,
    }
    run.runtime_provenance_json = {}
    run.mass_balance_relative_error = None
    details = {
        "calibration_run_id": calibration.id,
        "candidate_id": payload.candidate_id,
        "acceptance_reason": payload.acceptance_reason,
        "acceptance_criteria": payload.acceptance_criteria.model_dump(mode="json"),
        "acceptance_checks": criteria_checks,
        "overrides": matches[0].get("overrides", {}),
        "formal_task_id": formal_task.id,
    }
    _audit(
        session,
        dataset_version_id=calibration.dataset_version_id,
        action="CALIBRATION_ACCEPTANCE",
        actor=payload.accepted_by,
        entity_type="calibration_run",
        entity_id=str(calibration.id),
        payload=details,
    )
    _audit(
        session,
        dataset_version_id=calibration.dataset_version_id,
        action="PARAMETER_PROMOTION",
        actor=payload.accepted_by,
        entity_type="production_run",
        entity_id=str(run.id),
        payload=details,
    )
    session.flush()
    return CalibrationPromotionResponse(
        calibration=CalibrationRunRecord.model_validate(calibration, from_attributes=True),
        production_run=ProductionRunRecord.model_validate(run, from_attributes=True),
    )


def commit_validation_run(
    session: Session, payload: ValidationRunCommitRequest
) -> ValidationRunRecord:
    _require_dataset(session, payload.dataset_version_id)
    _require_case(session, payload.case_id, payload.dataset_version_id)
    run = _require_production_run(
        session, payload.production_run_id, payload.dataset_version_id, payload.case_id
    )
    if run.model_state != "CALIBRATED":
        raise ValueError("Formal validation requires a CALIBRATED Production Run")
    formal_task = session.get(SimulationTask, run.task_id)
    if formal_task is None or formal_task.status != "success":
        raise ValueError("Formal validation requires a successful promoted Production task")
    if payload.mass_balance_relative_error is not None and (
        run.mass_balance_relative_error is None
        or not isclose(
            payload.mass_balance_relative_error,
            run.mass_balance_relative_error,
            rel_tol=1e-12,
            abs_tol=1e-15,
        )
    ):
        raise ValueError(
            "Validation mass balance must match the persisted formal task diagnostic"
        )
    independence = evaluate_validation_independence(
        payload.calibration_dataset, payload.validation_dataset
    )
    evaluation = evaluate_acceptance(
        AcceptanceEvaluationRequest(
            metrics=payload.metrics,
            criteria=payload.criteria,
            independence=independence,
            mass_balance_relative_error=run.mass_balance_relative_error,
        )
    )
    status = "passed" if evaluation.criteria_passed else "failed"
    row = HydraulicModelValidationAssessment(
        production_run_id=run.id,
        validation_code=payload.validation_code,
        dataset_version_id=payload.dataset_version_id,
        case_id=payload.case_id,
        calibration_run_id=payload.calibration_run_id,
        status=status,
        validation_dataset_json=payload.validation_dataset.model_dump(mode="json"),
        independence_json=independence.model_dump(mode="json"),
        criteria_json=payload.criteria.model_dump(mode="json"),
        metrics_json=[item.model_dump(mode="json") for item in payload.metrics],
        evaluation_json=evaluation.model_dump(mode="json"),
    )
    session.add(row)
    session.flush()
    if status == "passed":
        run.model_state = "VALIDATED"
        _audit(
            session,
            dataset_version_id=payload.dataset_version_id,
            action="VALIDATION_ACCEPTANCE",
            actor=payload.actor,
            entity_type="model_validation_assessment",
            entity_id=str(row.id),
            payload={
                "validation_code": row.validation_code,
                "independent": independence.independent,
                "criteria_passed": evaluation.criteria_passed,
            },
        )
    return ValidationRunRecord.model_validate(row, from_attributes=True)


def approve_production_run(
    session: Session, run_id: int, payload: ProductionApprovalRequest
) -> ProductionRunRecord:
    """Require professional approval after a persisted passing validation."""

    run = session.get(HydraulicProductionRun, run_id)
    if run is None:
        raise ValueError("Production Run does not exist")
    if run.model_state != "VALIDATED":
        raise ValueError("Production approval requires VALIDATED model state")
    passing = session.scalar(
        select(HydraulicModelValidationAssessment.id).where(
            HydraulicModelValidationAssessment.production_run_id == run.id,
            HydraulicModelValidationAssessment.status == "passed",
        )
    )
    if passing is None:
        raise ValueError("Production approval requires persisted passing validation evidence")
    run.model_state = "PRODUCTION_APPROVED"
    run.approved_by = payload.approved_by
    run.approved_at = datetime.now(UTC)
    _audit(
        session,
        dataset_version_id=run.dataset_version_id,
        action="PRODUCTION_APPROVAL",
        actor=payload.approved_by,
        entity_type="production_run",
        entity_id=str(run.id),
        payload={"approval_reason": payload.approval_reason, "validation_id": passing},
    )
    session.flush()
    return ProductionRunRecord.model_validate(run, from_attributes=True)


def commit_result_product(
    session: Session, payload: ResultProductCommitRequest
) -> ResultProductRecord:
    run = session.get(HydraulicProductionRun, payload.production_run_id)
    if run is None:
        raise ValueError("Production Run does not exist")
    bundle = build_result_products(payload.request)
    product_payload = bundle.model_dump(mode="json")
    product_hash = snapshot_hash(product_payload)
    row = HydraulicResultProduct(
        product_code=payload.product_code,
        production_run_id=run.id,
        schema_version="dayu.hydraulic-result-product.v1",
        product_hash=product_hash,
        payload_json=product_payload,
    )
    session.add(row)
    session.flush()
    _audit(
        session,
        dataset_version_id=run.dataset_version_id,
        action="EXPORT",
        actor=payload.actor,
        entity_type="result_product",
        entity_id=str(row.id),
        payload={"product_code": row.product_code, "product_hash": product_hash},
    )
    return ResultProductRecord.model_validate(row, from_attributes=True)


def list_audit_events(
    session: Session, dataset_version_id: int | None = None
) -> list[AuditEventRecord]:
    statement = select(HydraulicProductionAuditEvent)
    if dataset_version_id is not None:
        statement = statement.where(
            HydraulicProductionAuditEvent.dataset_version_id == dataset_version_id
        )
    rows = session.scalars(statement.order_by(HydraulicProductionAuditEvent.id.desc())).all()
    return [AuditEventRecord.model_validate(row, from_attributes=True) for row in rows]


__all__ = [name for name in globals() if name.startswith(("commit_", "create_", "list_"))]
