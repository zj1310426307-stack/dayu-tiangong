"""Immutable v3 snapshot and explicit clone-transition contracts."""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from app.dispatch.hydraulic_schemas import HydraulicPlanCompileRequest
from app.dispatch.hydraulic_assets import HydraulicControlAsset
from app.dispatch.hydraulic_service import (
    HydraulicDispatchStateError,
    freeze_hydraulic_plan,
    hydraulic_snapshot_integrity,
    start_hydraulic_preview,
)
from app.dispatch.hydraulic_snapshot import build_hydraulic_plan_snapshot
from app.gis.models import DatasetVersion, DispatchPlan
from model.control.compiler import HydraulicControlCompiler, InitialActuatorState
from model.control.drtc import DRTCCompiler
from model.hydraulic_1d.capabilities import capabilities_for
from model.hydraulic_1d.controlled import DispatchPlanSnapshot
from model.hydraulic_1d.registry import DFLOW_FM_ENGINE_ID, DFLOW_FM_ENGINE_VERSION
from model.provenance import canonical_json, snapshot_hash
from tests.hydraulic_1d.helpers import model_fixture


def _plan(*, target: str = "hydraulic_v3", parent_id: int | None = 4) -> DispatchPlan:
    plan = DispatchPlan(
        dataset_version_id=2,
        simulation_case_id=3,
        name="synthetic-controlled-plan",
        version=2,
        status="validated",
        snapshot_target=target,
        cloned_from_plan_id=parent_id,
        description="synthetic fixture only",
        duration_seconds=60.0,
        evaluation_config={},
        storage_level="key_sections",
        created_by="pytest",
    )
    plan.id = 5
    return plan


def _request() -> HydraulicPlanCompileRequest:
    return HydraulicPlanCompileRequest(
        initial_actuator_state=(),
        observation_bindings=(),
        observation_sampling_interval_seconds=10.0,
        runtime_mode="container",
        timeout_seconds=120.0,
        synthetic_fixture=True,
    )


def _model_and_hash():
    model = model_fixture()
    return model, snapshot_hash(model.model_dump(mode="json"))


def test_v3_snapshot_self_hashes_and_freezes_evidence_boundaries() -> None:
    model, model_hash = _model_and_hash()
    manual = HydraulicControlCompiler().compile(
        actions=(),
        assets=(),
        initial_states=(),
        bindings=(),
        duration_seconds=60.0,
    )
    drtc = DRTCCompiler().compile(())
    with (
        patch(
            "app.dispatch.hydraulic_snapshot._ordered_plan_children",
            return_value=([], []),
        ),
        patch(
            "app.dispatch.hydraulic_snapshot.resolve_plan_asset_snapshots",
            return_value=([], []),
        ),
    ):
        frozen, digest, control_hash = build_hydraulic_plan_snapshot(
            Mock(),
            _plan(),
            request=_request(),
            hydraulic_model=model,
            hydraulic_model_snapshot_hash=model_hash,
            capability_facts=(),
            gate_specs=(),
            pump_specs=(),
            control_assets=(),
            control_bindings=(),
            manual_report=manual,
            drtc_report=drtc,
        )

    assert frozen["schema_version"] == "dayu.dispatch-plan.v3"
    assert digest == frozen["snapshot_hash"]
    assert digest == snapshot_hash(
        {key: value for key, value in frozen.items() if key != "snapshot_hash"}
    )
    assert len(control_hash) == 64
    assert frozen["hydraulic_feedback"] is True
    assert frozen["hydraulic_model_snapshot_hash"] == model_hash
    payload = json.loads(frozen["plan_payload_json"])
    assert snapshot_hash(payload["hydraulic_model_snapshot"]) == model_hash
    assert payload["engine_capabilities"] == []
    assert [
        item["component"] for item in frozen["runtime_provenance_requirements"]
    ] == [
        "dflowfm",
        "dimr",
        "fbc",
        "hydrolib-core",
    ]


def test_v3_snapshot_rejects_an_in_place_v2_upgrade() -> None:
    model, model_hash = _model_and_hash()
    manual = HydraulicControlCompiler().compile(
        actions=(),
        assets=(),
        initial_states=(),
        bindings=(),
        duration_seconds=60.0,
    )
    with pytest.raises(ValueError, match="explicit hydraulic clone lineage"):
        build_hydraulic_plan_snapshot(
            Mock(),
            _plan(target="static_v2", parent_id=None),
            request=_request(),
            hydraulic_model=model,
            hydraulic_model_snapshot_hash=model_hash,
            capability_facts=(),
            gate_specs=(),
            pump_specs=(),
            control_assets=(),
            control_bindings=(),
            manual_report=manual,
            drtc_report=DRTCCompiler().compile(()),
        )


