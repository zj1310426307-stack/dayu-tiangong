"""HYDRO-MODEL-01 reproducible 24-hour gate-pump closure test."""

import json
import math
from pathlib import Path

from model import HydraulicEngine


DEMO_DIRECTORY = (
    Path(__file__).resolve().parents[1] / "examples" / "hydraulic" / "gate-pump-demo"
)


def _load_input() -> dict:
    """Load the committed immutable demonstration input."""

    return json.loads((DEMO_DIRECTORY / "input.json").read_text(encoding="utf-8"))


def test_gate_pump_24_hour_simulation_closes_all_minimum_gates() -> None:
    """The 5 km case must finish 24 h with finite, balanced, audited results."""

    snapshot = _load_input()
    result = HydraulicEngine().run(snapshot).to_dict()

    assert snapshot["schema_version"] == "dayu.model-input.v3"
    assert snapshot["parameters"][0] == {
        "parameter_name": "duration_seconds",
        "value": 86400.0,
    }
    assert [
        (
            reach["id"],
            reach["start_chainage_m"],
            reach["end_chainage_m"],
            reach["upstream_node_id"],
            reach["downstream_node_id"],
        )
        for reach in snapshot["reaches"]
    ] == [
        (101, 0, 2500, 1, 2),
        (102, 2500, 4000, 2, 3),
        (103, 4000, 5000, 3, 4),
    ]
    assert snapshot["structures"]["gates"] == snapshot["gates"]
    assert snapshot["structures"]["pumps"] == snapshot["pumps"]
    assert snapshot["pumps"][0]["chainage"] == 4000
    assert snapshot["pumps"][0]["provenance"]["chainage_source"] == "synthetic_demo_contract"
    assert snapshot["controls"]["rules"] == snapshot["dispatch_plan"]["rules"]
    required_structure_fields = {
        "id",
        "dataset_version_id",
        "branch_id",
        "chainage",
        "geometry",
        "parameters",
        "control_state",
        "provenance",
    }
    assert all(
        required_structure_fields.issubset(structure)
        for collection in snapshot["structures"].values()
        for structure in collection
    )
    assert len(snapshot["cross_sections"]) == 20
    assert result["diagnostics"]["time_axis"] == [float(hour * 3600) for hour in range(25)]
    assert {row["structure_type"] for row in result["structure_series"]} == {
        "gate",
        "pump",
    }
    assert {event["structure_type"] for event in result["dispatch_events"]} == {
        "gate",
        "pump",
    }
    assert {event["source_type"] for event in result["dispatch_events"]} == {"rule"}
    assert result["diagnostics"]["rule_trigger_count"] == 2
    assert result["provenance"]["input_schema_version"] == "dayu.model-input.v3"
    assert result["water_balance"]["relative_balance_residual"] < 0.01
    assert result["water_balance"]["status"] == "pass"
    numeric_values = [
        value
        for series in result["section_series"]
        for key in ("water_level", "flow", "velocity")
        for value in series[key]
    ]
    numeric_values.extend(
        float(row[key])
        for row in result["structure_series"]
        for key in ("flow", "power_kw", "energy_kwh")
    )
    assert numeric_values
    assert all(math.isfinite(value) for value in numeric_values)


def test_gate_pump_24_hour_result_matches_the_committed_summary() -> None:
    """The concise checked-in summary must remain reproducible from input.json."""

    result = HydraulicEngine().run(_load_input()).to_dict()
    summary = json.loads(
        (DEMO_DIRECTORY / "result_summary.json").read_text(encoding="utf-8")
    )

    assert summary["result_schema_version"] == result["schema_version"]
    assert summary["input_schema_version"] == "dayu.model-input.v3"
    assert summary["hydraulic_reach_count"] == 3
    assert summary["rule_trigger_count"] == 2
    assert summary["section_series_count"] == len(result["section_series"])
    assert summary["structure_result_count"] == len(result["structure_series"])
    assert summary["dispatch_event_count"] == len(result["dispatch_events"])
    assert summary["water_balance"] == result["water_balance"]
