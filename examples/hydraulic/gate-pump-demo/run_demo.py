"""Run the committed 24-hour gate-pump input and verify its frozen summary."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
from typing import Any

DEMO_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = DEMO_DIRECTORY.parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from model import HydraulicEngine  # noqa: E402


def build_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Return the stable acceptance subset instead of writing a large result dump."""

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
    return {
        "input_schema_version": result["provenance"]["input_schema_version"],
        "result_schema_version": result["schema_version"],
        "solver": result["diagnostics"]["solver"],
        "hydraulic_reach_count": result["provenance"]["reach_count"],
        "duration_seconds": result["diagnostics"]["time_axis"][-1],
        "output_frame_count": len(result["diagnostics"]["time_axis"]),
        "section_series_count": len(result["section_series"]),
        "structure_result_count": len(result["structure_series"]),
        "dispatch_event_count": len(result["dispatch_events"]),
        "dispatch_event_source_types": sorted(
            {row["source_type"] for row in result["dispatch_events"]}
        ),
        "rule_trigger_count": result["diagnostics"]["rule_trigger_count"],
        "structure_types": sorted(
            {row["structure_type"] for row in result["structure_series"]}
        ),
        "all_numeric_results_finite": all(
            math.isfinite(float(value)) for value in numeric_values
        ),
        "water_balance": result["water_balance"],
        "scientific_scope": "quasi-steady software acceptance only",
        "production_calibrated": False,
    }


def main() -> None:
    """Execute the immutable input and compare it with the committed summary."""

    snapshot = json.loads(
        (DEMO_DIRECTORY / "input.json").read_text(encoding="utf-8")
    )
    actual = build_summary(HydraulicEngine().run(snapshot).to_dict())
    expected = json.loads(
        (DEMO_DIRECTORY / "result_summary.json").read_text(encoding="utf-8")
    )
    if actual != expected:
        raise SystemExit(
            "result summary drifted:\n"
            + json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True)
        )
    print(json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
