"""Run Phase 07 synthetic native Pump and joint Gate/Pump acceptance cases."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from typing import Any

from model.control.drtc import (
    DRTCFBCArtifactWriter,
    DRTCGateThresholdSpec,
    DRTCManualGateScheduleSpec,
    DRTCManualPumpScheduleSpec,
)
from model.hydraulic_1d import (
    BoundaryCondition,
    CrossSectionPoint,
    Hydraulic1DModel,
    HydraulicBranch,
    HydraulicCrossSection,
    HydraulicNode,
    HydraulicStructure,
    InitialCondition,
    SimulationSettings,
    TimeValue,
)
from model.hydraulic_1d.dflow_fm.adapter import DFlowFMModelBuilder
from model.hydraulic_1d.dflow_fm.config import DFlowRuntimeConfig
from model.hydraulic_1d.dflow_fm.parser import DFlowFMResultParser
from model.hydraulic_1d.dflow_fm.runtime import (
    DFlowRuntimeRequest,
    create_dflow_runtime,
)
from model.hydraulic_1d.dflow_fm.workspace import DFlowJobWorkspace
from model.hydraulic_1d.structures import (
    GateHydraulicSpec,
    HydraulicDataStatus,
    PumpControlMode,
    PumpHeadReductionCurve,
    PumpHeadReductionPoint,
    PumpHydraulicSpec,
    PumpOrientation,
    PumpTransferType,
    SourcedHydraulicBoolean,
    SourcedHydraulicScalar,
    StructureFlowDirection,
)
from model.provenance import snapshot_hash
from tools.run_dflow_gate_acceptance import IMAGE


SCHEMA = "dayu.dflow-pump-runtime-acceptance.v1"
CASES = ("PUMP01", "PUMP02", "GP01", "GP02", "GP03", "L01")


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _series(value: float, duration: float) -> tuple[TimeValue, ...]:
    return (
        TimeValue(time_seconds=0.0, value=value),
        TimeValue(time_seconds=duration, value=value),
    )


def _model(case_id: str, *, duration: float, pump_only: bool) -> Hydraulic1DModel:
    profile = (
        CrossSectionPoint(station_m=0.0, elevation_m=4.0),
        CrossSectionPoint(station_m=4.0, elevation_m=0.0),
        CrossSectionPoint(station_m=16.0, elevation_m=0.0),
        CrossSectionPoint(station_m=20.0, elevation_m=4.0),
    )
    section_locations = (
        ("section-up", 100.0),
        ("section-gate-up", 300.0),
        ("section-gate-down", 500.0),
        ("section-intake", 600.0),
        ("section-outlet", 800.0),
        ("section-down", 1100.0),
    )
    sections = tuple(
        HydraulicCrossSection(
            id=section_id,
            branch_id="branch-1",
            code=section_id.upper(),
            chainage_m=chainage,
            vertical_datum="1985-national-height-datum",
            points=profile,
            manning_n=0.03,
        )
        for section_id, chainage in section_locations
    )
    structures: tuple[HydraulicStructure, ...]
    pump = HydraulicStructure(
        id="pump-1",
        name="Phase 07 synthetic inline Pump",
        branch_id="branch-1",
        kind="pump",
        chainage_m=700.0 if not pump_only else 500.0,
        operation_rule_type=(
            "time_series" if case_id in {"PUMP02", "GP02", "GP03", "L01"} else "fixed"
        ),
    )
    if pump_only:
        structures = (pump,)
    else:
        structures = (
            HydraulicStructure(
                id="gate-1",
                name="Phase 07 synthetic vertical Gate",
                branch_id="branch-1",
                kind="gate",
                chainage_m=400.0,
                operation_rule_type=(
                    "water_level_controlled" if case_id == "GP03" else (
                        "time_series" if case_id in {"GP02", "L01"} else "fixed"
                    )
                ),
            ),
            pump,
        )
    return Hydraulic1DModel(
        simulation_id=case_id.lower(),
        scenario_id="phase07-synthetic-native-control",
        network_id=f"network-{case_id.lower()}",
        nodes=(
            HydraulicNode(
                id="node-up",
                code="N-UP",
                node_type="boundary",
                location_geometry={"type": "Point", "coordinates": [120.0, 30.0]},
            ),
            HydraulicNode(
                id="node-down",
                code="N-DOWN",
                node_type="boundary",
                location_geometry={"type": "Point", "coordinates": [120.01, 30.0]},
            ),
        ),
        branches=(
            HydraulicBranch(
                id="branch-1",
                code="B1",
                upstream_node_id="node-up",
                downstream_node_id="node-down",
                start_chainage_m=100.0,
                end_chainage_m=1100.0,
            ),
        ),
        cross_sections=sections,
        structures=structures,
        boundaries=(
            BoundaryCondition(
                id="upstream-q",
                branch_id="branch-1",
                location="upstream",
                variable="discharge",
                series=_series(1.0, duration),
            ),
            BoundaryCondition(
                id="downstream-h",
                branch_id="branch-1",
                location="downstream",
                variable="water_level",
                series=_series(2.0, duration),
            ),
        ),
        initial_condition=InitialCondition(water_level_m=2.0, discharge_m3s=0.0),
        settings=SimulationSettings(
            duration_seconds=duration,
            time_step_seconds=60.0 if case_id == "L01" else 10.0,
            output_interval_seconds=3600.0 if case_id == "L01" else 60.0,
        ),
        metadata={
            "engineering_crs": "EPSG:4547",
            "horizontal_unit": "m",
            "vertical_unit": "m",
            "vertical_datum": "1985-national-height-datum",
            "synthetic_fixture": "HYDRO-1D-GATE-PUMP-07",
            "dflow_fm": {
                "coordinate_reference_system": "EPSG:4547",
                "mesh_edge_length_m": 100.0,
                "node_coordinates": {
                    "node-up": [0.0, 0.0],
                    "node-down": [1000.0, 0.0],
                },
                "branch_geometries": {
                    "branch-1": {
                        "type": "LineString",
                        "coordinates": [[0.0, 0.0], [500.0, 0.0], [1000.0, 0.0]],
                    }
                },
            },
        },
    )


def _gate() -> GateHydraulicSpec:
    def value(number: float) -> SourcedHydraulicScalar:
        return SourcedHydraulicScalar.synthetic(number, "Phase 07 synthetic Gate fixture")

    return GateHydraulicSpec(
        structure_id="gate-1",
        name="Phase 07 synthetic vertical Gate",
        branch_id="branch-1",
        chainage_m=400.0,
        gate_subtype="vertical_underflow_gate",
        crest_level_m=value(0.0),
        crest_width_m=value(10.0),
        opening_m=value(2.0),
        maximum_opening_m=value(3.0),
        allowed_flow_direction=StructureFlowDirection.BOTH,
        use_velocity_height=False,
        correction_coefficient=value(0.61),
        maximum_opening_axis="vertical",
    )


def _pump(*, available: bool = True, chainage_m: float = 500.0) -> PumpHydraulicSpec:
    evidence = "Phase 07 synthetic native Pump fixture"
    return PumpHydraulicSpec(
        structure_id="pump-1",
        name="Phase 07 synthetic inline Pump",
        branch_id="branch-1",
        chainage_m=chainage_m,
        transfer_type=PumpTransferType.INLINE_BRANCH,
        intake_id="section-intake",
        outlet_id="section-outlet",
        orientation=PumpOrientation.POSITIVE,
        unit_count=1,
        control_mode=PumpControlMode.AGGREGATE_CAPACITY,
        aggregate_capacity_m3s=SourcedHydraulicScalar.synthetic(1.0, evidence),
        availability=SourcedHydraulicBoolean.synthetic(available, evidence),
        head_reduction_curve=PumpHeadReductionCurve(
            status=HydraulicDataStatus.SYNTHETIC_ASSUMPTION,
            points=(
                PumpHeadReductionPoint(head_m=-1.0, reduction_factor=1.0),
                PumpHeadReductionPoint(head_m=2.0, reduction_factor=1.0),
                PumpHeadReductionPoint(head_m=5.0, reduction_factor=0.0),
            ),
            evidence=evidence,
        ),
        native_num_stages=0,
        capacity_is_actual_discharge=False,
    )


def _runtime(root: Path, docker_executable: str):
    repository = Path(__file__).resolve().parents[1]
    return create_dflow_runtime(
        DFlowRuntimeConfig(
            runtime="container",
            dimr_executable="dimr",
            dimr_executable_sha256=None,
            docker_executable=docker_executable,
            container_image=IMAGE,
            provenance_file=repository
            / "model/hydraulic_1d/dflow_fm/acceptance/DIMRset_2026.02/runtime-provenance.json",
            timeout_seconds=600,
            workspace_root=root.resolve(),
        )
    )


def _execute(
    *,
    case_id: str,
    root: Path,
    job_id: str,
    model: Hydraulic1DModel,
    pump: PumpHydraulicSpec,
    gate: GateHydraulicSpec | None,
    docker_executable: str,
    controlled: bool,
    dynamic_gate: bool = False,
) -> dict[str, Any]:
    workspace = DFlowJobWorkspace.create(root, simulation_id=model.simulation_id, job_id=job_id)
    prepared = DFlowFMModelBuilder().build(
        model,
        workspace,
        gate_specs=(gate,) if gate is not None else (),
        pump_specs=(pump,),
    )
    dimr_config = prepared.dimr_config_file
    control_hash = None
    if controlled:
        schedules: list[DRTCManualGateScheduleSpec | DRTCManualPumpScheduleSpec] = []
        if gate is not None:
            schedules.append(
                DRTCManualGateScheduleSpec(
                    schedule_id="gate_schedule_1",
                    actuator_bmi_variable="orifices/gate-1/gateLowerEdgeLevel",
                    records=((0.0, 2.0), (180.0, 1.0), (420.0, 1.5)),
                )
            )
        schedules.append(
            DRTCManualPumpScheduleSpec(
                schedule_id="pump_schedule_1",
                actuator_bmi_variable="pumps/pump-1/capacity",
                records=((0.0, 0.0), (180.0, 1.0), (420.0, 0.4)),
            )
        )
        writer = DRTCFBCArtifactWriter()
        common = {
            "job_root": workspace.path,
            "dflow_input_file": prepared.case_file.name,
            "start": datetime(2020, 1, 1),
            "duration_seconds": float(model.settings.duration_seconds),
            "coupling_step_seconds": 60.0,
        }
        if dynamic_gate:
            artifacts = writer.write_gate_threshold_with_schedules(
                **common,
                threshold_spec=DRTCGateThresholdSpec(
                    rule_id="gate_rule_1",
                    observation_bmi_variable="observations/section-up/water_level",
                    actuator_bmi_variable="orifices/gate-1/gateLowerEdgeLevel",
                    operator=">=",
                    threshold=2.01,
                    target_native_value=0.5,
                    fallback_native_value=2.0,
                ),
                schedule_specs=tuple(
                    item
                    for item in schedules
                    if isinstance(item, DRTCManualPumpScheduleSpec)
                ),
            )
        else:
            artifacts = writer.write_schedules(**common, specs=tuple(schedules))
        dimr_config = artifacts.dimr_config
        control_hash = artifacts.artifact_hash
    runtime = _runtime(root, docker_executable)
    available, detail = runtime.availability()
    if not available:
        raise RuntimeError(detail)
    execution = runtime.execute(
        DFlowRuntimeRequest(workspace=workspace, dimr_config=dimr_config)
    )
    parser = DFlowFMResultParser()
    hydraulic = parser.parse(model, prepared, runtime_seconds=execution.elapsed_seconds)
    pumps, balance = parser.parse_pump_and_mass_balance(
        prepared,
        expected_structure_id="pump-1",
    )
    gates = ()
    if gate is not None:
        gates, gate_balance = parser.parse_gate_and_mass_balance(
            prepared,
            expected_structure_id="gate-1",
        )
        if abs(gate_balance.relative_residual - balance.relative_residual) > 1e-12:
            raise RuntimeError("joint Gate/Pump balance views disagree")
    if balance.relative_residual > 0.005:
        raise RuntimeError("mass-balance relative residual exceeds 0.5 percent")
    if any(
        not isfinite(value)
        for item in pumps
        for value in (
            item.actual_discharge_m3s,
            item.native_applied_capacity_m3s,
            item.intake_water_level_m,
            item.outlet_water_level_m,
            item.pump_head_m,
        )
    ):
        raise RuntimeError("Pump H/Q/capacity output contains a non-finite value")
    return {
        "case_id": case_id,
        "model_snapshot_hash": snapshot_hash(model.model_dump(mode="json")),
        "native_model_manifest_sha256": _sha(prepared.manifest_file),
        "control_artifact_hash": control_hash,
        "runtime_seconds": execution.elapsed_seconds,
        "hydraulic_record_count": len(hydraulic.records),
        "pump_samples": [asdict(item) for item in pumps],
        "gate_samples": [asdict(item) for item in gates],
        "mass_balance": asdict(balance),
        "native_result_sha256": _sha(prepared.result_file),
        "workspace": str(workspace.path),
    }


def run(case_id: str, root: Path, job_id: str, docker_executable: str) -> dict[str, Any]:
    if case_id not in CASES:
        raise ValueError(f"unsupported Phase 07 case: {case_id}")
    duration = 86400.0 if case_id == "L01" else 600.0
    pump_only = case_id.startswith("PUMP")
    if case_id == "PUMP01":
        variants = {
            label: _execute(
                case_id=case_id,
                root=root,
                job_id=f"{job_id}-{label}",
                model=_model(f"{case_id}-{label}", duration=duration, pump_only=True),
                pump=_pump(available=available),
                gate=None,
                docker_executable=docker_executable,
                controlled=False,
            )
            for label, available in (("capacity-0", False), ("capacity-1", True))
        }
        zero_active = variants["capacity-0"]["pump_samples"][1:]
        one_active = variants["capacity-1"]["pump_samples"][1:]
        if any(abs(item["actual_discharge_m3s"]) > 1e-9 for item in zero_active):
            raise RuntimeError("PUMP01 zero-capacity actual discharge is not zero")
        if any(
            abs(item["native_applied_capacity_m3s"] - 1.0) > 1e-9
            or abs(item["actual_discharge_m3s"] - 1.0) > 1e-9
            for item in one_active
        ):
            raise RuntimeError("PUMP01 one-capacity native output does not equal 1 m3/s")
        case_payload: dict[str, Any] = {"variants": variants}
    else:
        result = _execute(
            case_id=case_id,
            root=root,
            job_id=job_id,
            model=_model(case_id, duration=duration, pump_only=pump_only),
            pump=_pump(chainage_m=500.0 if pump_only else 700.0),
            gate=None if pump_only else _gate(),
            docker_executable=docker_executable,
            controlled=case_id in {"PUMP02", "GP02", "GP03"},
            dynamic_gate=case_id == "GP03",
        )
        active = result["pump_samples"][1:]
        if case_id in {"PUMP02", "GP02", "GP03"}:
            capacities = {round(item["native_applied_capacity_m3s"], 6) for item in active}
            if not {0.0, 0.4, 1.0}.issubset(capacities):
                raise RuntimeError("manual Pump capacity transitions were not observed")
        if case_id == "GP03":
            openings = {round(item["actual_opening_m"], 6) for item in result["gate_samples"]}
            if not {0.5, 2.0}.issubset(openings):
                raise RuntimeError("dynamic Gate threshold transition was not observed")
        if case_id == "L01":
            if result["pump_samples"][-1]["time_seconds"] != duration:
                raise RuntimeError("L01 did not reach the 24-hour horizon")
        case_payload = {"result": result}
    payload = {
        "schema_version": SCHEMA,
        "case_id": case_id,
        "status": "PASS",
        "evidence_class": "SYNTHETIC_NUMERICAL_ONLY",
        "runtime_image": IMAGE,
        "native_pump_control_variable": "pumps/<id>/capacity",
        "pump_capacity_is_actual_discharge": False,
        "real_engineering_validation": False,
        "real_equipment_command": False,
        "plc_scada_connected": False,
        **case_payload,
    }
    manifest_payload = {**payload, "acceptance_hash": snapshot_hash(payload)}
    manifest_dir = root.resolve() / "phase07-acceptance"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    target = manifest_dir / f"{case_id.lower()}-acceptance.json"
    target.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**manifest_payload, "manifest": str(target)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, choices=CASES)
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--docker-executable", default="docker")
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.case, args.workspace_root, args.job_id, args.docker_executable),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
