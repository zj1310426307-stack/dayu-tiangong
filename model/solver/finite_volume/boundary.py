"""Dynamic Q/H boundary series with an explicit no-extrapolation contract."""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import Literal, cast

from model.solver.finite_volume.diagnostics import BoundaryCoverageError
from model.solver.finite_volume.flux import GRAVITY, ConservedVector
from model.solver.finite_volume.mesh import FiniteVolumeCell

_TIME_TOLERANCE = 1.0e-9
_AREA_EPSILON = 1.0e-12
_CRITICAL_MARGIN = 1.0e-10
_ROOT_RELATIVE_TOLERANCE = 1.0e-12
_ROOT_RESIDUAL_TOLERANCE = 1.0e-10
_REVERSE_DISCHARGE_RELATIVE_TOLERANCE = 1.0e-12
_REVERSE_DISCHARGE_ABSOLUTE_TOLERANCE = 1.0e-12

ZERO_GRADIENT_COMPANION_V1 = "zero-gradient-companion-v1"
SUBCRITICAL_CHARACTERISTIC_V1 = "subcritical-characteristic-v1"
ZERO_GRADIENT_COMPANION_ALGORITHM_V1 = (
    "companion-area-q-hll-mass-override-v1"
)
SUBCRITICAL_CHARACTERISTIC_ALGORITHM_V1 = (
    "riemann-invariant-phi-gl8-h2-bisection-positive-flow-physical-trace-v1"
)
BoundaryClosure = Literal[
    "zero-gradient-companion-v1",
    "subcritical-characteristic-v1",
]
_SUPPORTED_BOUNDARY_CLOSURES = {
    ZERO_GRADIENT_COMPANION_V1,
    SUBCRITICAL_CHARACTERISTIC_V1,
}
_BOUNDARY_ALGORITHM_IDS = {
    ZERO_GRADIENT_COMPANION_V1: ZERO_GRADIENT_COMPANION_ALGORITHM_V1,
    SUBCRITICAL_CHARACTERISTIC_V1: SUBCRITICAL_CHARACTERISTIC_ALGORITHM_V1,
}


@dataclass(frozen=True)
class CharacteristicProperties:
    """Expose one verified wet, non-reverse, strictly subcritical state."""

    velocity: float
    celerity: float
    potential: float
    froude: float

    def __post_init__(self) -> None:
        """Keep public characteristic evidence finite and self-consistent."""

        values = (self.velocity, self.celerity, self.potential, self.froude)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("characteristic properties must be finite")
        if self.velocity < 0.0 or self.celerity <= 0.0 or self.potential <= 0.0:
            raise ValueError("characteristic properties require wet non-reverse flow")
        if self.froude < 0.0 or self.froude >= 1.0:
            raise ValueError("characteristic properties must be strictly subcritical")
        if not math.isclose(
            self.froude,
            abs(self.velocity) / self.celerity,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        ):
            raise ValueError("characteristic Froude number is inconsistent")

# Eight-point Gauss-Legendre quadrature on [-1, 1].  The characteristic
# potential is integrated after h=s**2, so none of these nodes samples the
# integrable dry-bed singularity directly.
_GAUSS_LEGENDRE_8 = (
    (-0.9602898564975363, 0.1012285362903763),
    (-0.7966664774136267, 0.2223810344533745),
    (-0.5255324099163290, 0.3137066458778873),
    (-0.1834346424956498, 0.3626837833783620),
    (0.1834346424956498, 0.3626837833783620),
    (0.5255324099163290, 0.3137066458778873),
    (0.7966664774136267, 0.2223810344533745),
    (0.9602898564975363, 0.1012285362903763),
)


def _validated_closure(value: object) -> BoundaryClosure:
    """Return one frozen closure identifier or reject an unknown algorithm."""

    if value not in _SUPPORTED_BOUNDARY_CLOSURES:
        raise ValueError(f"unsupported finite-volume boundary_closure: {value!r}")
    return cast(BoundaryClosure, value)


