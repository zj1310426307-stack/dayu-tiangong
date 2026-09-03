"""泵站运行、抽排、功率和能耗指标。"""

from typing import Any


def evaluate_pump_metrics(structure_series: list[dict[str, Any]]) -> dict[str, float | int | None]:
    """聚合泵站容量请求、原生响应、实际输水量和运行指标。"""

    rows = [item for item in structure_series if item.get("structure_type") == "pump"]
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["structure_id"]), []).append(row)
    runtime = 0.0
    starts = 0
    stops = 0
    volume = 0.0
    requested_capacity_volume = 0.0
    resolved_capacity_volume = 0.0
    native_capacity_volume = 0.0
    maximum_tracking_error = 0.0
    energy_values: list[float] = []
    power_values: list[float] = []
    actual_flows: list[float] = []
    intake_levels: list[float] = []
    outlet_levels: list[float] = []
    for items in grouped.values():
        ordered = sorted(items, key=lambda item: float(item["time_seconds"]))
        previous_running = False
        for left, right in zip(ordered, ordered[1:]):
            dt = float(right["time_seconds"]) - float(left["time_seconds"])
            running = float(left.get("actual_value") or 0.0) > 0
            if running:
                runtime += dt
            actual_flow = float(
                left.get("actual_discharge")
                if left.get("actual_discharge") is not None
                else left.get("flow") or 0.0
            )
            volume += actual_flow * dt
            requested_capacity_volume += float(left.get("requested_value") or 0.0) * dt
            resolved_capacity_volume += float(left.get("resolved_value") or 0.0) * dt
            native_capacity = float(
                left.get("native_applied_capacity")
                if left.get("native_applied_capacity") is not None
                else left.get("actual_value") or 0.0
            )
            native_capacity_volume += native_capacity * dt
            maximum_tracking_error = max(
                maximum_tracking_error,
                abs(native_capacity - float(left.get("resolved_value") or 0.0)),
            )
            if running and not previous_running:
                starts += 1
            if previous_running and not running:
                stops += 1
            previous_running = running
        if ordered:
            if ordered[-1].get("energy_kwh") is not None:
                energy_values.append(float(ordered[-1]["energy_kwh"]))
            power_values.extend(
                float(item["power_kw"])
                for item in ordered
                if item.get("power_kw") is not None
            )
            actual_flows.extend(
                float(
                    item.get("actual_discharge")
                    if item.get("actual_discharge") is not None
                    else item.get("flow") or 0.0
                )
                for item in ordered
            )
            intake_levels.extend(
                float(item["intake_water_level"])
                for item in ordered
                if item.get("intake_water_level") is not None
            )
            outlet_levels.extend(
                float(item["outlet_water_level"])
                for item in ordered
                if item.get("outlet_water_level") is not None
            )
    return {
        "pump_runtime_seconds": runtime,
        "pump_start_count": starts,
        "pump_stop_count": stops,
        "pump_total_volume_m3": volume,
        "pump_actual_transfer_volume_m3": volume,
        "pump_requested_capacity_volume_m3": requested_capacity_volume,
        "pump_resolved_capacity_volume_m3": resolved_capacity_volume,
        "pump_native_capacity_volume_m3": native_capacity_volume,
        "pump_maximum_capacity_tracking_error_m3s": maximum_tracking_error,
        "pump_minimum_actual_flow_m3s": min(actual_flows) if actual_flows else None,
        "pump_maximum_actual_flow_m3s": max(actual_flows) if actual_flows else None,
        "pump_minimum_intake_level_m": min(intake_levels) if intake_levels else None,
        "pump_maximum_intake_level_m": max(intake_levels) if intake_levels else None,
        "pump_minimum_outlet_level_m": min(outlet_levels) if outlet_levels else None,
        "pump_maximum_outlet_level_m": max(outlet_levels) if outlet_levels else None,
        "pump_total_energy_kwh": sum(energy_values) if energy_values else None,
        "pump_peak_power_kw": max(power_values) if power_values else None,
    }
