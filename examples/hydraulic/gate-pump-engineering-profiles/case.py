"""HYDRO-MODEL-02-D3A-3 gradual engineering-Profile Gate/Pump case."""

from __future__ import annotations

import math
import runpy
from pathlib import Path


def build_case() -> dict:
    """Add a mild single-channel contraction/expansion to the D3A-2 case."""

    d3a_2_case = Path(__file__).parents[1] / "gate-pump-manning-slope" / "case.py"
    payload = runpy.run_path(str(d3a_2_case))["build_case"]()
    section_count = len(payload["sections"])
    for index, section in enumerate(payload["sections"]):
        phase = index / (section_count - 1)
        width = 20.0 * (1.0 - 0.12 * math.sin(math.pi * phase))
        bed = section["bed_elevation_m"]
        section["points"] = [
            {"offset_m": 0.0, "elevation_m": bed + 3.0},
            {"offset_m": 0.5 * width, "elevation_m": bed},
            {"offset_m": width, "elevation_m": bed + 3.0},
        ]
        section["profile_hash"] = f"{300 + section['section_id']:064x}"
        section["bed_elevation_confirmed_by"] = "HYDRO-MODEL-02-D3A-3"
    payload["solver"]["geometry_policy"] = (
        "nonprismatic-engineering-linear-path-v1"
    )
    payload["solver"]["geometry_source"] = "hydraulic-function-linear-face-v1"
    payload["boundary"]["downstream"]["water_level_m"] = [9.79, 9.79, 9.79]
    payload["provenance"]["validation_policy_version"] = "d3a-3-v1"
    payload["provenance"]["engine_commit"] = "example-d3a-3-frozen"
    return payload


__all__ = ["build_case"]