def boundary_algorithm_id(value: object) -> str:
    """Return the provenance ID freezing one closure's numerical details."""

    return _BOUNDARY_ALGORITHM_IDS[_validated_closure(value)]


def _characteristic_potential(cell: FiniteVolumeCell, area: float) -> float:
    """Return ``Phi(A)=integral_0^A c(a)/a da`` in metres per second.

    For a rectangular section this is the analytic ``2*sqrt(g*h)``.  Other
    supported prismatic geometries use deterministic Gauss quadrature in the
    transformed coordinate ``h=s**2``.  The transform removes the dry-bed
    square-root singularity without evaluating outside the geometry domain.
    """

    if not math.isfinite(area) or area <= _AREA_EPSILON:
        raise ValueError(
            f"{SUBCRITICAL_CHARACTERISTIC_V1} requires finite positive wetted area"
        )
    geometry = cell.geometry
    stage = float(geometry.stage_from_area(area))
    minimum_stage = float(geometry.minimum_stage)
    depth = stage - minimum_stage
    if not math.isfinite(depth) or depth <= 0.0:
        raise ValueError(
            f"{SUBCRITICAL_CHARACTERISTIC_V1} requires positive water depth"
        )

    if (
        getattr(geometry, "geometry_type", None) == "rectangular"
        and hasattr(geometry, "width")
    ):
        result = 2.0 * math.sqrt(GRAVITY * depth)
        if not math.isfinite(result):
            raise ValueError("rectangular characteristic potential is non-finite")
        return result

    upper = math.sqrt(depth)
    raw_stages = getattr(geometry, "stages", None)
    if isinstance(raw_stages, tuple):
        breakpoints = [0.0]
        breakpoints.extend(
            math.sqrt(float(item) - minimum_stage)
            for item in raw_stages
            if minimum_stage < float(item) < stage
        )
        breakpoints.append(upper)
    else:
        # Unknown SectionGeometryLike implementations have no frozen table
        # knots.  A deterministic subdivision keeps the quadrature auditable.
        segment_count = 16
        breakpoints = [upper * index / segment_count for index in range(17)]

    result = 0.0
    for left, right in zip(breakpoints, breakpoints[1:]):
        if right <= left:
            continue
        midpoint = 0.5 * (left + right)
        half_width = 0.5 * (right - left)
        subtotal = 0.0
        for node, weight in _GAUSS_LEGENDRE_8:
            coordinate = midpoint + half_width * node
            local_stage = minimum_stage + coordinate * coordinate
            local_area = float(geometry.area(local_stage))
            top_width = float(geometry.top_width(local_stage))
            if (
                not math.isfinite(local_area)
                or not math.isfinite(top_width)
                or local_area <= 0.0
                or top_width <= 0.0
            ):
                raise ValueError(
                    f"{SUBCRITICAL_CHARACTERISTIC_V1} requires positive hydraulic geometry"
                )
            integrand = 2.0 * coordinate * math.sqrt(
                GRAVITY * top_width / local_area
            )
            if not math.isfinite(integrand):
                raise ValueError("characteristic quadrature produced a non-finite value")
            subtotal += weight * integrand
        result += half_width * subtotal
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError("characteristic potential must be finite and positive")
    return result


