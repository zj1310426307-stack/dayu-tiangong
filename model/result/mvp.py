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


def _time_tolerance(*values: float) -> float:
    """Return an absolute tolerance scaled to long-duration float clocks."""

    return max(1.0e-12, *(8.0 * math.ulp(abs(value)) for value in values))


class MvpSectionSeries(StrictResultModel):
    """Store aligned water-level, discharge, and velocity arrays for one section."""

    section_id: PositiveId
    section_code: NonBlankText
    time: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    water_level: tuple[FiniteNumber, ...] = Field(min_length=2)
    flow: tuple[FiniteNumber, ...] = Field(min_length=2)
    velocity: tuple[FiniteNumber, ...] = Field(min_length=2)
    volume_m3: tuple[NonNegativeFinite, ...] | None = None

    @model_validator(mode="after")
    def validate_alignment(self) -> Self:
        """Require one finite hydraulic sample per strictly increasing output time."""

        arrays = (self.water_level, self.flow, self.velocity)
        if self.volume_m3 is not None:
            arrays = (*arrays, self.volume_m3)
        _validate_aligned_series(self.time, arrays, "section")
        return self

    @model_serializer(mode="wrap")
    def serialize_optional_volume(self, handler: Any) -> dict[str, Any]:
        """Keep pre-D1 section result bytes free of the new volume field."""

        payload = handler(self)
        if self.volume_m3 is None:
            payload.pop("volume_m3", None)
        return payload


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