def test_hydraulic_request_rejects_duplicate_initial_states() -> None:
    payload = {
        "structure_type": "gate",
        "structure_id": 7,
        "gate_opening_m": 0.0,
        "evidence": "SYNTHETIC_INITIAL_STATE",
    }
    with pytest.raises(ValueError, match="initial actuator states must be unique"):
        HydraulicPlanCompileRequest(
            initial_actuator_state=(payload, payload),
            observation_sampling_interval_seconds=10,
        )


def _freeze_test_plan() -> DispatchPlan:
    plan = _plan()
    model, model_hash = _model_and_hash()
    manual = HydraulicControlCompiler().compile(
        actions=(),
        assets=(),
        initial_states=(),
        bindings=(),
        duration_seconds=60.0,
    )
    with (
        patch(
            "app.dispatch.hydraulic_snapshot._ordered_plan_children",
            return_value=([], []),
        ),
        patch(
            "app.dispatch.hydraulic_snapshot.resolve_plan_asset_snapshots",
            return_value=([], []),
        ),
    ):
        frozen, digest, _ = build_hydraulic_plan_snapshot(
            Mock(),
            plan,
            request=_request(),
            hydraulic_model=model,
            hydraulic_model_snapshot_hash=model_hash,
            capability_facts=(),
            gate_specs=(),
            pump_specs=(),
            control_assets=(),
            control_bindings=(),
            manual_report=manual,
            drtc_report=DRTCCompiler().compile(()),
        )
    plan.status = "frozen"
    plan.frozen_snapshot = frozen
    plan.frozen_snapshot_hash = digest
    return plan


def test_v3_asset_snapshot_uses_dflow_capability_and_one_initial_state_authority() -> (
    None
):
    from app.dispatch.hydraulic_snapshot import _controlled_asset_snapshots

    request = HydraulicPlanCompileRequest(
        initial_actuator_state=(
            InitialActuatorState(
                structure_type="gate",
                structure_id=7,
                gate_opening_m=0.8,
                evidence="SYNTHETIC_INITIAL_STATE",
            ),
        ),
        observation_sampling_interval_seconds=10,
    )
    dflow_gate = next(
        item.to_dict()
        for item in capabilities_for(DFLOW_FM_ENGINE_ID, DFLOW_FM_ENGINE_VERSION)
        if item.feature == "GATE"
    )
    assets = _controlled_asset_snapshots(
        [
            {
                "structure_type": "gate",
                "legacy_asset_id": 7,
                "constraints": {"initial_opening_m": 0.0, "height_m": 2.0},
                "capability": {"feature": "GATE", "status": "UNSUPPORTED"},
            }
        ],
        request=request,
        capability_facts=(dflow_gate,),
        control_assets=(
            HydraulicControlAsset(
                structure_type="gate",
                structure_id=7,
                constraints={
                    "availability": "online",
                    "height_m": 2.0,
                    "minimum_opening_m": 0.0,
                    "maximum_opening_m": 1.0,
                    "opening_rate_limit_m_per_s": 0.1,
                    "minimum_hold_seconds": 0.0,
                },
                provenance={
                    "availability": "SOURCE_DATA:gate[7].status",
                    "height_m": "SOURCE_DATA:gate[7].height",
                    "minimum_opening_m": "SOURCE_DATA:gate[7].minimum_opening",
                    "maximum_opening_m": "SOURCE_DATA:override.maximum_opening_m",
                    "opening_rate_limit_m_per_s": (
                        "SOURCE_DATA:gate[7].opening_rate_limit"
                    ),
                    "minimum_hold_seconds": (
                        "SOURCE_DATA:gate[7].minimum_hold_seconds"
                    ),
                },
            ),
        ),
    )

    assert assets[0]["capability"]["engine"] == DFLOW_FM_ENGINE_ID
    assert assets[0]["capability"]["status"] == "EXPERIMENTAL"
    assert "initial_opening_m" not in assets[0]["constraints"]
    assert assets[0]["constraints"]["maximum_opening_m"] == 1.0
    assert assets[0]["constraint_provenance"]["maximum_opening_m"].endswith(
        "override.maximum_opening_m"
    )
    assert assets[0]["initial_state_authority"] == "initial_actuator_state"


