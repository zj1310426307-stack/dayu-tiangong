"""Task create contract and v4 summary compatibility tests."""

import pytest
from pydantic import ValidationError

from app.model_engine.provenance import snapshot_summary
from app.model_engine.schemas import SimulationTaskCreate
from model.solver.registry import D1_SOLVER_ID
from tests.model_engine.helpers import native_v4_payload


def test_v4_task_requires_registered_solver_and_frozen_plan() -> None:
    """Keep every physical value in the snapshot rather than task.config overrides."""

    payload = SimulationTaskCreate(
        case_id=71,
        input_schema_version="dayu.model-input.v4",
        solver_id=D1_SOLVER_ID,
        dispatch_plan_id=91,
        execution_mode="validation",
        storage_level="full",
    )
    assert payload.solver_id == D1_SOLVER_ID
    assert payload.dispatch_plan_id == 91

    with pytest.raises(ValidationError, match="runtime physical overrides"):
        SimulationTaskCreate(
            case_id=71,
            input_schema_version="dayu.model-input.v4",
            solver_id=D1_SOLVER_ID,
            dispatch_plan_id=91,
            duration_seconds=21600.0,
        )
    with pytest.raises(ValidationError, match="requires solver_id"):
        SimulationTaskCreate(
            case_id=71,
            input_schema_version="dayu.model-input.v4",
            solver_id="legacy-network-continuity-manning-v1",
            dispatch_plan_id=91,
        )


def test_v1_v2_v3_task_contract_remains_compatible() -> None:
    """Preserve legacy defaults and reject only the v4-specific plan field."""

    legacy = SimulationTaskCreate(case_id=1)
    assert legacy.input_schema_version == "dayu.model-input.v1"
    assert legacy.duration_seconds is None
    with pytest.raises(ValidationError, match="reserved for v4"):
        SimulationTaskCreate(case_id=1, dispatch_plan_id=91)


def test_native_v4_snapshot_summary_reads_nested_structures() -> None:
    """Keep large snapshots out of task lists while reporting accurate v4 counts."""

    summary = snapshot_summary(native_v4_payload())
    assert summary["river_count"] == 1
    assert summary["section_count"] == 20
    assert summary["boundary_count"] == 2
    assert summary["gate_count"] == 1
    assert summary["pump_count"] == 1
