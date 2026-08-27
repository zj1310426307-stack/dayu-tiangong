"""Keep the checked-in v4-lite example and its evidence summary reproducible."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from model import HydraulicEngine


def test_synthetic_example_reproduces_the_checked_in_summary() -> None:
    """Run the public example and detect input, mesh, or diagnostic drift."""

    example = Path(__file__).parents[2] / "examples" / "hydraulic" / "saint-venant-mvp"
    payload = json.loads((example / "input_v4_lite.json").read_text(encoding="utf-8"))
    expected = json.loads((example / "result_summary.json").read_text(encoding="utf-8"))
    result = HydraulicEngine().run(payload).to_dict()

    assert result["schema_version"] == expected["result_schema_version"]
    assert result["provenance"]["input_snapshot_hash"] == expected[
        "input_snapshot_hash"
    ]
    assert result["provenance"]["mesh_hash"] == expected["mesh_hash"]
    assert result["sections"][0]["time"] == expected["output_times_seconds"]
    assert len(result["sections"]) == expected["section_count"]
    assert len(result["gates"]) == expected["gate_count"]
    assert len(result["pumps"]) == expected["pump_count"]
    assert result["water_balance"]["status"] == expected["water_balance_status"]
    relative_error = result["water_balance"]["relative_water_balance_error"]
    assert math.isfinite(relative_error)
    assert result["water_balance"]["tolerance"] == expected[
        "water_balance_tolerance"
    ]
    assert relative_error <= expected["water_balance_tolerance"]
    assert result["diagnostics"]["maximum_cfl"] == pytest.approx(
        expected["maximum_cfl"], rel=0.0, abs=1.0e-15
    )
    assert result["diagnostics"]["minimum_dt"] == expected["minimum_dt"]
    assert result["diagnostics"]["retry_count"] == expected["retry_count"]
    assert result["diagnostics"]["diagnostic_flags"] == expected[
        "diagnostic_flags"
    ]
