"""组合防洪、能耗、设备动作和数值质量指标。"""

from typing import Any

from model.metrics.energy import evaluate_pump_metrics
from model.metrics.flood_risk import evaluate_flood_risk
from model.metrics.operation import evaluate_gate_metrics
from model.metrics.water_balance import evaluate_quality


def evaluate_metrics(
    *,
    section_series: list[dict[str, Any]],
    structure_series: list[dict[str, Any]],
    diagnostics: dict[str, Any],
    evaluation_config: dict[str, Any],
    baseline_section_series: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """返回纯评价结果；不会搜索、推荐或自动执行所谓最优方案。"""

    metrics = {
        **evaluate_flood_risk(section_series, evaluation_config),
        **evaluate_pump_metrics(structure_series),
        **evaluate_gate_metrics(structure_series),
        **evaluate_quality(diagnostics),
    }
    if baseline_section_series:
        baseline = evaluate_flood_risk(baseline_section_series, evaluation_config)
        controlled_peak = metrics.get("network_maximum_water_level")
        baseline_peak = baseline.get("network_maximum_water_level")
        metrics["maximum_level_reduction"] = (
            float(baseline_peak) - float(controlled_peak)
            if baseline_peak is not None and controlled_peak is not None
            else None
        )
    else:
        metrics["maximum_level_reduction"] = None
    return metrics
