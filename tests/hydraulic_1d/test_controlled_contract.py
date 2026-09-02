"""Verify immutable controlled-run and result evidence contracts."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from model.hydraulic_1d.contracts import HydraulicResult
from model.hydraulic_1d.controlled import (
    DISPATCH_PLAN_V3_SCHEMA,
    ControlObservationBinding,
    ControlObservationContract,
    ControlRuntimeSelection,
    ControlledExecutionSettings,
    ControlledHydraulic1DRun,
    ControlledHydraulicResult,
    DispatchPlanSnapshot,
    EngineSelection,
    InitialActuatorState,
    RuntimeProvenanceRecord,
)
from model.hydraulic_1d.registry import (
    DFLOW_FM_ENGINE_ID,
    DFLOW_FM_ENGINE_VERSION,
    DFLOW_FM_UPSTREAM_COMMIT,
)
from model.provenance import canonical_json, snapshot_hash
from tests.hydraulic_1d.helpers import model_fixture


def _controlled_run() -> ControlledHydraulic1DRun:
    """Build one deterministic controlled snapshot with explicit initial state."""

    model = model_fixture()
    model_hash = snapshot_hash(model.model_dump(mode="json"))
    engine = EngineSelection.from_current_registry(runtime_mode="external")
    control = ControlRuntimeSelection(
        runtime_version="unverified-test-runtime",
        coupling_runtime_version="DIMRset_2026.02",
        compiler_id="dayu-drtc-compiler",
        compiler_version="v1-test",
    )
    observations = ControlObservationContract(
        sampling_interval_seconds=10.0,
        bindings=(
            ControlObservationBinding(
                observation_type="node_water_level",
                observation_object_id=1,
                source_kind="observation_point",
                source_id="observation-1",
                binding_evidence="SYNTHETIC_ASSUMPTION",
            ),
        ),
    )
    plan = DispatchPlanSnapshot(
        plan_payload_json=canonical_json(
            {
                "schema_version": DISPATCH_PLAN_V3_SCHEMA,
                "plan": {"id": 1, "version": 3},
                "actions": [],
                "rules": [],
            }
        ),
        hydraulic_model_snapshot_hash=model_hash,
        engine_registry_hash=engine.engine_registry_hash,
        control_compiler_version=control.compiler_version,
        initial_actuator_state=(
            InitialActuatorState(
                structure_type="gate",
                structure_id=1,
                gate_opening_m=0.25,
                evidence="SYNTHETIC_INITIAL_STATE",
            ),
        ),
        control_observation_contract=observations,
    )
    return ControlledHydraulic1DRun(
        hydraulic_model=model,
        hydraulic_model_snapshot_hash=model_hash,
        dispatch_plan_snapshot=plan,
        engine_selection=engine,
        control_runtime_selection=control,
        execution_settings=ControlledExecutionSettings(timeout_seconds=600.0),
    )


def _runtime_provenance() -> tuple[RuntimeProvenanceRecord, ...]:
    """Return the complete ordered four-component runtime identity."""

    records = []
    for index, component in enumerate(("dflowfm", "dimr", "fbc", "hydrolib-core")):
        records.append(
            RuntimeProvenanceRecord(
                component=component,
                version=(
                    DFLOW_FM_ENGINE_VERSION
                    if component == "dflowfm"
                    else f"unverified-test-{index}"
                ),
                upstream_tag=(
                    DFLOW_FM_ENGINE_VERSION
                    if component == "dflowfm"
                    else f"unverified-test-{index}"
                ),
                upstream_commit=(
                    DFLOW_FM_UPSTREAM_COMMIT
                    if component == "dflowfm"
                    else f"{index + 1:040x}"
                ),
                binary_sha256=f"{index + 1:064x}",
                source_manifest=f"metadata/{component}-source-manifest.json",
                platform="windows",
                architecture="amd64",
                build_timestamp=datetime(2026, 9, 2, tzinfo=timezone.utc),
            )
        )
    return tuple(records)


def test_controlled_run_freezes_v3_identity_and_synthetic_boundaries() -> None:
    """Bind the model, selected engines, compiler, and non-production evidence."""

    run = _controlled_run()
    assert len(run.snapshot_hash) == 64
    assert len(run.dispatch_plan_snapshot.snapshot_hash) == 64
    assert run.dispatch_plan_snapshot.hydraulic_feedback is True
    assert run.evidence_class == "SYNTHETIC_NUMERICAL_ONLY"
    assert run.execution_settings.development_mode is True
    assert run.execution_settings.production_mode is False
    assert run.real_engineering_validation is False
    assert run.real_equipment_command is False
    assert run.plc_scada_connected is False
    assert [
        item.component
        for item in run.dispatch_plan_snapshot.runtime_provenance_requirements
    ] == ["dflowfm", "dimr", "fbc", "hydrolib-core"]

    with pytest.raises(ValidationError, match="frozen"):
        run.snapshot_hash = "0" * 64


def test_controlled_run_rejects_evidence_escalation_and_snapshot_drift() -> None:
    """Make production claims and mismatched frozen identities unrepresentable."""

    run = _controlled_run()
    payload = run.model_dump(mode="python", exclude={"snapshot_hash"})
    payload["evidence_class"] = "PRODUCTION"
    with pytest.raises(ValidationError):
        ControlledHydraulic1DRun.model_validate(payload)

    payload = run.model_dump(mode="python", exclude={"snapshot_hash"})
    payload["real_equipment_command"] = True
    with pytest.raises(ValidationError):
        ControlledHydraulic1DRun.model_validate(payload)

    payload = run.model_dump(mode="python", exclude={"snapshot_hash"})
    payload["hydraulic_model_snapshot_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="does not match the model"):
        ControlledHydraulic1DRun.model_validate(payload)


def test_dispatch_snapshot_requires_canonical_v3_and_matching_digest() -> None:
    """Reject mutable-looking JSON text and supplied hashes that do not bind it."""

    run = _controlled_run()
    plan_payload = run.dispatch_plan_snapshot.model_dump(mode="python")
    plan_payload["plan_payload_json"] = '{ "schema_version": "dayu.dispatch-plan.v3" }'
    plan_payload["snapshot_hash"] = ""
    with pytest.raises(ValidationError, match="canonical JSON"):
        DispatchPlanSnapshot.model_validate(plan_payload)

    plan_payload = run.dispatch_plan_snapshot.model_dump(mode="python")
    plan_payload["snapshot_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="does not match"):
        DispatchPlanSnapshot.model_validate(plan_payload)


def test_controlled_result_composes_hydraulics_trace_and_complete_provenance() -> None:
    """Keep unified H/Q primary while binding controlled evidence and runtime identity."""

    run = _controlled_run()
    hydraulic_result = HydraulicResult(
        simulation_id=run.hydraulic_model.simulation_id,
        scenario_id=run.hydraulic_model.scenario_id,
        engine=DFLOW_FM_ENGINE_ID,
        engine_version=DFLOW_FM_ENGINE_VERSION,
        records=(),
    )
    result = ControlledHydraulicResult(
        run_snapshot_hash=run.snapshot_hash,
        hydraulic_result=hydraulic_result,
        dispatch_trace=(),
        control_events=(),
        structure_results=(),
        runtime_provenance=_runtime_provenance(),
    )
    assert len(result.result_hash) == 64
    assert result.evidence_class == "SYNTHETIC_NUMERICAL_ONLY"
    assert result.real_engineering_validation is False
    assert result.real_equipment_command is False
    assert result.plc_scada_connected is False

    with pytest.raises(ValidationError, match="frozen"):
        result.result_hash = "0" * 64

    wrong_engine = hydraulic_result.model_copy(update={"engine": "mascaret"})
    payload = result.model_dump(mode="python", exclude={"result_hash"})
    payload["hydraulic_result"] = wrong_engine
    with pytest.raises(ValidationError, match="pinned D-Flow FM"):
        ControlledHydraulicResult.model_validate(payload)


def test_result_rejects_incomplete_runtime_provenance() -> None:
    """Prevent a coupled result from omitting DIMR, FBC, or HYDROLIB identity."""

    run = _controlled_run()
    hydraulic_result = HydraulicResult(
        simulation_id=run.hydraulic_model.simulation_id,
        scenario_id=run.hydraulic_model.scenario_id,
        engine=DFLOW_FM_ENGINE_ID,
        engine_version=DFLOW_FM_ENGINE_VERSION,
        records=(),
    )
    with pytest.raises(ValidationError):
        ControlledHydraulicResult(
            run_snapshot_hash=run.snapshot_hash,
            hydraulic_result=hydraulic_result,
            dispatch_trace=(),
            control_events=(),
            structure_results=(),
            runtime_provenance=_runtime_provenance()[:3],
        )
