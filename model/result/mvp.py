"""Independent result DTO for the direct Saint-Venant MVP path."""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_serializer,
    model_validator,
)


HYDRAULIC_RESULT_MVP = "dayu.hydraulic-result.mvp"


def _finite_number(value: Any) -> float:
    """Accept JSON numbers and reject coercion, booleans, NaN, and infinity."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("value must be a JSON number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("value must be finite")
    return number


FiniteNumber = Annotated[float, BeforeValidator(_finite_number)]
PositiveFinite = Annotated[FiniteNumber, Field(gt=0.0)]
NonNegativeFinite = Annotated[FiniteNumber, Field(ge=0.0)]
PositiveId = Annotated[int, Field(strict=True, gt=0)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
Sha256 = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
NonBlankText = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, pattern=r".*\S.*"),
]


class StrictResultModel(BaseModel):
    """Keep every MVP result object immutable and closed to extra keys."""

    # JSON arrays become tuples; all scalar aliases independently reject
    # booleans, strings-as-numbers, non-finite values, and invalid identities.
    model_config = ConfigDict(extra="forbid", frozen=True)


class MvpSectionSeries(StrictResultModel):
    """Store aligned water-level, discharge, and velocity arrays for one section."""

    section_id: PositiveId
    section_code: NonBlankText
    time: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    water_level: tuple[FiniteNumber, ...] = Field(min_length=2)
    flow: tuple[FiniteNumber, ...] = Field(min_length=2)
    velocity: tuple[FiniteNumber, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_alignment(self) -> Self:
        """Require one finite hydraulic sample per strictly increasing output time."""

        _validate_aligned_series(
            self.time,
            (self.water_level, self.flow, self.velocity),
            "section",
        )
        return self


class MvpGateSeries(StrictResultModel):
    """Store the accepted actual opening and coupled Gate flow at output times."""

    gate_id: PositiveId
    time: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    opening: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    flow: tuple[FiniteNumber, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_alignment(self) -> Self:
        """Require Gate opening and flow arrays to align with their own time axis."""

        _validate_aligned_series(self.time, (self.opening, self.flow), "Gate")
        if any(
            opening == 0.0 and flow != 0.0
            for opening, flow in zip(self.opening, self.flow)
        ):
            raise ValueError("Gate result flow must be zero while opening is zero")
        return self


class MvpPumpSeries(StrictResultModel):
    """Store the accepted actual Pump state and external flow at output times."""

    pump_id: PositiveId
    time: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    status: tuple[Literal["on", "off"], ...] = Field(min_length=2)
    flow: tuple[NonNegativeFinite, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_alignment(self) -> Self:
        """Require Pump state and flow arrays to align with their own time axis."""

        _validate_aligned_series(self.time, (self.status, self.flow), "Pump")
        for status, flow in zip(self.status, self.flow):
            if status == "off" and flow != 0.0:
                raise ValueError("Pump result flow must be zero while status is off")
            if status == "on" and flow <= 0.0:
                raise ValueError("Pump result flow must be positive while status is on")
        on_flows = {
            flow for status, flow in zip(self.status, self.flow) if status == "on"
        }
        if len(on_flows) > 1:
            raise ValueError("Pump design flow must remain constant while status is on")
        return self


class MvpControlEvent(StrictResultModel):
    """Expose one accepted-state threshold action independently of device state."""

    time: NonNegativeFinite
    structure_id: PositiveId
    structure_type: Literal["gate", "pump"]
    action: Literal["open", "start"]
    threshold_water_level: FiniteNumber
    observed_water_level: FiniteNumber

    @model_validator(mode="after")
    def validate_causal_action(self) -> Self:
        """Require a strict crossing and the action defined for that device type."""

        if self.observed_water_level <= self.threshold_water_level:
            raise ValueError("control event observed level must exceed its threshold")
        if (self.structure_type, self.action) not in {
            ("gate", "open"),
            ("pump", "start"),
        }:
            raise ValueError("control event action does not match structure_type")
        return self


def _validate_aligned_series(
    times: tuple[float, ...], arrays: tuple[tuple[Any, ...], ...], label: str
) -> None:
    """Validate ordering and equal lengths for one result time-series family."""

    if any(right <= left for left, right in zip(times, times[1:])):
        raise ValueError(f"{label} result times must be strictly increasing")
    if any(len(values) != len(times) for values in arrays):
        raise ValueError(f"{label} result arrays must align with time")


class MvpWaterBalance(StrictResultModel):
    """Record the complete single-Branch storage and external-volume balance."""

    initial_storage: NonNegativeFinite
    final_storage: NonNegativeFinite
    upstream_boundary_volume: FiniteNumber
    downstream_boundary_volume: FiniteNumber
    pump_outflow_volume: NonNegativeFinite
    water_balance_residual: FiniteNumber
    relative_water_balance_error: NonNegativeFinite
    tolerance: Annotated[FiniteNumber, Field(gt=0.0, le=0.01)]
    status: Literal["pass", "fail"]

    @model_validator(mode="after")
    def validate_balance_semantics(self) -> Self:
        """Verify residual, normalization, and pass/fail semantics are self-consistent."""

        storage_change = self.final_storage - self.initial_storage
        expected_change = (
            self.upstream_boundary_volume
            - self.downstream_boundary_volume
            - self.pump_outflow_volume
        )
        expected_residual = storage_change - expected_change
        scale = max(
            abs(self.initial_storage),
            abs(storage_change),
            abs(self.upstream_boundary_volume)
            + abs(self.downstream_boundary_volume)
            + abs(self.pump_outflow_volume),
            1.0,
        )
        expected_relative = abs(expected_residual) / scale
        residual_tolerance = 1.0e-10 * scale
        if not math.isclose(
            self.water_balance_residual,
            expected_residual,
            rel_tol=1.0e-10,
            abs_tol=residual_tolerance,
        ):
            raise ValueError("water_balance_residual is inconsistent with storage and fluxes")
        if not math.isclose(
            self.relative_water_balance_error,
            expected_relative,
            rel_tol=1.0e-10,
            abs_tol=1.0e-12,
        ):
            raise ValueError("relative_water_balance_error uses an unknown normalization")
        expected_status = (
            "pass" if self.relative_water_balance_error < self.tolerance else "fail"
        )
        if self.status != expected_status:
            raise ValueError("water balance status is inconsistent with tolerance")
        return self


class MvpDiagnostics(StrictResultModel):
    """Expose the mandatory CFL, step, retry, and diagnostic-flag evidence."""

    maximum_cfl: NonNegativeFinite
    minimum_dt: PositiveFinite
    retry_count: NonNegativeInt
    step_count: PositiveInt
    diagnostic_flags: tuple[NonBlankText, ...]

    @model_validator(mode="after")
    def validate_flags(self) -> Self:
        """Reject duplicate flags so diagnostics remain deterministic."""

        if len(self.diagnostic_flags) != len(set(self.diagnostic_flags)):
            raise ValueError("diagnostic_flags must be unique")
        return self


class MvpResultProvenance(StrictResultModel):
    """Link one result to its frozen input, mesh, engine, and solver identity."""

    input_schema_version: Literal["dayu.model-input.v4-lite"]
    input_snapshot_hash: Sha256
    mesh_hash: Sha256
    solver_type: Literal["saint-venant"]
    scheme: Literal["finite-volume-hll"]
    time_integrator: Literal["ssp-rk2"]
    engine_version: NonBlankText
    engine_commit: NonBlankText
    validation_policy_version: Literal["v4-lite-1", "v4-lite-2"]
    solver_policy_hash: Sha256 | None = None

    @model_validator(mode="after")
    def validate_versioned_solver_policy(self) -> Self:
        """Require execution-policy evidence only for the versioned v2 route."""

        if self.validation_policy_version == "v4-lite-1":
            if "solver_policy_hash" in self.model_fields_set:
                raise ValueError("v4-lite-1 result must not add solver_policy_hash")
        elif self.solver_policy_hash is None:
            raise ValueError("v4-lite-2 result requires solver_policy_hash")
        return self

    @model_serializer(mode="wrap")
    def serialize_versioned_policy(self, handler: Any) -> dict[str, Any]:
        """Keep the v1 wire shape free of the v2-only policy field."""

        payload = handler(self)
        if self.validation_policy_version == "v4-lite-1":
            payload.pop("solver_policy_hash", None)
        return payload


class MvpHydraulicResult(StrictResultModel):
    """Canonical ``dayu.hydraulic-result.mvp`` DTO, independent of EngineResult."""

    schema_version: Literal["dayu.hydraulic-result.mvp"]
    sections: tuple[MvpSectionSeries, ...] = Field(min_length=3)
    gates: tuple[MvpGateSeries, ...] = Field(max_length=1)
    pumps: tuple[MvpPumpSeries, ...] = Field(max_length=1)
    control_events: tuple[MvpControlEvent, ...] = ()
    water_balance: MvpWaterBalance
    diagnostics: MvpDiagnostics
    provenance: MvpResultProvenance

    @model_validator(mode="after")
    def validate_result_identity_and_time(self) -> Self:
        """Require unique identities and one common section output time axis."""

        _require_unique((item.section_id for item in self.sections), "section_id")
        _require_unique((item.section_code for item in self.sections), "section_code")
        _require_unique((item.gate_id for item in self.gates), "gate_id")
        _require_unique((item.pump_id for item in self.pumps), "pump_id")
        expected_time = self.sections[0].time
        if any(item.time != expected_time for item in self.sections[1:]):
            raise ValueError("all section results must use the same output time axis")
        if any(item.time != expected_time for item in (*self.gates, *self.pumps)):
            raise ValueError(
                "all Gate and Pump results must use the common section output time axis"
            )
        event_times = tuple(item.time for item in self.control_events)
        if any(right < left for left, right in zip(event_times, event_times[1:])):
            raise ValueError("control events must be ordered by accepted-state time")
        if any(
            item.time < expected_time[0] or item.time > expected_time[-1]
            for item in self.control_events
        ):
            raise ValueError("control event time lies outside the result interval")
        event_keys = tuple(
            (item.structure_type, item.structure_id) for item in self.control_events
        )
        _require_unique(event_keys, "one-shot control event structure identity")
        event_key_set = set(event_keys)
        gate_ids = {item.gate_id for item in self.gates}
        pump_ids = {item.pump_id for item in self.pumps}
        for event in self.control_events:
            known_ids = gate_ids if event.structure_type == "gate" else pump_ids
            if event.structure_id not in known_ids:
                raise ValueError("control event references an unknown result structure")
            if event.structure_type == "gate":
                series = next(
                    item for item in self.gates if item.gate_id == event.structure_id
                )
                before = tuple(
                    opening
                    for time, opening in zip(series.time, series.opening)
                    if time < event.time
                )
                after = tuple(
                    opening
                    for time, opening in zip(series.time, series.opening)
                    if time >= event.time
                )
                if any(opening != 0.0 for opening in before) or any(
                    opening <= 0.0 for opening in after
                ):
                    raise ValueError("Gate event contradicts its accepted opening series")
                if len(set(after)) != 1:
                    raise ValueError("Gate target opening changes after its one-shot event")
            else:
                series = next(
                    item for item in self.pumps if item.pump_id == event.structure_id
                )
                before = tuple(
                    status
                    for time, status in zip(series.time, series.status)
                    if time < event.time
                )
                after = tuple(
                    status
                    for time, status in zip(series.time, series.status)
                    if time >= event.time
                )
                if any(status != "off" for status in before) or any(
                    status != "on" for status in after
                ):
                    raise ValueError("Pump event contradicts its accepted status series")
        for gate in self.gates:
            if ("gate", gate.gate_id) not in event_key_set and len(
                set(gate.opening)
            ) != 1:
                raise ValueError("Gate opening changes without a control event")
        for pump in self.pumps:
            if ("pump", pump.pump_id) not in event_key_set and len(
                set(pump.status)
            ) != 1:
                raise ValueError("Pump status changes without a control event")
        return self

    def to_dict(self) -> dict[str, Any]:
        """Return JSON while preserving the pre-control fixed-result shape."""

        payload = self.model_dump(mode="json")
        if not self.control_events:
            payload.pop("control_events")
        if self.provenance.solver_policy_hash is None:
            payload["provenance"].pop("solver_policy_hash", None)
        return payload


def _require_unique(values: Any, label: str) -> None:
    """Reject duplicate identities in a one-pass iterable."""

    materialized = tuple(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"{label} values must be unique")


__all__ = [
    "HYDRAULIC_RESULT_MVP",
    "MvpControlEvent",
    "MvpDiagnostics",
    "MvpGateSeries",
    "MvpHydraulicResult",
    "MvpPumpSeries",
    "MvpResultProvenance",
    "MvpSectionSeries",
    "MvpWaterBalance",
]
