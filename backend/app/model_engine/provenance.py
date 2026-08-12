"""在任务创建时冻结可复现输入并计算规范化 SHA-256。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.dataset.service import build_model_input, build_model_input_v2
from model.provenance import snapshot_hash


ENGINE_VERSION = "dayu-hydraulic-4.0.0"


def freeze_task_input(
    session: Session,
    case_id: int,
    config: dict[str, Any],
    *,
    schema_version: str,
    engine_commit: str,
) -> tuple[dict[str, Any], str]:
    """构建完整任务输入；返回冻结 JSON 和与其一一对应的哈希。"""

    if schema_version == "dayu.model-input.v2":
        snapshot = build_model_input_v2(
            session,
            case_id,
            controls={
                "allow_fallback_boundary": bool(
                    config.get("allow_fallback_boundary", False)
                ),
                "section_geometry": str(config.get("section_geometry", "rectangular")),
                "runtime_overrides": config,
            },
            engine_version=ENGINE_VERSION,
        )
    else:
        legacy = build_model_input(session, case_id)
        snapshot = legacy.model_dump(mode="json") if legacy is not None else None
        if snapshot is not None:
            snapshot["task_overrides"] = config
    if snapshot is None:
        raise LookupError("simulation case does not exist")
    snapshot["provenance"] = {
        "engine_version": ENGINE_VERSION,
        "engine_commit": engine_commit,
        "input_schema_version": schema_version,
    }
    return snapshot, snapshot_hash(snapshot)


def snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    """返回可安全展示的数量和来源摘要，不把大型 JSON 塞入任务列表。"""

    return {
        "schema_version": snapshot.get("schema_version"),
        "dataset_version_id": (snapshot.get("dataset_version") or {}).get("id"),
        "simulation_case_id": (snapshot.get("simulation_case") or {}).get("id"),
        "river_count": len(snapshot.get("rivers", [])),
        "section_count": len(snapshot.get("cross_sections", [])),
        "boundary_count": len(snapshot.get("boundary_conditions", [])),
        "gate_count": len(snapshot.get("gates", [])),
        "pump_count": len(snapshot.get("pumps", [])),
        "coordinate_system": snapshot.get("coordinate_system", "CGCS2000 (EPSG:4490)"),
    }
