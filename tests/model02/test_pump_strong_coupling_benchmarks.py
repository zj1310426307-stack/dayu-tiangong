"""D1 long-horizon Gate/Pump strong-coupling benchmark gates."""

from __future__ import annotations

import math
import runpy
from pathlib import Path

import pytest

from model import HydraulicEngine


def make_d1_six_hour_benchmark_payload() -> dict:
    """Return the frozen 20-section, six-hour flood/recession scenario."""

    case_path = (
        Path(__file__).parents[2]
        / "examples"
        / "hydraulic"
        / "gate-pump-strong-coupling"
        / "case.py"
    )
    build_case = runpy.run_path(str(case_path))["build_case"]
    if not callable(build_case):
        raise TypeError("frozen D1 example does not export build_case")
    return build_case()


def test_gp1_six_hour_gate_pump_benchmark_closes_all_budgets() -> None:
    """Freeze the D1 flood, Gate open, Pump start/stop, water, and energy loop."""

    document = HydraulicEngine().run(make_d1_six_hour_benchmark_payload()).to_dict()
    events = [
        (event["structure_type"], event["action"])
        for event in document["control_events"]
    ]
    assert events == [("gate", "open"), ("pump", "start"), ("pump", "stop")]
    assert [event["time"] for event in document["control_events"]] == [
        2940.0,
        7740.0,
        12540.0,
    ]
    assert document["diagnostics"]["step_count"] == 381

    pump = document["pumps"][0]
    assert pump["control_state"][0] == "off"
    assert "on" in pump["control_state"]
    assert pump["control_state"][-1] == "off"
    running_flows = [
        flow
        for flow, status in zip(pump["flow_m3s"], pump["control_state"])
        if status == "on"
    ]
    assert running_flows
    assert max(running_flows) - min(running_flows) > 1.0e-5

    evidence = document["pump_coupling_evidence"][0]
    assert len(evidence["stage_evaluations"]) == (
        2 * document["diagnostics"]["step_count"]
    )
    assert evidence["maximum_absolute_head_residual_m"] <= (
        evidence["head_residual_tolerance_m"]
    )
    assert evidence["total_external_volume_m3"] == pytest.approx(
        document["water_balance"]["pump_outflow_volume"]
    )
    assert evidence["total_input_energy_kwh"] == pytest.approx(
        pump["cumulative_energy_kwh"][-1]
    )
    assert document["water_balance"]["relative_water_balance_error"] < 1.0e-12
    assert all(
        math.isfinite(value)
        for section in document["sections"]
        for field in ("water_level", "flow", "velocity", "volume_m3")
        for value in section[field]
    )
    assert min(
        value for section in document["sections"] for value in section["volume_m3"]
    ) > 0.0
