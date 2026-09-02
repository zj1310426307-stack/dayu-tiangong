"""Resolve legacy dispatch assets into the unified HydraulicStructure domain."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.gis.models import DispatchAction, DispatchPlan, DispatchRule, Gate, Pump
from app.hydraulic.models import HydraulicStructure
from model.hydraulic_1d.capabilities import capabilities_for
from model.hydraulic_1d.registry import (
    DEFAULT_HYDRAULIC_1D_ENGINE_ID,
    DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
)


AssetKey = tuple[str, int]


def dispatch_asset_keys(
    actions: Iterable[DispatchAction], rules: Iterable[DispatchRule]
) -> tuple[AssetKey, ...]:
    """Return every manually or dynamically controlled asset in stable order."""

    keys: set[AssetKey] = set()
    for action in actions:
        asset_id = action.gate_id if action.structure_type == "gate" else action.pump_id
        if asset_id is not None:
            keys.add((action.structure_type, int(asset_id)))
    for rule in rules:
        template = rule.action_template
        if not isinstance(template, dict):
            continue
        structure_type = template.get("structure_type")
        structure_id = template.get("structure_id")
        if structure_type in {"gate", "pump"} and isinstance(structure_id, int):
            keys.add((structure_type, structure_id))
    return tuple(sorted(keys))


def _capability_fact(structure_type: str) -> dict[str, object]:
    """Read the current source-controlled capability fact for one asset type."""

    capability = next(
        (
            item
            for item in capabilities_for(
                DEFAULT_HYDRAULIC_1D_ENGINE_ID,
                DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
            )
            if item.feature == structure_type.upper()
        ),
        None,
    )
    if capability is None:
        return {
            "feature": structure_type.upper(),
            "status": "UNSUPPORTED",
            "reason": "feature is absent from the capability registry",
            "benchmark_ids": [],
        }
    return capability.to_dict()


def _gate_constraints(asset: Gate) -> dict[str, object]:
    """Freeze Gate actuator limits without importing a hydraulic equation."""

    return {
        "availability": asset.status,
        "height_m": float(asset.height),
        "minimum_opening_m": float(asset.minimum_opening or 0.0),
        "maximum_opening_m": float(
            asset.maximum_opening if asset.maximum_opening is not None else asset.height
        ),
        "opening_rate_limit_m_per_s": float(asset.opening_rate_limit or 0.0),
        "minimum_hold_seconds": float(asset.minimum_hold_seconds or 0.0),
        "initial_opening_m": 0.0,
    }


def _pump_constraints(asset: Pump) -> dict[str, object]:
    """Freeze Pump switching and static target limits without calculating flow."""

    unit_count = int(asset.unit_count if asset.unit_count is not None else 1)
    return {
        "availability": asset.status,
        # The authoritative Pump field is exposed elsewhere as station
        # capacity; it is not documented as a per-unit value.  Keep the
        # conservative total-capacity meaning instead of multiplying it by
        # unit count.
        "design_flow_capacity_m3s": float(asset.design_flow),
        "unit_count": unit_count,
        "minimum_running_units": int(
            asset.minimum_running_units
            if asset.minimum_running_units is not None
            else 1
        ),
        "maximum_running_units": int(
            asset.maximum_running_units
            if asset.maximum_running_units is not None
            else unit_count
        ),
        "minimum_run_seconds": float(asset.minimum_run_seconds or 0.0),
        "minimum_stop_seconds": float(asset.minimum_stop_seconds or 0.0),
        "maximum_starts_per_replay": int(
            asset.maximum_starts_per_run
            if asset.maximum_starts_per_run is not None
            else 2_147_483_647
        ),
        "initial_running_units": 0,
        "initial_stop_constraint_satisfied": True,
    }


def resolve_plan_asset_snapshots(
    session: Session,
    plan: DispatchPlan,
    actions: Iterable[DispatchAction],
    rules: Iterable[DispatchRule],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve frozen asset constraints and return all mapping errors together."""

    snapshots: list[dict[str, Any]] = []
    errors: list[str] = []
    for structure_type, legacy_id in dispatch_asset_keys(actions, rules):
        model = Gate if structure_type == "gate" else Pump
        asset = session.get(model, legacy_id)
        if asset is None or asset.dataset_version_id != plan.dataset_version_id:
            errors.append(
                f"[DISPATCH_ASSET_MISSING] {structure_type}:{legacy_id} 不存在或跨数据版本"
            )
            continue
        mapping_column = (
            HydraulicStructure.legacy_gate_id
            if structure_type == "gate"
            else HydraulicStructure.legacy_pump_id
        )
        mappings = list(
            session.scalars(
                select(HydraulicStructure).where(
                    HydraulicStructure.dataset_version_id == plan.dataset_version_id,
                    mapping_column == legacy_id,
                )
            ).all()
        )
        if len(mappings) != 1:
            errors.append(
                f"[HYDRAULIC_STRUCTURE_MAPPING] {structure_type}:{legacy_id} "
                "必须唯一映射到统一 HydraulicStructure"
            )
            continue
        unified = mappings[0]
        if unified.structure_type != structure_type or unified.status != "active":
            errors.append(
                f"[HYDRAULIC_STRUCTURE_STATE] {structure_type}:{legacy_id} 的统一结构类型或状态无效"
            )
            continue
        snapshots.append(
            {
                "structure_type": structure_type,
                "legacy_asset_id": legacy_id,
                "hydraulic_structure": {
                    "id": unified.id,
                    "network_id": unified.network_id,
                    "branch_id": unified.branch_id,
                    "chainage_m": unified.chainage_m,
                    "structure_code": unified.structure_code,
                    "status": unified.status,
                },
                "constraints": (
                    _gate_constraints(asset)
                    if structure_type == "gate"
                    else _pump_constraints(asset)
                ),
                "capability": _capability_fact(structure_type),
            }
        )
    return snapshots, errors


def lock_plan_asset_rows(session: Session, plan: DispatchPlan) -> None:
    """Lock every referenced legacy/unified asset before validation and freeze."""

    actions = session.scalars(
        select(DispatchAction).where(DispatchAction.plan_id == plan.id)
    ).all()
    rules = session.scalars(
        select(DispatchRule).where(DispatchRule.plan_id == plan.id)
    ).all()
    keys = dispatch_asset_keys(actions, rules)
    gate_ids = [asset_id for kind, asset_id in keys if kind == "gate"]
    pump_ids = [asset_id for kind, asset_id in keys if kind == "pump"]
    if gate_ids:
        session.scalars(
            select(Gate)
            .where(Gate.id.in_(gate_ids))
            .order_by(Gate.id)
            .with_for_update()
        ).all()
    if pump_ids:
        session.scalars(
            select(Pump)
            .where(Pump.id.in_(pump_ids))
            .order_by(Pump.id)
            .with_for_update()
        ).all()
    mapping_filters = []
    if gate_ids:
        mapping_filters.append(HydraulicStructure.legacy_gate_id.in_(gate_ids))
    if pump_ids:
        mapping_filters.append(HydraulicStructure.legacy_pump_id.in_(pump_ids))
    if mapping_filters:
        session.scalars(
            select(HydraulicStructure)
            .where(
                HydraulicStructure.dataset_version_id == plan.dataset_version_id,
                or_(*mapping_filters),
            )
            .order_by(HydraulicStructure.id)
            .with_for_update()
        ).all()
