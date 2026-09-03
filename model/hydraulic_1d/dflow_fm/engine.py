"""Development-only D-Flow FM engine orchestration through the official DIMR boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
from math import isclose
from pathlib import Path
from time import monotonic
from typing import Any

from model.control.compiler import (
    ActuatorControlBinding,
    HydraulicControlCompileReport,
    InitialActuatorState,
)
from model.control.drtc import (
    DRTC_COMPILER_VERSION,
    DRTCFBCArtifactWriter,
    DRTCGateThresholdSpec,
    DRTCManualGateScheduleSpec,
    DRTCManualPumpScheduleSpec,
    controlled_runtime_acceptance,
)
from model.control.observation_bridge import ObservationBinding
from model.control.rules import ThresholdRule
from model.provenance import canonical_json, snapshot_hash
from model.hydraulic_1d.capabilities import (
    CapabilityExecutionPolicy,
    enforce_compatibility,
)
from model.hydraulic_1d.contracts import Hydraulic1DModel, HydraulicResult
from model.hydraulic_1d.controlled import (
    CompiledControl,
    CompiledControlArtifact,
    ControlledEventRecord,
    ControlledHydraulic1DEngine,
    ControlledHydraulic1DRun,
    ControlledHydraulicResult,
    ControlledStructureResult,
    DispatchTraceRecord,
    RuntimeProvenanceRecord,
    SyntheticBenchmarkEvidence,
)
from model.hydraulic_1d.dflow_fm.adapter import (
    CASE_FILENAME,
    CROSS_DEF_FILENAME,
    CROSS_LOC_FILENAME,
    DIMR_FILENAME,
    EXTERNAL_FORCING_FILENAME,
    FORCING_FILENAME,
    MANIFEST_FILENAME,
    NETWORK_FILENAME,
    OBSERVATION_CROSS_SECTION_FILENAME,
    OBSERVATION_FILENAME,
    RESULT_FILENAME,
    ROUGHNESS_FILENAME,
    STRUCTURE_FILENAME,
    DFlowFMModelBuilder,
    DFlowFMPreparedCase,
)
from model.hydraulic_1d.dflow_fm.config import DFlowRuntimeConfig
from model.hydraulic_1d.dflow_fm.parser import DFlowFMResultParser
from model.hydraulic_1d.dflow_fm.runtime import (
    DFlowRuntime,
    DFlowRuntimeRequest,
    create_dflow_runtime,
)
from model.hydraulic_1d.dflow_fm.workspace import DFlowJobWorkspace
from model.hydraulic_1d.engine import Hydraulic1DExecutionContext
from model.hydraulic_1d.errors import (
    Hydraulic1DResultError,
    Hydraulic1DRuntimeUnavailable,
    Hydraulic1DValidationError,
)
from model.hydraulic_1d.registry import (
    DFLOW_FM_ADAPTER_ID,
    DFLOW_FM_ENGINE_ID,
    DFLOW_FM_ENGINE_VERSION,
)
from model.hydraulic_1d.structures import GateHydraulicSpec, PumpHydraulicSpec


RUNTIME_HEARTBEAT_INTERVAL_SECONDS = 15.0
CONTROL_COMPILER_BUNDLE_VERSION = (
    "dayu.hydraulic-control-compiler.v1+" + DRTC_COMPILER_VERSION
)


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class _ControlledStructureContract:
    gate_specs: tuple[GateHydraulicSpec, ...]
    pump_specs: tuple[PumpHydraulicSpec, ...]
    bindings: tuple[ActuatorControlBinding, ...]
    initial_states: tuple[InitialActuatorState, ...]
    manual: HydraulicControlCompileReport
    rules: tuple[ThresholdRule, ...]
    observations: tuple[ObservationBinding, ...]


class DFlowFMEngine(ControlledHydraulic1DEngine):
    """Build, execute, and parse the audited D-Flow/DIMR/FBC subset.

    The ordinary ``run`` path closes the DF01-shaped base-hydraulics adapter.
    The controlled path accepts only the hash-bound, single-Gate schedule or
    scalar water-level threshold subset.  DIMR remains the time-step owner;
    no Python time-step coupler is used as a substitute.
    """

    def __init__(
        self,
        config: DFlowRuntimeConfig | None = None,
        *,
        runtime: DFlowRuntime | None = None,
        builder: DFlowFMModelBuilder | None = None,
        parser: DFlowFMResultParser | None = None,
    ) -> None:
        self.config = config or DFlowRuntimeConfig.from_environment()
        self.runtime = runtime or create_dflow_runtime(self.config)
        self.builder = builder or DFlowFMModelBuilder()
        self.parser = parser or DFlowFMResultParser()

    @property
    def engine_id(self) -> str:
        """Return the explicit secondary-engine registration."""

        return DFLOW_FM_ENGINE_ID

    @property
    def engine_version(self) -> str:
        """Return the pinned FM-suite release identity."""

        return DFLOW_FM_ENGINE_VERSION

    def availability(self) -> tuple[bool, str]:
        """Report the reviewed DIMR runtime state without creating a workspace."""

        return self.runtime.availability()

    def runtime_provenance(self) -> dict[str, object]:
        """Expose complete provenance only when its reviewed manifest is valid."""

        available, detail, provenance = self.runtime.verified_provenance()
        if not available:
            return {
                "engine": self.engine_id,
                "engine_version": self.engine_version,
                "adapter_id": DFLOW_FM_ADAPTER_ID,
                "runtime_mode": self.config.mode,
                "provenance_complete": False,
                "runtime_available": False,
                "detail": detail,
            }
        if provenance is None:  # pragma: no cover - guarded by runtime contract
            raise Hydraulic1DRuntimeUnavailable(
                "reviewed runtime returned no verified provenance",
                code="DFLOW_RUNTIME_BLOCKED",
            )
        return {
            **provenance,
            "engine": self.engine_id,
            "engine_version": self.engine_version,
            "adapter_id": DFLOW_FM_ADAPTER_ID,
            "runtime_mode": self.config.mode,
            "provenance_complete": True,
            "runtime_available": True,
        }

    def validate(self, model: Hydraulic1DModel) -> None:
        """Validate the base model; controlled structure specs live outside it."""

        self.builder.validator.validate_base(model)
        enforce_compatibility(
            model,
            engine=self.engine_id,
            engine_version=self.engine_version,
            execution_policy=CapabilityExecutionPolicy.SYNTHETIC_NUMERICAL_ONLY,
            development_mode=True,
            production_mode=False,
        )

    def run(
        self,
        model: Hydraulic1DModel,
        context: Hydraulic1DExecutionContext,
    ) -> HydraulicResult:
        """Run one isolated base-1D job through DIMR and return unified H/Q."""

        self.validate(model)
        active_structures = [
            item.id for item in model.structures if item.status == "active"
        ]
        if active_structures:
            raise Hydraulic1DValidationError(
                "DFLOW_STRUCTURE_SPECS_REQUIRED",
                (
                    "ordinary D-Flow execution cannot infer Gate/Pump specs; "
                    f"active structures={active_structures}"
                ),
                field_path="structures",
            )
        available, readiness_detail = self.runtime.availability()
        if not available:
            raise Hydraulic1DRuntimeUnavailable(
                readiness_detail,
                code="DFLOW_RUNTIME_BLOCKED",
            )
        if context.progress_callback is not None:
            context.progress_callback(5.0, {"phase": "validated"})
        workspace = DFlowJobWorkspace.create(
            context.workspace_root or self.config.workspace_root,
            simulation_id=model.simulation_id,
            job_id=context.job_id,
        )
        build_started = monotonic()
        prepared = self.builder.build(model, workspace)
        build_seconds = monotonic() - build_started
        if context.progress_callback is not None:
            context.progress_callback(20.0, {"phase": "prepared"})
        last_heartbeat = monotonic()

        def supervise() -> bool:
            nonlocal last_heartbeat
            if context.cancel_check is not None and context.cancel_check():
                return True
            now = monotonic()
            if (
                context.progress_callback is not None
                and now - last_heartbeat >= RUNTIME_HEARTBEAT_INTERVAL_SECONDS
            ):
                context.progress_callback(50.0, {"phase": "executing"})
                last_heartbeat = now
            return False

        execution = self.runtime.execute(
            DFlowRuntimeRequest(
                workspace=prepared.job_workspace,
                dimr_config=prepared.dimr_config_file,
            ),
            cancel_check=supervise,
        )
        if context.progress_callback is not None:
            context.progress_callback(90.0, {"phase": "parsing"})
        parse_started = monotonic()
        result = self.parser.parse(
            model,
            prepared,
            runtime_seconds=execution.elapsed_seconds,
        )
        parse_seconds = monotonic() - parse_started
        if (
            result.simulation_id != model.simulation_id
            or result.scenario_id != model.scenario_id
            or result.engine != self.engine_id
            or result.engine_version != self.engine_version
        ):
            raise Hydraulic1DResultError(
                "D-Flow parser returned a result with a mismatched model or engine identity",
                code="DFLOW_RESULT_IDENTITY_MISMATCH",
            )
        manifest_sha256 = sha256(prepared.manifest_file.read_bytes()).hexdigest()
        result = result.model_copy(
            update={
                "diagnostics": {
                    **result.diagnostics,
                    "model_build_seconds": build_seconds,
                    "parser_seconds": parse_seconds,
                    "runtime_provenance": execution.provenance,
                    "runtime_verification": readiness_detail,
                    "native_manifest_sha256": manifest_sha256,
                    "evidence_class": "SYNTHETIC_NUMERICAL_ONLY",
                    "real_engineering_validation": False,
                    "real_equipment_command": False,
                    "plc_scada_connected": False,
                }
            }
        )
        if context.progress_callback is not None:
            context.progress_callback(100.0, {"phase": "complete"})
        return result

    @staticmethod
    def _payload(run: ControlledHydraulic1DRun) -> dict[str, Any]:
        payload = json.loads(run.dispatch_plan_snapshot.plan_payload_json)
        if not isinstance(payload, dict):  # pragma: no cover - snapshot validator guards
            raise Hydraulic1DValidationError(
                "CONTROLLED_SNAPSHOT_INVALID",
                "controlled DispatchPlan payload is not an object",
            )
        return payload

    @staticmethod
    def _native_target(binding: ActuatorControlBinding, value: float) -> float:
        opening = float(value)
        if binding.supported_command_type == "gate_opening_ratio":
            opening *= float(binding.gate_height_m)
        return float(binding.reference_level_m) + opening

    def _controlled_structure_contract(
        self,
        run: ControlledHydraulic1DRun,
    ) -> _ControlledStructureContract:
        payload = self._payload(run)
        gate_specs = tuple(
            GateHydraulicSpec.model_validate(item)
            for item in payload.get("gate_hydraulic_specs", [])
        )
        pump_specs = tuple(
            PumpHydraulicSpec.model_validate(item)
            for item in payload.get("pump_hydraulic_specs", [])
        )
        if (
            not gate_specs and not pump_specs
            or len(gate_specs) > 1
            or len(pump_specs) > 1
        ):
            raise Hydraulic1DValidationError(
                "CONTROLLED_STRUCTURE_SUBSET_UNSUPPORTED",
                "the accepted subset requires one Gate, one Pump, or one of each",
                field_path="hydraulic_structure_specs",
            )
        bindings = tuple(
            ActuatorControlBinding.model_validate(item)
            for item in payload.get("control_bindings", [])
        )
        initial_states = tuple(
            InitialActuatorState.model_validate(item)
            for item in payload.get("initial_actuator_state", [])
        )
        expected_native = {
            "gate": {item.structure_id for item in gate_specs},
            "pump": {item.structure_id for item in pump_specs},
        }
        if len(bindings) != len(gate_specs) + len(pump_specs):
            raise Hydraulic1DValidationError(
                "CONTROLLED_BINDING_SET_INVALID",
                "each controlled Gate/Pump requires exactly one native actuator binding",
            )
        identities: set[tuple[str, int]] = set()
        for binding in bindings:
            identity = (binding.structure_type, binding.structure_id)
            if (
                identity in identities
                or binding.native_structure_id not in expected_native[binding.structure_type]
            ):
                raise Hydraulic1DValidationError(
                    "CONTROLLED_STRUCTURE_IDENTITY_MISMATCH",
                    "structure specification and actuator binding identities do not match",
                )
            identities.add(identity)
        initial_identities = {
            (item.structure_type, item.structure_id) for item in initial_states
        }
        if len(initial_states) != len(identities) or initial_identities != identities:
            raise Hydraulic1DValidationError(
                "CONTROLLED_INITIAL_STATE_SET_INVALID",
                "each controlled Gate/Pump requires one matching explicit initial state",
            )
        manual = HydraulicControlCompileReport.model_validate(
            payload.get("manual_control_report")
        )
        rules = tuple(
            ThresholdRule(
                id=item.get("id"),
                name=str(item["name"]),
                enabled=bool(item["enabled"]),
                observation_type=str(item["observation_type"]),
                observation_object_id=item.get("observation_object_id"),
                operator=str(item["operator"]),
                threshold=float(item["threshold"]),
                hysteresis=float(item["hysteresis"]),
                minimum_hold_seconds=float(item["minimum_hold_seconds"]),
                cooldown_seconds=float(item["cooldown_seconds"]),
                action_template=dict(item["action_template"]),
                priority=int(item["priority"]),
            )
            for item in payload.get("rules", [])
            if item.get("enabled")
        )
        observations = tuple(
            ObservationBinding.model_validate(item)
            for item in payload.get("control_observation_contract", {}).get(
                "bindings", []
            )
        )
        return _ControlledStructureContract(
            gate_specs=gate_specs,
            pump_specs=pump_specs,
            bindings=bindings,
            initial_states=initial_states,
            manual=manual,
            rules=rules,
            observations=observations,
        )

    def validate_controlled_model(self, run: ControlledHydraulic1DRun) -> None:
        """Validate the exact Gate/Pump subset against committed native evidence."""

        if (
            run.engine_selection.engine_id != self.engine_id
            or run.engine_selection.engine_version != self.engine_version
        ):
            raise Hydraulic1DValidationError(
                "CONTROLLED_ENGINE_SELECTION_MISMATCH",
                "controlled run is not bound to the selected D-Flow FM release",
                field_path="engine_selection",
            )
        acceptance = controlled_runtime_acceptance()
        if (
            acceptance.compiler_version != DRTC_COMPILER_VERSION
            or run.control_runtime_selection.runtime_version != acceptance.fbc_version
            or run.control_runtime_selection.coupling_runtime_version != "2.00"
            or run.control_runtime_selection.compiler_version
            != CONTROL_COMPILER_BUNDLE_VERSION
        ):
            raise Hydraulic1DRuntimeUnavailable(
                "controlled runtime/compiler identity is outside the accepted registry",
                code="DRTC_COMPILER_BLOCKED",
            )
        expected_mode = "cli" if run.engine_selection.runtime_mode == "external" else "container"
        if self.config.mode != expected_mode:
            raise Hydraulic1DRuntimeUnavailable(
                "controlled run runtime mode does not match the configured D-Flow runtime",
                code="DFLOW_RUNTIME_BLOCKED",
            )
        self.builder.validator.validate_base(run.hydraulic_model)
        contract = self._controlled_structure_contract(run)
        if contract.manual.status != "COMPILED":
            raise Hydraulic1DValidationError(
                "CONTROLLED_MANUAL_COMPILE_INVALID",
                "frozen manual control report is not compiled",
            )
        gate_commands = tuple(
            item for item in contract.manual.commands if item.structure_type == "gate"
        )
        if len(contract.rules) > 1 or (contract.rules and gate_commands):
            raise Hydraulic1DValidationError(
                "CONTROL_CONFLICT_UNSUPPORTED",
                "one Gate rule cannot be combined with a manual Gate schedule",
            )
        if contract.rules:
            rule = contract.rules[0]
            gate_bindings = tuple(
                item for item in contract.bindings if item.structure_type == "gate"
            )
            if len(gate_bindings) != 1:
                raise Hydraulic1DValidationError(
                    "CONTROLLED_GATE_BINDING_MISSING",
                    "Gate rule requires one exact native actuator binding",
                )
            binding = gate_bindings[0]
            if (
                rule.hysteresis != 0
                or rule.minimum_hold_seconds != 0
                or rule.cooldown_seconds != 0
                or rule.action_template["structure_type"] != "gate"
                or rule.action_template["structure_id"] != binding.structure_id
                or rule.action_template["command_type"]
                != binding.supported_command_type
                or rule.observation_type
                not in {"node_water_level", "section_water_level"}
            ):
                raise Hydraulic1DValidationError(
                    "DRTC_RULE_SEMANTICS_UNSUPPORTED",
                    "rule is outside the accepted one-Gate scalar water-level subset",
                )
            matches = tuple(
                item
                for item in contract.observations
                if item.observation_type == rule.observation_type
                and item.observation_object_id == rule.observation_object_id
            )
            if len(matches) != 1 or len(matches[0].bmi_variables()) != 1:
                raise Hydraulic1DValidationError(
                    "CONTROL_OBSERVATION_BINDING_MISSING",
                    "Gate rule requires one exact scalar D-Flow water-level binding",
                )

    def compile_control(
        self,
        run: ControlledHydraulic1DRun,
        workspace: Path,
    ) -> CompiledControl:
        """Emit only the accepted FBC schedule or threshold artifact bundle."""

        self.validate_controlled_model(run)
        contract = self._controlled_structure_contract(run)
        root = Path(workspace).resolve()
        writer = DRTCFBCArtifactWriter()
        common = {
            "job_root": root,
            "dflow_input_file": CASE_FILENAME,
            "start": datetime(2020, 1, 1),
            "duration_seconds": float(run.hydraulic_model.settings.duration_seconds),
            "coupling_step_seconds": float(
                run.dispatch_plan_snapshot.control_observation_contract.sampling_interval_seconds
            ),
        }
        if contract.rules:
            rule = contract.rules[0]
            binding = next(
                item for item in contract.bindings if item.structure_type == "gate"
            )
            initial = next(
                item for item in contract.initial_states if item.structure_type == "gate"
            )
            observation = next(
                item
                for item in contract.observations
                if item.observation_type == rule.observation_type
                and item.observation_object_id == rule.observation_object_id
            )
            threshold_spec = DRTCGateThresholdSpec(
                rule_id=f"gate_rule_{rule.id or 1}",
                observation_bmi_variable=observation.bmi_variables()[0],
                actuator_bmi_variable=binding.bmi_variable,
                operator=rule.operator,
                threshold=float(rule.threshold),
                target_native_value=self._native_target(
                    binding, float(rule.action_template["target_value"])
                ),
                fallback_native_value=self._native_target(
                    binding, float(initial.gate_opening_m)
                ),
            )
            pump_schedules: list[DRTCManualPumpScheduleSpec] = []
            for pump_binding in (
                item for item in contract.bindings if item.structure_type == "pump"
            ):
                pump = next(
                    item
                    for item in contract.pump_specs
                    if item.structure_id == pump_binding.native_structure_id
                )
                pump_initial = next(
                    item
                    for item in contract.initial_states
                    if item.structure_type == "pump"
                    and item.structure_id == pump_binding.structure_id
                )
                if pump.aggregate_capacity_m3s.value is None:
                    raise Hydraulic1DValidationError(
                        "PUMP_CAPACITY_UNKNOWN",
                        "Pump aggregate capacity is unavailable",
                    )
                initial_capacity = (
                    float(pump.aggregate_capacity_m3s.value)
                    if pump_initial.pump_enabled
                    else 0.0
                )
                records: dict[float, float] = {0.0: initial_capacity}
                for command in contract.manual.commands:
                    if (
                        command.structure_type == "pump"
                        and command.structure_id == pump_binding.structure_id
                    ):
                        records[float(command.time_seconds)] = float(
                            command.native_target_value
                        )
                pump_schedules.append(
                    DRTCManualPumpScheduleSpec(
                        schedule_id=f"pump_schedule_{pump_binding.structure_id}",
                        actuator_bmi_variable=pump_binding.bmi_variable,
                        records=tuple(sorted(records.items())),
                    )
                )
            artifacts = (
                writer.write_gate_threshold_with_schedules(
                    **common,
                    threshold_spec=threshold_spec,
                    schedule_specs=tuple(pump_schedules),
                )
                if pump_schedules
                else writer.write_threshold(**common, spec=threshold_spec)
            )
        else:
            schedules: list[DRTCManualGateScheduleSpec | DRTCManualPumpScheduleSpec] = []
            pumps = {item.structure_id: item for item in contract.pump_specs}
            initial_by_identity = {
                (item.structure_type, item.structure_id): item
                for item in contract.initial_states
            }
            for binding in contract.bindings:
                initial = initial_by_identity[(binding.structure_type, binding.structure_id)]
                if binding.structure_type == "gate":
                    initial_native = self._native_target(
                        binding, float(initial.gate_opening_m)
                    )
                else:
                    pump = pumps[binding.native_structure_id]
                    if pump.aggregate_capacity_m3s.value is None:
                        raise Hydraulic1DValidationError(
                            "PUMP_CAPACITY_UNKNOWN",
                            "Pump aggregate capacity is unavailable",
                        )
                    initial_native = (
                        float(pump.aggregate_capacity_m3s.value)
                        if initial.pump_enabled
                        else 0.0
                    )
                records: dict[float, float] = {0.0: initial_native}
                for command in contract.manual.commands:
                    if (
                        command.structure_type == binding.structure_type
                        and command.structure_id == binding.structure_id
                    ):
                        records[float(command.time_seconds)] = float(
                            command.native_target_value
                        )
                schedule_id = f"{binding.structure_type}_schedule_{binding.structure_id}"
                if binding.structure_type == "gate":
                    schedules.append(
                        DRTCManualGateScheduleSpec(
                            schedule_id=schedule_id,
                            actuator_bmi_variable=binding.bmi_variable,
                            records=tuple(sorted(records.items())),
                        )
                    )
                else:
                    schedules.append(
                        DRTCManualPumpScheduleSpec(
                            schedule_id=schedule_id,
                            actuator_bmi_variable=binding.bmi_variable,
                            records=tuple(sorted(records.items())),
                        )
                    )
            artifacts = writer.write_schedules(
                **common,
                specs=tuple(schedules),
            )
        paths = (
            artifacts.dimr_config,
            artifacts.settings,
            artifacts.data_config,
            artifacts.runtime_config,
            artifacts.tools_config,
            artifacts.manifest,
        )
        return CompiledControl(
            compiler_id="dayu.drtc-fbc-artifact-writer",
            compiler_version=DRTC_COMPILER_VERSION,
            dispatch_plan_snapshot_hash=run.dispatch_plan_snapshot.snapshot_hash,
            artifacts=tuple(
                CompiledControlArtifact(
                    artifact_type=("manifest" if path == artifacts.manifest else "runtime_config"),
                    relative_path=str(path.relative_to(root)).replace("\\", "/"),
                    sha256=_sha256(path),
                )
                for path in paths
            ),
        )

    def run_controlled(
        self,
        run: ControlledHydraulic1DRun,
        context: Hydraulic1DExecutionContext,
    ) -> ControlledHydraulicResult:
        """Run the accepted DIMR + D-Flow FM + FBC Gate/Pump path in one job."""

        self.validate_controlled_model(run)
        available, detail = self.runtime.availability()
        if not available:
            raise Hydraulic1DRuntimeUnavailable(detail, code="DFLOW_RUNTIME_BLOCKED")
        contract = self._controlled_structure_contract(run)
        workspace = DFlowJobWorkspace.create(
            context.workspace_root or self.config.workspace_root,
            simulation_id=run.hydraulic_model.simulation_id,
            job_id=context.job_id,
        )
        if context.progress_callback:
            context.progress_callback(5.0, {"phase": "validated"})
        prepared = self.builder.build(
            run.hydraulic_model,
            workspace,
            gate_specs=contract.gate_specs,
            pump_specs=contract.pump_specs,
        )
        compiled = self.compile_control(run, workspace.path)
        if context.progress_callback:
            context.progress_callback(20.0, {"phase": "prepared"})
        last_heartbeat = monotonic()

        def supervise() -> bool:
            nonlocal last_heartbeat
            if context.cancel_check and context.cancel_check():
                return True
            now = monotonic()
            if context.progress_callback and now - last_heartbeat >= RUNTIME_HEARTBEAT_INTERVAL_SECONDS:
                context.progress_callback(50.0, {"phase": "executing"})
                last_heartbeat = now
            return False

        execution = self.runtime.execute(
            DFlowRuntimeRequest(
                workspace=workspace,
                dimr_config=workspace.control_dir / DIMR_FILENAME,
            ),
            cancel_check=supervise,
        )
        if context.progress_callback:
            context.progress_callback(90.0, {"phase": "parsing"})
        result = self._parse_controlled(
            run,
            prepared,
            runtime_seconds=execution.elapsed_seconds,
            runtime_provenance=execution.provenance,
            compiled=compiled,
        )
        if context.progress_callback:
            context.progress_callback(100.0, {"phase": "complete"})
        return result

    def parse_controlled_results(
        self,
        run: ControlledHydraulic1DRun,
        workspace: Path,
    ) -> ControlledHydraulicResult:
        """Strictly parse an already completed accepted controlled workspace."""

        self.validate_controlled_model(run)
        job = DFlowJobWorkspace.open(Path(workspace))
        prepared = DFlowFMPreparedCase(
            workspace=job.path,
            job_workspace=job,
            dimr_config_file=job.control_dir / DIMR_FILENAME,
            case_file=job.input_dir / CASE_FILENAME,
            network_file=job.input_dir / NETWORK_FILENAME,
            cross_definition_file=job.input_dir / CROSS_DEF_FILENAME,
            cross_location_file=job.input_dir / CROSS_LOC_FILENAME,
            roughness_file=job.input_dir / ROUGHNESS_FILENAME,
            forcing_file=job.input_dir / FORCING_FILENAME,
            external_forcing_file=job.input_dir / EXTERNAL_FORCING_FILENAME,
            observation_file=job.input_dir / OBSERVATION_FILENAME,
            observation_cross_section_file=job.input_dir / OBSERVATION_CROSS_SECTION_FILENAME,
            structure_file=job.input_dir / STRUCTURE_FILENAME,
            manifest_file=job.metadata_dir / MANIFEST_FILENAME,
            result_file=job.output_dir / RESULT_FILENAME,
            native_model=None,
            native_network_model=None,
            native_dimr_model=None,
        )
        _, _, provenance = self.runtime.verified_provenance()
        if provenance is None:
            raise Hydraulic1DRuntimeUnavailable(
                "accepted runtime provenance is unavailable while parsing results",
                code="DFLOW_RUNTIME_BLOCKED",
            )
        artifact_paths = (
            job.control_dir / DIMR_FILENAME,
            job.control_dir / "rtc" / "settings.json",
            job.control_dir / "rtc" / "xml_dir" / "rtcDataConfig.xml",
            job.control_dir / "rtc" / "xml_dir" / "rtcRuntimeConfig.xml",
            job.control_dir / "rtc" / "xml_dir" / "rtcToolsConfig.xml",
            job.control_dir / "drtc-artifact-manifest.json",
        )
        missing = tuple(path for path in artifact_paths if not path.is_file())
        if missing:
            raise Hydraulic1DResultError(
                "controlled artifact bundle is incomplete: "
                + ", ".join(str(path.relative_to(job.path)) for path in missing),
                code="DRTC_ARTIFACT_MISSING",
            )
        compiled = CompiledControl(
            compiler_id="dayu.drtc-fbc-artifact-writer",
            compiler_version=DRTC_COMPILER_VERSION,
            dispatch_plan_snapshot_hash=run.dispatch_plan_snapshot.snapshot_hash,
            artifacts=tuple(
                CompiledControlArtifact(
                    artifact_type=(
                        "manifest"
                        if path.name == "drtc-artifact-manifest.json"
                        else "runtime_config"
                    ),
                    relative_path=str(path.relative_to(job.path)).replace("\\", "/"),
                    sha256=_sha256(path),
                )
                for path in artifact_paths
            ),
        )
        return self._parse_controlled(
            run,
            prepared,
            runtime_seconds=0.0,
            runtime_provenance=provenance,
            compiled=compiled,
        )

    def _parse_controlled(
        self,
        run: ControlledHydraulic1DRun,
        prepared: DFlowFMPreparedCase,
        *,
        runtime_seconds: float,
        runtime_provenance: dict[str, Any],
        compiled: CompiledControl,
    ) -> ControlledHydraulicResult:
        contract = self._controlled_structure_contract(run)
        hydraulic = self.parser.parse(
            run.hydraulic_model,
            prepared,
            runtime_seconds=runtime_seconds,
        )
        gate_samples: tuple[Any, ...] = ()
        pump_samples: tuple[Any, ...] = ()
        balances: list[Any] = []
        if contract.gate_specs:
            gate_samples, gate_balance = self.parser.parse_gate_and_mass_balance(
                prepared,
                expected_structure_id=contract.gate_specs[0].structure_id,
            )
            balances.append(gate_balance)
        if contract.pump_specs:
            pump_samples, pump_balance = self.parser.parse_pump_and_mass_balance(
                prepared,
                expected_structure_id=contract.pump_specs[0].structure_id,
            )
            balances.append(pump_balance)
        balance = balances[0]
        if len(balances) == 2:
            for field in (
                "inflow_m3",
                "outflow_m3",
                "storage_change_m3",
                "residual_m3",
                "relative_residual",
                "native_max_abs_volume_error_m3",
            ):
                if not isclose(
                    float(getattr(balances[0], field)),
                    float(getattr(balances[1], field)),
                    rel_tol=0.0,
                    abs_tol=1e-9,
                ):
                    raise Hydraulic1DResultError(
                        "Gate/Pump parsers returned inconsistent global balance",
                        code="DFLOW_RESULT_FLOW_IDENTITY_INVALID",
                    )
            balance = type(balance)(
                **{
                    **asdict(balance),
                    "structure_transfer_m3": sum(
                        item.structure_transfer_m3 for item in balances
                    ),
                }
            )
        trace_file = prepared.job_workspace.control_dir / "rtc" / "xml_dir" / "timeseries_0000.csv"
        if not trace_file.is_file():
            raise Hydraulic1DResultError(
                "FBC control trace is missing",
                code="DRTC_CONTROL_TRACE_MISSING",
            )
        hydraulic = hydraulic.model_copy(
            update={
                "diagnostics": {
                    **hydraulic.diagnostics,
                    "mass_balance": asdict(balance),
                    "control_trace_sha256": _sha256(trace_file),
                    "compiled_control": compiled.model_dump(mode="json"),
                    "evidence_class": "SYNTHETIC_NUMERICAL_ONLY",
                    "real_engineering_validation": False,
                    "real_equipment_command": False,
                    "plc_scada_connected": False,
                },
                "artifacts": ("control/rtc/xml_dir/timeseries_0000.csv",),
            }
        )
        manual_commands = contract.manual.commands
        binding_by_kind = {item.structure_type: item for item in contract.bindings}
        initial_by_kind = {
            item.structure_type: item for item in contract.initial_states
        }

        def gate_logical_for(
            sample: Any,
        ) -> tuple[float, float, str, int | None, str, str]:
            binding = binding_by_kind["gate"]
            initial = initial_by_kind["gate"]
            if contract.rules:
                rule = contract.rules[0]
                target = float(rule.action_template["target_value"])
                fallback = float(initial.gate_opening_m)
                target_native = self._native_target(binding, target)
                active = abs(sample.gate_lower_edge_level_m - target_native) <= 1e-8
                value = target if active else fallback
                return value, value, "threshold_rule", rule.id, str(rule.action_template["command_type"]), ("ratio" if binding.supported_command_type == "gate_opening_ratio" else "m")
            matched = next(
                (
                    item
                    for item in reversed(manual_commands)
                    if item.structure_type == "gate"
                    and float(item.time_seconds) <= sample.time_seconds + 1e-8
                ),
                None,
            )
            if matched is None:
                return float(initial.gate_opening_m), float(initial.gate_opening_m), "initial_state", None, "gate_opening_m", "m"
            return float(matched.requested_value), float(matched.resolved_value), "manual_schedule", matched.source_id, matched.command_type, ("ratio" if matched.command_type == "gate_opening_ratio" else "m")

        traces: list[DispatchTraceRecord] = []
        events: list[ControlledEventRecord] = []
        structures: list[ControlledStructureResult] = []
        previous_opening: float | None = None
        for sample in gate_samples:
            gate = contract.gate_specs[0]
            binding = binding_by_kind["gate"]
            requested, resolved, source_type, source_id, command_type, unit = gate_logical_for(sample)
            applied = (
                sample.actual_opening_m / float(binding.gate_height_m)
                if command_type == "gate_opening_ratio"
                else sample.actual_opening_m
            )
            structures.append(
                ControlledStructureResult(
                    time_seconds=sample.time_seconds,
                    structure_type="gate",
                    asset_id=binding.structure_id,
                    hydraulic_structure_id=gate.structure_id,
                    requested_value=requested,
                    resolved_value=resolved,
                    applied_value=applied,
                    upstream_water_level_m=sample.upstream_water_level_m,
                    downstream_water_level_m=sample.downstream_water_level_m,
                    discharge_m3s=sample.discharge_m3s,
                )
            )
            if previous_opening is None or abs(sample.actual_opening_m - previous_opening) > 1e-8:
                traces.append(
                    DispatchTraceRecord(
                        time_seconds=sample.time_seconds,
                        source_type=source_type,
                        source_id=source_id,
                        structure_type="gate",
                        asset_id=binding.structure_id,
                        hydraulic_structure_id=gate.structure_id,
                        command_type=command_type,
                        requested_value=requested,
                        resolved_value=resolved,
                        applied_value=applied,
                        unit=unit,
                    )
                )
                events.append(
                    ControlledEventRecord(
                        time_seconds=sample.time_seconds,
                        event_type="gate_state_transition",
                        outcome="APPLIED",
                        reason_code="FBC_NATIVE_OUTPUT_OBSERVED",
                        structure_type="gate",
                        asset_id=binding.structure_id,
                        hydraulic_structure_id=gate.structure_id,
                    )
                )
                previous_opening = sample.actual_opening_m
        if pump_samples:
            pump = contract.pump_specs[0]
            binding = binding_by_kind["pump"]
            initial = initial_by_kind["pump"]
            if pump.aggregate_capacity_m3s.value is None:
                raise Hydraulic1DResultError(
                    "frozen Pump capacity is unavailable while parsing results",
                    code="DFLOW_RESULT_IDENTITY_MISMATCH",
                )
            initial_capacity = (
                float(pump.aggregate_capacity_m3s.value)
                if initial.pump_enabled
                else 0.0
            )
            pump_commands = tuple(
                item for item in manual_commands if item.structure_type == "pump"
            )
            previous_capacity: float | None = None
            for sample in pump_samples:
                matched = next(
                    (
                        item
                        for item in reversed(pump_commands)
                        if float(item.time_seconds) <= sample.time_seconds + 1e-8
                    ),
                    None,
                )
                if matched is None:
                    requested = resolved = initial_capacity
                    source_type = "initial_state"
                    source_id = None
                else:
                    requested = float(matched.requested_value)
                    resolved = float(matched.resolved_value)
                    source_type = "manual_schedule"
                    source_id = matched.source_id
                applied = sample.native_applied_capacity_m3s
                structures.append(
                    ControlledStructureResult(
                        time_seconds=sample.time_seconds,
                        structure_type="pump",
                        asset_id=binding.structure_id,
                        hydraulic_structure_id=pump.structure_id,
                        requested_value=requested,
                        resolved_value=resolved,
                        applied_value=applied,
                        upstream_water_level_m=sample.intake_water_level_m,
                        downstream_water_level_m=sample.outlet_water_level_m,
                        discharge_m3s=sample.actual_discharge_m3s,
                        active_unit_count=None,
                        active_stage=sample.active_stage,
                        requested_capacity_m3s=requested,
                        resolved_capacity_m3s=resolved,
                        native_applied_capacity_m3s=applied,
                        actual_discharge_m3s=sample.actual_discharge_m3s,
                        intake_water_level_m=sample.intake_water_level_m,
                        outlet_water_level_m=sample.outlet_water_level_m,
                        structure_head_difference_m=(
                            sample.structure_head_difference_m
                        ),
                        pump_head_m=sample.pump_head_m,
                        pump_reduction_factor=sample.reduction_factor,
                    )
                )
                if previous_capacity is None or abs(applied - previous_capacity) > 1e-8:
                    traces.append(
                        DispatchTraceRecord(
                            time_seconds=sample.time_seconds,
                            source_type=source_type,
                            source_id=source_id,
                            structure_type="pump",
                            asset_id=binding.structure_id,
                            hydraulic_structure_id=pump.structure_id,
                            command_type="pump_target_flow",
                            requested_value=requested,
                            resolved_value=resolved,
                            applied_value=applied,
                            unit="m3/s",
                        )
                    )
                    events.append(
                        ControlledEventRecord(
                            time_seconds=sample.time_seconds,
                            event_type="pump_capacity_transition",
                            outcome="APPLIED",
                            reason_code="FBC_NATIVE_CAPACITY_OBSERVED",
                            structure_type="pump",
                            asset_id=binding.structure_id,
                            hydraulic_structure_id=pump.structure_id,
                        )
                    )
                    previous_capacity = applied
        records = []
        for component, key in (
            ("dflowfm", "dflowfm"),
            ("dimr", "dimr"),
            ("fbc", "fbc"),
            ("hydrolib-core", "hydrolib_core"),
        ):
            records.append(RuntimeProvenanceRecord(component=component, **runtime_provenance[key]))
        acceptance = controlled_runtime_acceptance()
        evidence = tuple(
            SyntheticBenchmarkEvidence(
                benchmark_id=item.case_id,
                status=item.status,
                artifact_sha256=item.artifact_sha256,
                metrics_json=canonical_json({"registry": "dayu.controlled-runtime-acceptance.v1"}),
            )
            for item in (*acceptance.official_cases, *acceptance.dayu_cases)
        )
        numerical_result_sha256 = snapshot_hash(
            {
                "hydraulic_records": [
                    item.model_dump(mode="json") for item in hydraulic.records
                ],
                "dispatch_trace": [item.model_dump(mode="json") for item in traces],
                "control_events": [item.model_dump(mode="json") for item in events],
                "structure_results": [
                    item.model_dump(mode="json") for item in structures
                ],
                "mass_balance": asdict(balance),
            }
        )
        hydraulic = hydraulic.model_copy(
            update={
                "diagnostics": {
                    **hydraulic.diagnostics,
                    "numerical_result_sha256": numerical_result_sha256,
                }
            }
        )
        return ControlledHydraulicResult(
            run_snapshot_hash=run.snapshot_hash,
            hydraulic_result=hydraulic,
            dispatch_trace=tuple(traces),
            control_events=tuple(events),
            structure_results=tuple(structures),
            runtime_provenance=tuple(records),
            synthetic_benchmark_evidence=evidence,
        )


__all__ = ["DFlowFMEngine", "RUNTIME_HEARTBEAT_INTERVAL_SECONDS"]
