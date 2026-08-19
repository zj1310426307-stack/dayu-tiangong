"""HYDRO-MODEL-01 control-loop and explicit fixed-state tests."""

from model import HydraulicEngine
import pytest

from model.control.policy import CompositeControlPolicy, HydraulicObservation
from model.control.rules import ThresholdRule, ThresholdRulePolicy
from model.core.errors import HydraulicInputError
from tests.test_phase4_network import make_y_network


def test_water_level_rule_opens_only_after_the_threshold() -> None:
    """The gate remains untouched at 9.5 m and opens when 10.5 m is observed."""

    rule = ThresholdRule(
        id=1,
        name="high-water-open",
        observation_type="node_water_level",
        observation_object_id=3,
        operator=">",
        threshold=10.0,
        hysteresis=0.2,
        minimum_hold_seconds=0.0,
        cooldown_seconds=0.0,
        action_template={
            "structure_type": "gate",
            "structure_id": 1,
            "command_type": "gate_opening_m",
            "target_value": 0.2,
        },
        priority=10,
    )
    policy = ThresholdRulePolicy((rule,))

    low = policy.targets_at(
        0.0, HydraulicObservation(0.0, {("node_water_level", 3): 9.5})
    )
    high = policy.targets_at(
        1.0, HydraulicObservation(1.0, {("node_water_level", 3): 10.5})
    )

    assert low == []
    assert len(high) == 1
    assert high[0].target_value == 0.2


def test_pump_level_control_starts_above_ten_and_stops_at_nine() -> None:
    """Paired rules provide explicit hysteretic start/stop commands."""

    start = ThresholdRule(
        id=2,
        name="pump-start",
        observation_type="pump_intake_level",
        observation_object_id=7,
        operator=">",
        threshold=10.0,
        hysteresis=1.0,
        minimum_hold_seconds=0.0,
        cooldown_seconds=0.0,
        action_template={
            "structure_type": "pump",
            "structure_id": 7,
            "command_type": "pump_enabled",
            "target_value": 1.0,
        },
        priority=10,
    )
    stop = ThresholdRule(
        id=3,
        name="pump-stop",
        observation_type="pump_intake_level",
        observation_object_id=7,
        operator="<=",
        threshold=9.0,
        hysteresis=0.0,
        minimum_hold_seconds=0.0,
        cooldown_seconds=0.0,
        action_template={
            "structure_type": "pump",
            "structure_id": 7,
            "command_type": "pump_enabled",
            "target_value": 0.0,
        },
        priority=10,
    )
    policy = CompositeControlPolicy((ThresholdRulePolicy((start, stop)),))

    initial = policy.targets_at(
        0.0, HydraulicObservation(0.0, {("pump_intake_level", 7): 9.5})
    )
    running = policy.targets_at(
        1.0, HydraulicObservation(1.0, {("pump_intake_level", 7): 10.5})
    )
    held = policy.targets_at(
        2.0, HydraulicObservation(2.0, {("pump_intake_level", 7): 9.5})
    )
    stopped = policy.targets_at(
        3.0, HydraulicObservation(3.0, {("pump_intake_level", 7): 9.0})
    )

    assert initial == []
    assert [target.target_value for target in running] == [1.0]
    assert [target.target_value for target in held] == [1.0]
    assert [target.target_value for target in stopped] == [0.0]


def test_explicit_fixed_gate_and_pump_are_consumed_without_a_plan() -> None:
    """Only explicit fixed control state turns otherwise static assets into controls."""

    snapshot = make_y_network(bifurcation=True)
    snapshot["gates"] = [{
        "id": 1,
        "river_segment_id": 2,
        "upstream_node_id": 3,
        "downstream_node_id": 2,
        "width": 8.0,
        "height": 2.0,
        "maximum_opening": 2.0,
        "crest_elevation": 9.0,
        "max_flow": 10.0,
        "status": "online",
        "control_state": {"mode": "fixed", "opening": 2.0},
    }]
    snapshot["pumps"] = [{
        "id": 1,
        "intake_node_id": 3,
        "outlet_node_id": None,
        "transfer_type": "external_outflow",
        "design_flow": 2.0,
        "head": 4.0,
        "unit_count": 1,
        "minimum_running_units": 1,
        "maximum_running_units": 1,
        "minimum_run_seconds": 0.0,
        "minimum_stop_seconds": 0.0,
        "maximum_starts_per_run": 10,
        "minimum_operating_head": 0.0,
        "maximum_operating_head": 10.0,
        "efficiency_curve": {"points": [[0.0, 0.7], [1.0, 0.8]]},
        "status": "online",
        "control_state": {"mode": "fixed", "status": "running"},
    }]

    result = HydraulicEngine().run(snapshot).to_dict()

    assert {row["structure_type"] for row in result["structure_series"]} == {
        "gate",
        "pump",
    }
    assert {row["source_type"] for row in result["dispatch_events"]} == {"fixed"}
    assert result["water_balance"]["relative_balance_residual"] < 0.01


