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
    """Store the fixed opening and coupled Gate flow at each reported time."""

    gate_id: PositiveId
    time: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    opening: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    flow: tuple[FiniteNumber, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_alignment(self) -> Self:
        """Require Gate opening and flow arrays to align with their own time axis."""

        _validate_aligned_series(self.time, (self.opening, self.flow), "Gate")
        return self


class MvpPumpSeries(StrictResultModel):
    """Store ON/OFF state and external Pump flow at each reported time."""

    pump_id: PositiveId
    time: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    status: tuple[Literal["on", "off"], ...] = Field(min_length=2)
    flow: tuple[NonNegativeFinite, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_alignment(self) -> Self:
        """Require Pump state and flow arrays to align with their own time axis."""

        _validate_aligned_series(self.time, (self.status, self.flow), "Pump")
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
    validation_policy_version: Literal["v4-lite-1"]


class MvpHydraulicResult(StrictResultModel):
    """Canonical ``dayu.hydraulic-result.mvp`` DTO, independent of EngineResult."""

    schema_version: Literal["dayu.hydraulic-result.mvp"]
    sections: tuple[MvpSectionSeries, ...] = Field(min_length=3)
    gates: tuple[MvpGateSeries, ...] = Field(max_length=1)
    pumps: tuple[MvpPumpSeries, ...] = Field(max_length=1)
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
        return self

    def to_dict(self) -> dict[str, Any]:
        """Return the stable JSON-ready MVP result without legacy projection."""

        return self.model_dump(mode="json")


def _require_unique(values: Any, label: str) -> None:
    """Reject duplicate identities in a one-pass iterable."""

    materialized = tuple(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"{label} values must be unique")


__all__ = [
    "HYDRAULIC_RESULT_MVP",
    "MvpDiagnostics",
    "MvpGateSeries",
    "MvpHydraulicResult",
    "MvpPumpSeries",
    "MvpResultProvenance",
    "MvpSectionSeries",
    "MvpWaterBalance",
]
