"""Build immutable DispatchPlan v3 snapshots without changing legacy v2."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dispatch.assets import resolve_plan_asset_snapshots
from app.dispatch.hydraulic_assets import HydraulicControlAsset
from app.dispatch.hydraulic_schemas import HydraulicPlanCompileRequest
from app.dispatch.repository import dump
from app.gis.models import DispatchAction, DispatchPlan, DispatchRule
from model.control.compiler import (
    HYDRAULIC_CONTROL_COMPILER_VERSION,
    ActuatorControlBinding,
    HydraulicControlCompileReport,
)
from model.control.drtc import DRTC_COMPILER_VERSION, DRTCCompileReport
from model.hydraulic_1d.controlled import (
    ControlObservationContract,
    DispatchPlanSnapshot,
)
from model.hydraulic_1d.contracts import Hydraulic1DModel
from model.hydraulic_1d.registry import (
    DFLOW_FM_ENGINE_ID,
    DFLOW_FM_ENGINE_VERSION,
    selected_engine_hash,
)
from model.hydraulic_1d.structures import GateHydraulicSpec, PumpHydraulicSpec
from model.provenance import canonical_json, snapshot_hash


CONTROL_COMPILER_BUNDLE_VERSION = f"{HYDRAULIC_CONTROL_COMPILER_VERSION}+{DRTC_COMPILER_VERSION}"


def _controlled_asset_snapshots(
    assets: list[dict[str, Any]],
    *,
    request: HydraulicPlanCompileRequest,
    capability_facts: tuple[dict[str, Any], ...],
    control_assets: tuple[HydraulicControlAsset, ...],
) -> list[dict[str, Any]]:
    """Replace legacy MASCARET/default-state facts with the v3 authorities."""

    initial_keys = {
        (item.structure_type, item.structure_id) for item in request.initial_actuator_state
    }
    capability_by_feature = {str(item.get("feature")): item for item in capability_facts}
    controls_by_key = {(item.structure_type, item.structure_id): item for item in control_assets}
    asset_keys = {(str(item["structure_type"]), int(item["legacy_asset_id"])) for item in assets}
    if asset_keys != set(controls_by_key):
        raise ValueError("controlled asset snapshots do not match normalized v3 constraints")
    snapshots: list[dict[str, Any]] = []
    for asset in assets:
        structure_type = str(asset["structure_type"])
        legacy_asset_id = int(asset["legacy_asset_id"])
        key = (structure_type, legacy_asset_id)
        if key not in initial_keys:
            raise ValueError(
                "controlled asset snapshot is missing its explicit initial state: "
                f"{structure_type}:{legacy_asset_id}"
            )
        feature = structure_type.upper()
        capability = capability_by_feature.get(feature)
        if capability is None:
            raise ValueError(
                f"controlled asset snapshot is missing D-Flow capability fact: {feature}"
            )
        normalized = controls_by_key[key]
        constraints = dict(normalized.constraints)
        # Static v2 intentionally has closed/stopped defaults. Hydraulic v3 has
        # a mandatory initial-state contract, so those values cannot survive as
        # a second immutable source of truth.
        for field in (
            "initial_opening_m",
            "initial_running_units",
            "initial_runtime_seconds",
            "initial_stop_seconds",
            "initial_stop_constraint_satisfied",
            "initial_state_explicit",
        ):
            constraints.pop(field, None)
        snapshots.append(
            {
                **asset,
                "constraints": constraints,
                "constraint_provenance": dict(normalized.provenance),
                "capability": capability,
                "initial_state_authority": "initial_actuator_state",
            }
        )
    return snapshots


def _ordered_plan_children(
    session: Session,
    plan: DispatchPlan,
) -> tuple[list[DispatchAction], list[DispatchRule]]:
    """Read plan children under the same deterministic ordering as v2."""

    actions = list(
        session.scalars(
            select(DispatchAction)
            .where(DispatchAction.plan_id == plan.id)
            .order_by(
                DispatchAction.time_seconds,
                DispatchAction.sequence,
                DispatchAction.id,
            )
        ).all()
    )
    rules = list(
        session.scalars(
            select(DispatchRule)
            .where(DispatchRule.plan_id == plan.id)
            .order_by(DispatchRule.priority.desc(), DispatchRule.id)
        ).all()
    )
    return actions, rules


def build_hydraulic_plan_snapshot(
    session: Session,
    plan: DispatchPlan,
    *,
    request: HydraulicPlanCompileRequest,
    hydraulic_model: Hydraulic1DModel,
    hydraulic_model_snapshot_hash: str,
    capability_facts: tuple[dict[str, Any], ...],
    gate_specs: tuple[GateHydraulicSpec, ...],
    pump_specs: tuple[PumpHydraulicSpec, ...],
    control_assets: tuple[HydraulicControlAsset, ...],
    control_bindings: tuple[ActuatorControlBinding, ...],
    manual_report: HydraulicControlCompileReport,
    drtc_report: DRTCCompileReport,
) -> tuple[dict[str, object], str, str]:
    """Return canonical v3 storage payload, snapshot hash, and compiler hash."""

    if plan.snapshot_target != "hydraulic_v3" or plan.cloned_from_plan_id is None:
        raise ValueError("DispatchPlan v3 requires an explicit hydraulic clone lineage")
    if manual_report.status != "COMPILED" or drtc_report.status != "COMPILED":
        raise ValueError("unsupported control semantics cannot be frozen as v3")
    actions, rules = _ordered_plan_children(session, plan)
    assets, asset_errors = resolve_plan_asset_snapshots(
        session,
        plan,
        actions,
        rules,
    )
    if asset_errors:
        raise ValueError("; ".join(asset_errors))
    observed_model_hash = snapshot_hash(hydraulic_model.model_dump(mode="json"))
    if observed_model_hash != hydraulic_model_snapshot_hash:
        raise ValueError("hydraulic model snapshot hash does not match its frozen payload")
    assets = _controlled_asset_snapshots(
        assets,
        request=request,
        capability_facts=capability_facts,
        control_assets=control_assets,
    )
    observation_contract = ControlObservationContract(
        sampling_interval_seconds=request.observation_sampling_interval_seconds,
        bindings=request.observation_bindings,
    )
    execution_settings = {
        "runtime_mode": request.runtime_mode,
        "timeout_seconds": request.timeout_seconds,
        "development_mode": True,
        "production_mode": False,
        "workspace_isolation": True,
        "cancel_enabled": True,
    }
    control_contract_hash = snapshot_hash(
        {
            "manual": manual_report.model_dump(mode="json"),
            "drtc": drtc_report.model_dump(mode="json"),
            "bindings": [item.model_dump(mode="json") for item in control_bindings],
            "initial_actuator_state": [
                item.model_dump(mode="json") for item in request.initial_actuator_state
            ],
            "observation_contract": observation_contract.model_dump(mode="json"),
            "execution_settings": execution_settings,
        }
    )
    body = {
        "schema_version": "dayu.dispatch-plan.v3",
        "plan": {
            key: value
            for key, value in dump(plan).items()
            if key not in {"frozen_snapshot", "frozen_snapshot_hash"}
        },
        "actions": [dump(item) for item in actions],
        "rules": [dump(item) for item in rules],
        "assets": assets,
        "hydraulic_model_snapshot": hydraulic_model.model_dump(mode="json"),
        "engine_capabilities": list(capability_facts),
        "gate_hydraulic_specs": [item.model_dump(mode="json") for item in gate_specs],
        "pump_hydraulic_specs": [item.model_dump(mode="json") for item in pump_specs],
        "control_bindings": [item.model_dump(mode="json") for item in control_bindings],
        "manual_control_report": manual_report.model_dump(mode="json"),
        "drtc_compile_report": drtc_report.model_dump(mode="json"),
        "control_contract_hash": control_contract_hash,
        "hydraulic_model_snapshot_hash": hydraulic_model_snapshot_hash,
        "engine_id": DFLOW_FM_ENGINE_ID,
        "engine_version": DFLOW_FM_ENGINE_VERSION,
        "engine_registry_hash": selected_engine_hash(DFLOW_FM_ENGINE_ID),
        "control_runtime": "d-rtc/fbc",
        "control_compiler_version": CONTROL_COMPILER_BUNDLE_VERSION,
        "hydraulic_feedback": True,
        "execution_settings": execution_settings,
        "initial_actuator_state": [
            item.model_dump(mode="json") for item in request.initial_actuator_state
        ],
        "control_observation_contract": observation_contract.model_dump(mode="json"),
        "runtime_provenance_requirements": [
            {
                "component": component,
                "required_fields": [
                    "version",
                    "upstream_tag",
                    "upstream_commit",
                    "binary_sha256",
                    "source_manifest",
                    "platform",
                    "architecture",
                    "build_timestamp",
                ],
            }
            for component in ("dflowfm", "dimr", "fbc", "hydrolib-core")
        ],
        "evidence_class": "SYNTHETIC_NUMERICAL_ONLY",
        "real_engineering_validation": False,
        "real_equipment_command": False,
        "plc_scada_connected": False,
        "safety_notice": (
            "SYNTHETIC NUMERICAL DEVELOPMENT / NOT REAL ENGINEERING VALIDATION / "
            "NO REAL EQUIPMENT CONTROL"
        ),
    }
    canonical_body = json.loads(canonical_json(body))
    snapshot = DispatchPlanSnapshot(
        plan_payload_json=canonical_json(canonical_body),
        hydraulic_model_snapshot_hash=hydraulic_model_snapshot_hash,
        engine_registry_hash=selected_engine_hash(DFLOW_FM_ENGINE_ID),
        control_compiler_version=CONTROL_COMPILER_BUNDLE_VERSION,
        initial_actuator_state=request.initial_actuator_state,
        control_observation_contract=observation_contract,
    )
    frozen = json.loads(canonical_json(snapshot.model_dump(mode="json")))
    digest = snapshot_hash({key: value for key, value in frozen.items() if key != "snapshot_hash"})
    if digest != snapshot.snapshot_hash:
        raise ValueError("DispatchPlan v3 envelope hash mismatch")
    return frozen, digest, control_contract_hash
