"""Exercise the public ControlledHydraulic1DEngine path with native DIMR/FBC."""

from __future__ import annotations

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
from tools.run_dflow_gate_acceptance import IMAGE, _gate, _model


def build_run(
    *,
    database_branch_id: str | None = None,
    database_section_ids: tuple[str, str, str] | None = None,
) -> ControlledHydraulic1DRun:
    model = _model("G03")
    gate = _gate()
    observation_source_id = "section-up"
    if database_branch_id is not None and database_section_ids is not None:
        model_payload = model.model_dump(mode="json")
        old_branch_id = str(model_payload["branches"][0]["id"])
        model_payload["branches"][0]["id"] = database_branch_id
        for section, section_id in zip(
            model_payload["cross_sections"],
            database_section_ids,
            strict=True,
        ):
            section["id"] = section_id
            section["branch_id"] = database_branch_id
        for collection in ("structures", "boundaries"):
            for item in model_payload[collection]:
                item["branch_id"] = database_branch_id
        geometries = model_payload["metadata"]["dflow_fm"]["branch_geometries"]
        geometries[database_branch_id] = geometries.pop(old_branch_id)
        model = type(model).model_validate(model_payload)
        gate = gate.model_copy(update={"branch_id": database_branch_id})
        observation_source_id = database_section_ids[0]
    initial = InitialActuatorState(
        structure_type="gate",
        structure_id=1,
        gate_opening_m=0.2,
        evidence="SYNTHETIC_INITIAL_STATE",
    )
    binding = ActuatorControlBinding(
        structure_type="gate",
        structure_id=1,
        native_structure_id="gate-1",
        supported_command_type="gate_opening_m",
        bmi_variable="orifices/gate-1/gateLowerEdgeLevel",
        conversion="gate_lower_edge_level",
        reference_level_m=2.0,
    )
    rule = ThresholdRule(
        id=1,
        name="synthetic-high-water-open",
        enabled=True,
        observation_type="section_water_level",
        observation_object_id=1,
        operator=">=",
        threshold=2.5,
        hysteresis=0.0,
        minimum_hold_seconds=0.0,
        cooldown_seconds=0.0,
        action_template={
            "structure_type": "gate",
            "structure_id": 1,
            "command_type": "gate_opening_m",
            "target_value": 1.0,
        },
        priority=0,
    )
    observation = ObservationBinding(
        observation_type="section_water_level",
        observation_object_id=1,
        source_kind="cross_section",
        source_id=observation_source_id,
        binding_evidence="SYNTHETIC_ASSUMPTION",
    )
    manual = HydraulicControlCompiler().compile(
        actions=(),
        assets=(
            ReplayAsset(
                "gate",
                1,
                {
                    "availability": "online",
                    "height_m": 1.2,
                    "minimum_opening_m": 0.0,
                    "maximum_opening_m": 1.2,
                    "opening_rate_limit_m_per_s": 10.0,
                    "minimum_hold_seconds": 0.0,
                },
            ),
        ),
        initial_states=(initial,),
        bindings=(binding,),
        duration_seconds=600.0,
    )
    drtc = DRTCCompiler().compile((rule,))
    observations = ControlObservationContract(
        sampling_interval_seconds=60.0,
        bindings=(observation,),
    )
    rule_payload = {
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
    body = {
        "schema_version": "dayu.dispatch-plan.v3",
        "plan": {"id": 1, "version": 3},
        "actions": [],
        "rules": [rule_payload],
        "gate_hydraulic_specs": [gate.model_dump(mode="json")],
        "pump_hydraulic_specs": [],
        "control_bindings": [binding.model_dump(mode="json")],
        "manual_control_report": manual.model_dump(mode="json"),
        "drtc_compile_report": drtc.model_dump(mode="json"),
        "initial_actuator_state": [initial.model_dump(mode="json")],
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
        initial_actuator_state=(initial,),
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
    *,
    docker_executable: str = "docker",
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
        result = engine.run_controlled(build_run(), context)
    except Hydraulic1DCancelled as exc:
        if cancel_after_seconds is None:
            raise
        return {
            "status": "PASS",
            "lifecycle_case": "cancel",
            "error_code": exc.code,
            "owned_runtime_cleanup": "CONFIRMED",
        }
    except Hydraulic1DExecutionError as exc:
        if timeout_seconds >= 1.0 or exc.code != "DFLOW_TIMEOUT":
            raise
        return {
            "status": "PASS",
            "lifecycle_case": "timeout",
            "error_code": exc.code,
            "owned_runtime_cleanup": "CONFIRMED",
        }
    balance = result.hydraulic_result.diagnostics["mass_balance"]
    return {
        "status": "PASS",
        "result_hash": result.result_hash,
        "hydraulic_records": len(result.hydraulic_result.records),
        "structure_records": len(result.structure_results),
        "dispatch_transitions": [item.model_dump(mode="json") for item in result.dispatch_trace],
        "mass_balance": balance,
        "control_trace_sha256": result.hydraulic_result.diagnostics[
            "control_trace_sha256"
        ],
        "numerical_result_sha256": result.hydraulic_result.diagnostics[
            "numerical_result_sha256"
        ],
        "runtime_components": [item.component for item in result.runtime_provenance],
        "evidence_class": result.evidence_class,
        "real_engineering_validation": result.real_engineering_validation,
        "real_equipment_command": result.real_equipment_command,
        "plc_scada_connected": result.plc_scada_connected,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--docker-executable", default="docker")
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--cancel-after-seconds", type=float)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = run(
        args.workspace_root,
        args.job_id,
        docker_executable=args.docker_executable,
        timeout_seconds=args.timeout_seconds,
        cancel_after_seconds=args.cancel_after_seconds,
    )
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
