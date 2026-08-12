"""Ten quantitative Phase 4 hydraulic and dispatch benchmark cases."""

from __future__ import annotations

import copy
import math

import pytest

from model import HydraulicEngine
from model.diagnostics import evaluate_water_balance
from tests.test_hydraulic_engine import make_snapshot
from tests.test_phase4_network import make_y_network


def test_benchmark_01_variable_bed_high_lake() -> None:
    """A 12 m lake over a variable bed must remain at rest to the P0 tolerance."""

    snapshot = make_snapshot()
    beds = [8.0, 9.1, 10.2, 9.6, 8.8, 8.3]
    for section, bed in zip(snapshot["cross_sections"], beds):
        section["points"] = {"points": [[0.0, bed], [20.0, bed]]}
        section["elevation_min"] = bed
        section["roughness"] = 0.0
    snapshot["parameters"] = [
        {"parameter_name": "duration_seconds", "value": 600.0},
        {"parameter_name": "time_step", "value": 30.0},
        {"parameter_name": "output_interval", "value": 60.0},
        {"parameter_name": "cfl", "value": 0.75},
        {"parameter_name": "initial_water_level", "value": 12.0},
        {"parameter_name": "initial_flow", "value": 0.0},
        {"parameter_name": "minimum_depth", "value": 0.05},
    ]
    snapshot["boundary_conditions"][0]["values"] = {"mode": "constant", "value": 0.0}
    snapshot["boundary_conditions"][1]["values"] = {"mode": "constant", "value": 12.0}
    result = HydraulicEngine().run(snapshot).to_dict()
    maximum_velocity = max(abs(value) for row in result["series"] for value in row["velocity"])
    maximum_drift = max(abs(value - 12.0) for row in result["series"] for value in row["water_level"])
    assert maximum_velocity <= 1.0e-4
    assert maximum_drift <= 1.0e-4


def test_benchmark_02_manning_near_steady_relation() -> None:
    """Network backwater loss must reproduce the implemented Manning relation."""

    snapshot = make_y_network()
    result = HydraulicEngine().run(snapshot).to_dict()
    node_at_zero = {
        int(row["node_id"]): float(row["water_level"])
        for row in result["node_series"]
        if row["time_seconds"] == 0.0
    }
    area = 20.0
    radius = 20.0 / 22.0
    expected_loss = 0.03**2 * 10.0**2 * 1000.0 / (area**2 * radius ** (4.0 / 3.0))
    actual_loss = node_at_zero[1] - node_at_zero[3]
    assert actual_loss == pytest.approx(expected_loss, rel=1.0e-12, abs=1.0e-12)


def test_benchmark_03_flood_wave_propagation() -> None:
    """The hydrograph peak must reach an internal section with finite positive response."""

    result = HydraulicEngine().run(make_snapshot(flood=True)).to_dict()
    middle = result["series"][2]
    flow_gain = max(middle["flow"]) - middle["flow"][0]
    stage_gain = max(middle["water_level"]) - middle["water_level"][0]
    assert flow_gain > 1.0
    assert stage_gain > 0.0
    assert all(math.isfinite(value) for value in middle["flow"] + middle["water_level"])


def test_benchmark_04_y_confluence() -> None:
    """10 + 15 m³/s must produce 25 m³/s with zero junction residual."""

    result = HydraulicEngine().run(make_y_network()).to_dict()
    rows = [row for row in result["node_series"] if row["node_id"] == 3]
    assert all(row["inflow"] == pytest.approx(25.0) for row in rows)
    assert all(row["outflow"] == pytest.approx(25.0) for row in rows)
    assert max(abs(row["balance_residual"]) for row in rows) <= 1.0e-9


def test_benchmark_05_bifurcation() -> None:
    """Two equal conveyance branches must split 20 m³/s into 10 + 10 m³/s."""

    result = HydraulicEngine().run(make_y_network(bifurcation=True)).to_dict()
    flows = {
        row["river_id"]: row["flow"][0]
        for row in result["section_series"]
        if row["station"] == 0.0
    }
    assert flows[2] == pytest.approx(10.0)
    assert flows[3] == pytest.approx(10.0)
    assert result["diagnostics"]["maximum_node_balance_residual"] <= 1.0e-9


def _frozen_plan(actions: list[dict]) -> dict:
    """Build the minimum immutable plan shape consumed by the domain engine."""

    return {
        "schema_version": "dayu.dispatch-plan.v1",
        "plan": {"evaluation_config": {"warning_level": 200.0}},
        "actions": actions,
        "rules": [],
    }


def test_benchmark_06_internal_gate() -> None:
    """A 4 m³/s gate on one split branch must route the remaining 16 m³/s elsewhere."""

    snapshot = make_y_network(bifurcation=True)
    snapshot["gates"] = [{
        "id": 1, "river_segment_id": 2, "upstream_node_id": 3,
        "downstream_node_id": 2, "width": 4.0, "height": 2.0,
        "maximum_opening": 2.0, "minimum_opening": 0.0,
        "opening_rate_limit": 100.0, "minimum_hold_seconds": 0.0,
        "crest_elevation": 9.0, "discharge_coefficient": 0.62,
        "max_flow": 4.0, "status": "online", "allow_reverse_flow": False,
    }]
    snapshot["dispatch_plan"] = _frozen_plan([{
        "id": 1, "time_seconds": 0.0, "structure_type": "gate", "gate_id": 1,
        "command_type": "gate_opening_m", "target_value": 2.0,
        "interpolation": "step", "priority": 10,
    }])
    result = HydraulicEngine().run(snapshot).to_dict()
    gate_rows = result["structure_series"]
    assert gate_rows and all(row["flow"] == pytest.approx(4.0) for row in gate_rows)
    assert result["diagnostics"]["maximum_node_balance_residual"] <= 1.0e-9
    assert result["water_balance"]["gate_transfer_volume"] == pytest.approx(2400.0)


