"""Fail-closed contracts for controlled D-Flow/D-RTC development runs."""

from __future__ import annotations

import pytest

from model.control.compiler import (
    ActuatorControlBinding,
    HydraulicControlCompiler,
    InitialActuatorState,
)
from model.control.drtc import DRTCCompiler
from model.control.observation_bridge import (
    HydraulicObservationAdapter,
    ObservationBinding,
)
from model.control.replay import ReplayAsset
from model.control.rules import ThresholdRule
from model.control.schedule import ScheduledAction


def _gate_asset() -> ReplayAsset:
    return ReplayAsset(
        "gate",
        11,
        {
            "availability": "online",
            "height_m": 2.0,
            "minimum_opening_m": 0.1,
            "maximum_opening_m": 2.0,
            "opening_rate_limit_m_per_s": 0.02,
            "minimum_hold_seconds": 0.0,
        },
    )


def _pump_asset() -> ReplayAsset:
    return ReplayAsset(
        "pump",
        12,
        {
            "availability": "online",
            "unit_count": 2,
            "minimum_running_units": 1,
            "maximum_running_units": 2,
            "design_flow_capacity_m3s": 4.0,
            "minimum_run_seconds": 0.0,
            "minimum_stop_seconds": 0.0,
            "maximum_starts_per_replay": 10,
        },
    )


def test_manual_gate_compile_freezes_initial_state_and_native_target() -> None:
    report = HydraulicControlCompiler().compile(
        actions=(ScheduledAction(1, 10.0, "gate", 11, "gate_opening_m", 1.0),),
        assets=(_gate_asset(),),
        initial_states=(
            InitialActuatorState(
                structure_type="gate",
                structure_id=11,
                gate_opening_m=0.5,
                evidence="SYNTHETIC_INITIAL_STATE",
            ),
        ),
        bindings=(
            ActuatorControlBinding(
                structure_type="gate",
                structure_id=11,
                native_structure_id="gate-11",
                supported_command_type="gate_opening_m",
                bmi_variable="orifices/gate-11/gateLowerEdgeLevel",
                conversion="gate_lower_edge_level",
                reference_level_m=5.0,
            ),
        ),
        duration_seconds=20.0,
    )

    assert report.status == "COMPILED"
    assert len(report.artifact_hash) == 64
    first = report.commands[0]
    assert first.time_seconds == 10.0
    assert first.requested_value == 1.0
    assert first.resolved_value == pytest.approx(0.7)
    assert first.native_target_value == pytest.approx(5.7)
    assert first.constraint_outcome == "limited"


def test_explicit_closed_gate_state_is_valid_below_minimum_operating_opening() -> None:
    report = HydraulicControlCompiler().compile(
        actions=(),
        assets=(_gate_asset(),),
        initial_states=(
            InitialActuatorState(
                structure_type="gate",
                structure_id=11,
                gate_opening_m=0.0,
                evidence="SYNTHETIC_INITIAL_STATE",
            ),
        ),
        bindings=(),
        duration_seconds=60.0,
    )

    assert report.status == "COMPILED"
    assert report.commands == ()


def test_pump_enabled_and_unit_count_are_not_relabelled_as_capacity() -> None:
    report = HydraulicControlCompiler().compile(
        actions=(ScheduledAction(2, 0.0, "pump", 12, "pump_unit_count", 2.0),),
        assets=(_pump_asset(),),
        initial_states=(
            InitialActuatorState(
                structure_type="pump",
                structure_id=12,
                pump_enabled=False,
                running_units=0,
                stop_seconds=30.0,
                evidence="SYNTHETIC_INITIAL_STATE",
            ),
        ),
        bindings=(
            ActuatorControlBinding(
                structure_type="pump",
                structure_id=12,
                native_structure_id="pump-12",
                supported_command_type="pump_target_flow",
                bmi_variable="pumps/pump-12/Capacity",
                conversion="identity_capacity",
            ),
        ),
        duration_seconds=60.0,
    )

    assert report.status == "UNSUPPORTED"
    assert {issue.code for issue in report.issues} == {
        "HYDRAULIC_COMMAND_SEMANTICS_UNSUPPORTED"
    }
    assert report.commands == ()


