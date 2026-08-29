"""HYDRO-MODEL-02-D3A-1 six-hour positive-Manning Gate/Pump case."""

from __future__ import annotations

import runpy
from pathlib import Path


def build_case() -> dict:
    """Clone the frozen D1 case and change only capability identity and Manning n."""

    d1_case = Path(__file__).parents[1] / "gate-pump-strong-coupling" / "case.py"
    payload = runpy.run_path(str(d1_case))["build_case"]()
    for section in payload["sections"]:
        section["default_manning_n"] = 0.025
    payload["provenance"]["validation_policy_version"] = "d3a-1-v1"
    payload["provenance"]["engine_commit"] = "example-d3a-1-frozen"
    return payload


__all__ = ["build_case"]
