"""从持久化基准/受控结果构建曲线差值和评价指标。"""

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.gis.models import DispatchRun, SimulationResult, SimulationTask, StructureResult
from model.metrics import evaluate_metrics


def build_comparison(
    session: Session, run: DispatchRun, evaluation_config: dict[str, Any]
) -> dict[str, Any]:
    """选择共同断面、对齐水位并计算防洪/能耗/动作/质量指标。"""

    if run.baseline_task_id is None or run.controlled_task_id is None:
        return {"section_code": None, "time": [], "baseline_water_level": [],
                "controlled_water_level": [], "difference": [], "metrics": {}, "diagnostics": {}}
    rows = list(
        session.scalars(
            select(SimulationResult)
            .where(SimulationResult.task_id.in_((run.baseline_task_id, run.controlled_task_id)))
            .order_by(SimulationResult.task_id, SimulationResult.section_code, SimulationResult.time_seconds)
        ).all()
    )
    grouped: dict[tuple[int, str], list[SimulationResult]] = defaultdict(list)
    for row in rows:
        grouped[(row.task_id, row.section_code)].append(row)
    baseline_codes = {code for task_id, code in grouped if task_id == run.baseline_task_id}
    controlled_codes = {code for task_id, code in grouped if task_id == run.controlled_task_id}
    section_code = sorted(baseline_codes & controlled_codes)[0] if baseline_codes & controlled_codes else None
    baseline_rows = grouped.get((run.baseline_task_id, section_code or ""), [])
    controlled_rows = grouped.get((run.controlled_task_id, section_code or ""), [])
    time = [row.time_seconds for row in controlled_rows]
    baseline_levels = [row.water_level for row in baseline_rows]
    controlled_levels = [row.water_level for row in controlled_rows]
    structures = [
        {
            "structure_type": row.structure_type, "structure_id": row.structure_id,
            "time_seconds": row.time_seconds, "actual_value": row.actual_value,
            "flow": row.flow, "power_kw": row.power_kw, "energy_kwh": row.energy_kwh,
            "constraint_flags": row.constraint_flags,
        }
        for row in session.scalars(
            select(StructureResult)
            .where(StructureResult.task_id == run.controlled_task_id)
            .order_by(StructureResult.time_seconds)
        ).all()
    ]
    controlled_task = session.get(SimulationTask, run.controlled_task_id)
    controlled_series = [
        {"section_code": section_code, "time": time, "water_level": controlled_levels}
    ] if section_code else []
    baseline_series = [
        {"section_code": section_code, "time": [row.time_seconds for row in baseline_rows],
         "water_level": baseline_levels}
    ] if section_code else []
    metrics = evaluate_metrics(
        section_series=controlled_series,
        structure_series=structures,
        diagnostics=controlled_task.diagnostics or {} if controlled_task else {},
        evaluation_config=evaluation_config,
        baseline_section_series=baseline_series,
    )
    common = min(len(baseline_levels), len(controlled_levels))
    return {
        "section_code": section_code,
        "time": time[:common],
        "baseline_water_level": baseline_levels[:common],
        "controlled_water_level": controlled_levels[:common],
        "difference": [controlled_levels[index] - baseline_levels[index] for index in range(common)],
        "metrics": metrics,
        "diagnostics": controlled_task.diagnostics or {} if controlled_task else {},
    }
