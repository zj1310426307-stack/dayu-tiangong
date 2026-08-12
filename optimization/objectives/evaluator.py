"""Versioned multi-objective score calculation for dispatch candidates."""

from __future__ import annotations

from typing import Any


def _scaled(value: Any, scale: float) -> float:
    """Return a safe non-negative normalized value."""

    return max(0.0, float(value or 0.0)) / max(float(scale), 1e-9)


def evaluate_objectives(
    metrics: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    """Return flood, energy and operation components plus weighted total score."""

    if config.get("version") != "dayu.objectives.v1":
        raise ValueError("unsupported objective config version")
    weights = config.get("weights") or {}
    raw_weights = {
        "flood_risk": float(weights.get("flood_risk", 0.5)),
        "energy_cost": float(weights.get("energy_cost", 0.3)),
        "operation_cost": float(weights.get("operation_cost", 0.2)),
    }
    if any(value < 0 for value in raw_weights.values()) or sum(raw_weights.values()) <= 0:
        raise ValueError("objective weights must be non-negative and have a positive sum")
    total_weight = sum(raw_weights.values())
    normalized_weights = {key: value / total_weight for key, value in raw_weights.items()}
    scales = config.get("normalization") or {}
    flood_risk = (
        _scaled(metrics.get("network_maximum_water_level"), scales.get("maximum_water_level", 400))
        + _scaled(metrics.get("warning_exceedance_seconds"), scales.get("warning_duration", 3600))
        + 2.0
        * _scaled(
            metrics.get("guarantee_exceedance_seconds"),
            scales.get("guarantee_duration", 3600),
        )
    )
    energy_cost = (
        _scaled(metrics.get("pump_total_energy_kwh"), scales.get("pump_energy_kwh", 1000))
        + _scaled(metrics.get("pump_runtime_seconds"), scales.get("pump_runtime_seconds", 3600))
        + _scaled(metrics.get("pump_start_count"), scales.get("pump_start_count", 10))
    )
    operation_cost = (
        _scaled(metrics.get("gate_action_count"), scales.get("gate_action_count", 20))
        + _scaled(
            metrics.get("gate_cumulative_opening_change_m"),
            scales.get("gate_cumulative_opening_change", 10),
        )
        + _scaled(metrics.get("pump_start_count"), scales.get("pump_start_count", 10))
        + _scaled(metrics.get("pump_stop_count"), scales.get("pump_stop_count", 10))
    )
    values = {
        "flood_risk": flood_risk,
        "energy_cost": energy_cost,
        "operation_cost": operation_cost,
    }
    score = sum(normalized_weights[key] * values[key] for key in values)
    return {
        "version": "dayu.objectives.v1",
        "weights": normalized_weights,
        "values": values,
        "score": score,
    }