class MvpGateStageEvidence(StrictResultModel):
    """Persist one RK-stage completed-interface Gate closure."""

    step_index: PositiveInt
    rk_stage: Literal[1, 2]
    evaluation_time: NonNegativeFinite
    step_dt: PositiveFinite
    flow: PositiveFinite
    upstream_stage: FiniteNumber
    downstream_stage: FiniteNumber
    upstream_area: PositiveFinite
    downstream_area: PositiveFinite
    upstream_top_width: PositiveFinite
    downstream_top_width: PositiveFinite
    upstream_pressure_moment: NonNegativeFinite
    downstream_pressure_moment: NonNegativeFinite
    head_loss: PositiveFinite
    energy_residual: FiniteNumber
    iterations: PositiveInt
    momentum_flux_left: FiniteNumber
    momentum_flux_right: FiniteNumber
    reaction_force_per_density: FiniteNumber
    regime: Literal["submerged_orifice_completed_interface"]

    @model_validator(mode="after")
    def validate_closure(self) -> Self:
        """Require positive forward head and a consistent signed reaction."""

        if self.upstream_stage <= self.downstream_stage:
            raise ValueError("completed Gate stage requires positive forward head")
        expected = self.momentum_flux_right - self.momentum_flux_left
        tolerance = max(1.0e-12, 8.0 * math.ulp(abs(expected)))
        if not math.isclose(
            self.reaction_force_per_density,
            expected,
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            raise ValueError("completed Gate stage reaction is inconsistent")
        return self


class MvpGateCouplingEvidence(StrictResultModel):
    """Persist the exact SSP stage evidence for one completed-interface Gate."""

    gate_id: PositiveId
    coupling_policy: Literal["submerged-orifice-energy-momentum-v1"]
    spatial_support: Literal["bound-internal-section-face-v1"]
    opening: PositiveFinite
    width: PositiveFinite
    opening_area: PositiveFinite
    discharge_coefficient: Annotated[FiniteNumber, Field(gt=0.0, le=1.0)]
    sill_elevation: FiniteNumber
    equation_tolerance: PositiveFinite
    maximum_allowed_iterations: PositiveInt
    total_transfer_volume: NonNegativeFinite
    maximum_absolute_energy_residual: NonNegativeFinite
    maximum_iterations: PositiveInt
    stage_evaluations: tuple[MvpGateStageEvidence, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_stage_summary(self) -> Self:
        """Recompute the RK2 volume and summary metrics from paired stages."""

        expected_keys = tuple(
            (index, stage)
            for index in range(1, len(self.stage_evaluations) // 2 + 1)
            for stage in (1, 2)
        )
        actual_keys = tuple(
            (item.step_index, item.rk_stage) for item in self.stage_evaluations
        )
        if len(self.stage_evaluations) % 2 or actual_keys != expected_keys:
            raise ValueError("completed Gate stages must be ordered RK1/RK2 pairs")
        if not math.isclose(
            self.opening_area,
            self.opening * self.width,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        ):
            raise ValueError("completed Gate opening area is inconsistent")
        total = 0.0
        for first, second in zip(
            self.stage_evaluations[::2],
            self.stage_evaluations[1::2],
        ):
            if first.step_dt != second.step_dt:
                raise ValueError("completed Gate RK stages must share one step_dt")
            if not math.isclose(
                second.evaluation_time - first.evaluation_time,
                first.step_dt,
                rel_tol=0.0,
                abs_tol=1.0e-12,
            ):
                raise ValueError("completed Gate RK2 time must follow RK1 by step_dt")
            total += 0.5 * first.step_dt * (first.flow + second.flow)
        if any(
            not math.isclose(
                right.evaluation_time,
                left.evaluation_time,
                rel_tol=0.0,
                abs_tol=_time_tolerance(
                    right.evaluation_time,
                    left.evaluation_time,
                ),
            )
            for left, right in zip(
                self.stage_evaluations[1::2],
                self.stage_evaluations[2::2],
            )
        ):
            raise ValueError("completed Gate accepted steps must share their boundary time")
        scale = max(abs(total), 1.0)
        if not math.isclose(
            self.total_transfer_volume,
            total,
            rel_tol=1.0e-10,
            abs_tol=1.0e-12 * scale,
        ):
            raise ValueError("completed Gate transfer volume is inconsistent")
        maximum_residual = max(
            abs(item.energy_residual) for item in self.stage_evaluations
        )
        if not math.isclose(
            self.maximum_absolute_energy_residual,
            maximum_residual,
            rel_tol=1.0e-10,
            abs_tol=1.0e-14,
        ):
            raise ValueError("completed Gate maximum energy residual is inconsistent")
        if self.maximum_iterations != max(
            item.iterations for item in self.stage_evaluations
        ):
            raise ValueError("completed Gate maximum iterations is inconsistent")
        if self.maximum_absolute_energy_residual > self.equation_tolerance:
            raise ValueError("completed Gate energy residual exceeds its tolerance")
        if self.maximum_iterations > self.maximum_allowed_iterations:
            raise ValueError("completed Gate iteration count exceeds its limit")
        for item in self.stage_evaluations:
            if min(item.upstream_stage, item.downstream_stage) <= (
                self.sill_elevation + self.opening
            ):
                raise ValueError("completed Gate stage is not submerged")
            expected_loss = item.flow * item.flow / (
                2.0
                * 9.81
                * (self.discharge_coefficient * self.opening_area) ** 2
            )
            expected_residual = (
                item.upstream_stage
                + item.flow * item.flow / (2.0 * 9.81 * item.upstream_area**2)
                - item.downstream_stage
                - item.flow * item.flow / (2.0 * 9.81 * item.downstream_area**2)
                - expected_loss
            )
            expected_left = (
                item.flow * item.flow / item.upstream_area
                + 9.81 * item.upstream_pressure_moment
            )
            expected_right = (
                item.flow * item.flow / item.downstream_area
                + 9.81 * item.downstream_pressure_moment
            )
            scale = max(abs(expected_left), abs(expected_right), 1.0)
            if not math.isclose(
                item.head_loss,
                expected_loss,
                rel_tol=1.0e-10,
                abs_tol=1.0e-12,
            ):
                raise ValueError("completed Gate head loss is inconsistent")
            if not math.isclose(
                item.energy_residual,
                expected_residual,
                rel_tol=0.0,
                abs_tol=max(self.equation_tolerance, 1.0e-12),
            ):
                raise ValueError("completed Gate energy residual is inconsistent")
            if not math.isclose(
                item.momentum_flux_left,
                expected_left,
                rel_tol=1.0e-10,
                abs_tol=1.0e-12 * scale,
            ) or not math.isclose(
                item.momentum_flux_right,
                expected_right,
                rel_tol=1.0e-10,
                abs_tol=1.0e-12 * scale,
            ):
                raise ValueError("completed Gate momentum flux is inconsistent")
            upstream_froude = item.flow / item.upstream_area / math.sqrt(
                9.81 * item.upstream_area / item.upstream_top_width
            )
            downstream_froude = item.flow / item.downstream_area / math.sqrt(
                9.81 * item.downstream_area / item.downstream_top_width
            )
            if max(upstream_froude, downstream_froude) >= 1.0:
                raise ValueError("completed Gate stage is not subcritical")
        return self


class MvpControlledGateStageEvidence(StrictResultModel):
    """Persist one closed/open RK-stage from the bracketed strong Gate path."""

    step_index: PositiveInt
    rk_stage: Literal[1, 2]
    evaluation_time: NonNegativeFinite
    step_dt: PositiveFinite
    actual_opening: NonNegativeFinite
    flow: NonNegativeFinite
    upstream_stage: FiniteNumber
    downstream_stage: FiniteNumber
    upstream_area: PositiveFinite
    downstream_area: PositiveFinite
    upstream_top_width: PositiveFinite
    downstream_top_width: PositiveFinite
    upstream_pressure_moment: NonNegativeFinite
    downstream_pressure_moment: NonNegativeFinite
    head_loss: NonNegativeFinite
    energy_residual: FiniteNumber
    iterations: NonNegativeInt
    momentum_flux_left: FiniteNumber
    momentum_flux_right: FiniteNumber
    reaction_force_per_density: FiniteNumber
    regime: Literal[
        "closed_barrier_completed_interface",
        "submerged_orifice_completed_interface",
    ]

    @model_validator(mode="after")
    def validate_reaction(self) -> Self:
        """Require each side-specific momentum pair to reproduce the reaction."""

        expected = self.momentum_flux_right - self.momentum_flux_left
        tolerance = max(1.0e-12, 8.0 * math.ulp(abs(expected)))
        if not math.isclose(
            self.reaction_force_per_density,
            expected,
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            raise ValueError("controlled Gate stage reaction is inconsistent")
        return self


class MvpControlledGateCouplingEvidence(StrictResultModel):
    """Prove that a located Gate command activates strong coupling afterward."""

    gate_id: PositiveId
    coupling_policy: Literal["submerged-orifice-energy-momentum-v1"]
    event_policy: Literal["bracketed-conservative-replay-right-end-v1"]
    command_effect: Literal["next-accepted-subinterval-v1"]
    spatial_support: Literal["bound-internal-section-face-v1"]
    event_time: NonNegativeFinite
    target_opening: PositiveFinite
    width: PositiveFinite
    discharge_coefficient: Annotated[FiniteNumber, Field(gt=0.0, le=1.0)]
    sill_elevation: FiniteNumber
    equation_tolerance: PositiveFinite
    maximum_allowed_iterations: PositiveInt
    total_transfer_volume: NonNegativeFinite
    maximum_absolute_energy_residual: NonNegativeFinite
    maximum_iterations: PositiveInt
    stage_evaluations: tuple[MvpControlledGateStageEvidence, ...] = Field(
        min_length=4
    )

    @model_validator(mode="after")
    def validate_combined_stage_history(self) -> Self:
        """Recompute volume, closure and the no-forward-fill event transition."""

        expected_keys = tuple(
            (index, stage)
            for index in range(1, len(self.stage_evaluations) // 2 + 1)
            for stage in (1, 2)
        )
        actual_keys = tuple(
            (item.step_index, item.rk_stage) for item in self.stage_evaluations
        )
        if len(self.stage_evaluations) % 2 or actual_keys != expected_keys:
            raise ValueError("controlled Gate stages must be ordered RK1/RK2 pairs")

        total = 0.0
        open_rows: list[MvpControlledGateStageEvidence] = []
        closed_rows: list[MvpControlledGateStageEvidence] = []
        event_step_found = False
        for first, second in zip(
            self.stage_evaluations[::2],
            self.stage_evaluations[1::2],
        ):
            expected_second_time = first.evaluation_time + first.step_dt
            if first.step_dt != second.step_dt or not math.isclose(
                second.evaluation_time,
                expected_second_time,
                rel_tol=0.0,
                abs_tol=_time_tolerance(
                    second.evaluation_time,
                    expected_second_time,
                ),
            ):
                raise ValueError("controlled Gate RK stage timing is inconsistent")
            if second.evaluation_time <= self.event_time + 1.0e-12:
                if first.actual_opening != 0.0 or second.actual_opening != 0.0:
                    raise ValueError("Gate opening was backfilled before its event")
                if math.isclose(
                    second.evaluation_time,
                    self.event_time,
                    rel_tol=0.0,
                    abs_tol=1.0e-12,
                ):
                    event_step_found = True
            elif first.evaluation_time >= self.event_time - 1.0e-12:
                if (
                    first.actual_opening != self.target_opening
                    or second.actual_opening != self.target_opening
                ):
                    raise ValueError("Gate target was not applied after its event")
            else:
                raise ValueError("controlled Gate step straddles an unaligned event")
            total += 0.5 * first.step_dt * (first.flow + second.flow)

        if not event_step_found:
            raise ValueError("controlled Gate evidence has no accepted event step")
        if any(
            not math.isclose(
                right.evaluation_time,
                left.evaluation_time,
                rel_tol=0.0,
                abs_tol=1.0e-12,
            )
            for left, right in zip(
                self.stage_evaluations[1::2],
                self.stage_evaluations[2::2],
            )
        ):
            raise ValueError("controlled Gate accepted steps must share boundary time")

        for item in self.stage_evaluations:
            expected_left = (
                item.flow * item.flow / item.upstream_area
                + 9.81 * item.upstream_pressure_moment
            )
            expected_right = (
                item.flow * item.flow / item.downstream_area
                + 9.81 * item.downstream_pressure_moment
            )
            scale = max(abs(expected_left), abs(expected_right), 1.0)
            if not math.isclose(
                item.momentum_flux_left,
                expected_left,
                rel_tol=1.0e-10,
                abs_tol=1.0e-12 * scale,
            ) or not math.isclose(
                item.momentum_flux_right,
                expected_right,
                rel_tol=1.0e-10,
                abs_tol=1.0e-12 * scale,
            ):
                raise ValueError("controlled Gate momentum flux is inconsistent")
            if item.regime == "closed_barrier_completed_interface":
                closed_rows.append(item)
                expected_loss = max(item.upstream_stage - item.downstream_stage, 0.0)
                if (
                    item.actual_opening != 0.0
                    or item.flow != 0.0
                    or item.iterations != 0
                    or item.energy_residual != 0.0
                    or not math.isclose(
                        item.head_loss,
                        expected_loss,
                        rel_tol=0.0,
                        abs_tol=1.0e-12,
                    )
                ):
                    raise ValueError("closed Gate stage evidence is inconsistent")
                continue

            open_rows.append(item)
            if item.actual_opening != self.target_opening or item.flow <= 0.0:
                raise ValueError("open Gate stage command/flow is inconsistent")
            if item.iterations <= 0 or min(
                item.upstream_stage, item.downstream_stage
            ) <= self.sill_elevation + self.target_opening:
                raise ValueError("open Gate stage is not submerged/converged")
            opening_area = self.width * self.target_opening
            expected_loss = item.flow * item.flow / (
                2.0
                * 9.81
                * (self.discharge_coefficient * opening_area) ** 2
            )
            expected_residual = (
                item.upstream_stage
                + item.flow * item.flow / (2.0 * 9.81 * item.upstream_area**2)
                - item.downstream_stage
                - item.flow * item.flow / (2.0 * 9.81 * item.downstream_area**2)
                - expected_loss
            )
            if not math.isclose(
                item.head_loss,
                expected_loss,
                rel_tol=1.0e-10,
                abs_tol=1.0e-12,
            ) or not math.isclose(
                item.energy_residual,
                expected_residual,
                rel_tol=0.0,
                abs_tol=max(self.equation_tolerance, 1.0e-12),
            ):
                raise ValueError("open Gate energy closure is inconsistent")
            upstream_froude = item.flow / item.upstream_area / math.sqrt(
                9.81 * item.upstream_area / item.upstream_top_width
            )
            downstream_froude = item.flow / item.downstream_area / math.sqrt(
                9.81 * item.downstream_area / item.downstream_top_width
            )
            if max(upstream_froude, downstream_froude) >= 1.0:
                raise ValueError("open Gate stage is not subcritical")

        if not closed_rows or not open_rows:
            raise ValueError("controlled Gate evidence requires closed and open stages")
        scale = max(abs(total), 1.0)
        if not math.isclose(
            self.total_transfer_volume,
            total,
            rel_tol=1.0e-10,
            abs_tol=1.0e-12 * scale,
        ):
            raise ValueError("controlled Gate transfer volume is inconsistent")
        maximum_residual = max(abs(item.energy_residual) for item in open_rows)
        if not math.isclose(
            self.maximum_absolute_energy_residual,
            maximum_residual,
            rel_tol=1.0e-10,
            abs_tol=1.0e-14,
        ) or maximum_residual > self.equation_tolerance:
            raise ValueError("controlled Gate maximum energy residual is inconsistent")
        maximum_iterations = max(item.iterations for item in open_rows)
        if (
            self.maximum_iterations != maximum_iterations
            or maximum_iterations > self.maximum_allowed_iterations
        ):
            raise ValueError("controlled Gate maximum iterations is inconsistent")
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


class MvpHydraulicPumpSeries(StrictResultModel):
    """Store output-aligned D1 Pump hydraulics, power, energy, and control state."""

    pump_id: PositiveId
    coupling_policy: Literal["qh-operating-point-external-sink-v1"]
    time: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    running_units: tuple[NonNegativeInt, ...] = Field(min_length=2)
    flow_m3s: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    source_stage_m: tuple[FiniteNumber, ...] = Field(min_length=2)
    outlet_or_target_stage_m: tuple[FiniteNumber, ...] = Field(min_length=2)
    pump_head_m: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    system_head_m: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    efficiency: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    hydraulic_power_kw: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    input_power_kw: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    cumulative_energy_kwh: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    control_state: tuple[Literal["on", "off"], ...] = Field(min_length=2)
    regime: tuple[Literal["off", "running_qh_operating_point"], ...] = Field(
        min_length=2
    )
    iterations: tuple[NonNegativeInt, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_hydraulic_series(self) -> Self:
        """Require aligned ON/OFF semantics and monotone accepted energy."""

        arrays = (
            self.running_units,
            self.flow_m3s,
            self.source_stage_m,
            self.outlet_or_target_stage_m,
            self.pump_head_m,
            self.system_head_m,
            self.efficiency,
            self.hydraulic_power_kw,
            self.input_power_kw,
            self.cumulative_energy_kwh,
            self.control_state,
            self.regime,
            self.iterations,
        )
        _validate_aligned_series(self.time, arrays, "hydraulic Pump")
        for index, status in enumerate(self.control_state):
            if status == "off":
                if any(
                    values[index] != 0
                    for values in (
                        self.running_units,
                        self.flow_m3s,
                        self.pump_head_m,
                        self.system_head_m,
                        self.efficiency,
                        self.hydraulic_power_kw,
                        self.input_power_kw,
                        self.iterations,
                    )
                ) or self.regime[index] != "off":
                    raise ValueError("OFF hydraulic Pump result must have zero outputs")
            elif (
                self.running_units[index] <= 0
                or self.flow_m3s[index] <= 0.0
                or not 0.0 < self.efficiency[index] <= 1.0
                or self.regime[index] != "running_qh_operating_point"
            ):
                raise ValueError("ON hydraulic Pump result is incomplete")
        if any(
            right < left
            for left, right in zip(
                self.cumulative_energy_kwh,
                self.cumulative_energy_kwh[1:],
            )
        ):
            raise ValueError("Pump cumulative energy must be non-decreasing")
        return self


class MvpPumpStageEvidence(StrictResultModel):
    """Persist one actual D1 Pump operating point used by an SSP-RK2 stage."""

    step_start_time: NonNegativeFinite
    rk_stage: Literal[1, 2]
    evaluation_time: NonNegativeFinite
    dt: PositiveFinite
    pump_id: PositiveId
    source_stage_m: FiniteNumber
    outlet_or_target_stage_m: FiniteNumber
    running_units: NonNegativeInt
    total_flow_m3s: NonNegativeFinite
    per_unit_flow_m3s: NonNegativeFinite
    pump_head_m: NonNegativeFinite
    system_head_m: FiniteNumber
    head_residual_m: FiniteNumber
    efficiency: NonNegativeFinite
    hydraulic_power_kw: NonNegativeFinite
    input_power_kw: NonNegativeFinite
    iterations: NonNegativeInt
    curve_segment: NonNegativeInt | None
    efficiency_segment: NonNegativeInt | None
    static_loss_m: NonNegativeFinite
    quadratic_loss_coefficient_s2_m5: NonNegativeFinite
    pump_coupling_policy: Literal["qh-operating-point-external-sink-v1"]
    pump_curve_policy: Literal["piecewise-linear-qh-v1"]
    pump_efficiency_policy: Literal["piecewise-linear-q-efficiency-v1"]
    system_loss_policy: Literal["quadratic-q-v1"]
    regime: Literal["off", "running_qh_operating_point"]

    @model_validator(mode="after")
    def validate_stage_closure(self) -> Self:
        """Recompute timing, system head, residual, and input power."""

        expected_time = self.step_start_time + (self.dt if self.rk_stage == 2 else 0.0)
        if not math.isclose(
            self.evaluation_time,
            expected_time,
            rel_tol=0.0,
            abs_tol=_time_tolerance(self.evaluation_time, expected_time),
        ):
            raise ValueError("Pump RK-stage evaluation time is inconsistent")
        if self.running_units == 0:
            if any(
                value != 0
                for value in (
                    self.total_flow_m3s,
                    self.per_unit_flow_m3s,
                    self.pump_head_m,
                    self.system_head_m,
                    self.head_residual_m,
                    self.efficiency,
                    self.hydraulic_power_kw,
                    self.input_power_kw,
                    self.iterations,
                )
            ) or self.regime != "off":
                raise ValueError("OFF Pump stage evidence must have zero outputs")
            return self
        if self.regime != "running_qh_operating_point":
            raise ValueError("running Pump stage has an unknown regime")
        if self.total_flow_m3s <= 0.0 or self.per_unit_flow_m3s <= 0.0:
            raise ValueError("running Pump stage requires positive flow")
        if not 0.0 < self.efficiency <= 1.0:
            raise ValueError("running Pump stage has invalid efficiency")
        expected_system = (
            self.outlet_or_target_stage_m
            - self.source_stage_m
            + self.static_loss_m
            + self.quadratic_loss_coefficient_s2_m5
            * self.total_flow_m3s
            * abs(self.total_flow_m3s)
        )
        tolerance = max(1.0e-10, 8.0 * math.ulp(abs(expected_system)))
        if not math.isclose(
            self.system_head_m,
            expected_system,
            rel_tol=0.0,
            abs_tol=tolerance,
        ) or not math.isclose(
            self.head_residual_m,
            self.pump_head_m - self.system_head_m,
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            raise ValueError("Pump stage head closure is inconsistent")
        hydraulic_power = (
            1000.0
            * 9.81
            * self.total_flow_m3s
            * self.pump_head_m
            / 1000.0
        )
        input_power = hydraulic_power / self.efficiency
        if not math.isclose(
            self.hydraulic_power_kw,
            hydraulic_power,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        ) or not math.isclose(
            self.input_power_kw,
            input_power,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        ):
            raise ValueError("Pump stage power is inconsistent")
        return self


class MvpPumpCouplingEvidence(StrictResultModel):
    """Aggregate accepted D1 Pump stages into exact volume and energy budgets."""

    pump_id: PositiveId
    pump_coupling_policy: Literal["qh-operating-point-external-sink-v1"]
    pump_curve_policy: Literal["piecewise-linear-qh-v1"]
    pump_efficiency_policy: Literal["piecewise-linear-q-efficiency-v1"]
    pump_control_policy: Literal["stage-hysteresis-min-runtime-v1"]
    system_loss_policy: Literal["quadratic-q-v1"]
    momentum_policy: Literal["local-advective-external-sink-v1"]
    head_residual_tolerance_m: PositiveFinite
    maximum_iterations: PositiveInt
    total_external_volume_m3: NonNegativeFinite
    total_input_energy_kwh: NonNegativeFinite
    maximum_absolute_head_residual_m: NonNegativeFinite
    stage_evaluations: tuple[MvpPumpStageEvidence, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_accepted_stage_budget(self) -> Self:
        """Reintegrate paired RK stages and reject probe/retry contamination."""

        if len(self.stage_evaluations) % 2:
            raise ValueError("Pump evidence must contain complete RK1/RK2 pairs")
        volume = 0.0
        energy = 0.0
        maximum_residual = 0.0
        previous_end = -1.0
        for index in range(0, len(self.stage_evaluations), 2):
            first, second = self.stage_evaluations[index : index + 2]
            if (first.rk_stage, second.rk_stage) != (1, 2):
                raise ValueError("Pump stages must be ordered RK1/RK2 pairs")
            if first.pump_id != self.pump_id or second.pump_id != self.pump_id:
                raise ValueError("Pump stage evidence references another Pump")
            if first.step_start_time != second.step_start_time or first.dt != second.dt:
                raise ValueError("Pump RK stages must share one accepted step")
            if previous_end >= 0.0 and not math.isclose(
                first.step_start_time,
                previous_end,
                rel_tol=0.0,
                abs_tol=_time_tolerance(first.step_start_time, previous_end),
            ):
                raise ValueError("Pump accepted stage evidence is not contiguous")
            if first.iterations > self.maximum_iterations or (
                second.iterations > self.maximum_iterations
            ):
                raise ValueError("Pump stage evidence exceeds maximum_iterations")
            previous_end = first.step_start_time + first.dt
            volume += 0.5 * first.dt * (
                first.total_flow_m3s + second.total_flow_m3s
            )
            energy += 0.5 * first.dt * (
                first.input_power_kw + second.input_power_kw
            ) / 3600.0
            maximum_residual = max(
                maximum_residual,
                abs(first.head_residual_m),
                abs(second.head_residual_m),
            )
        if not math.isclose(
            self.total_external_volume_m3,
            volume,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        ):
            raise ValueError("Pump external volume is inconsistent with accepted stages")
        if not math.isclose(
            self.total_input_energy_kwh,
            energy,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        ):
            raise ValueError("Pump energy is inconsistent with accepted stages")
        if not math.isclose(
            self.maximum_absolute_head_residual_m,
            maximum_residual,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            raise ValueError("Pump maximum head residual is inconsistent")
        if maximum_residual > self.head_residual_tolerance_m:
            raise ValueError("Pump stage head residual exceeds the configured tolerance")
        return self


class MvpControlEvent(StrictResultModel):
    """Expose one accepted-state threshold action independently of device state."""

    time: NonNegativeFinite
    structure_id: PositiveId
    structure_type: Literal["gate", "pump"]
    action: Literal["open", "start", "stop"]
    threshold_water_level: FiniteNumber
    observed_water_level: FiniteNumber
    previous_time: NonNegativeFinite | None = None
    previous_observed_water_level: FiniteNumber | None = None
    bracket_end_time: NonNegativeFinite | None = None
    event_time_tolerance: PositiveFinite | None = None
    locator_policy: Literal[
        "bracketed-conservative-replay-right-end-v1"
    ] | None = None
    refinement_count: NonNegativeInt | None = None
    monitored_section_id: PositiveId | None = None
    spatial_support: Literal["bound-section-cell-center-v1"] | None = None
    reason: NonBlankText | None = None

    @model_validator(mode="after")
    def validate_causal_action(self) -> Self:
        """Require a strict crossing and the action defined for that device type."""

        if (self.structure_type, self.action) not in {
            ("gate", "open"),
            ("pump", "start"),
            ("pump", "stop"),
        }:
            raise ValueError("control event action does not match structure_type")
        if self.action == "open" and (
            self.observed_water_level <= self.threshold_water_level
        ):
            raise ValueError("Gate open event level must exceed its threshold")
        if self.action == "start" and (
            self.observed_water_level < self.threshold_water_level
        ):
            raise ValueError("Pump start event level must be at or above its threshold")
        if self.action == "stop" and (
            self.observed_water_level > self.threshold_water_level
        ):
            raise ValueError("stop event level must be at or below its threshold")
        bracket_fields = (
            self.previous_time,
            self.previous_observed_water_level,
            self.bracket_end_time,
            self.event_time_tolerance,
            self.locator_policy,
            self.refinement_count,
            self.monitored_section_id,
            self.spatial_support,
        )
        if all(value is None for value in bracket_fields):
            return self
        if self.action == "stop":
            raise ValueError("stop event cannot contain rising bracket evidence")
        if any(value is None for value in bracket_fields):
            raise ValueError("bracketed control event evidence must be complete")
        previous_time = float(self.previous_time)
        previous_level = float(self.previous_observed_water_level)
        bracket_end_time = float(self.bracket_end_time)
        event_tolerance = float(self.event_time_tolerance)
        if bracket_end_time != self.time:
            raise ValueError("control event time must equal bracket_end_time")
        if previous_time >= self.time:
            raise ValueError("control event previous_time must precede event time")
        if self.time - previous_time > event_tolerance + 1.0e-12:
            raise ValueError("control event bracket exceeds event_time_tolerance")
        if previous_level > self.threshold_water_level:
            raise ValueError("control event bracket must start at or below threshold")
        return self

    @property
    def has_bracket_evidence(self) -> bool:
        """Return whether the versioned crossing-evidence tuple is present."""

        return self.locator_policy is not None

    @model_serializer(mode="wrap")
    def serialize_bracket_evidence(self, handler: Any) -> dict[str, Any]:
        """Keep pre-v4 event bytes free of nullable bracket fields."""

        payload = handler(self)
        for key in (
            "previous_time",
            "previous_observed_water_level",
            "bracket_end_time",
            "event_time_tolerance",
            "locator_policy",
            "refinement_count",
            "monitored_section_id",
            "spatial_support",
        ):
            if payload.get(key) is None:
                payload.pop(key, None)
        if payload.get("reason") is None:
            payload.pop("reason", None)
        return payload


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
    validation_policy_version: Literal[
        "v4-lite-1",
        "v4-lite-2",
        "v4-lite-3",
        "v4-lite-4",
        "v4-lite-5",
        "v4-lite-6",
        "v4-lite-7",
    ]
    solver_policy_hash: Sha256 | None = None

    @model_validator(mode="after")
    def validate_versioned_solver_policy(self) -> Self:
        """Require execution-policy evidence for every post-v1 route."""

        if self.validation_policy_version == "v4-lite-1":
            if "solver_policy_hash" in self.model_fields_set:
                raise ValueError("v4-lite-1 result must not add solver_policy_hash")
        elif self.solver_policy_hash is None:
            raise ValueError(
                f"{self.validation_policy_version} result requires solver_policy_hash"
            )
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
    pumps: tuple[MvpPumpSeries | MvpHydraulicPumpSeries, ...] = Field(max_length=1)
    control_events: tuple[MvpControlEvent, ...] = ()
    gate_coupling_evidence: tuple[MvpGateCouplingEvidence, ...] = Field(
        default=(), max_length=1
    )
    controlled_gate_coupling_evidence: tuple[
        MvpControlledGateCouplingEvidence, ...
    ] = Field(default=(), max_length=1)
    pump_coupling_evidence: tuple[MvpPumpCouplingEvidence, ...] = Field(
        default=(), max_length=1
    )
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
        version = self.provenance.validation_policy_version
        expects_bracket_evidence = version in {
            "v4-lite-4",
            "v4-lite-6",
        }
        expects_gate_coupling = (
            version == "v4-lite-5"
        )
        expects_controlled_gate_coupling = (
            version in {"v4-lite-6", "v4-lite-7"}
        )
        expects_pump_coupling = version == "v4-lite-7"
        if version == "v4-lite-7" and any(
            section.volume_m3 is None for section in self.sections
        ):
            raise ValueError("v4-lite-7 requires section control-volume series")
        if version != "v4-lite-7" and any(
            section.volume_m3 is not None for section in self.sections
        ):
            raise ValueError("pre-v7 section results must not add volume series")
        if expects_gate_coupling:
            if len(self.gate_coupling_evidence) != 1 or len(self.gates) != 1:
                raise ValueError("v4-lite-5 requires one Gate coupling evidence object")
            if self.pumps or self.control_events:
                raise ValueError("v4-lite-5 result cannot contain Pump/control evidence")
            if self.gate_coupling_evidence[0].gate_id != self.gates[0].gate_id:
                raise ValueError("Gate coupling evidence references an unknown Gate")
        elif self.gate_coupling_evidence:
            raise ValueError("pre-v5 result must not add Gate coupling evidence")
        if expects_controlled_gate_coupling:
            if (
                len(self.controlled_gate_coupling_evidence) != 1
                or len(self.gates) != 1
                or (version == "v4-lite-6" and self.pumps)
            ):
                raise ValueError(
                    "v4-lite-6 requires one controlled Gate coupling evidence object"
                )
            evidence = self.controlled_gate_coupling_evidence[0]
            if evidence.gate_id != self.gates[0].gate_id:
                raise ValueError("controlled Gate evidence references an unknown Gate")
            matching_events = tuple(
                item
                for item in self.control_events
                if item.structure_type == "gate" and item.structure_id == evidence.gate_id
            )
            if len(matching_events) != 1 or not math.isclose(
                matching_events[0].time,
                evidence.event_time,
                rel_tol=0.0,
                abs_tol=1.0e-12,
            ):
                raise ValueError("controlled Gate evidence does not match its event")
        elif self.controlled_gate_coupling_evidence:
            raise ValueError("pre-v6 result must not add controlled Gate evidence")
        if expects_pump_coupling:
            if len(self.pumps) != 1 or not isinstance(
                self.pumps[0], MvpHydraulicPumpSeries
            ):
                raise ValueError("v4-lite-7 requires one hydraulic Pump result")
            if len(self.pump_coupling_evidence) != 1:
                raise ValueError("v4-lite-7 requires one Pump coupling evidence object")
            pump_evidence = self.pump_coupling_evidence[0]
            pump_series = self.pumps[0]
            if pump_evidence.pump_id != pump_series.pump_id:
                raise ValueError("Pump coupling evidence references an unknown Pump")
            if not math.isclose(
                pump_evidence.total_external_volume_m3,
                self.water_balance.pump_outflow_volume,
                rel_tol=0.0,
                abs_tol=1.0e-9,
            ):
                raise ValueError("Pump coupling evidence contradicts water balance")
            if len(pump_evidence.stage_evaluations) != 2 * self.diagnostics.step_count:
                raise ValueError("Pump stage evidence count contradicts diagnostics")
            first_stage = pump_evidence.stage_evaluations[0]
            last_stage = pump_evidence.stage_evaluations[-1]
            if not math.isclose(
                first_stage.step_start_time,
                expected_time[0],
                rel_tol=0.0,
                abs_tol=_time_tolerance(
                    first_stage.step_start_time,
                    expected_time[0],
                ),
            ) or not math.isclose(
                last_stage.step_start_time + last_stage.dt,
                expected_time[-1],
                rel_tol=0.0,
                abs_tol=_time_tolerance(
                    last_stage.step_start_time + last_stage.dt,
                    expected_time[-1],
                ),
            ):
                raise ValueError("Pump stage evidence does not cover the result interval")
            if not math.isclose(
                pump_series.cumulative_energy_kwh[-1],
                pump_evidence.total_input_energy_kwh,
                rel_tol=0.0,
                abs_tol=1.0e-9,
            ):
                raise ValueError("Pump output energy contradicts coupling evidence")
        elif self.pump_coupling_evidence:
            raise ValueError("pre-v7 result must not add Pump coupling evidence")
        for event in self.control_events:
            if expects_bracket_evidence and not event.has_bracket_evidence:
                raise ValueError("v4-lite-4 control events require bracket evidence")
            if not expects_bracket_evidence and event.has_bracket_evidence:
                if not (
                    version == "v4-lite-7"
                    and event.structure_type == "gate"
                    and event.action == "open"
                ):
                    raise ValueError(
                        "pre-v4 control events must not add bracket evidence"
                    )
            if (
                version == "v4-lite-7"
                and event.structure_type == "gate"
                and not event.has_bracket_evidence
            ):
                raise ValueError("v4-lite-7 Gate event requires bracket evidence")
            if (
                version == "v4-lite-7"
                and event.structure_type == "pump"
                and event.has_bracket_evidence
            ):
                raise ValueError("v4-lite-7 Pump hysteresis event cannot use a bracket")
        event_keys = tuple(
            (item.structure_type, item.structure_id) for item in self.control_events
        )
        if version == "v4-lite-7":
            _require_unique(
                (
                    (item.time, item.structure_type, item.structure_id, item.action)
                    for item in self.control_events
                ),
                "D1 control event identity",
            )
            gate_event_keys = tuple(
                key for key in event_keys if key[0] == "gate"
            )
            _require_unique(gate_event_keys, "D1 one-shot Gate event identity")
        else:
            _require_unique(event_keys, "one-shot control event structure identity")
        event_key_set = set(event_keys)
        gate_ids = {item.gate_id for item in self.gates}
        pump_ids = {item.pump_id for item in self.pumps}
        section_ids = {item.section_id for item in self.sections}
        for event in self.control_events:
            known_ids = gate_ids if event.structure_type == "gate" else pump_ids
            if event.structure_id not in known_ids:
                raise ValueError("control event references an unknown result structure")
            if (
                event.monitored_section_id is not None
                and event.monitored_section_id not in section_ids
            ):
                raise ValueError("control event references an unknown monitored section")
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
            elif isinstance(
                next(item for item in self.pumps if item.pump_id == event.structure_id),
                MvpPumpSeries,
            ):
                series = next(
                    item for item in self.pumps if item.pump_id == event.structure_id
                )
                assert isinstance(series, MvpPumpSeries)
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
            if isinstance(pump, MvpPumpSeries):
                if ("pump", pump.pump_id) not in event_key_set and len(
                    set(pump.status)
                ) != 1:
                    raise ValueError("Pump status changes without a control event")
            else:
                pump_events = tuple(
                    event
                    for event in self.control_events
                    if event.structure_type == "pump"
                    and event.structure_id == pump.pump_id
                )
                if len(set(pump.control_state)) > 1 and not pump_events:
                    raise ValueError("hydraulic Pump state changes without an event")
                expected_status = "off"
                event_index = 0
                for time, actual_status in zip(pump.time, pump.control_state):
                    while (
                        event_index < len(pump_events)
                        and pump_events[event_index].time <= time
                    ):
                        action = pump_events[event_index].action
                        if (expected_status, action) == ("off", "start"):
                            expected_status = "on"
                        elif (expected_status, action) == ("on", "stop"):
                            expected_status = "off"
                        else:
                            raise ValueError(
                                "hydraulic Pump event sequence contradicts hysteresis"
                            )
                        event_index += 1
                    if actual_status != expected_status:
                        raise ValueError(
                            "hydraulic Pump event contradicts its control-state series"
                        )
        return self

    @model_serializer(mode="wrap")
    def serialize_controlled_gate_evidence(self, handler: Any) -> dict[str, Any]:
        """Keep every pre-v6 wire shape free of the new combination field."""

        payload = handler(self)
        if not self.controlled_gate_coupling_evidence:
            payload.pop("controlled_gate_coupling_evidence", None)
        if not self.pump_coupling_evidence:
            payload.pop("pump_coupling_evidence", None)
        return payload

    def to_dict(self) -> dict[str, Any]:
        """Return JSON while preserving the pre-control fixed-result shape."""

        payload = self.model_dump(mode="json")
        if not self.control_events:
            payload.pop("control_events")
        if not self.gate_coupling_evidence:
            payload.pop("gate_coupling_evidence")
        if not self.controlled_gate_coupling_evidence:
            payload.pop("controlled_gate_coupling_evidence", None)
        if not self.pump_coupling_evidence:
            payload.pop("pump_coupling_evidence", None)
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
    "MvpGateCouplingEvidence",
    "MvpGateStageEvidence",
    "MvpHydraulicPumpSeries",
    "MvpHydraulicResult",
    "MvpPumpCouplingEvidence",
    "MvpPumpSeries",
    "MvpPumpStageEvidence",
    "MvpResultProvenance",
    "MvpSectionSeries",
    "MvpWaterBalance",
]