def _strictly_subcritical_characteristics(
    *,
    state: ConservedVector,
    cell: FiniteVolumeCell,
    label: str,
) -> tuple[float, float, float]:
    """Return ``(u,c,Phi)`` after a strict wet/subcritical regime gate."""

    if state.area <= _AREA_EPSILON:
        raise ValueError(
            f"{SUBCRITICAL_CHARACTERISTIC_V1} {label} state must be wet"
        )
    stage = float(cell.geometry.stage_from_area(state.area))
    top_width = float(cell.geometry.top_width(stage))
    if not math.isfinite(top_width) or top_width <= 0.0:
        raise ValueError(
            f"{SUBCRITICAL_CHARACTERISTIC_V1} {label} top width must be positive"
        )
    celerity = math.sqrt(GRAVITY * state.area / top_width)
    if not math.isfinite(celerity) or celerity <= 0.0:
        raise ValueError(
            f"{SUBCRITICAL_CHARACTERISTIC_V1} {label} wave state is non-finite"
        )
    reverse_tolerance = max(
        _REVERSE_DISCHARGE_ABSOLUTE_TOLERANCE,
        _REVERSE_DISCHARGE_RELATIVE_TOLERANCE * state.area * celerity,
    )
    if state.discharge < -reverse_tolerance:
        raise ValueError(
            f"{SUBCRITICAL_CHARACTERISTIC_V1} does not support reverse discharge "
            f"in the {label} state"
        )
    # Geometry/source cancellation can leave round-off-scale negative Q in an
    # otherwise exact lake-at-rest stage.  Normalize only that invisible band;
    # any material reverse flow already failed the scale-aware gate above.
    effective_discharge = max(state.discharge, 0.0)
    velocity = effective_discharge / state.area
    froude = abs(velocity) / celerity
    if not math.isfinite(froude) or froude >= 1.0 - _CRITICAL_MARGIN:
        raise ValueError(
            f"{SUBCRITICAL_CHARACTERISTIC_V1} {label} state must be strictly subcritical"
        )
    return velocity, celerity, _characteristic_potential(cell, state.area)


def characteristic_potential(*, cell: FiniteVolumeCell, area: float) -> float:
    """Return the versioned ``Phi(A)`` used by boundaries and Junctions."""

    return _characteristic_potential(cell, area)


def subcritical_characteristic_properties(
    *,
    state: ConservedVector,
    cell: FiniteVolumeCell,
    label: str,
) -> CharacteristicProperties:
    """Return public characteristic properties after the existing regime gate."""

    velocity, celerity, potential = _strictly_subcritical_characteristics(
        state=state,
        cell=cell,
        label=label,
    )
    return CharacteristicProperties(
        velocity=velocity,
        celerity=celerity,
        potential=potential,
        froude=abs(velocity) / celerity,
    )


def _maximum_wetted_area(cell: FiniteVolumeCell) -> float | None:
    """Return the finite section-domain ceiling, or ``None`` if unbounded."""

    maximum_stage = cell.geometry.maximum_stage
    if maximum_stage is None:
        return None
    area = float(cell.geometry.area(float(maximum_stage)))
    if not math.isfinite(area) or area <= _AREA_EPSILON:
        raise ValueError("finite section domain has no positive maximum wetted area")
    return area


