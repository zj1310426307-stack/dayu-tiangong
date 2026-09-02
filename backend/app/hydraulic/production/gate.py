"""Bind the centralized Production QA result to an immutable task snapshot."""

from __future__ import annotations

from collections.abc import Mapping
from hmac import compare_digest
from typing import Any, NoReturn

from app.hydraulic.production.contracts import (
    HydraulicModelQARequest,
    HydraulicModelQAResult,
)
from app.hydraulic.production.qa import HydraulicModelQA
from model.hydraulic_1d import Hydraulic1DModel
from model.hydraulic_1d.errors import Hydraulic1DValidationError
from model.provenance import snapshot_hash


PRODUCTION_GATE_SCHEMA = "dayu.hydraulic-production-gate.v1"


def _model_identity(model: Hydraulic1DModel) -> dict[str, Any]:
    """Return QA-relevant identities that must agree with the frozen model."""

    metadata = model.metadata
    return {
        "engineering_crs": metadata.get("engineering_crs"),
        "vertical_datum": metadata.get("vertical_datum"),
        "duration_seconds": model.settings.duration_seconds,
        "branch_ids": sorted(item.id for item in model.branches),
        "cross_section_ids": sorted(item.id for item in model.cross_sections),
        "boundary_ids": sorted(item.id for item in model.boundaries),
        "structure_ids": sorted(item.id for item in model.structures if item.status == "active"),
    }


def _qa_identity(request: HydraulicModelQARequest) -> dict[str, Any]:
    """Return the corresponding identities from the reviewed QA input."""

    return {
        "engineering_crs": request.engineering_crs,
        "vertical_datum": request.vertical_datum,
        "duration_seconds": request.simulation_duration_seconds,
        "branch_ids": sorted(item.branch_id for item in request.branches),
        "cross_section_ids": sorted(item.section_id for item in request.cross_sections),
        "boundary_ids": sorted(item.boundary_id for item in request.boundaries),
        "structure_ids": sorted(
            item.structure_id for item in request.structures if item.status == "active"
        ),
    }


def _reject(message: str) -> NoReturn:
    """Raise one stable pre-runtime production gate error."""

    raise Hydraulic1DValidationError(
        "DAYU_PRODUCTION_QA_GATE_FAILED",
        message,
        field_path="simulation_task.config.production_gate",
    )


def build_production_gate(
    request: HydraulicModelQARequest,
    result: HydraulicModelQAResult,
    model: Hydraulic1DModel,
    input_snapshot_hash: str,
) -> dict[str, Any]:
    """Create a server-owned gate after matching QA input to the frozen task."""

    if not result.run_allowed or result.error_count:
        _reject("centralized QA contains blocking errors")
    model_identity = _model_identity(model)
    qa_identity = _qa_identity(request)
    if model_identity != qa_identity:
        differing = sorted(
            key for key in model_identity if model_identity[key] != qa_identity.get(key)
        )
        _reject(f"QA input does not describe the frozen model fields: {differing}")
    evidence = {
        "schema_version": PRODUCTION_GATE_SCHEMA,
        "input_snapshot_hash": input_snapshot_hash,
        "qa_request": request.model_dump(mode="json"),
        "qa_result": result.model_dump(mode="json"),
        "model_identity": model_identity,
    }
    return {**evidence, "gate_hash": snapshot_hash(evidence)}


def assert_production_gate(
    config: Mapping[str, Any],
    model: Hydraulic1DModel,
    input_snapshot_hash: str,
) -> None:
    """Re-evaluate a production gate inside the Worker before engine execution."""

    if not config.get("production_mode"):
        return
    raw = config.get("production_gate")
    if not isinstance(raw, Mapping):
        _reject("production task has no server QA envelope")
    evidence = {key: value for key, value in raw.items() if key != "gate_hash"}
    observed_hash = raw.get("gate_hash")
    if not isinstance(observed_hash, str) or not compare_digest(
        snapshot_hash(evidence), observed_hash
    ):
        _reject("production QA envelope digest is invalid")
    if raw.get("schema_version") != PRODUCTION_GATE_SCHEMA:
        _reject("production QA envelope schema is unsupported")
    if raw.get("input_snapshot_hash") != input_snapshot_hash:
        _reject("production QA envelope belongs to another task snapshot")
    try:
        request = HydraulicModelQARequest.model_validate(raw.get("qa_request"))
        expected = HydraulicModelQAResult.model_validate(raw.get("qa_result"))
    except ValueError as exc:
        _reject(f"production QA envelope is invalid: {exc}")
    current = HydraulicModelQA().validate(request)
    if current != expected or not current.run_allowed or current.error_count:
        _reject("production QA result is no longer reproducible or contains errors")
    if _model_identity(model) != _qa_identity(request):
        _reject("production QA input no longer matches the frozen model")


__all__ = ["assert_production_gate", "build_production_gate"]
