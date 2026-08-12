"""Compose constraint and objective evaluation without persistence concerns."""

from __future__ import annotations

from typing import Any

from optimization.constraints import validate_candidate
from optimization.objectives import evaluate_objectives


def evaluate_candidate(
    plan: dict[str, Any],
    metrics: dict[str, Any],
    *,
    gates: list[dict[str, Any]],
    pumps: list[dict[str, Any]],
    objective_config: dict[str, Any],
    constraint_config: dict[str, Any],
) -> dict[str, Any]:
    """Return objective values and the stable feasibility response together."""

    constraints = validate_candidate(
        plan,
        gates=gates,
        pumps=pumps,
        config=constraint_config,
        metrics=metrics,
    )
    objectives = evaluate_objectives(metrics, objective_config)
    return {"constraints": constraints.as_dict(), "objectives": objectives}
