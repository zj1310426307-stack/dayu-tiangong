"""泵站运行、抽排、功率和能耗指标。"""

from typing import Any


def evaluate_pump_metrics(structure_series: list[dict[str, Any]]) -> dict[str, float | int]:
    """聚合泵站结果中的运行时长、启动、体积、能耗和峰值功率。"""

    rows = [item for item in structure_series if item.get("structure_type") == "pump"]
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["structure_id"]), []).append(row)
    runtime = 0.0
    starts = 0
    stops = 0
    volume = 0.0
    energy = 0.0
    peak_power = 0.0
    for items in grouped.values():
        ordered = sorted(items, key=lambda item: float(item["time_seconds"]))
        previous_running = False
        for left, right in zip(ordered, ordered[1:]):
            dt = float(right["time_seconds"]) - float(left["time_seconds"])
            running = float(left.get("actual_value") or 0.0) > 0
            if running:
                runtime += dt
                volume += float(left.get("flow") or 0.0) * dt
            if running and not previous_running:
                starts += 1
            if previous_running and not running:
                stops += 1
            previous_running = running
        if ordered:
            energy += float(ordered[-1].get("energy_kwh") or 0.0)
            peak_power = max(peak_power, max(float(item.get("power_kw") or 0.0) for item in ordered))
    return {
        "pump_runtime_seconds": runtime,
        "pump_start_count": starts,
        "pump_stop_count": stops,
        "pump_total_volume_m3": volume,
        "pump_total_energy_kwh": energy,
        "pump_peak_power_kw": peak_power,
    }