def _upstream_characteristic_state(
    *,
    prescribed_discharge: float,
    interior: ConservedVector,
    cell: FiniteVolumeCell,
) -> ConservedVector:
    """Complete prescribed upstream Q with the outgoing ``u-Phi(A)``."""

    interior_velocity, interior_celerity, interior_potential = (
        _strictly_subcritical_characteristics(
            state=interior,
            cell=cell,
            label="interior",
        )
    )
    reverse_tolerance = max(
        _REVERSE_DISCHARGE_ABSOLUTE_TOLERANCE,
        _REVERSE_DISCHARGE_RELATIVE_TOLERANCE
        * interior.area
        * interior_celerity,
    )
    if prescribed_discharge < -reverse_tolerance:
        raise ValueError(
            f"{SUBCRITICAL_CHARACTERISTIC_V1} does not support reverse upstream Q"
        )
    prescribed_discharge = max(prescribed_discharge, 0.0)
    outgoing_invariant = interior_velocity - interior_potential

    def residual(area: float) -> float:
        return (
            prescribed_discharge / area
            - _characteristic_potential(cell, area)
            - outgoing_invariant
        )

    initial_value = residual(interior.area)
    initial_scale = max(
        abs(prescribed_discharge / interior.area),
        abs(interior_potential),
        abs(outgoing_invariant),
        1.0,
    )
    if abs(initial_value) <= _ROOT_RELATIVE_TOLERANCE * initial_scale:
        area = interior.area
    else:
        if initial_value < 0.0:
            # The root is shallower than the interior state.  Bracket it by
            # halving only through valid wet geometry; never evaluate at a
            # machine-epsilon area where a tabulated inverse rounds to dry.
            upper = interior.area
            lower = 0.5 * upper
            for _ in range(128):
                try:
                    lower_value = residual(lower)
                except ValueError as exc:
                    raise ValueError(
                        f"{SUBCRITICAL_CHARACTERISTIC_V1} upstream Q has no "
                        "positive root in the supported wet geometry"
                    ) from exc
                if lower_value > 0.0:
                    break
                upper = lower
                lower *= 0.5
            else:
                raise ValueError(
                    f"{SUBCRITICAL_CHARACTERISTIC_V1} upstream Q has no positive root"
                )
        else:
            # The root is deeper than the interior state.  Respect any finite
            # bank ceiling and otherwise expand the unbounded wet domain.
            lower = interior.area
            maximum_area = _maximum_wetted_area(cell)
            if maximum_area is not None:
                upper = maximum_area
                upper_value = residual(upper)
                if upper_value > 0.0:
                    raise ValueError(
                        f"{SUBCRITICAL_CHARACTERISTIC_V1} upstream Q root lies "
                        "outside the section domain"
                    )
            else:
                upper = max(2.0 * interior.area, 1.0)
                upper_value = residual(upper)
                for _ in range(128):
                    if upper_value <= 0.0:
                        break
                    upper *= 2.0
                    if not math.isfinite(upper):
                        break
                    upper_value = residual(upper)
                else:
                    raise ValueError(
                        f"{SUBCRITICAL_CHARACTERISTIC_V1} upstream Q root was not bracketed"
                    )
                if not math.isfinite(upper) or not math.isfinite(upper_value):
                    raise ValueError(
                        f"{SUBCRITICAL_CHARACTERISTIC_V1} upstream Q root is non-finite"
                    )

        for _ in range(128):
            midpoint = 0.5 * (lower + upper)
            value = residual(midpoint)
            if value > 0.0:
                lower = midpoint
            else:
                upper = midpoint
            if upper - lower <= _ROOT_RELATIVE_TOLERANCE * max(midpoint, 1.0):
                break
        area = 0.5 * (lower + upper)
    candidate = ConservedVector(area, prescribed_discharge)
    velocity, _, potential = _strictly_subcritical_characteristics(
        state=candidate,
        cell=cell,
        label="completed upstream",
    )
    invariant_residual = velocity - potential - outgoing_invariant
    scale = max(abs(velocity), abs(potential), abs(outgoing_invariant), 1.0)
    if abs(invariant_residual) > _ROOT_RESIDUAL_TOLERANCE * scale:
        raise ValueError(
            f"{SUBCRITICAL_CHARACTERISTIC_V1} upstream invariant residual is too large"
        )
    return candidate


