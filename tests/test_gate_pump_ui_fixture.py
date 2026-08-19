"""Contract checks for the live-engine browser acceptance fixture."""

from __future__ import annotations

import json
from pathlib import Path
import runpy

from model import HydraulicEngine


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEMO_DIRECTORY = REPOSITORY_ROOT / "examples" / "hydraulic" / "gate-pump-demo"


def test_ui_fixture_exposes_unmodified_engine_structure_results() -> None:
    module = runpy.run_path(str(DEMO_DIRECTORY / "serve_ui_fixture.py"))
    payloads, evidence = module["build_fixture_payloads"]()
    snapshot = json.loads((DEMO_DIRECTORY / "input.json").read_text(encoding="utf-8"))
    expected = HydraulicEngine().run(snapshot).to_dict()

    rows = payloads["/api/v1/dispatch/runs/1/structures"]
    assert rows == expected["structure_series"]
    assert evidence["scope"].endswith("not a real database/API closure")
    assert evidence["input_schema_version"] == "dayu.model-input.v3"
    assert evidence["water_balance"]["status"] == "pass"


def test_ui_fixture_has_exact_24_hour_curve_and_auditable_rule_sources() -> None:
    module = runpy.run_path(str(DEMO_DIRECTORY / "serve_ui_fixture.py"))
    payloads, _ = module["build_fixture_payloads"]()

    rows = payloads["/api/v1/dispatch/runs/1/structures"]
    hours_by_type = {
        kind: {
            float(row["time_seconds"]) / 3600
            for row in rows
            if row["structure_type"] == kind
        }
        for kind in ("gate", "pump")
    }
    expected_hours = {float(hour) for hour in range(25)}
    assert hours_by_type == {"gate": expected_hours, "pump": expected_hours}
    assert {0.0, 6.0, 12.0, 24.0}.issubset(hours_by_type["gate"])

    events = payloads["/api/v1/dispatch/runs/1/events"]
    assert events
    assert {row["source_type"] for row in events} == {"rule"}
    assert {row["structure_type"] for row in events} == {"gate", "pump"}

    latest_pump = max(
        (row for row in rows if row["structure_type"] == "pump"),
        key=lambda row: row["time_seconds"],
    )
    assert latest_pump["energy_kwh"] > 0
    assert latest_pump["regime"] == "running"
