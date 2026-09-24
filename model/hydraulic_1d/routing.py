"""Resolve explicit Engine routes before a hydraulic Task reaches a runtime."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from model.hydraulic_1d.capabilities import (
    CapabilityStatus,
    SolverCapability,
    capabilities_for,
    required_capabilities,
)
from model.hydraulic_1d.contracts import Hydraulic1DModel
from model.hydraulic_1d.errors import Hydraulic1DValidationError
from model.hydraulic_1d.registry import (
    HydraulicEngineRegistration,
    engine_registration,
    task_engine_provenance_for,
)


class ExecutionClass(StrEnum):
    """Classify a run without changing the Engine's production eligibility."""

    PRODUCTION = "production"
    PILOT = "pilot"
    SYNTHETIC = "synthetic"


class FrozenEngineTask(Protocol):
    """Describe the frozen identity fields required before Worker execution."""

    engine_id: str | None
    execution_class: str | None
    engine_version: str | None
    solver_id: str | None
    capability_id: str | None
    runtime_adapter_id: str | None
    result_schema_version: str | None
    registry_hash: str | None


def resolve_engine_registration(engine_id: str | None) -> HydraulicEngineRegistration:
    """Resolve one explicit registration and forbid missing/unknown Engine IDs."""

    if not isinstance(engine_id, str) or not engine_id:
        raise Hydraulic1DValidationError(
            "HYDRAULIC_TASK_ENGINE_IDENTITY_MISSING",
            "hydraulic task has no frozen engine_id",
            field_path="simulation_task.engine_id",
        )
    try:
        return engine_registration(engine_id)
    except KeyError as exc:
        raise Hydraulic1DValidationError(
            "HYDRAULIC_ENGINE_NOT_REGISTERED",
            f"hydraulic engine is not registered: {engine_id}",
            field_path="engine_id",
        ) from exc


def parse_execution_class(value: str | None) -> ExecutionClass:
    """Return the only executable run classes; unknown values fail closed."""

    try:
        return ExecutionClass(value or "")
    except ValueError as exc:
        raise Hydraulic1DValidationError(
            "HYDRAULIC_ENGINE_EXECUTION_CLASS_FORBIDDEN",
            f"hydraulic execution class is not allowed: {value!r}",
            field_path="simulation_task.execution_class",
        ) from exc


def validate_engine_execution_class(
    registration: HydraulicEngineRegistration,
    execution_class: ExecutionClass,
) -> None:
    """Reject production promotion and unregistered Engine/class combinations."""

    # Production eligibility is an engineering commitment, not merely a
    # configurable class preference.  Expose that precise failure to callers.
    if execution_class is ExecutionClass.PRODUCTION and not registration.production_eligible:
        raise Hydraulic1DValidationError(
            "HYDRAULIC_ENGINE_NOT_PRODUCTION_ELIGIBLE",
            f"{registration.engine_id} is not production eligible",
            field_path="execution_class",
        )
    if execution_class.value not in registration.allowed_execution_classes:
        raise Hydraulic1DValidationError(
            "HYDRAULIC_ENGINE_EXECUTION_CLASS_FORBIDDEN",
            (
                f"{registration.engine_id} cannot execute as {execution_class.value}; "
                f"allowed={','.join(registration.allowed_execution_classes)}"
            ),
            field_path="execution_class",
        )


def _capability_allowed(
    capability: SolverCapability,
    execution_class: ExecutionClass,
) -> bool:
    """Apply evidence requirements consistently for every selected Engine."""

    verified = {
        CapabilityStatus.VERIFIED_NATIVE,
        CapabilityStatus.VERIFIED_EQUIVALENT,
    }
    if execution_class is ExecutionClass.PRODUCTION:
        return capability.status in verified
    if execution_class is ExecutionClass.SYNTHETIC:
        return capability.synthetic_status == "ACCEPTED"
    return capability.status not in {
        CapabilityStatus.UNSUPPORTED,
        CapabilityStatus.UNVERIFIED,
    }


def validate_required_capabilities(
    model: Hydraulic1DModel,
    *,
    engine_id: str | None,
    execution_class: str | None,
) -> tuple[str, ...]:
    """Validate the model once against the explicit Engine and run class."""

    registration = resolve_engine_registration(engine_id)
    selected_class = parse_execution_class(execution_class)
    validate_engine_execution_class(registration, selected_class)
    matrix = {
        item.feature: item
        for item in capabilities_for(
            registration.engine_id,
            registration.engine_version,
        )
    }
    required = required_capabilities(model)
    issues: list[str] = []
    for feature in required:
        capability = matrix.get(feature)
        if capability is None:
            issues.append(f"{feature}=UNSUPPORTED")
        elif not _capability_allowed(capability, selected_class):
            issues.append(f"{feature}={capability.status.value}")
    if issues:
        code = (
            "HYDRAULIC_ENGINE_CAPABILITY_UNSUPPORTED"
            if any("UNSUPPORTED" in item for item in issues)
            else "HYDRAULIC_ENGINE_CAPABILITY_UNVERIFIED"
        )
        raise Hydraulic1DValidationError(
            code,
            (
                f"{registration.engine_id} cannot run {selected_class.value}; "
                f"required capability issues: {', '.join(issues)}"
            ),
            field_path="capabilities",
        )
    return required


def validate_frozen_task_identity(task: FrozenEngineTask) -> HydraulicEngineRegistration:
    """Ensure stored Task identity exactly matches the registered Engine route."""

    registration = resolve_engine_registration(task.engine_id)
    validate_engine_execution_class(registration, parse_execution_class(task.execution_class))
    expected = task_engine_provenance_for(registration.engine_id)
    observed = {
        "solver_id": task.solver_id,
        "capability_id": task.capability_id,
        "runtime_adapter_id": task.runtime_adapter_id,
        "result_schema_version": task.result_schema_version,
        "registry_hash": task.registry_hash,
    }
    required = {
        **expected,
    }
    mismatches = [
        f"{field}: task={observed[field]!r}, registered={value!r}"
        for field, value in required.items()
        if observed[field] != value
    ]
    if mismatches:
        raise Hydraulic1DValidationError(
            "HYDRAULIC_TASK_ENGINE_IDENTITY_MISMATCH",
            "; ".join(mismatches),
            field_path="simulation_task",
        )
    return registration
