"""Build stable PSO gene descriptors from frozen Phase 4 assets."""

from __future__ import annotations

from typing import Any


def build_dispatch_space(
    snapshot: dict[str, Any],
) -> tuple[list[tuple[float, float]], list[dict[str, Any]]]:
    """Return box bounds and asset/time descriptors for a complete plan particle."""

    bounds: list[tuple[float, float]] = []
    descriptors: list[dict[str, Any]] = []
    for gate in snapshot.get("gates", []):
        if gate.get("river_segment_id") is not None:
            for slot in (0.0, 0.5):
                bounds.append((0.0, 1.0))
                descriptors.append({"structure_type": "gate", "asset": gate, "slot": slot})
    for pump in snapshot.get("pumps", []):
        maximum = int(pump.get("maximum_running_units") or pump.get("unit_count") or 1)
        for slot in (0.0, 0.5):
            bounds.append((0.0, float(max(maximum, 1))))
            descriptors.append({"structure_type": "pump", "asset": pump, "slot": slot})
    if not bounds:
        return [(0.0, 1.0)], [{"structure_type": "noop", "asset": {}, "slot": 0.0}]
    return bounds, descriptors
