"""HYDRO-MODEL-02-D3A-2 six-hour explicit-slope Gate/Pump case."""

from __future__ import annotations

import runpy
from pathlib import Path


BED_SLOPE = 1.0e-7
BED_CONFIRMATION_TIME = "2026-08-29T00:00:00Z"


def build_case() -> dict:
    """Translate the D3A-1 Profile by one declared downstream bed slope."""

    d3a_1_case = Path(__file__).parents[1] / "gate-pump-manning" / "case.py"
    payload = runpy.run_path(str(d3a_1_case))["build_case"]()
    for section in payload["sections"]:
        bed = 9.0 - BED_SLOPE * section["chainage_m"]
        vertical_shift = bed - 9.0
        for point in section["points"]:
            point["elevation_m"] += vertical_shift
        section["profile_hash"] = f"{200 + section['section_id']:064x}"
        section["bed_elevation_m"] = bed
        section["bed_elevation_source"] = "synthetic"
        section["bed_elevation_confirmed_by"] = "HYDRO-MODEL-02-D3A-2"
        section["bed_elevation_confirmed_at"] = BED_CONFIRMATION_TIME
    payload["solver"]["geometry_policy"] = "relative-prismatic-linear-bed-v1"
    payload["solver"]["bed_elevation_source"] = (
        "explicit-section-bed-elevation-v1"
    )
    payload["boundary"]["downstream"]["water_level_m"] = [9.8, 9.8, 9.8]
    for value in payload["initial_state"]["values"]:
        if value["section_id"] >= 9:
            value["water_level_m"] = 9.8
    pump_control = payload["structures"]["pumps"][0]["control"]
    pump_control["start_level_m"] = 9.782
    pump_control["stop_level_m"] = 9.778
    pump_control["minimum_stop_seconds"] = 4000.0
    payload["provenance"]["validation_policy_version"] = "d3a-2-v1"
    payload["provenance"]["engine_commit"] = "example-d3a-2-frozen"
    return payload


__all__ = ["BED_SLOPE", "build_case"]