def test_compile_rejects_duplicate_bindings_and_out_of_range_time() -> None:
    binding = ActuatorControlBinding(
        structure_type="gate",
        structure_id=11,
        native_structure_id="gate-11",
        supported_command_type="gate_opening_m",
        bmi_variable="orifices/gate-11/gateLowerEdgeLevel",
        conversion="gate_lower_edge_level",
        reference_level_m=5.0,
    )
    report = HydraulicControlCompiler().compile(
        actions=(ScheduledAction(3, -1.0, "gate", 11, "gate_opening_m", 1.0),),
        assets=(_gate_asset(),),
        initial_states=(
            InitialActuatorState(
                structure_type="gate",
                structure_id=11,
                gate_opening_m=0.0,
                evidence="SYNTHETIC_INITIAL_STATE",
            ),
        ),
        bindings=(binding, binding),
        duration_seconds=60.0,
    )

    assert report.status == "UNSUPPORTED"
    assert {issue.code for issue in report.issues} == {
        "CONTROL_BINDING_DUPLICATE",
        "CONTROL_ACTION_OUTSIDE_DURATION",
    }


def test_observation_bridge_requires_exact_sources_and_oriented_gate_pair() -> None:
    adapter = HydraulicObservationAdapter(
        (
            ObservationBinding(
                observation_type="pump_intake_level",
                observation_object_id=12,
                source_kind="observation_point",
                source_id="pump-12-intake",
                binding_evidence="SYNTHETIC_ASSUMPTION",
            ),
            ObservationBinding(
                observation_type="gate_head_difference",
                observation_object_id=11,
                source_kind="oriented_observation_pair",
                upstream_source_id="gate-11-up",
                downstream_source_id="gate-11-down",
                binding_evidence="SYNTHETIC_ASSUMPTION",
            ),
        )
    )

    assert adapter.required_bmi_variables() == (
        "observations/gate-11-down/water_level",
        "observations/gate-11-up/water_level",
        "observations/pump-12-intake/water_level",
    )
    values = adapter.adapt(
        {
            "observations/pump-12-intake/water_level": 8.0,
            "observations/gate-11-up/water_level": 10.2,
            "observations/gate-11-down/water_level": 9.7,
        }
    )
    assert values[("pump_intake_level", 12)] == 8.0
    assert values[("gate_head_difference", 11)] == pytest.approx(0.5)
    with pytest.raises(KeyError, match="gate-11-down"):
        adapter.adapt(
            {
                "observations/pump-12-intake/water_level": 8.0,
                "observations/gate-11-up/water_level": 10.2,
            }
        )


def _rule(*, enabled: bool) -> ThresholdRule:
    return ThresholdRule(
        id=21,
        name="high-water-open",
        enabled=enabled,
        observation_type="node_water_level",
        observation_object_id=7,
        operator=">=",
        threshold=10.0,
        hysteresis=0.0,
        minimum_hold_seconds=0.0,
        cooldown_seconds=0.0,
        action_template={
            "structure_type": "gate",
            "structure_id": 11,
            "command_type": "gate_opening_m",
            "target_value": 1.0,
        },
        priority=10,
    )


def test_drtc_compiler_omits_disabled_rules_but_blocks_unproven_dynamic_rules() -> None:
    disabled = DRTCCompiler().compile((_rule(enabled=False),))
    enabled = DRTCCompiler().compile((_rule(enabled=True),))

    assert disabled.status == "COMPILED"
    assert disabled.rules[0].compiled_component is None
    assert disabled.runtime_validated is False
    assert enabled.status == "UNSUPPORTED"
    assert "inactive-rule state retention" in enabled.rules[0].unsupported_reason
