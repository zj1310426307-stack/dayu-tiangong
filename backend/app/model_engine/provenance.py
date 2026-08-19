"""在任务创建时冻结可复现输入并计算规范化 SHA-256。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.dataset.service import build_model_input, build_model_input_v2
from app.hydraulic.model_input import build_model_input_v3
from model.adapters import adapt_v3_to_v2
from model.provenance import snapshot_hash


ENGINE_VERSION = "dayu-hydraulic-4.0.0"


def freeze_task_input(
    session: Session,
    case_id: int,
    config: dict[str, Any],
    *,
    schema_version: str,
    engine_commit: str,
    dispatch_plan: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    """构建完整任务输入；返回冻结 JSON 和与其一一对应的哈希。

    调度计划必须在生成水力快照时一并传入，使 v3 能在冻结前完成
    public 标识到 hydraulic 标识的严格重写。
    """

    if schema_version == "dayu.model-input.v3":
        snapshot = build_model_input_v3(
            session,
            case_id,
            controls={
                "allow_fallback_boundary": bool(config.get("allow_fallback_boundary", False)),
                "section_geometry": "tabulated",
                "runtime_overrides": config,
            },
            dispatch_plan=dispatch_plan,
            engine_version=ENGINE_VERSION,
        )
    elif schema_version == "dayu.model-input.v2":
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
            dispatch_plan=dispatch_plan,
            engine_version=ENGINE_VERSION,
        )
    else:
        if dispatch_plan is not None:
            raise ValueError("dispatch plans require dayu.model-input.v2 or v3")
        legacy = build_model_input(session, case_id)
        snapshot = legacy.model_dump(mode="json") if legacy is not None else None
        if snapshot is not None:
            snapshot["task_overrides"] = config
    if snapshot is None:
        raise LookupError("simulation case does not exist")
    if schema_version == "dayu.model-input.v3":
        # Freeze only inputs that the current solver boundary can consume.  The
        # returned projection is discarded; v3 remains the immutable authority.
        adapt_v3_to_v2(snapshot)
    existing_provenance = snapshot.get("provenance")
    if existing_provenance is None:
        existing_provenance = {}
    elif not isinstance(existing_provenance, dict):
        raise ValueError("model input provenance must be an object")
    snapshot["provenance"] = {
        **existing_provenance,
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
        "river_count": len(snapshot.get("branches", snapshot.get("rivers", []))),
        "section_count": len(snapshot.get("cross_sections", [])),
        "reach_count": len(snapshot.get("reaches", [])),
        "profile_count": len(snapshot.get("cross_section_profiles", [])),
        "boundary_count": len(snapshot.get("boundary_conditions", [])),
        "gate_count": len(snapshot.get("gates", [])),
        "pump_count": len(snapshot.get("pumps", [])),
        "coordinate_system": snapshot.get(
            "coordinate_reference", snapshot.get("coordinate_system", "CGCS2000 (EPSG:4490)")
        ),
    }
