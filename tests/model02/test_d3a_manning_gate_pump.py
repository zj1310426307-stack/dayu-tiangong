"""D3A-1 positive-Manning six-hour Gate/Pump integration gate."""

from __future__ import annotations

import math
import runpy
from pathlib import Path

from model import HydraulicEngine


def _load(path: Path) -> dict:
    build_case = runpy.run_path(str(path))["build_case"]
    if not callable(build_case):
        raise TypeError("benchmark case does not export build_case")
    return build_case()


def _case_paths() -> tuple[Path, Path]:
    root = Path(__file__).parents[2] / "examples" / "hydraulic"
    return (
        root / "gate-pump-strong-coupling" / "case.py",
        root / "gate-pump-manning" / "case.py",
    )


def test_d3a_manning_case_changes_only_roughness_and_capability_identity() -> None:
    """No hidden bed, Profile, structure, boundary or control change is allowed."""

    d1_path, d3a_path = _case_paths()
    d1 = _load(d1_path)
    d3a = _load(d3a_path)
    d1["provenance"]["validation_policy_version"] = "d3a-1-v1"
    d1["provenance"]["engine_commit"] = "example-d3a-1-frozen"
    for section in d1["sections"]:
        section["default_manning_n"] = 0.025
    assert d3a == d1
    assert all(section["default_manning_n"] == 0.025 for section in d3a["sections"])
    beds = {min(point["elevation_m"] for point in item["points"]) for item in d3a["sections"]}
    profiles = {
        tuple((point["offset_m"], point["elevation_m"]) for point in item["points"])
        for item in d3a["sections"]
    }
    assert beds == {9.0}
    assert len(profiles) == 1


def test_d3a_manning_gate_pump_closes_science_and_accounting_evidence() -> None:
    """Positive friction must retain causal structures, energy and water closure."""

    _, d3a_path = _case_paths()
    document = HydraulicEngine().run(_load(d3a_path)).to_dict()
    events = [
        (event["structure_type"], event["action"], event["time"])
        for event in document["control_events"]
    ]
    assert events == [("pump", "start", 3000.0), ("gate", "open", 3015.0)]
    assert all(right[2] >= left[2] for left, right in zip(events, events[1:]))

    diagnostics = document["diagnostics"]
    assert 0.0 < diagnostics["maximum_friction_number"] <= 0.1 + 1.0e-12
    assert diagnostics["friction_retry_count"] >= 0
    assert "friction_number_retry_gate_v1" in diagnostics["diagnostic_flags"]
    assert document["water_balance"]["relative_water_balance_error"] <= 1.0e-10

    gate = document["controlled_gate_coupling_evidence"][0]
    assert gate["maximum_absolute_energy_residual"] <= gate["equation_tolerance"]
    open_rows = [row for row in gate["stage_evaluations"] if row["actual_opening"] > 0.0]
    assert open_rows
    assert all(row["head_loss"] >= 0.0 for row in open_rows)
    assert all(row["flow"] >= 0.0 for row in open_rows)

    pump = document["pump_coupling_evidence"][0]
    assert pump["total_external_volume_m3"] > 0.0
    assert pump["total_input_energy_kwh"] > 0.0
    assert pump["maximum_absolute_head_residual_m"] <= pump["head_residual_tolerance_m"]
    assert all(row["input_power_kw"] >= 0.0 for row in pump["stage_evaluations"])
    assert all(
        math.isfinite(value)
        for section in document["sections"]
        for field in ("water_level", "flow", "velocity", "volume_m3")
        for value in section[field]
    )
    assert min(
        value for section in document["sections"] for value in section["volume_m3"]
    ) > 0.0
