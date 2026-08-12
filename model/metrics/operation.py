"""闸门动作、开度变化、速率与约束次数指标。"""

from typing import Any


def evaluate_gate_metrics(structure_series: list[dict[str, Any]]) -> dict[str, float | int]:
    """按设备时序聚合实际开度变化和限幅/拒绝。"""

    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in structure_series:
        if row.get("structure_type") == "gate":
            grouped.setdefault(int(row["structure_id"]), []).append(row)
    action_count = 0
    cumulative_change = 0.0
    maximum_rate = 0.0
    constrained = 0
    for items in grouped.values():
        ordered = sorted(items, key=lambda item: float(item["time_seconds"]))
        for left, right in zip(ordered, ordered[1:]):
            change = abs(float(right.get("actual_value") or 0.0) - float(left.get("actual_value") or 0.0))
            dt = float(right["time_seconds"]) - float(left["time_seconds"])
            if change > 1.0e-12:
                action_count += 1
                cumulative_change += change
                maximum_rate = max(maximum_rate, change / max(dt, 1.0e-12))
        constrained += sum(bool(item.get("constraint_flags")) for item in ordered)
    return {
        "gate_action_count": action_count,
        "gate_cumulative_opening_change_m": cumulative_change,
        "gate_maximum_opening_rate_mps": maximum_rate,
        "gate_limited_or_rejected_count": constrained,
    }