def _downstream_characteristic_state(
    *,
    prescribed_stage: float,
    interior: ConservedVector,
    cell: FiniteVolumeCell,
) -> ConservedVector:
    """Complete prescribed downstream H with the outgoing ``u+Phi(A)``."""

    interior_velocity, _, interior_potential = _strictly_subcritical_characteristics(
        state=interior,
        cell=cell,
        label="interior",
    )
    minimum_stage = float(cell.geometry.minimum_stage)
    maximum_stage = cell.geometry.maximum_stage
    if prescribed_stage <= minimum_stage:
        raise ValueError(
            f"{SUBCRITICAL_CHARACTERISTIC_V1} downstream H must be above the bed"
        )
    if maximum_stage is not None and prescribed_stage > float(maximum_stage):
        raise ValueError(
            f"{SUBCRITICAL_CHARACTERISTIC_V1} downstream H lies outside the section domain"
        )
    area = float(cell.geometry.area(prescribed_stage))
    potential = _characteristic_potential(cell, area)
    outgoing_invariant = interior_velocity + interior_potential
    discharge = area * (outgoing_invariant - potential)
    candidate = ConservedVector(area, discharge)
    velocity, _, candidate_potential = _strictly_subcritical_characteristics(
        state=candidate,
        cell=cell,
        label="completed downstream",
    )
    invariant_residual = velocity + candidate_potential - outgoing_invariant
    scale = max(
        abs(velocity),
        abs(candidate_potential),
        abs(outgoing_invariant),
        1.0,
    )
    if abs(invariant_residual) > _ROOT_RESIDUAL_TOLERANCE * scale:
        raise ValueError(
            f"{SUBCRITICAL_CHARACTERISTIC_V1} downstream invariant residual is too large"
        )
    if candidate.discharge < 0.0:
        candidate = ConservedVector(candidate.area, 0.0)
    return candidate


@dataclass(frozen=True)
class BoundarySeries:
    """Store a finite, strictly ordered, piecewise-linear boundary process."""

    times: tuple[float, ...]
    values: tuple[float, ...]
    variable: Literal["discharge", "stage"]

    def __post_init__(self) -> None:
        """Validate the full interpolation domain before time integration."""

        object.__setattr__(self, "times", tuple(float(item) for item in self.times))
        object.__setattr__(self, "values", tuple(float(item) for item in self.values))
        if len(self.times) != len(self.values) or not self.times:
            raise ValueError("boundary times and values must have the same non-zero length")
        if any(not math.isfinite(item) for item in (*self.times, *self.values)):
            raise ValueError("boundary series must contain only finite values")
        if any(right <= left for left, right in zip(self.times, self.times[1:])):
            raise ValueError("boundary times must be strictly increasing")

    @property
    def start_time(self) -> float:
        """Return the first time at which interpolation is defined."""

        return self.times[0]

    @property
    def end_time(self) -> float:
        """Return the final time at which interpolation is defined."""

        return self.times[-1]

    def value_at(self, time: float) -> float:
        """Interpolate inside the closed domain and reject all extrapolation."""

        if not math.isfinite(time):
            raise BoundaryCoverageError("boundary evaluation time must be finite")
        if time < self.start_time - _TIME_TOLERANCE or time > self.end_time + _TIME_TOLERANCE:
            raise BoundaryCoverageError(
                f"{self.variable} boundary time {time} is outside "
                f"[{self.start_time}, {self.end_time}]"
            )
        if time <= self.start_time + _TIME_TOLERANCE:
            return self.values[0]
        if time >= self.end_time - _TIME_TOLERANCE:
            return self.values[-1]
        right = bisect.bisect_right(self.times, time)
        left = right - 1
        ratio = (time - self.times[left]) / (self.times[right] - self.times[left])
        return self.values[left] + ratio * (self.values[right] - self.values[left])

    def validate_coverage(self, start_time: float, end_time: float) -> None:
        """Fail preflight when a requested run would need extrapolation."""

        if end_time < start_time:
            raise ValueError("boundary coverage end_time must not precede start_time")
        self.value_at(start_time)
        self.value_at(end_time)

    def next_breakpoint_after(self, time: float) -> float | None:
        """Return the next series knot so a time step can land on it exactly."""

        index = bisect.bisect_right(self.times, time + _TIME_TOLERANCE)
        return self.times[index] if index < len(self.times) else None


