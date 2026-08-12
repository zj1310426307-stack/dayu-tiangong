"""冻结调度计划、动作和规则并计算不可变 SHA-256。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dispatch.repository import dump
from app.gis.models import DispatchAction, DispatchPlan, DispatchRule
from model.provenance import canonical_json, snapshot_hash
import json


def build_plan_snapshot(session: Session, plan: DispatchPlan) -> tuple[dict, str]:
    """按稳定顺序序列化计划、动作和规则，返回快照及哈希。"""

    actions = list(
        session.scalars(
            select(DispatchAction).where(DispatchAction.plan_id == plan.id)
            .order_by(DispatchAction.time_seconds, DispatchAction.sequence, DispatchAction.id)
        ).all()
    )
    rules = list(
        session.scalars(
            select(DispatchRule).where(DispatchRule.plan_id == plan.id)
            .order_by(DispatchRule.priority.desc(), DispatchRule.id)
        ).all()
    )
    snapshot = {
        "schema_version": "dayu.dispatch-plan.v1",
        "plan": {
            key: value
            for key, value in dump(plan).items()
            if key not in {"frozen_snapshot", "frozen_snapshot_hash"}
        },
        "actions": [dump(item) for item in actions],
        "rules": [dump(item) for item in rules],
        "command_units": {
            "gate_opening_m": "m", "gate_opening_ratio": "ratio",
            "pump_enabled": "boolean_0_or_1", "pump_unit_count": "count",
            "pump_target_flow": "m3/s",
        },
        "safety_notice": "simulation only; no command is sent to real equipment",
    }
    # Persist the exact canonical JSON form that was hashed.  This guarantees
    # PostgreSQL JSON receives only portable primitives (not datetimes) and
    # that the stored payload and digest remain a one-to-one pair.
    frozen = json.loads(canonical_json(snapshot))
    return frozen, snapshot_hash(frozen)
