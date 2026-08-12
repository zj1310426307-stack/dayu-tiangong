"""Hard constraints for generated dispatch plans and hydraulic outcomes."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConstraintResult:
    """Expose the required stable constraint response shape."""

    valid: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Serialize to the API contract requested by Phase 5."""

        return {"valid": self.valid, "reasons": list(self.reasons)}


def validate_candidate(
    plan: dict[str, Any],
    *,
    gates: list[dict[str, Any]],
    pumps: list[dict[str, Any]],
    config: dict[str, Any],
    metrics: dict[str, Any] | None = None,
) -> ConstraintResult:
    """Validate gate/pump action limits and optional hydraulic outcome limits."""

    reasons: list[str] = []
    gate_by_id = {int(item["id"]): item for item in gates}
    pump_by_id = {int(item["id"]): item for item in pumps}
    actions_by_asset: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for action in plan.get("actions", []):
        asset_id = int(action.get("gate_id") or action.get("pump_id") or 0)
        asset_type = str(action.get("structure_type"))
        actions_by_asset[(asset_type, asset_id)].append(action)
    maximum_actions = int(config.get("maximum_actions_per_asset", 8))
    for (asset_type, asset_id), actions in actions_by_asset.items():
        ordered = sorted(actions, key=lambda item: float(item.get("time_seconds", 0)))
        if len(ordered) > maximum_actions:
            reasons.append(f"{asset_type}:{asset_id}:action_count_exceeded")
        if asset_type == "gate":
            gate = gate_by_id.get(asset_id)
            if gate is None:
                reasons.append(f"gate:{asset_id}:not_found")
                continue
            previous: dict[str, Any] | None = None
            for action in ordered:
                target = float(action.get("target_value", 0))
                command = action.get("command_type")
                maximum_opening = float(gate.get("maximum_opening") or gate.get("height") or 0)
                low = (
                    float(gate.get("minimum_opening") or 0) / max(maximum_opening, 1e-9)
                    if command == "gate_opening_ratio"
                    else float(gate.get("minimum_opening") or 0)
                )
                high = 1.0 if command == "gate_opening_ratio" else maximum_opening
                if not low <= target <= high:
                    reasons.append(f"gate:{asset_id}:opening_out_of_range")
                if previous is not None and gate.get("opening_rate_limit"):
                    delta = abs(target - float(previous.get("target_value", 0)))
                    if command == "gate_opening_ratio":
                        delta *= float(gate.get("maximum_opening") or gate.get("height") or 0)
                    elapsed = float(action.get("time_seconds", 0)) - float(previous.get("time_seconds", 0))
                    limit = float(gate["opening_rate_limit"])
                    if elapsed <= 0 or delta / elapsed > limit * (1.0 + 1e-9) + 1e-12:
                        reasons.append(f"gate:{asset_id}:opening_rate_exceeded")
                previous = action
        elif asset_type == "pump":
            pump = pump_by_id.get(asset_id)
            if pump is None:
                reasons.append(f"pump:{asset_id}:not_found")
                continue
            starts = 0
            previous_on = False
            previous_time = 0.0
            for action in ordered:
                on = float(action.get("target_value", 0)) > 0
                action_time = float(action.get("time_seconds", 0))
                if on and not previous_on:
                    starts += 1
                if previous_on and not on and action_time - previous_time < float(pump.get("minimum_run_seconds") or 0):
                    reasons.append(f"pump:{asset_id}:minimum_runtime_violated")
                if on != previous_on:
                    previous_time = action_time
                previous_on = on
            allowed_starts = int(pump.get("maximum_starts_per_run") or config.get("maximum_pump_starts", 8))
            if starts > allowed_starts:
                reasons.append(f"pump:{asset_id}:maximum_starts_exceeded")
    if metrics is not None:
        limits = config.get("hydraulic_limits") or {}
        if limits.get("maximum_water_level") is not None and float(metrics.get("network_maximum_water_level") or 0) > float(limits["maximum_water_level"]):
            reasons.append("hydraulic:maximum_water_level_exceeded")
        if limits.get("maximum_flow") is not None and float(metrics.get("network_maximum_flow") or 0) > float(limits["maximum_flow"]):
            reasons.append("hydraulic:maximum_flow_exceeded")
        if limits.get("maximum_pump_power_kw") is not None and float(metrics.get("pump_peak_power_kw") or 0) > float(limits["maximum_pump_power_kw"]):
            reasons.append("pump:maximum_power_exceeded")
    unique_reasons = tuple(dict.fromkeys(reasons))
    return ConstraintResult(valid=not unique_reasons, reasons=unique_reasons)
