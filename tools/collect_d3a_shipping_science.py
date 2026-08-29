"""Collect Python 3.12 D3A shipping-science identity and envelope evidence."""

from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from model.adapters import (
    v4_lite_solver_policy_hash,
    v4_lite_validation_policy_hash,
)
from model.api import parse_v4_lite_input
from model.build_identity import runtime_build_diagnostic
from model.solver.registry import (
    D3A_1_CAPABILITY_ID,
    D3A_2_CAPABILITY_ID,
    D3A_3_CAPABILITY_ID,
    registry_hash,
    resolve_capability,
)


_CASES = {
    "d3a-1": "gate-pump-manning",
    "d3a-2": "gate-pump-manning-slope",
    "d3a-3": "gate-pump-engineering-profiles",
}


def _write_json(path: Path, value: object) -> None:
    """Write one stable UTF-8 JSON evidence document."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def collect(evidence_dir: Path, final_convergence: Path) -> None:
    """Validate the convergence artifact and emit all requested identities."""

    report = json.loads(final_convergence.read_text(encoding="utf-8"))
    levels = report.get("levels")
    completion_gates = report.get("completion_gates")
    if (
        report.get("schema_version") != "dayu.d3a-final-convergence.v2"
        or report.get("status") != "pass"
        or not isinstance(levels, list)
        or len(levels) != 4
        or not isinstance(completion_gates, dict)
        or not completion_gates
        or not all(value is True for value in completion_gates.values())
    ):
        raise ValueError("FIX1 FINAL convergence artifact is not a four-level v2 PASS")
    runtime = runtime_build_diagnostic()
    if runtime["python"]["major_minor"] != "3.12":
        raise ValueError("D3A shipping science must execute on Python 3.12")
    _write_json(evidence_dir / "runtime-build-identity.json", runtime)
    _write_json(evidence_dir / "python-version.json", runtime["python"])

    policy_hashes: dict[str, object] = {}
    for label, directory in _CASES.items():
        case_path = (
            _REPOSITORY_ROOT / "examples" / "hydraulic" / directory / "case.py"
        )
        payload = runpy.run_path(str(case_path))["build_case"]()
        parsed = parse_v4_lite_input(payload)
        policy_hashes[label] = {
            "validation_policy_version": (
                parsed.provenance.validation_policy_version
            ),
            "solver_policy_hash": v4_lite_solver_policy_hash(parsed),
            "validation_policy_hash": v4_lite_validation_policy_hash(parsed),
        }
    capabilities = {
        capability_id: {
            "runtime_envelope_id": entry.runtime_envelope_id,
            "runtime_envelope_hash": entry.runtime_envelope_hash,
        }
        for capability_id in (
            D3A_1_CAPABILITY_ID,
            D3A_2_CAPABILITY_ID,
            D3A_3_CAPABILITY_ID,
        )
        for entry in (resolve_capability(capability_id),)
    }
    _write_json(
        evidence_dir / "solver-registry-identity.json",
        {
            "registry_hash": registry_hash(),
            "capabilities": capabilities,
            "policies": policy_hashes,
        },
    )
    _write_json(
        evidence_dir / "runtime-envelope-summary.json",
        {
            "schema_version": "dayu.d3a-runtime-envelope-summary.v1",
            "status": "pass"
            if all(row["runtime_envelope_status"] == "pass" for row in levels)
            else "fail",
            "minimum_water_depth_m": min(
                row["minimum_water_depth_m"] for row in levels
            ),
            "minimum_discharge_m3s": min(
                row["minimum_discharge_m3s"] for row in levels
            ),
            "maximum_froude_number": max(
                row["maximum_froude_number"] for row in levels
            ),
            "runtime_envelope_retry_count": sum(
                row["runtime_envelope_retry_count"] for row in levels
            ),
            "friction_retry_count": sum(
                row["friction_retry_count"] for row in levels
            ),
            "accepted_step_count": sum(
                row["accepted_step_count"] for row in levels
            ),
        },
    )


def main() -> int:
    """Parse paths and collect D3A hosted shipping-science evidence."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--final-convergence", type=Path, required=True)
    arguments = parser.parse_args()
    collect(arguments.evidence_dir, arguments.final_convergence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
