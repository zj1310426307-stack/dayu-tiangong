"""Pure Pump Q-H/Q-efficiency curves and deterministic operating-point solve."""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

WATER_DENSITY_KG_M3 = 1000.0
GRAVITY_M_S2 = 9.81

PUMP_COUPLING_POLICY = "qh-operating-point-external-sink-v1"
PUMP_CURVE_POLICY = "piecewise-linear-qh-v1"
PUMP_EFFICIENCY_POLICY = "piecewise-linear-q-efficiency-v1"
PUMP_SYSTEM_LOSS_POLICY = "quadratic-q-v1"
PUMP_CONTROL_POLICY = "stage-hysteresis-min-runtime-v1"


def _finite(value: float, label: str) -> float:
    """Return one finite float while rejecting booleans and non-numbers."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def _validate_points(
    points: tuple[tuple[float, float], ...],
    *,
    ordinate_label: str,
) -> tuple[tuple[float, float], ...]:
    """Validate an input-order-preserving curve without sorting or guessing."""

    if len(points) < 2:
        raise ValueError(f"{ordinate_label} curve requires at least two points")
    normalized = tuple(
        (
            _finite(flow, "curve flow_m3s"),
            _finite(ordinate, f"curve {ordinate_label}"),
        )
        for flow, ordinate in points
    )
    if any(flow < 0.0 for flow, _ in normalized):
        raise ValueError("curve flow_m3s must be non-negative")
    if any(
        right[0] <= left[0]
        for left, right in zip(normalized, normalized[1:])
    ):
        raise ValueError("curve flow_m3s values must be strictly increasing")
    return normalized


def _segment_index(points: tuple[tuple[float, float], ...], flow: float) -> int:
    """Return the stable zero-based segment containing an in-range flow."""

    xs = tuple(point[0] for point in points)
    if flow < xs[0] or flow > xs[-1]:
        raise ValueError(
            f"curve flow {flow} lies outside [{xs[0]}, {xs[-1]}]"
        )
    if flow == xs[-1]:
        return len(xs) - 2
    return max(0, bisect.bisect_right(xs, flow) - 1)


def _interpolate(points: tuple[tuple[float, float], ...], flow: float) -> float:
    """Evaluate deterministic piecewise-linear interpolation without extrapolation."""

    query = _finite(flow, "curve query flow")
    segment = _segment_index(points, query)
    left_flow, left_value = points[segment]
    right_flow, right_value = points[segment + 1]
    ratio = (query - left_flow) / (right_flow - left_flow)
    return left_value + ratio * (right_value - left_value)


@dataclass(frozen=True)
class PumpHeadCurve:
    """Store one per-unit Q-H curve with a stable interpolation policy."""

    points: tuple[tuple[float, float], ...]
    policy_id: str = PUMP_CURVE_POLICY

    def __post_init__(self) -> None:
        """Reject malformed, negative-head, or unsupported Q-H curves."""

        if self.policy_id != PUMP_CURVE_POLICY:
            raise ValueError("unsupported Pump Q-H curve policy")
        normalized = _validate_points(self.points, ordinate_label="head_m")
        if any(head < 0.0 for _, head in normalized):
            raise ValueError("Pump Q-H head_m must be non-negative")
        object.__setattr__(self, "points", normalized)

    @property
    def flow_range_m3s(self) -> tuple[float, float]:
        """Return the closed per-unit flow domain admitted by the curve."""

        return self.points[0][0], self.points[-1][0]

    def head_at(self, per_unit_flow_m3s: float) -> float:
        """Return Pump head for one in-domain per-unit flow."""

        return _interpolate(self.points, per_unit_flow_m3s)

    def segment_at(self, per_unit_flow_m3s: float) -> int:
        """Return the stable Q-H segment index used for interpolation."""

        return _segment_index(self.points, _finite(per_unit_flow_m3s, "flow"))


@dataclass(frozen=True)
class PumpEfficiencyCurve:
    """Store one per-unit Q-efficiency curve without extrapolation."""

    points: tuple[tuple[float, float], ...]
    policy_id: str = PUMP_EFFICIENCY_POLICY

    def __post_init__(self) -> None:
        """Require a finite efficiency in the physical interval ``(0, 1]``."""

        if self.policy_id != PUMP_EFFICIENCY_POLICY:
            raise ValueError("unsupported Pump efficiency curve policy")
        normalized = _validate_points(self.points, ordinate_label="efficiency")
        if any(not 0.0 < efficiency <= 1.0 for _, efficiency in normalized):
            raise ValueError("Pump efficiency must satisfy 0 < efficiency <= 1")
        object.__setattr__(self, "points", normalized)

    @property
    def flow_range_m3s(self) -> tuple[float, float]:
        """Return the closed per-unit flow domain admitted by the curve."""

        return self.points[0][0], self.points[-1][0]

    def efficiency_at(self, per_unit_flow_m3s: float) -> float:
        """Return efficiency for one in-domain per-unit flow."""

        return _interpolate(self.points, per_unit_flow_m3s)

    def segment_at(self, per_unit_flow_m3s: float) -> int:
        """Return the stable efficiency segment index used for interpolation."""

        return _segment_index(self.points, _finite(per_unit_flow_m3s, "flow"))


@dataclass(frozen=True)
class PumpUnitConfiguration:
    """Freeze identical parallel-unit limits and one commanded running count."""

    total_units: int
    running_units: int
    minimum_running_units: int
    maximum_running_units: int

    def __post_init__(self) -> None:
        """Reject mixed/invalid unit counts before the operating-point solve."""

        values = (
            self.total_units,
            self.running_units,
            self.minimum_running_units,
            self.maximum_running_units,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ValueError("Pump unit counts must be integers")
        if self.total_units <= 0:
            raise ValueError("total_units must be positive")
        if not 1 <= self.minimum_running_units <= self.maximum_running_units:
            raise ValueError("Pump running-unit limits are inconsistent")
        if self.maximum_running_units > self.total_units:
            raise ValueError("maximum_running_units exceeds total_units")
        if self.running_units != 0 and not (
            self.minimum_running_units
            <= self.running_units
            <= self.maximum_running_units
        ):
            raise ValueError("running_units lies outside its configured limits")


@dataclass(frozen=True)
class PumpOperatingEnvelope:
    """Expose the total-flow interval shared by Q-H and Q-efficiency curves."""

    minimum_total_flow_m3s: float
    maximum_total_flow_m3s: float

    def __post_init__(self) -> None:
        """Require a non-empty finite operating interval."""

        lower = _finite(self.minimum_total_flow_m3s, "minimum total flow")
        upper = _finite(self.maximum_total_flow_m3s, "maximum total flow")
        if lower < 0.0 or upper <= lower:
            raise ValueError("Pump operating envelope must have 0 <= min < max")

    @classmethod
    def from_curves(
        cls,
        *,
        head_curve: PumpHeadCurve,
        efficiency_curve: PumpEfficiencyCurve,
        running_units: int,
    ) -> "PumpOperatingEnvelope":
        """Intersect per-unit curve domains and scale them for parallel units."""

        if isinstance(running_units, bool) or running_units <= 0:
            raise ValueError("running_units must be positive for an operating envelope")
        lower = max(head_curve.flow_range_m3s[0], efficiency_curve.flow_range_m3s[0])
        upper = min(head_curve.flow_range_m3s[1], efficiency_curve.flow_range_m3s[1])
        return cls(lower * running_units, upper * running_units)


@dataclass(frozen=True)
class PumpSystemLoss:
    """Define external system head with explicit SI units.

    ``quadratic_loss_coefficient_s2_m5`` multiplies ``Q*abs(Q)`` in m3/s,
    yielding metres of head. ``static_loss_m`` is an additional fixed loss;
    the explicit outlet-minus-source stage term is evaluated separately.
    """

    static_loss_m: float
    quadratic_loss_coefficient_s2_m5: float
    policy_id: str = PUMP_SYSTEM_LOSS_POLICY

    def __post_init__(self) -> None:
        """Reject negative/non-finite losses and unregistered policies."""

        if self.policy_id != PUMP_SYSTEM_LOSS_POLICY:
            raise ValueError("unsupported Pump system-loss policy")
        static = _finite(self.static_loss_m, "static_loss_m")
        coefficient = _finite(
            self.quadratic_loss_coefficient_s2_m5,
            "quadratic_loss_coefficient_s2_m5",
        )
        if static < 0.0 or coefficient < 0.0:
            raise ValueError("Pump system losses must be non-negative")

    def head_at(
        self,
        *,
        total_flow_m3s: float,
        source_stage_m: float,
        outlet_stage_m: float,
    ) -> float:
        """Return required system head for one signed stage difference and flow."""

        flow = _finite(total_flow_m3s, "total_flow_m3s")
        source = _finite(source_stage_m, "source_stage_m")
        outlet = _finite(outlet_stage_m, "outlet_stage_m")
        return (
            outlet
            - source
            + self.static_loss_m
            + self.quadratic_loss_coefficient_s2_m5 * flow * abs(flow)
        )


@dataclass(frozen=True)
class PumpOperatingPointEvidence:
    """Persist one independently checkable Pump SSP-stage operating point."""

    evaluation_time: float
    dt: float
    pump_id: str
    source_stage_m: float
    outlet_or_target_stage_m: float
    running_units: int
    total_flow_m3s: float
    per_unit_flow_m3s: float
    pump_head_m: float
    system_head_m: float
    head_residual_m: float
    efficiency: float
    hydraulic_power_kw: float
    input_power_kw: float
    iterations: int
    curve_segment: int | None
    efficiency_segment: int | None
    static_loss_m: float
    quadratic_loss_coefficient_s2_m5: float
    pump_coupling_policy: str = PUMP_COUPLING_POLICY
    pump_curve_policy: str = PUMP_CURVE_POLICY
    pump_efficiency_policy: str = PUMP_EFFICIENCY_POLICY
    system_loss_policy: str = PUMP_SYSTEM_LOSS_POLICY
    regime: str = "running_qh_operating_point"

    def __post_init__(self) -> None:
        """Validate head closure and power without becoming runtime state."""

        numeric = (
            self.evaluation_time,
            self.dt,
            self.source_stage_m,
            self.outlet_or_target_stage_m,
            self.total_flow_m3s,
            self.per_unit_flow_m3s,
            self.pump_head_m,
            self.system_head_m,
            self.head_residual_m,
            self.efficiency,
            self.hydraulic_power_kw,
            self.input_power_kw,
            self.static_loss_m,
            self.quadratic_loss_coefficient_s2_m5,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("Pump operating-point evidence must be finite")
        if self.evaluation_time < 0.0 or self.dt <= 0.0:
            raise ValueError("Pump evidence time must be non-negative and dt positive")
        if isinstance(self.running_units, bool) or self.running_units < 0:
            raise ValueError("Pump evidence running_units must be non-negative")
        if isinstance(self.iterations, bool) or self.iterations < 0:
            raise ValueError("Pump evidence iterations must be non-negative")
        policies = (
            (self.pump_coupling_policy, PUMP_COUPLING_POLICY),
            (self.pump_curve_policy, PUMP_CURVE_POLICY),
            (self.pump_efficiency_policy, PUMP_EFFICIENCY_POLICY),
            (self.system_loss_policy, PUMP_SYSTEM_LOSS_POLICY),
        )
        if any(actual != expected for actual, expected in policies):
            raise ValueError("Pump evidence contains an unsupported policy")
        if self.running_units == 0:
            if any(
                value != 0.0
                for value in (
                    self.total_flow_m3s,
                    self.per_unit_flow_m3s,
                    self.pump_head_m,
                    self.system_head_m,
                    self.head_residual_m,
                    self.efficiency,
                    self.hydraulic_power_kw,
                    self.input_power_kw,
                )
            ):
                raise ValueError("OFF Pump evidence must have zero hydraulic outputs")
            if self.iterations != 0 or self.curve_segment is not None:
                raise ValueError("OFF Pump evidence must not claim a root solve")
            return
        if self.regime != "running_qh_operating_point":
            raise ValueError("running Pump evidence has an unknown regime")
        if self.total_flow_m3s <= 0.0 or self.per_unit_flow_m3s <= 0.0:
            raise ValueError("running Pump evidence requires positive flow")
        if not 0.0 < self.efficiency <= 1.0:
            raise ValueError("running Pump evidence has invalid efficiency")
        expected_system = (
            self.outlet_or_target_stage_m
            - self.source_stage_m
            + self.static_loss_m
            + self.quadratic_loss_coefficient_s2_m5
            * self.total_flow_m3s
            * abs(self.total_flow_m3s)
        )
        tolerance = max(1.0e-12, 8.0 * math.ulp(abs(expected_system)))
        if not math.isclose(
            self.system_head_m,
            expected_system,
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            raise ValueError("Pump evidence system head is inconsistent")
        if not math.isclose(
            self.head_residual_m,
            self.pump_head_m - self.system_head_m,
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            raise ValueError("Pump evidence head residual is inconsistent")
        expected_hydraulic = (
            WATER_DENSITY_KG_M3
            * GRAVITY_M_S2
            * self.total_flow_m3s
            * self.pump_head_m
            / 1000.0
        )
        expected_input = expected_hydraulic / self.efficiency
        power_tolerance = max(1.0e-10, 8.0 * math.ulp(abs(expected_input)))
        if not math.isclose(
            self.hydraulic_power_kw,
            expected_hydraulic,
            rel_tol=0.0,
            abs_tol=power_tolerance,
        ) or not math.isclose(
            self.input_power_kw,
            expected_input,
            rel_tol=0.0,
            abs_tol=power_tolerance,
        ):
            raise ValueError("Pump evidence power is inconsistent")


def off_pump_evidence(
    *,
    evaluation_time: float,
    dt: float,
    pump_id: str,
    source_stage_m: float,
    outlet_stage_m: float,
    system_loss: PumpSystemLoss,
) -> PumpOperatingPointEvidence:
    """Return an explicit zero-power stage row for an accepted OFF command."""

    return PumpOperatingPointEvidence(
        evaluation_time=_finite(evaluation_time, "evaluation_time"),
        dt=_finite(dt, "dt"),
        pump_id=pump_id,
        source_stage_m=_finite(source_stage_m, "source_stage_m"),
        outlet_or_target_stage_m=_finite(outlet_stage_m, "outlet_stage_m"),
        running_units=0,
        total_flow_m3s=0.0,
        per_unit_flow_m3s=0.0,
        pump_head_m=0.0,
        system_head_m=0.0,
        head_residual_m=0.0,
        efficiency=0.0,
        hydraulic_power_kw=0.0,
        input_power_kw=0.0,
        iterations=0,
        curve_segment=None,
        efficiency_segment=None,
        static_loss_m=system_loss.static_loss_m,
        quadratic_loss_coefficient_s2_m5=(
            system_loss.quadratic_loss_coefficient_s2_m5
        ),
        regime="off",
    )


def solve_pump_operating_point(
    *,
    evaluation_time: float,
    dt: float,
    pump_id: str,
    source_stage_m: float,
    outlet_stage_m: float,
    head_curve: PumpHeadCurve,
    efficiency_curve: PumpEfficiencyCurve,
    units: PumpUnitConfiguration,
    system_loss: PumpSystemLoss,
    head_residual_tolerance_m: float,
    maximum_iterations: int,
) -> PumpOperatingPointEvidence:
    """Solve ``H_pump(Q/N) = H_system(Q)`` by deterministic bisection."""

    if units.running_units <= 0:
        raise ValueError("Pump operating-point solve requires running_units > 0")
    tolerance = _finite(head_residual_tolerance_m, "head residual tolerance")
    if tolerance <= 0.0:
        raise ValueError("head_residual_tolerance_m must be positive")
    if isinstance(maximum_iterations, bool) or maximum_iterations <= 0:
        raise ValueError("Pump maximum_iterations must be positive")
    source = _finite(source_stage_m, "source_stage_m")
    outlet = _finite(outlet_stage_m, "outlet_stage_m")
    envelope = PumpOperatingEnvelope.from_curves(
        head_curve=head_curve,
        efficiency_curve=efficiency_curve,
        running_units=units.running_units,
    )

    def values(total_flow: float) -> tuple[float, float, float]:
        per_unit = total_flow / units.running_units
        pump_head = head_curve.head_at(per_unit)
        system_head = system_loss.head_at(
            total_flow_m3s=total_flow,
            source_stage_m=source,
            outlet_stage_m=outlet,
        )
        return pump_head, system_head, pump_head - system_head

    lower = envelope.minimum_total_flow_m3s
    upper = envelope.maximum_total_flow_m3s
    lower_values = values(lower)
    upper_values = values(upper)
    if abs(lower_values[2]) <= tolerance:
        flow = lower
        pump_head, system_head, residual = lower_values
        iterations = 0
    elif abs(upper_values[2]) <= tolerance:
        flow = upper
        pump_head, system_head, residual = upper_values
        iterations = 0
    else:
        if lower_values[2] * upper_values[2] > 0.0:
            raise ValueError("Pump operating-point equation has no bracketed root")
        flow = lower
        pump_head, system_head, residual = lower_values
        for iterations in range(1, maximum_iterations + 1):
            flow = 0.5 * (lower + upper)
            pump_head, system_head, residual = values(flow)
            if abs(residual) <= tolerance:
                break
            if lower_values[2] * residual <= 0.0:
                upper = flow
            else:
                lower = flow
                lower_values = (pump_head, system_head, residual)
        else:
            raise ValueError("Pump operating-point equation did not converge")

    per_unit_flow = flow / units.running_units
    efficiency = efficiency_curve.efficiency_at(per_unit_flow)
    hydraulic_power_kw = (
        WATER_DENSITY_KG_M3
        * GRAVITY_M_S2
        * flow
        * pump_head
        / 1000.0
    )
    input_power_kw = hydraulic_power_kw / efficiency
    return PumpOperatingPointEvidence(
        evaluation_time=_finite(evaluation_time, "evaluation_time"),
        dt=_finite(dt, "dt"),
        pump_id=pump_id,
        source_stage_m=source,
        outlet_or_target_stage_m=outlet,
        running_units=units.running_units,
        total_flow_m3s=flow,
        per_unit_flow_m3s=per_unit_flow,
        pump_head_m=pump_head,
        system_head_m=system_head,
        head_residual_m=residual,
        efficiency=efficiency,
        hydraulic_power_kw=hydraulic_power_kw,
        input_power_kw=input_power_kw,
        iterations=iterations,
        curve_segment=head_curve.segment_at(per_unit_flow),
        efficiency_segment=efficiency_curve.segment_at(per_unit_flow),
        static_loss_m=system_loss.static_loss_m,
        quadratic_loss_coefficient_s2_m5=(
            system_loss.quadratic_loss_coefficient_s2_m5
        ),
    )


__all__ = [
    "GRAVITY_M_S2",
    "PUMP_CONTROL_POLICY",
    "PUMP_COUPLING_POLICY",
    "PUMP_CURVE_POLICY",
    "PUMP_EFFICIENCY_POLICY",
    "PUMP_SYSTEM_LOSS_POLICY",
    "PumpEfficiencyCurve",
    "PumpHeadCurve",
    "PumpOperatingEnvelope",
    "PumpOperatingPointEvidence",
    "PumpSystemLoss",
    "PumpUnitConfiguration",
    "WATER_DENSITY_KG_M3",
    "off_pump_evidence",
    "solve_pump_operating_point",
]