def test_legacy_assets_without_fixed_state_keep_the_natural_baseline() -> None:
    """Adding an unaddressed legacy gate must not close the baseline river edge."""

    snapshot = make_y_network(bifurcation=True)
    snapshot["gates"] = [{
        "id": 1,
        "river_segment_id": 2,
        "upstream_node_id": 3,
        "downstream_node_id": 2,
        "width": 4.0,
        "height": 2.0,
        "crest_elevation": 9.0,
        "max_flow": 4.0,
        "status": "online",
    }]

    result = HydraulicEngine().run(snapshot).to_dict()

    assert result["structure_series"] == []
    assert result["dispatch_events"] == []
    assert result["water_balance"]["status"] == "pass"


def test_uninitialized_fixed_envelope_does_not_change_the_baseline() -> None:
    """A generated but uninitialized fixed state is not an executable command."""

    snapshot = make_y_network(bifurcation=True)
    snapshot["gates"] = [{
        "id": 1,
        "river_segment_id": 2,
        "upstream_node_id": 3,
        "downstream_node_id": 2,
        "width": 4.0,
        "height": 2.0,
        "crest_elevation": 9.0,
        "status": "online",
        "control_state": {
            "mode": "fixed",
            "status": "uninitialized",
            "opening": None,
            "state_source": "uninitialized",
        },
    }]
    snapshot["pumps"] = [{
        "id": 1,
        "intake_node_id": 3,
        "outlet_node_id": None,
        "transfer_type": "external_outflow",
        "design_flow": 2.0,
        "status": "online",
        "control_state": {
            "mode": "fixed",
            "status": "uninitialized",
            "enabled": None,
            "running_units": None,
            "state_source": "uninitialized",
        },
    }]

    result = HydraulicEngine().run(snapshot).to_dict()

    assert result["structure_series"] == []
    assert result["dispatch_events"] == []


def test_nonfinite_fixed_control_state_fails_closed() -> None:
    """NaN must be rejected before it can enter a structure flow equation."""

    snapshot = make_y_network(bifurcation=True)
    snapshot["gates"] = [{
        "id": 1,
        "river_segment_id": 2,
        "upstream_node_id": 3,
        "downstream_node_id": 2,
        "width": 4.0,
        "height": 2.0,
        "crest_elevation": 9.0,
        "status": "online",
        "control_state": {"mode": "fixed", "opening": float("nan")},
    }]

    with pytest.raises(HydraulicInputError, match="must be finite"):
        HydraulicEngine().run(snapshot)


def test_nonfinite_dispatch_event_time_fails_closed() -> None:
    """A non-finite schedule time may not be silently dropped from the time axis."""

    snapshot = make_y_network(bifurcation=True)
    snapshot["dispatch_plan"] = {
        "actions": [{
            "id": 1,
            "time_seconds": float("inf"),
            "structure_type": "gate",
            "structure_id": 1,
            "command_type": "gate_opening_m",
            "target_value": 0.5,
            "interpolation": "step",
            "priority": 10,
        }],
        "rules": [],
    }

    with pytest.raises(HydraulicInputError, match="time_seconds.*finite"):
        HydraulicEngine().run(snapshot)


def test_rule_high_low_high_cycle_retains_the_second_trigger_and_application() -> None:
    """Recovery starts a new audit generation instead of swallowing a repeated command."""

    snapshot = make_y_network(bifurcation=True)
    for parameter in snapshot["parameters"]:
        if parameter["parameter_name"] == "duration_seconds":
            parameter["value"] = 120.0
        elif parameter["parameter_name"] == "output_interval":
            parameter["value"] = 60.0
    snapshot["boundary_conditions"][1]["values"] = {
        "mode": "series",
        "times": [0.0, 60.0, 120.0],
        "values": [10.5, 9.0, 10.5],
    }
    snapshot["gates"] = [{
        "id": 1,
        "river_segment_id": 2,
        "upstream_node_id": 3,
        "downstream_node_id": 2,
        "width": 8.0,
        "height": 2.0,
        "maximum_opening": 2.0,
        "crest_elevation": 9.0,
        "max_flow": 10.0,
        "status": "online",
    }]
    snapshot["dispatch_plan"] = {
        "actions": [],
        "rules": [{
            "id": 10,
            "name": "repeat-high-water-open",
            "enabled": True,
            "observation_type": "node_water_level",
            "observation_object_id": 2,
            "operator": ">",
            "threshold": 10.0,
            "hysteresis": 0.5,
            "minimum_hold_seconds": 0.0,
            "cooldown_seconds": 0.0,
            "action_template": {
                "structure_type": "gate",
                "structure_id": 1,
                "command_type": "gate_opening_m",
                "target_value": 0.5,
            },
            "priority": 10,
        }],
    }

    events = HydraulicEngine().run(snapshot).to_dict()["dispatch_events"]
    lifecycle = [event for event in events if event["applied_command"] is None]
    applications = [event for event in events if event["applied_command"] is not None]

    assert [
        (event["time_seconds"], event["outcome"])
        for event in lifecycle
    ] == [(0.0, "triggered"), (60.0, "recovered"), (120.0, "triggered")]
    assert [event["time_seconds"] for event in applications] == [0.0, 120.0]
