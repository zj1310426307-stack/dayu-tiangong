"""Create canonical, versioned optimization task snapshots."""

from __future__ import annotations

from typing import Any

from model.provenance import snapshot_hash


def build_optimization_snapshot(
    *,
    dataset_version_id: int,
    simulation_case_id: int,
    algorithm: str,
    algorithm_version: str,
    objective_config: dict[str, Any],
    algorithm_config: dict[str, Any],
    hydraulic_input: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Return a complete optimization input and its canonical SHA-256."""

    snapshot = {
        "schema_version": "dayu.optimization-task.v1",
        "coordinate_system": "CGCS2000 (EPSG:4490)",
        "dataset_version_id": dataset_version_id,
        "simulation_case_id": simulation_case_id,
        "algorithm": algorithm,
        "algorithm_version": algorithm_version,
        "objective_config": objective_config,
        "algorithm_config": algorithm_config,
        "hydraulic_input": hydraulic_input,
        "safety_notice": "recommendation only; no command is sent to real equipment",
    }
    return snapshot, snapshot_hash(snapshot)
