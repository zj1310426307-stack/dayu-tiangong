"""Exercise the public controlled-engine boundary with a native Pump schedule."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import monotonic

from model.control.compiler import (
    ActuatorControlBinding,
    HydraulicControlCompiler,
    InitialActuatorState,
)
from model.control.drtc import DRTCCompiler
from model.control.observation_bridge import ObservationBinding
from model.control.replay import ReplayAsset
from model.control.rules import ThresholdRule
from model.control.schedule import ScheduledAction
from model.hydraulic_1d.controlled import (
    ControlObservationContract,
    ControlRuntimeSelection,
    ControlledExecutionSettings,
    ControlledHydraulic1DRun,
    DispatchPlanSnapshot,
    EngineSelection,
)
from model.hydraulic_1d.dflow_fm.config import DFlowRuntimeConfig
from model.hydraulic_1d.dflow_fm.engine import (
    CONTROL_COMPILER_BUNDLE_VERSION,
    DFlowFMEngine,
)
from model.hydraulic_1d.engine import Hydraulic1DExecutionContext
from model.hydraulic_1d.errors import Hydraulic1DCancelled, Hydraulic1DExecutionError
from model.provenance import canonical_json, snapshot_hash
from tools.run_dflow_gate_acceptance import IMAGE
from tools.run_dflow_pump_acceptance import _gate, _model, _pump


def build_run(
    *,
    joint: bool = False,
    gate_rule: bool = False,
    database_branch_id: str | None = None,
    database_section_ids: tuple[str, ...] | None = None,
) -> ControlledHydraulic1DRun:
    """Build the public Pump-only or joint Gate/Pump manual-control contract."""

    if gate_rule and not joint:
        raise ValueError("a Gate rule requires the joint Gate/Pump model")
    case_id = "GP03" if gate_rule else ("GP02" if joint else "PUMP02")
    model = _model(case_id, duration=600.0, pump_only=not joint)
    pump = _pump(chainage_m=700.0 if joint else 500.0)
    gate = _gate() if joint else None
    if (database_branch_id is None) != (database_section_ids is None):
        raise ValueError("database branch and Section ids must be supplied together")
    if database_branch_id is not None and database_section_ids is not None:
        model_payload = model.model_dump(mode="json")
        if len(database_section_ids) != len(model_payload["cross_sections"]):
            raise ValueError("database Section id count must match the hydraulic model")
        old_branch_id = str(model_payload["branches"][0]["id"])
        model_payload["branches"][0]["id"] = database_branch_id
        section_id_map: dict[str, str] = {}
        for section, section_id in zip(
            model_payload["cross_sections"],
            database_section_ids,
            strict=True,
        ):
            section_id_map[str(section["id"])] = section_id
            section["id"] = section_id
            section["branch_id"] = database_branch_id
        for collection in ("structures", "boundaries"):
            for item in model_payload[collection]:
                item["branch_id"] = database_branch_id
        geometries = model_payload["metadata"]["dflow_fm"]["branch_geometries"]
        geometries[database_branch_id] = geometries.pop(old_branch_id)
        model = type(model).model_validate(model_payload)
        pump = pump.model_copy(
            update={
                "branch_id": database_branch_id,
                "intake_id": section_id_map[pump.intake_id],
                "outlet_id": section_id_map[pump.outlet_id],
            }
        )
        if gate is not None:
            gate = gate.model_copy(update={"branch_id": database_branch_id})
    pump_initial = InitialActuatorState(
        structure_type="pump",
        structure_id=1,
        pump_enabled=False,
        running_units=0,
        stop_seconds=180.0,
        evidence="SYNTHETIC_INITIAL_STATE",
    )
    pump_binding = ActuatorControlBinding(
        structure_type="pump",
        structure_id=1,
        native_structure_id="pump-1",
        supported_command_type="pump_target_flow",
        bmi_variable="pumps/pump-1/capacity",
        conversion="identity_capacity",
    )
    pump_actions = (
        ScheduledAction(1, 180.0, "pump", 1, "pump_target_flow", 1.0),
        ScheduledAction(2, 420.0, "pump", 1, "pump_target_flow", 0.4),
    )
    gate_initial = (
        InitialActuatorState(
            structure_type="gate",
            structure_id=2,
            gate_opening_m=2.0,
            evidence="SYNTHETIC_INITIAL_STATE",
        )
        if joint
        else None
    )
    gate_binding = (
        ActuatorControlBinding(
            structure_type="gate",
            structure_id=2,
            native_structure_id="gate-1",
            supported_command_type="gate_opening_m",
            bmi_variable="orifices/gate-1/gateLowerEdgeLevel",
            conversion="gate_lower_edge_level",
            reference_level_m=0.0,
        )
        if joint
        else None
    )
    gate_actions = (
        (
            ScheduledAction(3, 180.0, "gate", 2, "gate_opening_m", 0.5),
            ScheduledAction(4, 420.0, "gate", 2, "gate_opening_m", 1.0),
        )
        if joint and not gate_rule
        else ()
    )
    actions = (*pump_actions, *gate_actions)
    initial_states = (
        (pump_initial, gate_initial) if gate_initial is not None else (pump_initial,)
    )
    bindings = (
        (pump_binding, gate_binding) if gate_binding is not None else (pump_binding,)
    )
    replay_assets = [
        ReplayAsset(
            "pump",
            1,
            {
                "availability": "online",
                "unit_count": 1,
                "minimum_running_units": 0,
                "maximum_running_units": 1,
                "design_flow_capacity_m3s": 1.0,
                "minimum_run_seconds": 0.0,
                "minimum_stop_seconds": 0.0,
                "maximum_starts_per_replay": 10,
            },
        )
    ]
    if joint:
        replay_assets.append(
            ReplayAsset(
                "gate",
                2,
                {
                    "availability": "online",
                    "height_m": 3.0,
                    "minimum_opening_m": 0.0,
                    "maximum_opening_m": 3.0,
                    "opening_rate_limit_m_per_s": 10.0,
                    "minimum_hold_seconds": 0.0,
                },
            )
        )
    manual = HydraulicControlCompiler().compile(
        actions=actions,
        assets=tuple(replay_assets),
        initial_states=initial_states,
        bindings=bindings,
        duration_seconds=600.0,
    )
    if manual.status != "COMPILED":
        raise RuntimeError(manual.model_dump_json())
    rule = (
        ThresholdRule(
            id=3,
            name="synthetic-joint-high-water-gate",
            enabled=True,
            observation_type="section_water_level",
            observation_object_id=3,
            operator=">=",
            threshold=2.01,
            hysteresis=0.0,
            minimum_hold_seconds=0.0,
            cooldown_seconds=0.0,
            action_template={
                "structure_type": "gate",
                "structure_id": 2,
                "command_type": "gate_opening_m",
                "target_value": 0.5,
            },
            priority=0,
        )
        if gate_rule
        else None
    )
    observation = (
        ObservationBinding(
            observation_type="section_water_level",
            observation_object_id=3,
            source_kind="cross_section",
            source_id=(database_section_ids[0] if database_section_ids else "section-up"),
            binding_evidence="SYNTHETIC_ASSUMPTION",
        )
        if gate_rule
        else None
    )
    drtc = DRTCCompiler().compile(
        (rule,) if rule is not None else (),
        manual_actuators=(("pump", 1),) if gate_rule else (),
    )
    observations = ControlObservationContract(
        sampling_interval_seconds=60.0,
        bindings=(observation,) if observation is not None else (),
    )
    body = {
        "schema_version": "dayu.dispatch-plan.v3",
        "plan": {"id": 7, "version": 3},
        "actions": [
            {
                "id": item.id,
                "time_seconds": item.time_seconds,
                "structure_type": item.structure_type,
                "structure_id": item.structure_id,
                "command_type": item.command_type,
                "target_value": item.target_value,
            }
            for item in actions
        ],
        "rules": (
            [
                {
                    "id": rule.id,
                    "name": rule.name,
                    "enabled": rule.enabled,
                    "observation_type": rule.observation_type,
                    "observation_object_id": rule.observation_object_id,
                    "operator": rule.operator,
                    "threshold": rule.threshold,
                    "hysteresis": rule.hysteresis,
                    "minimum_hold_seconds": rule.minimum_hold_seconds,
                    "cooldown_seconds": rule.cooldown_seconds,
                    "action_template": rule.action_template,
                    "priority": rule.priority,
                }
            ]
            if rule is not None
            else []
        ),
        "gate_hydraulic_specs": [gate.model_dump(mode="json")] if gate else [],
        "pump_hydraulic_specs": [pump.model_dump(mode="json")],
        "control_bindings": [item.model_dump(mode="json") for item in bindings],
        "manual_control_report": manual.model_dump(mode="json"),
        "drtc_compile_report": drtc.model_dump(mode="json"),
        "initial_actuator_state": [item.model_dump(mode="json") for item in initial_states],
        "control_observation_contract": observations.model_dump(mode="json"),
        "evidence_class": "SYNTHETIC_NUMERICAL_ONLY",
        "real_engineering_validation": False,
        "real_equipment_command": False,
        "plc_scada_connected": False,
    }
    model_hash = snapshot_hash(model.model_dump(mode="json"))
    selection = EngineSelection.from_current_registry(runtime_mode="container")
    control = ControlRuntimeSelection(
        runtime_version="1.6.1",
        coupling_runtime_version="2.00",
        compiler_id="dayu-drtc-fbc-artifact-writer",
        compiler_version=CONTROL_COMPILER_BUNDLE_VERSION,
    )
    plan = DispatchPlanSnapshot(
        plan_payload_json=canonical_json(body),
        hydraulic_model_snapshot_hash=model_hash,
        engine_registry_hash=selection.engine_registry_hash,
        control_compiler_version=control.compiler_version,
        initial_actuator_state=initial_states,
        control_observation_contract=observations,
    )
    return ControlledHydraulic1DRun(
        hydraulic_model=model,
        hydraulic_model_snapshot_hash=model_hash,
        dispatch_plan_snapshot=plan,
        engine_selection=selection,
        control_runtime_selection=control,
        execution_settings=ControlledExecutionSettings(timeout_seconds=300.0),
    )


def run(
    workspace_root: Path,
    job_id: str,
    docker_executable: str,
    *,
    joint: bool = False,
    gate_rule: bool = False,
    timeout_seconds: float = 300.0,
    cancel_after_seconds: float | None = None,
) -> dict[str, object]:
    repository = Path(__file__).resolve().parents[1]
    engine = DFlowFMEngine(
        DFlowRuntimeConfig(
            runtime="container",
            dimr_executable="dimr",
            dimr_executable_sha256=None,
            docker_executable=docker_executable,
            container_image=IMAGE,
            provenance_file=repository
            / "model/hydraulic_1d/dflow_fm/acceptance/DIMRset_2026.02/runtime-provenance.json",
            timeout_seconds=timeout_seconds,
            workspace_root=workspace_root.resolve(),
        )
    )
    started = monotonic()
    context = Hydraulic1DExecutionContext(
        job_id=job_id,
        workspace_root=workspace_root,
        cancel_check=(
            (lambda: monotonic() - started >= cancel_after_seconds)
            if cancel_after_seconds is not None
            else None
        ),
    )
    try:
        result = engine.run_controlled(
            build_run(joint=joint, gate_rule=gate_rule), context
        )
    except Hydraulic1DCancelled as exc:
        if cancel_after_seconds is None:
            raise
        return {
            "status": "PASS",
            "case_id": "GP-CANCEL",
            "error_code": exc.code,
            "owned_runtime_cleanup": "CONFIRMED",
        }
    except Hydraulic1DExecutionError as exc:
        if timeout_seconds >= 1.0 or exc.code != "DFLOW_TIMEOUT":
            raise
        return {
            "status": "PASS",
            "case_id": "GP-TIMEOUT",
            "error_code": exc.code,
            "owned_runtime_cleanup": "CONFIRMED",
        }
    pump_rows = [item for item in result.structure_results if item.structure_type == "pump"]
    transitions = [
        item for item in result.dispatch_trace if item.structure_type == "pump"
    ]
    capacities = {round(float(item.applied_value), 6) for item in transitions}
    if not {0.0, 0.4, 1.0}.issubset(capacities):
        raise RuntimeError("public engine did not return all native Pump capacity transitions")
    if any(
        item.native_applied_capacity_m3s is None
        or item.actual_discharge_m3s is None
        or item.active_unit_count is not None
        or item.active_stage is not None
        for item in pump_rows
    ):
        raise RuntimeError("public Pump result semantics are incomplete or inferred")
    gate_rows = [item for item in result.structure_results if item.structure_type == "gate"]
    if joint and not gate_rows:
        raise RuntimeError("public joint result omitted Gate history")
    gate_transitions = [
        item for item in result.dispatch_trace if item.structure_type == "gate"
    ]
    if gate_rule and not any(
        item.source_type == "threshold_rule"
        and abs(float(item.applied_value) - 0.5) <= 1e-8
        for item in gate_transitions
    ):
        raise RuntimeError("GP03 did not observe the native Gate rule transition")
    return {
        "status": "PASS",
        "case_id": (
            "GP03-PUBLIC-ENGINE"
            if gate_rule
            else ("GP02-PUBLIC-ENGINE" if joint else "PUMP02-PUBLIC-ENGINE")
        ),
        "result_hash": result.result_hash,
        "hydraulic_records": len(result.hydraulic_result.records),
        "pump_structure_records": len(pump_rows),
        "gate_structure_records": len(gate_rows),
        "pump_transitions": [item.model_dump(mode="json") for item in transitions],
        "gate_transitions": [item.model_dump(mode="json") for item in gate_transitions],
        "mass_balance": result.hydraulic_result.diagnostics["mass_balance"],
        "evidence_class": result.evidence_class,
        "real_engineering_validation": result.real_engineering_validation,
        "real_equipment_command": result.real_equipment_command,
        "plc_scada_connected": result.plc_scada_connected,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--docker-executable", default="docker")
    parser.add_argument("--joint", action="store_true")
    parser.add_argument("--gate-rule", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--cancel-after-seconds", type=float)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = run(
        args.workspace_root,
        args.job_id,
        args.docker_executable,
        joint=args.joint,
        gate_rule=args.gate_rule,
        timeout_seconds=args.timeout_seconds,
        cancel_after_seconds=args.cancel_after_seconds,
    )
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
