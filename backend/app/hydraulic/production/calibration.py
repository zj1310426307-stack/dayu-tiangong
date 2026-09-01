"""Bounded manual calibration, sweep ranking, and independent validation gates."""

from __future__ import annotations

from datetime import UTC
from hashlib import sha256
import itertools
import json
from typing import Any

from app.hydraulic.production.contracts import (
    AcceptanceCriteria,
    AcceptanceEvaluation,
    AcceptanceEvaluationRequest,
    CalibrationCandidate,
    CalibrationRankingRequest,
    DatasetWindow,
    HydraulicMetrics,
    ParameterSweepPlan,
    ParameterSweepRequest,
    QAIssue,
    ValidationIndependenceResult,
)


def _candidate_id(overrides: dict[str, float]) -> str:
    """Derive a stable identity from canonical parameter overrides."""

    payload = json.dumps(overrides, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"candidate-{sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def build_parameter_sweep(request: ParameterSweepRequest) -> ParameterSweepPlan:
    """Build deterministic candidates and reject Cartesian combination explosion."""

    group_ids = [item.group_id for item in request.parameters]
    if len(group_ids) != len(set(group_ids)):
        raise ValueError("calibration parameter group_id values must be unique")
    candidate_count = 1
    for parameter in request.parameters:
        candidate_count *= len(parameter.values)
        if candidate_count > request.max_runs:
            raise ValueError(
                f"parameter sweep requires {candidate_count} runs, exceeding max_runs="
                f"{request.max_runs}; reduce ranges or parameter groups"
            )
    candidates: list[CalibrationCandidate] = []
    for values in itertools.product(*(parameter.values for parameter in request.parameters)):
        overrides = {
            f"{parameter.parameter}:{parameter.group_id}": float(value)
            for parameter, value in zip(request.parameters, values)
        }
        candidates.append(
            CalibrationCandidate(candidate_id=_candidate_id(overrides), overrides=overrides)
        )
    return ParameterSweepPlan(
        total_candidates=len(candidates),
        max_runs=request.max_runs,
        candidates=candidates,
    )


def _metric_by_key(metrics: list[HydraulicMetrics]) -> dict[str, float]:
    """Flatten only finite, sufficient metrics into explicit objective keys."""

    flattened: dict[str, float] = {}
    for metric in metrics:
        if not metric.sufficient_samples:
            continue
        values: dict[str, float | None] = {
            "mae": metric.mae,
            "rmse": metric.rmse,
            "bias": abs(metric.bias) if metric.bias is not None else None,
            "nse": 1.0 - metric.nse if metric.nse is not None else None,
            "r_squared": 1.0 - metric.r_squared if metric.r_squared is not None else None,
            "peak_value_error": (
                abs(metric.peak_value_error) if metric.peak_value_error is not None else None
            ),
            "peak_relative_error": (
                abs(metric.peak_relative_error) if metric.peak_relative_error is not None else None
            ),
            "peak_time_error_seconds": (
                abs(metric.peak_time_error_seconds)
                if metric.peak_time_error_seconds is not None
                else None
            ),
        }
        for name, value in values.items():
            if value is not None:
                flattened[f"{metric.variable}.{name}"] = float(value)
    return flattened


def rank_calibration_candidates(
    request: CalibrationRankingRequest,
) -> list[CalibrationCandidate]:
    """Rank completed candidates using the user-declared weighted loss formula."""

    weights = {key: float(value) for key, value in request.objective.weights.items()}
    total_weight = sum(weights.values())
    evaluated: list[CalibrationCandidate] = []
    for candidate in request.candidates:
        values = _metric_by_key(candidate.metrics)
        qualified = candidate.status == "completed" and all(key in values for key in weights)
        score = (
            sum(weights[key] * values[key] for key in weights) / total_weight
            if qualified
            else None
        )
        evaluated.append(
            candidate.model_copy(
                update={"qualified": qualified, "objective_score": score, "rank": None}
            )
        )
    qualified = sorted(
        (item for item in evaluated if item.qualified),
        key=lambda item: (float(item.objective_score or 0.0), item.candidate_id),
    )
    rank_by_id = {item.candidate_id: rank for rank, item in enumerate(qualified, start=1)}
    return [
        item.model_copy(update={"rank": rank_by_id.get(item.candidate_id)})
        for item in sorted(
            evaluated,
            key=lambda value: (
                not value.qualified,
                float(value.objective_score) if value.objective_score is not None else float("inf"),
                value.candidate_id,
            ),
        )
    ]


def evaluate_validation_independence(
    calibration: DatasetWindow,
    validation: DatasetWindow,
) -> ValidationIndependenceResult:
    """Reject reused evidence and distinguish temporal holdout from an independent event."""

    if calibration.role != "calibration" or validation.role != "validation":
        raise ValueError("dataset windows must have calibration and validation roles")
    overlap_start = max(calibration.start_time.astimezone(UTC), validation.start_time.astimezone(UTC))
    overlap_end = min(calibration.end_time.astimezone(UTC), validation.end_time.astimezone(UTC))
    shared_stations = set(calibration.station_ids) & set(validation.station_ids)
    overlaps = overlap_start < overlap_end and bool(shared_stations)
    same_data = (
        calibration.dataset_id == validation.dataset_id
        and calibration.event_id == validation.event_id
        and set(calibration.station_ids) == set(validation.station_ids)
        and calibration.start_time == validation.start_time
        and calibration.end_time == validation.end_time
    )
    issues: list[QAIssue] = []
    if same_data or validation.holdout_type == "same_data":
        issues.append(
            QAIssue(
                code="VALIDATION_DATA_REUSED",
                severity="ERROR",
                category="Observation",
                entity_type="ValidationDataset",
                entity_id=validation.dataset_id,
                message="Calibration data cannot be presented as independent validation evidence.",
            )
        )
        return ValidationIndependenceResult(
            independent=False,
            temporal_holdout=False,
            issues=issues,
        )
    if overlaps:
        issues.append(
            QAIssue(
                code="VALIDATION_WINDOW_OVERLAP",
                severity="WARNING",
                category="Observation",
                entity_type="ValidationDataset",
                entity_id=validation.dataset_id,
                message="Calibration and validation windows overlap at shared stations.",
                context={"shared_stations": sorted(shared_stations)},
            )
        )
    temporal = validation.holdout_type == "temporal_holdout"
    if temporal:
        issues.append(
            QAIssue(
                code="VALIDATION_TEMPORAL_HOLDOUT",
                severity="INFO",
                category="Observation",
                entity_type="ValidationDataset",
                entity_id=validation.dataset_id,
                message="Validation is a temporal holdout, not an independent flood event.",
            )
        )
    independent = (
        validation.holdout_type == "independent_event"
        and calibration.event_id != validation.event_id
        and not overlaps
    )
    if not independent and not temporal:
        issues.append(
            QAIssue(
                code="VALIDATION_INDEPENDENCE_NOT_PROVEN",
                severity="ERROR",
                category="Observation",
                entity_type="ValidationDataset",
                entity_id=validation.dataset_id,
                message="Independent validation evidence has not been proven.",
            )
        )
    return ValidationIndependenceResult(
        independent=independent,
        temporal_holdout=temporal,
        issues=issues,
    )


def _metric_for(
    metrics: list[HydraulicMetrics], variable: str
) -> HydraulicMetrics | None:
    """Return the unique metric record for one physical variable."""

    matches = [item for item in metrics if item.variable == variable]
    if len(matches) > 1:
        raise ValueError(f"more than one metric record supplied for {variable}")
    return matches[0] if matches else None


def evaluate_project_metric_criteria(
    metrics: list[HydraulicMetrics],
    criteria: AcceptanceCriteria,
    mass_balance_relative_error: float | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    """Evaluate only declared project metrics for calibration or validation."""

    water = _metric_for(metrics, "water_level")
    discharge = _metric_for(metrics, "discharge")
    checks: list[dict[str, Any]] = []

    def maximum(name: str, actual: float | None, limit: float | None) -> None:
        if limit is None:
            return
        passed = actual is not None and abs(actual) <= limit
        checks.append({"criterion": name, "actual": actual, "limit": limit, "passed": passed})

    def minimum(name: str, actual: float | None, limit: float | None) -> None:
        if limit is None:
            return
        passed = actual is not None and actual >= limit
        checks.append({"criterion": name, "actual": actual, "limit": limit, "passed": passed})

    maximum(
        "maximum_water_level_rmse",
        water.rmse if water else None,
        criteria.maximum_water_level_rmse,
    )
    maximum(
        "maximum_discharge_rmse",
        discharge.rmse if discharge else None,
        criteria.maximum_discharge_rmse,
    )
    peak_relative_values = [
        abs(item.peak_relative_error)
        for item in metrics
        if item.peak_relative_error is not None
    ]
    maximum(
        "maximum_peak_relative_error",
        max(peak_relative_values) if peak_relative_values else None,
        criteria.maximum_peak_relative_error,
    )
    peak_time_values = [
        abs(item.peak_time_error_seconds)
        for item in metrics
        if item.peak_time_error_seconds is not None
    ]
    maximum(
        "maximum_peak_time_error_seconds",
        max(peak_time_values) if peak_time_values else None,
        criteria.maximum_peak_time_error_seconds,
    )
    nse_values = [item.nse for item in metrics if item.nse is not None]
    minimum("minimum_nse", min(nse_values) if nse_values else None, criteria.minimum_nse)
    r2_values = [item.r_squared for item in metrics if item.r_squared is not None]
    minimum(
        "minimum_r_squared",
        min(r2_values) if r2_values else None,
        criteria.minimum_r_squared,
    )
    coverage_values = [item.coverage_ratio for item in metrics]
    minimum(
        "minimum_observation_coverage",
        min(coverage_values) if coverage_values else None,
        criteria.minimum_observation_coverage,
    )
    maximum(
        "maximum_mass_balance_relative_error",
        mass_balance_relative_error,
        criteria.maximum_mass_balance_relative_error,
    )
    return bool(checks) and all(bool(item["passed"]) for item in checks), checks


def evaluate_acceptance(request: AcceptanceEvaluationRequest) -> AcceptanceEvaluation:
    """Evaluate project criteria and independent evidence without human self-approval."""

    metrics_passed, checks = evaluate_project_metric_criteria(
        request.metrics,
        request.criteria,
        request.mass_balance_relative_error,
    )
    checks.append(
        {
            "criterion": "independent_validation_dataset",
            "actual": request.independence.independent,
            "limit": True,
            "passed": request.independence.independent,
        }
    )
    passed = metrics_passed and request.independence.independent
    return AcceptanceEvaluation(
        criteria_passed=passed,
        model_state="VALIDATED" if passed else "CALIBRATED",
        checks=checks,
        professional_approval_required=True,
    )


__all__ = [
    "build_parameter_sweep",
    "evaluate_acceptance",
    "evaluate_project_metric_criteria",
    "evaluate_validation_independence",
    "rank_calibration_candidates",
]