@dataclass(frozen=True)
class UpstreamDischargeBoundary:
    """Prescribe upstream Q while retaining the interior companion stage."""

    series: BoundarySeries
    boundary_closure: BoundaryClosure = ZERO_GRADIENT_COMPANION_V1

    def __post_init__(self) -> None:
        """Prevent accidental binding of an H series to a Q boundary."""

        if self.series.variable != "discharge":
            raise ValueError("upstream discharge boundary requires a discharge series")
        object.__setattr__(
            self,
            "boundary_closure",
            _validated_closure(self.boundary_closure),
        )

    def ghost_state(
        self,
        *,
        time: float,
        interior: ConservedVector,
        cell: FiniteVolumeCell,
    ) -> ConservedVector:
        """Build a versioned upstream ghost/face state in SI units.

        The default retains the original zero-gradient companion area exactly.
        ``subcritical-characteristic-v1`` instead preserves the outgoing
        ``u-Phi(A)`` Riemann invariant and solves the positive area associated
        with prescribed ``Q``.
        """

        prescribed_discharge = self.series.value_at(time)
        if self.boundary_closure == ZERO_GRADIENT_COMPANION_V1:
            del cell
            return ConservedVector(interior.area, prescribed_discharge)
        return _upstream_characteristic_state(
            prescribed_discharge=prescribed_discharge,
            interior=interior,
            cell=cell,
        )


@dataclass(frozen=True)
class DownstreamStageBoundary:
    """Prescribe downstream absolute H while retaining companion discharge."""

    series: BoundarySeries
    boundary_closure: BoundaryClosure = ZERO_GRADIENT_COMPANION_V1

    def __post_init__(self) -> None:
        """Prevent accidental binding of a Q series to an H boundary."""

        if self.series.variable != "stage":
            raise ValueError("downstream stage boundary requires a stage series")
        object.__setattr__(
            self,
            "boundary_closure",
            _validated_closure(self.boundary_closure),
        )

    def ghost_state(
        self,
        *,
        time: float,
        interior: ConservedVector,
        cell: FiniteVolumeCell,
    ) -> ConservedVector:
        """Build a versioned downstream ghost/face state in SI units.

        The default retains the original companion discharge exactly.
        ``subcritical-characteristic-v1`` instead preserves the outgoing
        ``u+Phi(A)`` Riemann invariant at prescribed absolute stage ``H``.
        """

        stage = self.series.value_at(time)
        if self.boundary_closure == SUBCRITICAL_CHARACTERISTIC_V1:
            return _downstream_characteristic_state(
                prescribed_stage=stage,
                interior=interior,
                cell=cell,
            )
        area = float(cell.geometry.area(stage))
        return ConservedVector(area, interior.discharge if area > 1.0e-12 else 0.0)


@dataclass(frozen=True)
class BoundaryPair:
    """Bind the two MVP open boundaries and coordinate their time domains."""

    upstream: UpstreamDischargeBoundary
    downstream: DownstreamStageBoundary

    def __post_init__(self) -> None:
        """Reject mixed closure algorithms inside one scientific run."""

        if self.upstream.boundary_closure != self.downstream.boundary_closure:
            raise ValueError(
                "upstream and downstream boundary_closure versions must match"
            )

    @property
    def boundary_closure(self) -> BoundaryClosure:
        """Return the common, explicitly versioned boundary algorithm."""

        return self.upstream.boundary_closure

    @property
    def boundary_algorithm_id(self) -> str:
        """Return the exact numerical algorithm identity for provenance."""

        return boundary_algorithm_id(self.boundary_closure)

    def validate_coverage(self, start_time: float, end_time: float) -> None:
        """Require both Q and H to cover the complete requested run."""

        self.upstream.series.validate_coverage(start_time, end_time)
        self.downstream.series.validate_coverage(start_time, end_time)

    def next_breakpoint_after(self, time: float) -> float | None:
        """Return the earliest future knot across upstream and downstream data."""

        candidates = (
            self.upstream.series.next_breakpoint_after(time),
            self.downstream.series.next_breakpoint_after(time),
        )
        available = [item for item in candidates if item is not None]
        return min(available) if available else None
