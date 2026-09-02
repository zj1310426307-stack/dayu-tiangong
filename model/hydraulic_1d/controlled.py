"""Immutable contracts for synthetic controlled one-dimensional hydraulic runs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    field_validator,
    model_validator,
)

from model.control.compiler import InitialActuatorState
from model.control.observation_bridge import ObservationBinding
from model.hydraulic_1d.contracts import Hydraulic1DModel, HydraulicResult
from model.hydraulic_1d.engine import Hydraulic1DEngine, Hydraulic1DExecutionContext
from model.hydraulic_1d.registry import (
    CONTROLLED_HYDRAULIC_1D_RUN_SCHEMA,
    CONTROLLED_HYDRAULIC_RESULT_SCHEMA,
    DFLOW_FM_ADAPTER_ID,
    DFLOW_FM_CAPABILITY_ID,
    DFLOW_FM_ENGINE_ID,
    DFLOW_FM_ENGINE_VERSION,
    DFLOW_FM_SOLVER_ID,
    engine_catalog_hash as current_engine_catalog_hash,
    selected_engine_hash as current_selected_engine_hash,
)
from model.provenance import canonical_json, snapshot_hash as hash_snapshot


DISPATCH_PLAN_V3_SCHEMA = "dayu.dispatch-plan.v3"
CONTROL_OBSERVATION_CONTRACT_SCHEMA = "dayu.control-observation-contract.v1"
COMPILED_CONTROL_SCHEMA = "dayu.compiled-control.v1"

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_OPTIONAL_SHA256_PATTERN = r"^(?:|[0-9a-f]{64})$"
_GIT_COMMIT_PATTERN = r"^[0-9a-f]{40}$"


class StrictControlledModel(BaseModel):
    """Reject undeclared fields and freeze every controlled-run envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceClass(StrEnum):
    """Limit 06 controlled runs to the user-authorized evidence boundary."""

    SYNTHETIC_NUMERICAL_ONLY = "SYNTHETIC_NUMERICAL_ONLY"


class EngineSelection(StrictControlledModel):
    """Freeze the selected D-Flow FM registration and runtime mode."""

    engine_id: Literal["d-flow-fm"] = DFLOW_FM_ENGINE_ID
    engine_version: Literal["DIMRset_2026.02"] = DFLOW_FM_ENGINE_VERSION
    solver_id: Literal["d-flow-fm-DIMRset_2026.02"] = DFLOW_FM_SOLVER_ID
    adapter_id: Literal["dayu-dflow-fm-adapter-v1"] = DFLOW_FM_ADAPTER_ID
    capability_id: Literal["synthetic-controlled-1d-dflow-fm-v1"] = (
        DFLOW_FM_CAPABILITY_ID
    )
    engine_catalog_hash: str = Field(pattern=_SHA256_PATTERN)
    engine_registry_hash: str = Field(pattern=_SHA256_PATTERN)
    runtime_mode: Literal["external", "container"]

    @classmethod
    def from_current_registry(
        cls,
        *,
        runtime_mode: Literal["external", "container"],
    ) -> Self:
        """Create a selection bound to the current additive catalog."""

        return cls(
            engine_catalog_hash=current_engine_catalog_hash(),
            engine_registry_hash=current_selected_engine_hash(DFLOW_FM_ENGINE_ID),
            runtime_mode=runtime_mode,
        )


class ControlRuntimeSelection(StrictControlledModel):
    """Freeze D-RTC/FBC, DIMR, and compiler identities independently of D-Flow FM."""

    runtime_id: Literal["d-rtc/fbc"] = "d-rtc/fbc"
    runtime_version: str = Field(min_length=1, max_length=128)
    coupling_runtime_id: Literal["dimr"] = "dimr"
    coupling_runtime_version: str = Field(min_length=1, max_length=128)
    compiler_id: str = Field(min_length=1, max_length=128)
    compiler_version: str = Field(min_length=1, max_length=128)


