"""集中维护工具名称、用途与只读权限边界。"""

from __future__ import annotations


TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_river_info": "只读查询河道、断面、闸门和泵站信息",
    "get_simulation_result": "只读聚合已完成水动力任务结果",
    "get_optimization_result": "只读查询推荐候选、Pareto 和评价指标",
    "generate_report": "基于已核验数据生成 Markdown/PDF 报告",
}


def allowed_tool_names() -> tuple[str, ...]:
    """返回固定工具白名单，禁止运行期注册任意函数。"""

    return tuple(TOOL_DESCRIPTIONS)