def test_benchmark_07_pump_cross_node_transfer() -> None:
    """A 2 m³/s pump transfers mass between source nodes and reports positive energy."""

    snapshot = make_y_network()
    snapshot["pumps"] = [{
        "id": 1, "intake_node_id": 1, "outlet_node_id": 2,
        "design_flow": 2.0, "unit_count": 1, "minimum_running_units": 1,
        "maximum_running_units": 1, "minimum_run_seconds": 0.0,
        "minimum_stop_seconds": 0.0, "maximum_starts_per_run": 5,
        "minimum_operating_head": 0.0, "maximum_operating_head": 100.0,
        "efficiency_curve": {"points": [[0.0, 0.7], [1.0, 0.8]]},
        "status": "online",
    }]
    snapshot["dispatch_plan"] = _frozen_plan([{
        "id": 2, "time_seconds": 0.0, "structure_type": "pump", "pump_id": 1,
        "command_type": "pump_unit_count", "target_value": 1.0,
        "interpolation": "step", "priority": 10,
    }])
    result = HydraulicEngine().run(snapshot).to_dict()
    rows = result["structure_series"]
    assert rows and all(row["flow"] == pytest.approx(2.0) for row in rows)
    assert rows[-1]["energy_kwh"] > 0.0
    assert result["water_balance"]["pump_transfer_volume"] == pytest.approx(1200.0)
    assert result["water_balance"]["relative_balance_residual"] <= 1.0e-9


def test_pump_head_curve_drives_power_on_equal_stage_nodes() -> None:
    """等节点水位时仍应使用 Q-H 曲线计算泵扬程、功率和能耗。"""

    snapshot = make_y_network()
    snapshot["pumps"] = [{
        "id": 1, "intake_node_id": 1, "outlet_node_id": 2,
        "design_flow": 2.0, "head_curve": {"points": [[0.0, 6.0], [2.0, 5.0]]},
        "unit_count": 1, "minimum_running_units": 1, "maximum_running_units": 1,
        "minimum_run_seconds": 0.0, "minimum_stop_seconds": 0.0,
        "maximum_starts_per_run": 5, "minimum_operating_head": 0.0,
        "maximum_operating_head": 100.0,
        "efficiency_curve": {"points": [[0.0, 0.7], [1.0, 0.8]]},
        "status": "online",
    }]
    snapshot["dispatch_plan"] = _frozen_plan([{
        "id": 2, "time_seconds": 0.0, "structure_type": "pump", "pump_id": 1,
        "command_type": "pump_unit_count", "target_value": 1.0,
        "interpolation": "step", "priority": 10,
    }])
    rows = HydraulicEngine().run(snapshot).to_dict()["structure_series"]
    assert rows[0]["power_kw"] > 0.0
    assert rows[-1]["energy_kwh"] > 0.0


def test_benchmark_08_gate_pump_combined_dispatch() -> None:
    """Combined controls remain deterministic, audited and mass conservative."""

    snapshot = make_y_network(bifurcation=True)
    snapshot["gates"] = [{
        "id": 1, "river_segment_id": 2, "upstream_node_id": 3,
        "downstream_node_id": 2, "width": 4.0, "height": 2.0,
        "maximum_opening": 2.0, "opening_rate_limit": 100.0,
        "crest_elevation": 9.0, "max_flow": 4.0, "status": "online",
    }]
    snapshot["pumps"] = [{
        "id": 1, "intake_node_id": 2, "outlet_node_id": 1,
        "design_flow": 2.0, "unit_count": 1, "minimum_running_units": 1,
        "maximum_running_units": 1, "minimum_run_seconds": 0.0,
        "minimum_stop_seconds": 0.0, "maximum_starts_per_run": 5,
        "minimum_operating_head": 0.0, "maximum_operating_head": 100.0,
        "efficiency_curve": {"points": [[0.0, 0.7], [1.0, 0.8]]},
        "status": "online",
    }]
    snapshot["dispatch_plan"] = _frozen_plan([
        {"id": 1, "time_seconds": 0.0, "structure_type": "gate", "gate_id": 1,
         "command_type": "gate_opening_m", "target_value": 2.0, "priority": 10},
        {"id": 2, "time_seconds": 0.0, "structure_type": "pump", "pump_id": 1,
         "command_type": "pump_unit_count", "target_value": 1.0, "priority": 10},
    ])
    first = HydraulicEngine().run(copy.deepcopy(snapshot)).to_dict()
    second = HydraulicEngine().run(copy.deepcopy(snapshot)).to_dict()
    assert first == second
    assert len(first["dispatch_events"]) >= 2
    assert {row["structure_type"] for row in first["structure_series"]} == {"gate", "pump"}
    assert first["water_balance"]["relative_balance_residual"] <= 1.0e-9


def test_benchmark_09_closed_system_mass_conservation() -> None:
    """A closed 100,000 m³ control volume with no flux has exactly zero residual."""

    balance = evaluate_water_balance(initial_storage=100_000.0, final_storage=100_000.0)
    assert balance.balance_residual == 0.0
    assert balance.relative_balance_residual == 0.0
    assert balance.status == "pass"


def test_benchmark_10_external_boundary_water_balance() -> None:
    """A 25 m³/s Y network over 600 s must balance 15,000 m³ in and out."""

    result = HydraulicEngine().run(make_y_network()).to_dict()
    balance = result["water_balance"]
    assert balance["external_inflow_volume"] == pytest.approx(15_000.0)
    assert balance["external_outflow_volume"] == pytest.approx(15_000.0)
    assert balance["relative_balance_residual"] <= 1.0e-9
    assert balance["status"] == "pass"