class ControlledExecutionSettings(StrictControlledModel):
    """Allow only isolated, cancellable, synthetic numerical development execution."""

    execution_policy: Literal["SYNTHETIC_NUMERICAL_ONLY"] = (
        EvidenceClass.SYNTHETIC_NUMERICAL_ONLY.value
    )
    development_mode: Literal[True] = True
    production_mode: Literal[False] = False
    workspace_isolation: Literal[True] = True
    cancel_enabled: Literal[True] = True
    timeout_seconds: FiniteFloat = Field(gt=0.0)


# Compatibility alias only; the authoritative binding model lives in
# ``model.control.observation_bridge`` and is not duplicated here.
ControlObservationBinding = ObservationBinding


class ControlObservationContract(StrictControlledModel):
    """Freeze the complete whitelist of values the control compiler may observe."""

    schema_version: Literal["dayu.control-observation-contract.v1"] = (
        CONTROL_OBSERVATION_CONTRACT_SCHEMA
    )
    sampling_interval_seconds: FiniteFloat = Field(gt=0.0)
    elapsed_time_enabled: Literal[True] = True
    bindings: tuple[ObservationBinding, ...] = ()

    @model_validator(mode="after")
    def validate_unique_bindings(self) -> Self:
        """Forbid ambiguous duplicate observation keys."""

        keys = [
            (item.observation_type, item.observation_object_id)
            for item in self.bindings
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("control observation bindings must be unique")
        return self


RuntimeComponent = Literal["dflowfm", "dimr", "fbc", "hydrolib-core"]
RuntimeProvenanceField = Literal[
    "version",
    "upstream_tag",
    "upstream_commit",
    "binary_sha256",
    "source_manifest",
    "platform",
    "architecture",
    "build_timestamp",
]
RUNTIME_PROVENANCE_FIELDS: tuple[RuntimeProvenanceField, ...] = (
    "version",
    "upstream_tag",
    "upstream_commit",
    "binary_sha256",
    "source_manifest",
    "platform",
    "architecture",
    "build_timestamp",
)


class RuntimeProvenanceRequirement(StrictControlledModel):
    """Declare the complete runtime identity required before a run may start."""

    component: RuntimeComponent
    required_fields: tuple[RuntimeProvenanceField, ...] = RUNTIME_PROVENANCE_FIELDS

    @field_validator("required_fields")
    @classmethod
    def require_complete_identity(
        cls,
        value: tuple[RuntimeProvenanceField, ...],
    ) -> tuple[RuntimeProvenanceField, ...]:
        """Prevent a development route from weakening runtime provenance."""

        if value != RUNTIME_PROVENANCE_FIELDS:
            raise ValueError("runtime provenance requirements cannot be weakened")
        return value


def default_runtime_provenance_requirements() -> tuple[
    RuntimeProvenanceRequirement, ...
]:
    """Return the four runtime components mandated by the controlled-run task."""

    return tuple(
        RuntimeProvenanceRequirement(component=component)
        for component in ("dflowfm", "dimr", "fbc", "hydrolib-core")
    )


def _set_or_verify_snapshot_hash(
    model: StrictControlledModel,
    *,
    field_name: str,
) -> None:
    """Set an omitted digest once or reject a mismatched supplied digest."""

    expected = hash_snapshot(model.model_dump(mode="json", exclude={field_name}))
    current = getattr(model, field_name)
    if current and current != expected:
        raise ValueError(f"{field_name} does not match the immutable snapshot")
    if not current:
        object.__setattr__(model, field_name, expected)


class DispatchPlanSnapshot(StrictControlledModel):
    """Freeze DispatchPlan v3 control content and every hydraulic binding."""

    schema_version: Literal["dayu.dispatch-plan.v3"] = DISPATCH_PLAN_V3_SCHEMA
    snapshot_hash: str = Field(default="", pattern=_OPTIONAL_SHA256_PATTERN)
    plan_payload_json: str = Field(min_length=2)
    hydraulic_model_snapshot_hash: str = Field(pattern=_SHA256_PATTERN)
    engine_id: Literal["d-flow-fm"] = DFLOW_FM_ENGINE_ID
    engine_version: Literal["DIMRset_2026.02"] = DFLOW_FM_ENGINE_VERSION
    engine_registry_hash: str = Field(pattern=_SHA256_PATTERN)
    control_runtime: Literal["d-rtc/fbc"] = "d-rtc/fbc"
    control_compiler_version: str = Field(min_length=1, max_length=128)
    hydraulic_feedback: Literal[True] = True
    initial_actuator_state: tuple[InitialActuatorState, ...]
    control_observation_contract: ControlObservationContract
    runtime_provenance_requirements: tuple[RuntimeProvenanceRequirement, ...] = Field(
        default_factory=default_runtime_provenance_requirements
    )

    @field_validator("plan_payload_json")
    @classmethod
    def validate_canonical_plan_payload(cls, value: str) -> str:
        """Store the plan body as immutable canonical JSON, never as a mutable dict."""

        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("plan_payload_json must contain valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("plan_payload_json must contain a JSON object")
        if payload.get("schema_version") != DISPATCH_PLAN_V3_SCHEMA:
            raise ValueError("plan_payload_json must declare dayu.dispatch-plan.v3")
        if canonical_json(payload) != value:
            raise ValueError("plan_payload_json must use dayu canonical JSON")
        return value

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        """Require all four provenance components and bind the exact snapshot hash."""

        components = [item.component for item in self.runtime_provenance_requirements]
        if components != ["dflowfm", "dimr", "fbc", "hydrolib-core"]:
            raise ValueError("runtime provenance components must use the frozen order")
        _set_or_verify_snapshot_hash(self, field_name="snapshot_hash")
        return self


class ControlledHydraulic1DRun(StrictControlledModel):
    """Freeze model, DispatchPlan v3, engines, evidence, and execution settings."""

    schema_version: Literal["dayu.controlled-hydraulic-1d.run.v1"] = (
        CONTROLLED_HYDRAULIC_1D_RUN_SCHEMA
    )
    snapshot_hash: str = Field(default="", pattern=_OPTIONAL_SHA256_PATTERN)
    hydraulic_model: Hydraulic1DModel
    hydraulic_model_snapshot_hash: str = Field(pattern=_SHA256_PATTERN)
    dispatch_plan_snapshot: DispatchPlanSnapshot
    engine_selection: EngineSelection
    control_runtime_selection: ControlRuntimeSelection
    evidence_class: Literal["SYNTHETIC_NUMERICAL_ONLY"] = (
        EvidenceClass.SYNTHETIC_NUMERICAL_ONLY.value
    )
    execution_settings: ControlledExecutionSettings
    real_engineering_validation: Literal[False] = False
    real_equipment_command: Literal[False] = False
    plc_scada_connected: Literal[False] = False

    @model_validator(mode="after")
    def validate_bound_snapshots(self) -> Self:
        """Reject drift between the frozen model, plan, engine, and control runtime."""

        model_hash = hash_snapshot(self.hydraulic_model.model_dump(mode="json"))
        if self.hydraulic_model_snapshot_hash != model_hash:
            raise ValueError("hydraulic_model_snapshot_hash does not match the model")
        plan = self.dispatch_plan_snapshot
        engine = self.engine_selection
        control = self.control_runtime_selection
        if plan.hydraulic_model_snapshot_hash != model_hash:
            raise ValueError("DispatchPlan v3 does not bind the hydraulic model")
        if (
            plan.engine_id != engine.engine_id
            or plan.engine_version != engine.engine_version
            or plan.engine_registry_hash != engine.engine_registry_hash
        ):
            raise ValueError("DispatchPlan v3 does not bind the selected engine")
        if (
            plan.control_runtime != control.runtime_id
            or plan.control_compiler_version != control.compiler_version
        ):
            raise ValueError(
                "DispatchPlan v3 does not bind the selected control runtime"
            )
        _set_or_verify_snapshot_hash(self, field_name="snapshot_hash")
        return self


class DispatchTraceRecord(StrictControlledModel):
    """Keep requested, conflict-resolved, and actually applied commands distinct."""

    time_seconds: FiniteFloat = Field(ge=0.0)
    source_type: Literal["initial_state", "manual_schedule", "threshold_rule", "safety"]
    source_id: int | None = None
    structure_type: Literal["gate", "pump"]
    asset_id: int = Field(gt=0)
    hydraulic_structure_id: str = Field(min_length=1, max_length=128)
    command_type: Literal[
        "gate_opening_m",
        "gate_opening_ratio",
        "pump_enabled",
        "pump_unit_count",
        "pump_target_flow",
    ]
    requested_value: FiniteFloat
    resolved_value: FiniteFloat
    applied_value: FiniteFloat
    unit: Literal["m", "ratio", "boolean_0_or_1", "count", "m3/s"]


class ControlledEventRecord(StrictControlledModel):
    """Record deterministic control-runtime outcomes without executable payloads."""

    time_seconds: FiniteFloat = Field(ge=0.0)
    event_type: str = Field(min_length=1, max_length=64)
    outcome: Literal["APPLIED", "REJECTED", "NO_CHANGE", "RESOLVED"]
    reason_code: str = Field(min_length=1, max_length=128)
    structure_type: Literal["gate", "pump"] | None = None
    asset_id: int | None = Field(default=None, gt=0)
    hydraulic_structure_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_optional_structure_identity(self) -> Self:
        """Require all or none of the optional structure identity fields."""

        values = (
            self.structure_type,
            self.asset_id,
            self.hydraulic_structure_id,
        )
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError("control event structure identity must be complete")
        return self


class ControlledStructureResult(StrictControlledModel):
    """Return Gate/Pump hydraulic state separately from the unified H/Q records."""

    time_seconds: FiniteFloat = Field(ge=0.0)
    structure_type: Literal["gate", "pump"]
    asset_id: int = Field(gt=0)
    hydraulic_structure_id: str = Field(min_length=1, max_length=128)
    requested_value: FiniteFloat | None = None
    resolved_value: FiniteFloat | None = None
    applied_value: FiniteFloat | None = None
    upstream_water_level_m: FiniteFloat | None = None
    downstream_water_level_m: FiniteFloat | None = None
    discharge_m3s: FiniteFloat | None = None
    active_unit_count: int | None = Field(default=None, ge=0)


class RuntimeProvenanceRecord(StrictControlledModel):
    """Capture one complete external runtime identity required by the task book."""

    component: RuntimeComponent
    version: str = Field(min_length=1, max_length=128)
    upstream_tag: str = Field(min_length=1, max_length=128)
    upstream_commit: str = Field(pattern=_GIT_COMMIT_PATTERN)
    binary_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_manifest: str = Field(min_length=1, max_length=512)
    platform: str = Field(min_length=1, max_length=128)
    architecture: str = Field(min_length=1, max_length=64)
    build_timestamp: datetime

    @field_validator("build_timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Require an unambiguous build instant in every runtime record."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("build_timestamp must include a timezone")
        return value


class SyntheticBenchmarkEvidence(StrictControlledModel):
    """Reference synthetic numerical evidence without claiming engineering validity."""

    benchmark_id: str = Field(min_length=1, max_length=64)
    status: Literal["PASS", "FAIL", "SKIPPED"]
    artifact_sha256: str = Field(pattern=_SHA256_PATTERN)
    metrics_json: str = Field(default="{}", min_length=2)

    @field_validator("metrics_json")
    @classmethod
    def validate_metrics_json(cls, value: str) -> str:
        """Require immutable canonical JSON for benchmark metrics."""

        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("metrics_json must contain valid JSON") from exc
        if not isinstance(payload, dict) or canonical_json(payload) != value:
            raise ValueError("metrics_json must contain a canonical JSON object")
        return value


class ControlledHydraulicResult(StrictControlledModel):
    """Compose H/Q, dispatch, structures, provenance, and synthetic evidence."""

    schema_version: Literal["dayu.controlled-hydraulic-result.v1"] = (
        CONTROLLED_HYDRAULIC_RESULT_SCHEMA
    )
    result_hash: str = Field(default="", pattern=_OPTIONAL_SHA256_PATTERN)
    run_snapshot_hash: str = Field(pattern=_SHA256_PATTERN)
    evidence_class: Literal["SYNTHETIC_NUMERICAL_ONLY"] = (
        EvidenceClass.SYNTHETIC_NUMERICAL_ONLY.value
    )
    hydraulic_result: HydraulicResult
    dispatch_trace: tuple[DispatchTraceRecord, ...]
    control_events: tuple[ControlledEventRecord, ...]
    structure_results: tuple[ControlledStructureResult, ...]
    runtime_provenance: tuple[RuntimeProvenanceRecord, ...] = Field(min_length=4)
    synthetic_benchmark_evidence: tuple[SyntheticBenchmarkEvidence, ...] = ()
    real_engineering_validation: Literal[False] = False
    real_equipment_command: Literal[False] = False
    plc_scada_connected: Literal[False] = False

    @model_validator(mode="after")
    def validate_result_identity(self) -> Self:
        """Require D-Flow result identity and the complete four-component provenance."""

        if (
            self.hydraulic_result.engine != DFLOW_FM_ENGINE_ID
            or self.hydraulic_result.engine_version != DFLOW_FM_ENGINE_VERSION
        ):
            raise ValueError(
                "controlled hydraulic result must come from pinned D-Flow FM"
            )
        components = [item.component for item in self.runtime_provenance]
        if components != ["dflowfm", "dimr", "fbc", "hydrolib-core"]:
            raise ValueError(
                "runtime provenance must contain the frozen four components"
            )
        _set_or_verify_snapshot_hash(self, field_name="result_hash")
        return self


class CompiledControlArtifact(StrictControlledModel):
    """Bind one compiler output to its job-relative path and digest."""

    artifact_type: str = Field(min_length=1, max_length=64)
    relative_path: str = Field(min_length=1, max_length=512)
    sha256: str = Field(pattern=_SHA256_PATTERN)


class CompiledControl(StrictControlledModel):
    """Return a frozen compiler manifest rather than mutable runtime files."""

    schema_version: Literal["dayu.compiled-control.v1"] = COMPILED_CONTROL_SCHEMA
    compiler_id: str = Field(min_length=1, max_length=128)
    compiler_version: str = Field(min_length=1, max_length=128)
    dispatch_plan_snapshot_hash: str = Field(pattern=_SHA256_PATTERN)
    artifacts: tuple[CompiledControlArtifact, ...] = Field(min_length=1)


class ControlledHydraulic1DEngine(Hydraulic1DEngine, ABC):
    """Extend the ordinary engine boundary without changing MASCARET's interface."""

    @abstractmethod
    def validate_controlled_model(self, run: ControlledHydraulic1DRun) -> None:
        """Fail closed before compilation when a controlled model is unsupported."""

    @abstractmethod
    def compile_control(
        self,
        run: ControlledHydraulic1DRun,
        workspace: Path,
    ) -> CompiledControl:
        """Compile a frozen plan into job-local runtime artifacts."""

    @abstractmethod
    def run_controlled(
        self,
        run: ControlledHydraulic1DRun,
        context: Hydraulic1DExecutionContext,
    ) -> ControlledHydraulicResult:
        """Execute one isolated coupled run and return only the controlled contract."""

    @abstractmethod
    def parse_controlled_results(
        self,
        run: ControlledHydraulic1DRun,
        workspace: Path,
    ) -> ControlledHydraulicResult:
        """Parse job-local external outputs without exposing native files as the API."""
