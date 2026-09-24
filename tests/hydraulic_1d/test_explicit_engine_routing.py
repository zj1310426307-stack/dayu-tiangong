"""Enforce frozen multi-Engine task routing without solver fallback."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from model.hydraulic_1d import HydraulicStructure
from model.hydraulic_1d.errors import Hydraulic1DValidationError
from model.hydraulic_1d.registry import (
    DEFAULT_HYDRAULIC_1D_ENGINE_ID,
    DFLOW_FM_ENGINE_ID,
    engine_catalog_payload,
    task_engine_provenance_for,
)
from model.hydraulic_1d.routing import (
    validate_frozen_task_identity,
    validate_required_capabilities,
)
from tests.hydraulic_1d.helpers import model_fixture


def _model_with_structure(kind: str):
    """Attach one active Structure so routing derives its required capability."""

    source = model_fixture()
    return source.model_copy(
        update={
            "structures": (
                HydraulicStructure(
                    id=f"{kind}-1",
                    name=f"Synthetic {kind}",
                    branch_id="branch-1",
                    kind=kind,
                    chainage_m=500.0,
                    status="active",
                ),
            )
        }
    )


def _frozen_task(engine_id: str, execution_class: str) -> SimpleNamespace:
    """Build one complete identity envelope independent of database fixtures."""

    return SimpleNamespace(
        engine_id=engine_id,
        execution_class=execution_class,
        engine_version="dayu-hydraulic-platform-5.0.0",
        **task_engine_provenance_for(engine_id),
    )


def test_catalog_exposes_evidence_and_allowed_execution_classes() -> None:
    """The API catalog must distinguish verified production from synthetic evidence."""

    rows = {item["engine_id"]: item for item in engine_catalog_payload()["engines"]}
    assert rows["mascaret"]["evidence_class"] == "VERIFIED_NATIVE"
    assert rows["mascaret"]["allowed_execution_classes"] == [
        "production",
        "pilot",
        "synthetic",
    ]
    assert rows[DFLOW_FM_ENGINE_ID]["evidence_class"] == "SYNTHETIC_NUMERICAL_ONLY"
    assert rows[DFLOW_FM_ENGINE_ID]["production_eligible"] is False
    assert rows[DFLOW_FM_ENGINE_ID]["allowed_execution_classes"] == [
        "pilot",
        "synthetic",
    ]


def test_capability_routing_is_explicit_and_fail_closed() -> None:
    """Exercise MASCARET/D-Flow capability selection without any automatic fallback."""

    assert validate_required_capabilities(
        model_fixture(),
        engine_id=DEFAULT_HYDRAULIC_1D_ENGINE_ID,
        execution_class="production",
    ) == ("UNSTEADY_1D",)

    gate_model = _model_with_structure("gate")
    with pytest.raises(Hydraulic1DValidationError) as mascaret_gate:
        validate_required_capabilities(
            gate_model,
            engine_id=DEFAULT_HYDRAULIC_1D_ENGINE_ID,
            execution_class="production",
        )
    assert mascaret_gate.value.code == "HYDRAULIC_ENGINE_CAPABILITY_UNSUPPORTED"

    assert validate_required_capabilities(
        gate_model,
        engine_id=DFLOW_FM_ENGINE_ID,
        execution_class="synthetic",
    ) == ("GATE", "UNSTEADY_1D")

    with pytest.raises(Hydraulic1DValidationError) as dflow_production:
        validate_required_capabilities(
            gate_model,
            engine_id=DFLOW_FM_ENGINE_ID,
            execution_class="production",
        )
    assert dflow_production.value.code == "HYDRAULIC_ENGINE_NOT_PRODUCTION_ELIGIBLE"

    with pytest.raises(Hydraulic1DValidationError) as unsupported_subtype:
        validate_required_capabilities(
            _model_with_structure("sluice"),
            engine_id=DFLOW_FM_ENGINE_ID,
            execution_class="synthetic",
        )
    assert unsupported_subtype.value.code == "HYDRAULIC_ENGINE_CAPABILITY_UNVERIFIED"


def test_frozen_task_identity_cannot_change_engine_or_registry() -> None:
    """A task's Engine registration is immutable before a Worker may claim it."""

    task = _frozen_task(DEFAULT_HYDRAULIC_1D_ENGINE_ID, "production")
    assert validate_frozen_task_identity(task).engine_id == "mascaret"

    task.engine_id = DFLOW_FM_ENGINE_ID
    task.execution_class = "synthetic"
    with pytest.raises(Hydraulic1DValidationError) as mismatch:
        validate_frozen_task_identity(task)
    assert mismatch.value.code == "HYDRAULIC_TASK_ENGINE_IDENTITY_MISMATCH"


def test_production_code_has_no_parameterless_engine_factory_calls() -> None:
    """Prevent a future Worker or service change from restoring implicit routing."""

    repository = Path(__file__).resolve().parents[2]
    production_sources = [
        *repository.glob("backend/app/**/*.py"),
        *repository.glob("model/**/*.py"),
    ]
    offenders = [
        path.relative_to(repository).as_posix()
        for path in production_sources
        if "create_hydraulic_1d_engine()" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
