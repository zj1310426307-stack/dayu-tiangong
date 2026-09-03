"""Compile Dayu manual schedules after the shared actuator constraint layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from model.control.replay import ReplayAsset, ReplayObservationFrame, replay_schedule
from model.control.schedule import ScheduledAction
from model.provenance import snapshot_hash


HYDRAULIC_CONTROL_COMPILER_VERSION = "dayu.hydraulic-control-compiler.v1"


class InitialActuatorState(BaseModel):
    """Freeze an explicit hydraulic-preview actuator state and its duration clocks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    structure_type: Literal["gate", "pump"]
    structure_id: int = Field(gt=0)
    gate_opening_m: FiniteFloat | None = Field(default=None, ge=0)
    pump_enabled: bool | None = None
    running_units: int | None = Field(default=None, ge=0)
    runtime_seconds: FiniteFloat = Field(default=0, ge=0)
    stop_seconds: FiniteFloat = Field(default=0, ge=0)
    control_state: dict[str, str | int | float | bool] = Field(default_factory=dict)
    evidence: Literal["SOURCE_DATA", "SYNTHETIC_INITIAL_STATE"]

    @model_validator(mode="after")
    def validate_kind(self) -> "InitialActuatorState":
        """Require exactly the state fields that belong to the actuator type."""

        if self.structure_type == "gate":
            if self.gate_opening_m is None:
                raise ValueError("gate initial state requires gate_opening_m")
            if self.pump_enabled is not None or self.running_units is not None:
                raise ValueError("gate initial state must not define pump fields")
            if self.runtime_seconds or self.stop_seconds:
                raise ValueError(
                    "gate initial state must not define pump duration clocks"
                )
            return self
        if self.pump_enabled is None or self.running_units is None:
            raise ValueError("pump initial state requires enabled and running_units")
        if self.pump_enabled != (self.running_units > 0):
            raise ValueError("pump enabled and running_units are inconsistent")
        if self.gate_opening_m is not None:
            raise ValueError("pump initial state must not define gate_opening_m")
        if self.running_units > 0 and self.stop_seconds > 0:
            raise ValueError("running pump must have zero stop_seconds")
        if self.running_units == 0 and self.runtime_seconds > 0:
            raise ValueError("stopped pump must have zero runtime_seconds")
        return self


class ActuatorControlBinding(BaseModel):
    """Bind a Dayu command to one exact D-Flow BMI control variable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    structure_type: Literal["gate", "pump"]
    structure_id: int = Field(gt=0)
    native_structure_id: str = Field(min_length=1, max_length=255)
    supported_command_type: Literal[
        "gate_opening_m", "gate_opening_ratio", "pump_target_flow"
    ]
    bmi_variable: str = Field(min_length=1, max_length=512)
    conversion: Literal["gate_lower_edge_level", "identity_capacity"]
    reference_level_m: FiniteFloat | None = None
    gate_height_m: FiniteFloat | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_conversion(self) -> "ActuatorControlBinding":
        """Close command, variable, and unit conversions before compilation."""

        if self.structure_type == "gate":
            if (
                self.conversion != "gate_lower_edge_level"
                or self.reference_level_m is None
            ):
                raise ValueError("gate binding requires a lower-edge datum")
            if not self.bmi_variable.endswith("/gateLowerEdgeLevel"):
                raise ValueError("gate binding must target gateLowerEdgeLevel")
            if (
                self.supported_command_type == "gate_opening_ratio"
                and self.gate_height_m is None
            ):
                raise ValueError("gate opening ratio requires explicit gate height")
        else:
            if self.conversion != "identity_capacity":
                raise ValueError("pump binding requires identity capacity conversion")
            if self.reference_level_m is not None or self.gate_height_m is not None:
                raise ValueError("pump binding must not define gate geometry")
            if self.bmi_variable != f"pumps/{self.native_structure_id}/capacity":
                raise ValueError(
                    "pump binding must target the pinned capacity BMI variable"
                )
        return self


class CompiledControlCommand(BaseModel):
    """Keep requested, constraint-resolved, and native target values distinct."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    time_seconds: FiniteFloat = Field(ge=0)
    structure_type: Literal["gate", "pump"]
    structure_id: int = Field(gt=0)
    command_type: str
    requested_value: FiniteFloat
    resolved_value: FiniteFloat
    native_target_value: FiniteFloat
    bmi_variable: str
    source_type: Literal["manual", "rule"]
    source_id: int | None
    constraint_outcome: Literal["selected", "limited", "rejected"]
    constraint_reason: str | None = None


