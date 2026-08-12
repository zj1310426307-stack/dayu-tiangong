"""根据计划阈值评价水位风险，不在代码中硬编码警戒/保证水位。"""

from typing import Any


def evaluate_flood_risk(
    section_series: list[dict[str, Any]], evaluation_config: dict[str, Any]
) -> dict[str, Any]:
    """计算全网峰值、峰现时刻和各阈值超限时长。"""

    warning = evaluation_config.get("warning_level")
    guarantee = evaluation_config.get("guarantee_level")
    maximum = float("-inf")
    peak_time = 0.0
    warning_duration = 0.0
    guarantee_duration = 0.0
    section_maxima: dict[str, float] = {}
    for row in section_series:
        levels = [float(value) for value in row.get("water_level", [])]
        times = [float(value) for value in row.get("time", [])]
        if not levels:
            continue
        local_max = max(levels)
        section_maxima[str(row.get("section_code"))] = local_max
        if local_max > maximum:
            maximum = local_max
            peak_time = times[levels.index(local_max)]
        for left, right, level in zip(times, times[1:], levels[:-1]):
            if warning is not None and level > float(warning):
                warning_duration += right - left
            if guarantee is not None and level > float(guarantee):
                guarantee_duration += right - left
    return {
        "network_maximum_water_level": maximum if maximum != float("-inf") else None,
        "peak_time_seconds": peak_time,
        "section_maximum_water_levels": section_maxima,
        "warning_exceedance_seconds": warning_duration,
        "guarantee_exceedance_seconds": guarantee_duration,
    }
