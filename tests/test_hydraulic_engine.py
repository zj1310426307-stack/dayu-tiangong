"""Unit tests for the framework-neutral Phase 3 hydraulic engine."""

import math

import pytest

from model import HydraulicEngine
from model.structure.gate import gate_discharge
from model.structure.pump import pump_discharge


def make_snapshot(*, flood: bool = False, requested_time_step: float = 30.0) -> dict:
    """Build a deterministic straight-channel snapshot without database access."""

    section_count = 6
    sections = [
        {
            "id": index + 1,
            "dataset_version_id": 1,
            "river_id": 1,
            "section_code": f"CS-{index + 1:02d}",
            "station": index * 200.0,
            "points": {"points": [[0.0, 9.0], [20.0, 9.0]]},
            "elevation_min": 9.0,
            "elevation_max": 9.0,
            "roughness": 0.0,
        }
        for index in range(section_count)
    ]
    upstream_values = (
        {"mode": "series", "times": [0, 150, 300, 600], "values": [20, 80, 80, 20]}
        if flood
        else {"mode": "constant", "value": 20.0}
    )
    return {
        "schema_version": "dayu.model-input.v1",
        "dataset_version": {"id": 1, "version_code": "TEST-V1"},
        "rivers": [
            {
                "id": 1,
                "dataset_version_id": 1,
                "code": "R-TEST",
                "name": "Test River",
                "river_level": 1,
                "status": "active",
                "length": 1000.0,
            }
        ],
        "nodes": [
            {"id": 1, "river_id": 1, "node_code": "N-UP"},
            {"id": 2, "river_id": 1, "node_code": "N-DOWN"},
        ],
        "segments": [
            {
                "id": 1,
                "river_id": 1,
                "segment_code": "S-01",
                "upstream_node_id": 1,
                "downstream_node_id": 2,
                "length": 1000.0,
            }
        ],
        "cross_sections": sections,
        "boundary_conditions": [
            {
                "id": 1,
                "boundary_type": "upstream_flow",
                "target_node_id": 1,
                "values": upstream_values,
            },
            {
                "id": 2,
                "boundary_type": "downstream_water_level",
                "target_node_id": 2,
                "values": {"mode": "constant", "value": 10.0},
            },
        ],
        "parameters": [
            {"parameter_name": "duration_seconds", "value": 600.0},
            {"parameter_name": "time_step", "value": requested_time_step},
            {"parameter_name": "output_interval", "value": 60.0},
            {"parameter_name": "cfl", "value": 0.75},
            {"parameter_name": "initial_water_level", "value": 10.0},
            {"parameter_name": "initial_flow", "value": 20.0},
            {"parameter_name": "minimum_depth", "value": 0.05},
        ],
        "gates": [
            {
                "id": 1,
                "gate_code": "G-01",
                "width": 5.0,
                "height": 2.0,
                "max_flow": 30.0,
                "bottom_elevation": 9.0,
                "status": "online",
            }
        ],
        "pumps": [
            {
                "id": 1,
                "pump_code": "P-01",
                "design_flow": 8.0,
                "status": "online",
            }
        ],
    }


def test_single_river_produces_finite_section_time_series() -> None:
    """Every section must expose aligned and finite stage/flow/velocity arrays."""

    result = HydraulicEngine().run(make_snapshot()).to_dict()

    assert result["schema_version"] == "dayu.hydraulic-result.v1"
    assert len(result["series"]) == 6
    assert result["diagnostics"]["coordinate_system"] == "CGCS2000 (EPSG:4490)"
    for series in result["series"]:
        lengths = {
            len(series["time"]),
            len(series["water_level"]),
            len(series["flow"]),
            len(series["velocity"]),
        }
        assert lengths == {11}
        assert series["time"][0] == 0.0
        assert series["time"][-1] == 600.0
        assert all(math.isfinite(value) for value in series["water_level"])
        assert all(math.isfinite(value) for value in series["flow"])
        assert all(math.isfinite(value) for value in series["velocity"])


def test_steady_uniform_channel_remains_steady() -> None:
    """A flat frictionless channel with matching boundaries is an exact state."""

    result = HydraulicEngine().run(make_snapshot()).to_dict()
    middle = result["series"][3]

    assert middle["water_level"] == pytest.approx([10.0] * 11, abs=1.0e-8)
    assert middle["flow"] == pytest.approx([20.0] * 11, abs=1.0e-8)


def test_upstream_flood_wave_reaches_internal_sections() -> None:
    """An upstream hydrograph must change flow away from the boundary cell."""

    result = HydraulicEngine().run(make_snapshot(flood=True)).to_dict()
    middle = result["series"][2]

    assert max(middle["flow"]) > middle["flow"][0] + 1.0
    assert max(middle["water_level"]) > middle["water_level"][0]


def test_cfl_controller_reduces_an_unsafe_requested_step() -> None:
    """The solver must adapt an oversized requested step to its CFL limit."""

    result = HydraulicEngine().run(make_snapshot(requested_time_step=500.0)).to_dict()
    diagnostics = result["diagnostics"]["river_diagnostics"]["R-TEST"]

    assert diagnostics["time_step_reduction_count"] > 0
    assert diagnostics["minimum_used_time_step"] < 500.0
    assert diagnostics["maximum_cfl"] <= 0.75 + 1.0e-9


def test_gate_and_pump_placeholders_enforce_capacity_and_status() -> None:
    """Reserved structure equations expose deterministic bounded discharges."""

    assert gate_discharge(5.0, 2.0, 12.0, 9.0, 9.0, maximum_flow=25.0) == 25.0
    assert pump_discharge(8.0, enabled=True) == 8.0
    assert pump_discharge(8.0, enabled=False) == 0.0
