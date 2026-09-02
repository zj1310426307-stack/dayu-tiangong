"""Run one real synthetic DIMR + D-Flow FM + FBC Gate acceptance case."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from model.control.drtc import (
    DRTCFBCArtifactWriter,
    DRTCGateThresholdSpec,
    DRTCManualGateScheduleSpec,
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
    SourcedHydraulicScalar,
    StructureFlowDirection,
)
from model.provenance import snapshot_hash


IMAGE = (
    "dayu-dflow-runtime@sha256:"
    "e53a7c22cdce6a63f39357006ba73f2254ace24979c1f374ba111ee52d5b12b9"
)
SCHEMA = "dayu.dflow-gate-runtime-acceptance.v1"


def _series(*values: tuple[float, float]) -> tuple[TimeValue, ...]:
    return tuple(TimeValue(time_seconds=time, value=value) for time, value in values)


def _model(case_id: str) -> Hydraulic1DModel:
    points = (
        CrossSectionPoint(station_m=0.0, elevation_m=4.0),
        CrossSectionPoint(station_m=4.0, elevation_m=0.0),
        CrossSectionPoint(station_m=16.0, elevation_m=0.0),
        CrossSectionPoint(station_m=20.0, elevation_m=4.0),
    )
    sections = tuple(
        HydraulicCrossSection(
            id=section_id,
            branch_id="branch-1",
            code=section_id.upper(),
            chainage_m=chainage,
            vertical_datum="1985-national-height-datum",
            points=points,
            manning_n=0.03,
        )
        for section_id, chainage in (
            ("section-up", 100.0),
            ("section-mid", 600.0),
            ("section-down", 1100.0),
        )
    )
    downstream = (
        _series((0, 2.0), (120, 2.0), (180, 3.0), (360, 3.0), (420, 2.0), (600, 2.0))
        if case_id == "DRTC-S01"
        else _series((0, 2.0), (600, 2.0))
    )
    upstream = (
        _series((0, 2.0), (120, 2.0), (180, 32.0), (360, 32.0), (420, 0.0), (600, 0.0))
        if case_id == "G03"
        else _series((0, 10.0), (600, 10.0))
    )
    return Hydraulic1DModel(
        simulation_id=case_id.lower().replace("-", "_"),
        scenario_id="synthetic-controlled",
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
        structures=(
            HydraulicStructure(
                id="gate-1",
                name="Synthetic vertical Gate",
                branch_id="branch-1",
                kind="gate",
                chainage_m=500.0,
                operation_rule_type=(
                    "water_level_controlled" if case_id != "G02" else "time_series"
                ),
            ),
        ),
        boundaries=(
            BoundaryCondition(
                id="upstream-q",
                branch_id="branch-1",
                location="upstream",
                variable="discharge",
                series=upstream,
            ),
            BoundaryCondition(
                id="downstream-h",
                branch_id="branch-1",
                location="downstream",
                variable="water_level",
                series=downstream,
            ),
        ),
        initial_condition=InitialCondition(water_level_m=2.0, discharge_m3s=0.0),
        settings=SimulationSettings(
            duration_seconds=600.0,
            time_step_seconds=10.0,
            output_interval_seconds=60.0,
        ),
        metadata={
            "engineering_crs": "EPSG:4547",
            "horizontal_unit": "m",
            "vertical_unit": "m",
            "vertical_datum": "1985-national-height-datum",
            "dflow_fm": {
                "coordinate_reference_system": "EPSG:4547",
                "mesh_edge_length_m": 100.0,
                "node_coordinates": {"node-up": [0.0, 0.0], "node-down": [1000.0, 0.0]},
                "branch_geometries": {
                    "branch-1": {
                        "type": "LineString",
                        "coordinates": [[0.0, 0.0], [400.0, 0.0], [1000.0, 0.0]],
                    }
                },
            },
        },
    )


def _gate() -> GateHydraulicSpec:
    def value(number: float) -> SourcedHydraulicScalar:
        return SourcedHydraulicScalar.synthetic(number, "06R synthetic Gate acceptance")

    return GateHydraulicSpec(
        structure_id="gate-1",
        name="Synthetic vertical Gate",
        branch_id="branch-1",
        chainage_m=500.0,
        gate_subtype="vertical_underflow_gate",
        crest_level_m=value(2.0),
        crest_width_m=value(3.5),
        opening_m=value(0.2),
        maximum_opening_m=value(1.2),
        allowed_flow_direction=StructureFlowDirection.BOTH,
        use_velocity_height=False,
        correction_coefficient=value(0.61),
        maximum_opening_axis="vertical",
    )


def _sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(case_id: str, root: Path, job_id: str) -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[1]
    model = _model(case_id)
    workspace = DFlowJobWorkspace.create(
        root,
        simulation_id=model.simulation_id,
        job_id=job_id,
    )
    prepared = DFlowFMModelBuilder().build(
        model,
        workspace,
        gate_specs=(_gate(),),
    )
    writer = DRTCFBCArtifactWriter()
    common = {
        "job_root": workspace.path,
        "dflow_input_file": prepared.case_file.name,
        "start": datetime(2020, 1, 1),
        "duration_seconds": 600.0,
        "coupling_step_seconds": 60.0,
    }
    if case_id == "G02":
        controls = writer.write_schedule(
            **common,
            spec=DRTCManualGateScheduleSpec(
                schedule_id="gate_schedule_1",
                actuator_bmi_variable="orifices/gate-1/gateLowerEdgeLevel",
                records=((0, 2.2), (180, 3.0), (420, 2.5)),
            ),
        )
    else:
        controls = writer.write_threshold(
            **common,
            spec=DRTCGateThresholdSpec(
                rule_id="gate_rule_1",
                observation_bmi_variable=(
                    "observations/section-down/water_level"
                    if case_id == "DRTC-S01"
                    else "observations/section-up/water_level"
                ),
                actuator_bmi_variable="orifices/gate-1/gateLowerEdgeLevel",
                operator=">=",
                threshold=2.5,
                target_native_value=3.0,
                fallback_native_value=2.2,
            ),
        )
    provenance = repository / "model/hydraulic_1d/dflow_fm/acceptance/DIMRset_2026.02/runtime-provenance.json"
    runtime = create_dflow_runtime(
        DFlowRuntimeConfig(
            runtime="container",
            dimr_executable="dimr",
            dimr_executable_sha256=None,
            docker_executable="docker",
            container_image=IMAGE,
            provenance_file=provenance,
            timeout_seconds=300,
            workspace_root=root.resolve(),
        )
    )
    available, detail = runtime.availability()
    if not available:
        raise RuntimeError(detail)
    execution = runtime.execute(
        DFlowRuntimeRequest(workspace=workspace, dimr_config=controls.dimr_config)
    )
    parser = DFlowFMResultParser()
    hydraulic = parser.parse(model, prepared, runtime_seconds=execution.elapsed_seconds)
    gates, balance = parser.parse_gate_and_mass_balance(
        prepared,
        expected_structure_id="gate-1",
    )
    active = [item for item in gates if item.time_seconds > 0]
    if any(item.discharge_m3s is None for item in active):
        raise RuntimeError("active Gate discharge contains undefined samples")
    if balance.relative_residual > 0.005:
        raise RuntimeError("mass-balance relative residual exceeds 0.5 percent")
    opening_transitions = [
        {"time_seconds": item.time_seconds, "actual_opening_m": item.actual_opening_m}
        for index, item in enumerate(gates)
        if index == 0
        or abs(item.actual_opening_m - gates[index - 1].actual_opening_m) > 1e-9
    ]
    output_series = workspace.control_dir / "rtc" / "xml_dir" / "timeseries_0000.csv"
    payload: dict[str, Any] = {
        "schema_version": SCHEMA,
        "case_id": case_id,
        "status": "PASS",
        "evidence_class": "SYNTHETIC_NUMERICAL_ONLY",
        "real_engineering_validation": False,
        "real_equipment_command": False,
        "plc_scada_connected": False,
        "model_snapshot_hash": snapshot_hash(model.model_dump(mode="json")),
        "native_model_manifest_sha256": _sha(prepared.manifest_file),
        "control_artifact_hash": controls.artifact_hash,
        "runtime_image": IMAGE,
        "runtime_seconds": execution.elapsed_seconds,
        "hydraulic_record_count": len(hydraulic.records),
        "gate_samples": [asdict(item) for item in gates],
        "opening_transitions": opening_transitions,
        "mass_balance": asdict(balance),
        "native_result_sha256": _sha(prepared.result_file),
        "control_trace_file": (
            str(output_series.relative_to(workspace.path)).replace("\\", "/")
            if output_series.is_file()
            else None
        ),
        "control_trace_sha256": _sha(output_series) if output_series.is_file() else None,
    }
    manifest_payload = {**payload, "acceptance_hash": snapshot_hash(payload)}
    target = workspace.metadata_dir / f"{case_id.lower()}-acceptance.json"
    target.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**manifest_payload, "manifest": str(target)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, choices=("DRTC-S01", "G02", "G03"))
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.case, args.workspace_root, args.job_id), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
