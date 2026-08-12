"""把水量平衡和节点残差映射为评价指标。"""

from typing import Any


def evaluate_quality(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """提取全域残差、节点残差、CFL、时间步和控制统计。"""

    balance = diagnostics.get("water_balance", {})
    return {
        "global_balance_residual": balance.get("balance_residual"),
        "relative_balance_residual": balance.get("relative_balance_residual"),
        "balance_status": balance.get("status"),
        "maximum_node_balance_residual": diagnostics.get("maximum_node_balance_residual"),
        "maximum_cfl": diagnostics.get("maximum_cfl", 0.0),
        "minimum_time_step": diagnostics.get(
            "minimum_used_time_step", diagnostics.get("minimum_time_step")
        ),
        "dry_clamp_count": diagnostics.get("dry_clamp_count", 0),
        "rule_trigger_count": diagnostics.get("rule_trigger_count", 0),
        "conflict_resolution_count": diagnostics.get("conflict_resolution_count", 0),
    }