class ControlCompileIssue(BaseModel):
    """Return one stable, actionable compile blocker or warning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    structure_type: Literal["gate", "pump"] | None = None
    structure_id: int | None = None
    source_id: int | None = None


class HydraulicControlCompileReport(BaseModel):
    """Return deterministic commands or explicit unsupported semantics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    compiler_version: Literal[HYDRAULIC_CONTROL_COMPILER_VERSION] = (
        HYDRAULIC_CONTROL_COMPILER_VERSION
    )
    status: Literal["COMPILED", "UNSUPPORTED"]
    commands: tuple[CompiledControlCommand, ...] = ()
    issues: tuple[ControlCompileIssue, ...] = ()
    artifact_hash: str


class HydraulicControlCompiler:
    """Compile manual commands without duplicating the shared constraint rules."""

    def compile(
        self,
        *,
        actions: tuple[ScheduledAction, ...],
        assets: tuple[ReplayAsset, ...],
        initial_states: tuple[InitialActuatorState, ...],
        bindings: tuple[ActuatorControlBinding, ...],
        duration_seconds: float,
    ) -> HydraulicControlCompileReport:
        """Resolve a manual schedule and map only exact D-Flow control variables."""

        asset_map = {(item.structure_type, item.structure_id): item for item in assets}
        state_map = {
            (item.structure_type, item.structure_id): item for item in initial_states
        }
        binding_map = {
            (item.structure_type, item.structure_id, item.supported_command_type): item
            for item in bindings
        }
        issues: list[ControlCompileIssue] = []
        if len(asset_map) != len(assets):
            issues.append(
                ControlCompileIssue(
                    code="CONTROL_ASSET_DUPLICATE",
                    message="each actuator requires one frozen constraint record",
                )
            )
        if len(state_map) != len(initial_states):
            issues.append(
                ControlCompileIssue(
                    code="INITIAL_ACTUATOR_STATE_DUPLICATE",
                    message="each actuator requires one immutable initial state",
                )
            )
        extra_states = set(state_map) - set(asset_map)
        for key in sorted(extra_states):
            issues.append(
                ControlCompileIssue(
                    code="INITIAL_ACTUATOR_STATE_UNKNOWN",
                    message="initial state references an actuator absent from the snapshot",
                    structure_type=key[0],
                    structure_id=key[1],
                )
            )
        if len(binding_map) != len(bindings):
            issues.append(
                ControlCompileIssue(
                    code="CONTROL_BINDING_DUPLICATE",
                    message="each actuator command requires one exact native binding",
                )
            )
        prepared_assets: list[ReplayAsset] = []
        for key, asset in asset_map.items():
            state = state_map.get(key)
            if state is None:
                issues.append(
                    ControlCompileIssue(
                        code="INITIAL_ACTUATOR_STATE_MISSING",
                        message="hydraulic control cannot assume closed/stopped state",
                        structure_type=key[0],
                        structure_id=key[1],
                    )
                )
                continue
            constraints = dict(asset.constraints)
            constraints["initial_state_explicit"] = True
            if key[0] == "gate":
                constraints["initial_opening_m"] = state.gate_opening_m
            else:
                constraints.update(
                    initial_running_units=state.running_units,
                    initial_runtime_seconds=state.runtime_seconds,
                    initial_stop_seconds=state.stop_seconds,
                    initial_stop_constraint_satisfied=(state.stop_seconds > 0),
                )
            prepared_assets.append(ReplayAsset(key[0], key[1], constraints))
        action_keys = {(item.structure_type, item.structure_id) for item in actions}
        unknown_assets = action_keys - set(asset_map)
        for key in sorted(unknown_assets):
            issues.append(
                ControlCompileIssue(
                    code="CONTROL_ASSET_MISSING",
                    message="manual action references an actuator absent from the snapshot",
                    structure_type=key[0],
                    structure_id=key[1],
                )
            )
        if duration_seconds <= 0:
            issues.append(
                ControlCompileIssue(
                    code="CONTROL_DURATION_INVALID",
                    message="duration_seconds must be positive",
                )
            )
        outside_actions = [
            item
            for item in actions
            if item.time_seconds < 0 or item.time_seconds > duration_seconds
        ]
        if outside_actions:
            issues.append(
                ControlCompileIssue(
                    code="CONTROL_ACTION_OUTSIDE_DURATION",
                    message="manual schedule contains an action outside the run duration",
                    source_id=outside_actions[0].id,
                )
            )
        if issues:
            return self._report((), issues)
        timeline = sorted(
            {0.0, float(duration_seconds), *(float(a.time_seconds) for a in actions)}
        )
        replay = replay_schedule(
            actions=actions,
            rules=(),
            assets=tuple(prepared_assets),
            observations=tuple(ReplayObservationFrame(value, {}) for value in timeline),
        )
        commands: list[CompiledControlCommand] = []
        for step in replay["steps"]:
            for target in step["targets"]:
                key = (
                    str(target["structure_type"]),
                    int(target["structure_id"]),
                    str(target["command_type"]),
                )
                binding = binding_map.get(key)
                if binding is None:
                    issues.append(
                        ControlCompileIssue(
                            code="HYDRAULIC_COMMAND_SEMANTICS_UNSUPPORTED",
                            message=(
                                f"{key[2]} has no exact D-Flow control binding; "
                                "pump unit-count/enabled commands are not capacity"
                            ),
                            structure_type=key[0],
                            structure_id=key[1],
                            source_id=target["source_id"],
                        )
                    )
                    continue
                resolved = target["resolved_value"]
                if resolved is None:
                    issues.append(
                        ControlCompileIssue(
                            code="CONTROL_CONSTRAINT_REJECTED",
                            message=str(target["reason"] or "control target rejected"),
                            structure_type=key[0],
                            structure_id=key[1],
                            source_id=target["source_id"],
                        )
                    )
                    continue
                native_value = float(resolved)
                if binding.conversion == "gate_lower_edge_level":
                    opening_m = native_value
                    if key[2] == "gate_opening_ratio":
                        opening_m *= float(binding.gate_height_m)
                    native_value = float(binding.reference_level_m) + opening_m
                commands.append(
                    CompiledControlCommand(
                        time_seconds=float(step["time_seconds"]),
                        structure_type=key[0],
                        structure_id=key[1],
                        command_type=key[2],
                        requested_value=float(target["requested_value"]),
                        resolved_value=float(resolved),
                        native_target_value=native_value,
                        bmi_variable=binding.bmi_variable,
                        source_type=str(target["source_type"]),
                        source_id=target["source_id"],
                        constraint_outcome=str(target["outcome"]),
                        constraint_reason=target["reason"],
                    )
                )
        return self._report(tuple(commands), issues)

    @staticmethod
    def _report(
        commands: tuple[CompiledControlCommand, ...],
        issues: list[ControlCompileIssue],
    ) -> HydraulicControlCompileReport:
        payload = {
            "compiler_version": HYDRAULIC_CONTROL_COMPILER_VERSION,
            "status": "UNSUPPORTED" if issues else "COMPILED",
            "commands": [item.model_dump(mode="json") for item in commands],
            "issues": [item.model_dump(mode="json") for item in issues],
        }
        return HydraulicControlCompileReport(
            **payload,
            artifact_hash=snapshot_hash(payload),
        )
