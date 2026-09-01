"""Synthetic-only Gate/Pump schedule replay and fail-closed contracts."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.dispatch import service
from app.dispatch.schemas import (
    DispatchActionCreate,
    DispatchSchedulePreviewRequest,
)
from app.gis.models import DispatchPlan
from app.main import app
from model.control.constraints import validate_target_against_asset
from model.control.policy import ControlTarget
from model.control.replay import (
    ReplayAsset,
    ReplayObservationFrame,
    SYNTHETIC_INITIAL_STATE_BASIS,
    SYNTHETIC_SCHEDULE_EVALUATOR_ID,
    SYNTHETIC_TIE_BREAK_POLICY,
    replay_schedule,
)
from model.control.rules import ThresholdRule
from model.control.schedule import ScheduledAction
from model.provenance import snapshot_hash


def _gate_asset(*, availability: str = "online") -> ReplayAsset:
    """Return one frozen Gate constraint fixture without hydraulic parameters."""

    return ReplayAsset(
        structure_type="gate",
        structure_id=1,
        constraints={
            "availability": availability,
            "height_m": 2.0,
            "minimum_opening_m": 0.0,
            "maximum_opening_m": 2.0,
            "opening_rate_limit_m_per_s": 10.0,
            "minimum_hold_seconds": 0.0,
            "initial_opening_m": 0.0,
        },
    )


def _pump_asset() -> ReplayAsset:
    """Return one frozen Pump switching fixture without Q-H calculations."""

    return ReplayAsset(
        structure_type="pump",
        structure_id=2,
        constraints={
            "availability": "online",
            "design_flow_capacity_m3s": 3.0,
            "unit_count": 2,
            "minimum_running_units": 1,
            "maximum_running_units": 2,
            "minimum_run_seconds": 20.0,
            "minimum_stop_seconds": 10.0,
            "maximum_starts_per_replay": 1,
            "initial_running_units": 0,
            "initial_stop_constraint_satisfied": True,
        },
    )


def test_discrete_pump_commands_reject_linear_interpolation() -> None:
    """Never synthesize fractional enabled or unit-count commands."""

    with pytest.raises(ValidationError, match="discrete_command_requires_step"):
        DispatchActionCreate(
            sequence=1,
            time_seconds=0,
            structure_type="pump",
            pump_id=2,
            command_type="pump_unit_count",
            target_value=1,
            interpolation="linear",
        )


def test_manual_and_rule_replay_is_deterministic_and_auditable() -> None:
    """Resolve interpolation, rule priority, trigger, recovery, and conflicts."""

    actions = (
        ScheduledAction(1, 0.0, "gate", 1, "gate_opening_m", 0.0, "linear", 1),
        ScheduledAction(2, 10.0, "gate", 1, "gate_opening_m", 1.0, "step", 1),
    )
    rules = (
        ThresholdRule(
            id=3,
            name="synthetic-high-water",
            observation_type="node_water_level",
            observation_object_id=9,
            operator=">=",
            threshold=10.0,
            hysteresis=0.2,
            minimum_hold_seconds=0.0,
            cooldown_seconds=0.0,
            action_template={
                "structure_type": "gate",
                "structure_id": 1,
                "command_type": "gate_opening_m",
                "target_value": 0.8,
            },
            priority=10,
        ),
    )
    observations = (
        ReplayObservationFrame(0.0, {("node_water_level", 9): 9.0}),
        ReplayObservationFrame(5.0, {("node_water_level", 9): 10.1}),
        ReplayObservationFrame(10.0, {("node_water_level", 9): 9.7}),
    )
    first = replay_schedule(
        actions=actions,
        rules=rules,
        assets=(_gate_asset(),),
        observations=observations,
    )
    second = replay_schedule(
        actions=actions,
        rules=rules,
        assets=(_gate_asset(),),
        observations=observations,
    )
    assert first == second
    assert first["rule_trigger_count"] == 1
    assert first["rule_recovery_count"] == 1
    assert first["conflict_evaluations"] == 1
    assert first["steps"][1]["targets"][0]["source_type"] == "rule"
    assert first["steps"][1]["targets"][0]["resolved_value"] == pytest.approx(0.8)
    assert first["steps"][2]["targets"][0]["source_type"] == "manual"


def test_pump_replay_enforces_start_count_without_claiming_flow() -> None:
    """Reject a second start and return only the resolved switching target."""

    result = replay_schedule(
        actions=(
            ScheduledAction(1, 0.0, "pump", 2, "pump_enabled", 1.0),
            ScheduledAction(2, 30.0, "pump", 2, "pump_enabled", 0.0),
            ScheduledAction(3, 60.0, "pump", 2, "pump_enabled", 1.0),
        ),
        rules=(),
        assets=(_pump_asset(),),
        observations=(
            ReplayObservationFrame(0.0, {}),
            ReplayObservationFrame(30.0, {}),
            ReplayObservationFrame(60.0, {}),
        ),
    )
    rejected = result["steps"][2]["targets"][0]
    assert rejected["outcome"] == "rejected"
    assert rejected["reason"] == "maximum_starts_rejected"
    assert rejected["resolved_value"] == 0.0
    assert "flow" not in rejected
    assert "energy" not in rejected


def test_offline_asset_is_rejected_in_static_replay() -> None:
    """Keep asset availability fail closed for manual and rule targets alike."""

    result = replay_schedule(
        actions=(
            ScheduledAction(1, 0.0, "gate", 1, "gate_opening_m", 1.0),
        ),
        rules=(),
        assets=(_gate_asset(availability="maintenance"),),
        observations=(
            ReplayObservationFrame(0.0, {}),
            ReplayObservationFrame(10.0, {}),
        ),
    )
    target = result["steps"][0]["targets"][0]
    assert target["outcome"] == "rejected"
    assert target["reason"] == "asset_maintenance"


def test_pump_target_flow_uses_conservative_station_capacity() -> None:
    """Never multiply an undocumented station design flow by unit count."""

    result = replay_schedule(
        actions=(
            ScheduledAction(1, 0.0, "pump", 2, "pump_target_flow", 3.1),
        ),
        rules=(),
        assets=(_pump_asset(),),
        observations=(
            ReplayObservationFrame(0.0, {}),
            ReplayObservationFrame(10.0, {}),
        ),
    )
    target = result["steps"][0]["targets"][0]
    assert target["outcome"] == "rejected"
    assert target["reason"] == "pump_target_flow_above_static_capacity"


def test_invalid_static_asset_constraints_fail_closed() -> None:
    """Reject malformed frozen limits instead of silently normalizing them."""

    gate_target = ControlTarget(
        "gate", 1, "gate_opening_m", 1.0, 1, "manual", 1
    )
    invalid_gate = dict(_gate_asset().constraints)
    invalid_gate["opening_rate_limit_m_per_s"] = -0.1
    assert validate_target_against_asset(gate_target, invalid_gate) == (
        False,
        "gate_constraint_configuration_invalid",
    )

    pump_target = ControlTarget(
        "pump", 2, "pump_enabled", 1.0, 1, "manual", 2
    )
    invalid_pump = dict(_pump_asset().constraints)
    invalid_pump["unit_count"] = 0
    assert validate_target_against_asset(pump_target, invalid_pump) == (
        False,
        "pump_constraint_configuration_invalid",
    )


def test_evaluator_v1_exposes_and_applies_its_synthetic_t0_basis() -> None:
    """Make the closed/stopped t=0 assumption observable and regression-locked."""

    gate = _gate_asset()
    gate.constraints["opening_rate_limit_m_per_s"] = 0.01
    gate.constraints["minimum_hold_seconds"] = 1.0e20
    pump = _pump_asset()
    pump.constraints["minimum_stop_seconds"] = 1.0e20
    result = replay_schedule(
        actions=(
            ScheduledAction(1, 0.0, "gate", 1, "gate_opening_m", 1.0),
            ScheduledAction(2, 0.0, "pump", 2, "pump_enabled", 1.0),
        ),
        rules=(),
        assets=(gate, pump),
        observations=(
            ReplayObservationFrame(0.0, {}),
            ReplayObservationFrame(1.0, {}),
        ),
    )
    assert result["evaluator_id"] == SYNTHETIC_SCHEDULE_EVALUATOR_ID
    assert result["initial_state_basis"] == SYNTHETIC_INITIAL_STATE_BASIS
    assert all(
        target["outcome"] == "selected"
        for target in result["steps"][0]["targets"]
    )


def test_preview_request_rejects_implicit_or_rewound_time() -> None:
    """Require callers to submit a complete, explicit synthetic timeline."""

    with pytest.raises(ValidationError, match="start at 0"):
        DispatchSchedulePreviewRequest.model_validate(
            {
                "evidence_class": "SYNTHETIC_DEVELOPMENT_ONLY",
                "observations": [
                    {"time_seconds": 1, "values": []},
                    {"time_seconds": 2, "values": []},
                ],
            }
        )
    with pytest.raises(ValidationError, match="strictly increasing"):
        DispatchSchedulePreviewRequest.model_validate(
            {
                "evidence_class": "SYNTHETIC_DEVELOPMENT_ONLY",
                "observations": [
                    {"time_seconds": 0, "values": []},
                    {"time_seconds": 0, "values": []},
                ],
            }
        )


def test_hydraulic_dispatch_run_remains_fail_closed_without_writes() -> None:
    """Static replay must not reopen the disabled MASCARET dispatch writer."""

    session = Mock(spec=Session)
    session.get.return_value = DispatchPlan(id=7)
    with pytest.raises(service.DispatchStateError, match="UNSUPPORTED_BY_MASCARET_ADAPTER"):
        service.create_run(session, 7)
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_service_preview_uses_only_the_frozen_snapshot_without_writes() -> None:
    """Exercise the API service boundary locally even when PostGIS is unavailable."""

    frozen = {
        "schema_version": "dayu.dispatch-plan.v2",
        "plan": {"duration_seconds": 10.0},
        "actions": [
            {
                "id": 11,
                "time_seconds": 0.0,
                "structure_type": "gate",
                "gate_id": 1,
                "pump_id": None,
                "command_type": "gate_opening_m",
                "target_value": 1.0,
                "interpolation": "step",
                "priority": 1,
            }
        ],
        "rules": [],
        "assets": [
            {
                "structure_type": "gate",
                "legacy_asset_id": 1,
                "constraints": _gate_asset().constraints,
            }
        ],
        "control_evaluator": {
            "version": SYNTHETIC_SCHEDULE_EVALUATOR_ID,
            "tie_break_policy": SYNTHETIC_TIE_BREAK_POLICY,
            "hydraulic_feedback": False,
            "initial_state_basis": SYNTHETIC_INITIAL_STATE_BASIS,
        },
    }
    plan = DispatchPlan(
        id=7,
        status="frozen",
        frozen_snapshot=frozen,
        frozen_snapshot_hash=snapshot_hash(frozen),
    )
    session = Mock(spec=Session)
    session.get.return_value = plan
    payload = DispatchSchedulePreviewRequest.model_validate(
        {
            "evidence_class": "SYNTHETIC_DEVELOPMENT_ONLY",
            "observations": [
                {"time_seconds": 0, "values": []},
                {"time_seconds": 10, "values": []},
            ],
        }
    )

    result = service.preview_schedule(session, 7, payload)

    assert result.plan_snapshot_hash == plan.frozen_snapshot_hash
    assert result.hydraulic_execution_supported is False
    assert result.no_hydraulic_feedback is True
    assert result.steps[0].targets[0].resolved_value == 1.0
    assert result.evaluator_id == SYNTHETIC_SCHEDULE_EVALUATOR_ID
    assert result.initial_state_basis == SYNTHETIC_INITIAL_STATE_BASIS
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_preview_rejects_hash_valid_unknown_evaluator_contract() -> None:
    """A self-consistent hash cannot opt a frozen plan into unknown semantics."""

    frozen = {
        "schema_version": "dayu.dispatch-plan.v2",
        "plan": {"duration_seconds": 10.0},
        "actions": [],
        "rules": [],
        "assets": [],
        "control_evaluator": {
            "version": "dayu.synthetic-static-schedule.v999",
            "tie_break_policy": SYNTHETIC_TIE_BREAK_POLICY,
            "hydraulic_feedback": False,
            "initial_state_basis": SYNTHETIC_INITIAL_STATE_BASIS,
        },
    }
    plan = DispatchPlan(
        id=8,
        status="frozen",
        frozen_snapshot=frozen,
        frozen_snapshot_hash=snapshot_hash(frozen),
    )
    session = Mock(spec=Session)
    session.get.return_value = plan
    payload = DispatchSchedulePreviewRequest.model_validate(
        {
            "evidence_class": "SYNTHETIC_DEVELOPMENT_ONLY",
            "observations": [
                {"time_seconds": 0, "values": []},
                {"time_seconds": 10, "values": []},
            ],
        }
    )
    with pytest.raises(service.DispatchStateError, match="unsupported evaluator"):
        service.preview_schedule(session, 8, payload)
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_archived_frozen_plan_cannot_be_deleted() -> None:
    """Archiving must never turn an immutable snapshot into a deletable draft."""

    session = Mock(spec=Session)
    session.scalar.return_value = DispatchPlan(id=9, status="archived")
    with pytest.raises(service.DispatchStateError, match="cannot be deleted"):
        service.delete_plan(session, 9)
    session.delete.assert_not_called()


def test_openapi_exposes_readiness_and_synthetic_preview_only() -> None:
    """Publish both contracts while retaining the separately blocked run endpoint."""

    schema = TestClient(app).get("/openapi.json").json()
    paths = schema["paths"]
    assert "/api/v1/dispatch/plans/{plan_id}/readiness" in paths
    assert "/api/v1/dispatch/plans/{plan_id}/schedule-preview" in paths
    response_schema = schema["components"]["schemas"]["DispatchSchedulePreview"]
    assert "hydraulic_execution_supported" in response_schema["properties"]
    assert "no_hydraulic_feedback" in response_schema["properties"]
    readiness_schema = schema["components"]["schemas"]["DispatchExecutionReadiness"]
    assert "static_preview_allowed" in readiness_schema["properties"]
    assert "hydraulic_runtime_supported" in readiness_schema["properties"]
    assert "real_validation_status" in readiness_schema["properties"]
