"""HTTP contracts for the isolated synthetic hydraulic dispatch workflow."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from model.control.compiler import (
    HydraulicControlCompileReport,
    InitialActuatorState,
)
from model.control.drtc import DRTCCompileReport
from model.control.observation_bridge import ObservationBinding


class HydraulicPlanCompileRequest(BaseModel):
    """Supply only explicit initial state, observation, and execution contracts."""

    model_config = ConfigDict(extra="forbid")

    initial_actuator_state: tuple[InitialActuatorState, ...]
    observation_bindings: tuple[ObservationBinding, ...] = ()
    observation_sampling_interval_seconds: FiniteFloat = Field(gt=0)
    runtime_mode: Literal["external", "container"] = "container"
    timeout_seconds: FiniteFloat = Field(default=3600.0, gt=0, le=86_400)
    synthetic_fixture: Literal[True] = True

    @model_validator(mode="after")
    def validate_unique_state_and_observations(self) -> "HydraulicPlanCompileRequest":
        """Reject ambiguous duplicate state or observation identities."""

        state_keys = [
            (item.structure_type, item.structure_id) for item in self.initial_actuator_state
        ]
        if len(state_keys) != len(set(state_keys)):
            raise ValueError("initial actuator states must be unique")
        observation_keys = [
            (item.observation_type, item.observation_object_id)
            for item in self.observation_bindings
        ]
        if len(observation_keys) != len(set(observation_keys)):
            raise ValueError("observation bindings must be unique")
        return self


class HydraulicCompileIssue(BaseModel):
    """Return one stable mapping, compiler, model, or runtime diagnostic."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: Literal[
        "plan",
        "hydraulic_model",
        "capability",
        "asset_mapping",
        "gate_mapping",
        "pump_mapping",
        "manual_control",
        "drtc",
        "observation",
        "runtime",
    ]
    code: str
    message: str
    field_path: str | None = None
    structure_type: Literal["gate", "pump"] | None = None
    structure_id: int | None = None


class HydraulicPlanCompileReport(BaseModel):
    """Separate freeze readiness from external runtime availability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: int
    snapshot_target: Literal["hydraulic_v3"] = "hydraulic_v3"
    target_schema_version: Literal["dayu.dispatch-plan.v3"] = "dayu.dispatch-plan.v3"
    evidence_class: Literal["SYNTHETIC_NUMERICAL_ONLY"] = "SYNTHETIC_NUMERICAL_ONLY"
    engine_id: Literal["d-flow-fm"] = "d-flow-fm"
    engine_version: Literal["DIMRset_2026.02"] = "DIMRset_2026.02"
    control_runtime: Literal["d-rtc/fbc"] = "d-rtc/fbc"
    plan_valid: bool
    hydraulic_model_valid: bool
    capability_valid: bool
    structure_mapping_valid: bool
    manual_control_valid: bool
    drtc_valid: bool
    observation_contract_valid: bool
    ready_to_freeze: bool
    runtime_available: bool
    controlled_runtime_accepted: bool
    ready_to_run: bool
    runtime_detail: str
    runtime_provenance: dict[str, Any] | None = None
    capabilities: tuple[dict[str, Any], ...] = ()
    hydraulic_model_snapshot_hash: str | None = None
    manual_control_report: HydraulicControlCompileReport | None = None
    drtc_compile_report: DRTCCompileReport | None = None
    issues: tuple[HydraulicCompileIssue, ...] = ()
    warnings: tuple[HydraulicCompileIssue, ...] = ()
    report_hash: str
    real_engineering_validation: Literal[False] = False
    real_equipment_command: Literal[False] = False
    plc_scada_connected: Literal[False] = False


class HydraulicPlanFreezeResponse(BaseModel):
    """Return immutable v3 identity without exposing generated native files."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: int
    status: Literal["frozen"] = "frozen"
    schema_version: Literal["dayu.dispatch-plan.v3"] = "dayu.dispatch-plan.v3"
    snapshot_hash: str
    hydraulic_model_snapshot_hash: str
    control_contract_hash: str
    evidence_class: Literal["SYNTHETIC_NUMERICAL_ONLY"] = "SYNTHETIC_NUMERICAL_ONLY"
    runtime_available: bool
    real_engineering_validation: Literal[False] = False
    real_equipment_command: Literal[False] = False
    plc_scada_connected: Literal[False] = False


class HydraulicPreviewJobRecord(BaseModel):
    """Expose the existing job lifecycle through the development-only endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: int
    run_id: int
    evidence_class: Literal["SYNTHETIC_NUMERICAL_ONLY"] = "SYNTHETIC_NUMERICAL_ONLY"
    engine: Literal["d-flow-fm"] = "d-flow-fm"
    control_runtime: Literal["d-rtc/fbc"] = "d-rtc/fbc"
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
    real_engineering_validation: Literal[False] = False
    real_equipment_command: Literal[False] = False
    plc_scada_connected: Literal[False] = False