def test_v3_integrity_validates_typed_envelope_and_nested_evidence() -> None:
    plan = _freeze_test_plan()
    assert hydraulic_snapshot_integrity(plan) == (True, None)

    assert plan.frozen_snapshot is not None
    plan.frozen_snapshot["snapshot_hash"] = "0" * 64
    valid, reason = hydraulic_snapshot_integrity(plan)
    assert valid is False
    assert reason is not None


def test_v3_integrity_rejects_rehashed_inner_observation_contract_drift() -> None:
    plan = _freeze_test_plan()
    assert plan.frozen_snapshot is not None
    changed = dict(plan.frozen_snapshot)
    payload = json.loads(str(changed["plan_payload_json"]))
    payload["control_observation_contract"]["sampling_interval_seconds"] = 20.0
    changed["plan_payload_json"] = canonical_json(payload)
    changed.pop("snapshot_hash")
    rehashed = DispatchPlanSnapshot.model_validate(changed).model_dump(mode="json")
    plan.frozen_snapshot = rehashed
    plan.frozen_snapshot_hash = str(rehashed["snapshot_hash"])

    valid, reason = hydraulic_snapshot_integrity(plan)

    assert valid is False
    assert reason == "frozen hydraulic snapshot envelope and payload drifted"


def test_v3_integrity_rejects_rehashed_nested_compiler_report_drift() -> None:
    plan = _freeze_test_plan()
    assert plan.frozen_snapshot is not None
    changed = dict(plan.frozen_snapshot)
    payload = json.loads(str(changed["plan_payload_json"]))
    payload["manual_control_report"]["artifact_hash"] = "0" * 64
    control_contract = {
        "manual": payload["manual_control_report"],
        "drtc": payload["drtc_compile_report"],
        "bindings": payload["control_bindings"],
        "initial_actuator_state": payload["initial_actuator_state"],
        "observation_contract": payload["control_observation_contract"],
        "execution_settings": payload["execution_settings"],
    }
    payload["control_contract_hash"] = snapshot_hash(control_contract)
    changed["plan_payload_json"] = canonical_json(payload)
    changed.pop("snapshot_hash")
    rehashed = DispatchPlanSnapshot.model_validate(changed).model_dump(mode="json")
    plan.frozen_snapshot = rehashed
    plan.frozen_snapshot_hash = str(rehashed["snapshot_hash"])

    valid, reason = hydraulic_snapshot_integrity(plan)

    assert valid is False
    assert reason is not None
    assert "manual control report artifact hash mismatch" in reason


def test_hydraulic_freeze_locks_dataset_before_plan_and_assets() -> None:
    plan = _plan()
    session = Mock()
    events: list[str] = []

    def get_candidate(entity, identity):
        assert entity is DispatchPlan
        assert identity == plan.id
        events.append("candidate")
        return plan

    def scalar(statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is DatasetVersion:
            events.append("dataset_lock")
            return object()
        assert entity is DispatchPlan
        events.append("plan_lock")
        return plan

    session.get.side_effect = get_candidate
    session.scalar.side_effect = scalar
    with (
        patch(
            "app.dispatch.hydraulic_service.lock_plan_asset_rows",
            side_effect=lambda *_args: events.append("asset_locks"),
        ),
        patch(
            "app.dispatch.hydraulic_service._compile",
            side_effect=lambda *_args: (
                events.append("compile"),
                (_ for _ in ()).throw(RuntimeError("stop after lock order")),
            )[1],
        ),
        pytest.raises(RuntimeError, match="stop after lock order"),
    ):
        freeze_hydraulic_plan(session, plan.id, _request())

    assert events == [
        "candidate",
        "dataset_lock",
        "plan_lock",
        "asset_locks",
        "compile",
    ]


def test_hydraulic_preview_blocks_before_creating_rows_without_runtime() -> None:
    plan = _freeze_test_plan()
    session = Mock()
    session.get.return_value = plan
    with patch(
        "app.dispatch.hydraulic_service._runtime_readiness",
        return_value=(False, "DFLOW_RUNTIME_BLOCKED: disabled", None),
    ):
        with pytest.raises(HydraulicDispatchStateError) as blocked:
            start_hydraulic_preview(session, plan.id, _request())
    assert blocked.value.code == "DFLOW_RUNTIME_BLOCKED"
    session.add.assert_not_called()
