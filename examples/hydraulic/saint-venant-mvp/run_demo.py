"""Run the deterministic v4-lite single-river example and print a compact summary."""

from __future__ import annotations

import json
from pathlib import Path

from model import HydraulicEngine


def main() -> None:
    """Execute the frozen JSON through the direct finite-volume engine route."""

    input_path = Path(__file__).with_name("input_v4_lite.json")
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    result = HydraulicEngine().run(payload)
    document = result.to_dict()
    summary = {
        "input_schema_version": payload["schema_version"],
        "result_schema_version": document["schema_version"],
        "output_times_seconds": document["sections"][0]["time"],
        "section_count": len(document["sections"]),
        "gate_count": len(document["gates"]),
        "pump_count": len(document["pumps"]),
        "water_balance_status": document["water_balance"]["status"],
        "relative_water_balance_error": document["water_balance"][
            "relative_water_balance_error"
        ],
        "maximum_cfl": document["diagnostics"]["maximum_cfl"],
        "minimum_dt": document["diagnostics"]["minimum_dt"],
        "retry_count": document["diagnostics"]["retry_count"],
        "diagnostic_flags": document["diagnostics"]["diagnostic_flags"],
        "input_snapshot_hash": document["provenance"]["input_snapshot_hash"],
        "mesh_hash": document["provenance"]["mesh_hash"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
