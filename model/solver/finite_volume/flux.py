"""First-order HLL flux with a Rusanov reference implementation."""

from __future__ import annotations

import math
from dataclasses import dataclass

from model.solver.finite_volume.diagnostics import NumericalStateError
from model.solver.finite_volume.geometry import pressure_moment_from_area
from model.solver.finite_volume.mesh import SectionGeometryLike

GRAVITY = 9.81
_AREA_EPSILON = 1.0e-12


@dataclass(frozen=True)
class ConservedVector:
    """Represent one cell or reconstructed face value ``U=(A,Q)``."""

    area: float
    discharge: float

    def __post_init__(self) -> None:
        """Reject non-finite values and negative wetted area at the flux edge."""

        if not math.isfinite(self.area) or self.area < 0.0:
            raise NumericalStateError("conserved area must be finite and non-negative")
        if not math.isfinite(self.discharge):
            raise NumericalStateError("conserved discharge must be finite")
        if self.area <= _AREA_EPSILON and abs(self.discharge) > _AREA_EPSILON:
            raise NumericalStateError("a dry conserved state cannot carry discharge")


@dataclass(frozen=True)
class NumericalFlux:
    """Store mass and momentum flux in SI units."""

    mass: float
    momentum: float

    def __post_init__(self) -> None:
        """Keep non-finite numerical fluxes from entering a control volume."""

        if not math.isfinite(self.mass) or not math.isfinite(self.momentum):
            raise NumericalStateError("numerical flux must be finite")


def velocity(state: ConservedVector) -> float:
    """Return mean velocity, taking the exact dry-state value as zero."""

    return state.discharge / state.area if state.area > _AREA_EPSILON else 0.0


def wave_speed(
    state: ConservedVector,
    geometry: SectionGeometryLike,
    *,
    gravity: float = GRAVITY,
) -> float:
    """Return ``sqrt(g A/T)`` for the frozen beta=1 MVP baseline."""

    if state.area <= _AREA_EPSILON:
        return 0.0
    stage = geometry.stage_from_area(state.area)
    width = float(geometry.top_width(stage))
    if not math.isfinite(width) or width <= 0.0:
        raise NumericalStateError("a wet section must have finite positive top width")
    result = math.sqrt(gravity * state.area / width)
    if not math.isfinite(result):
        raise NumericalStateError("local gravity-wave speed is non-finite")
    return result


def maximum_signal_speed(
    state: ConservedVector,
    geometry: SectionGeometryLike,
    *,
    gravity: float = GRAVITY,
) -> float:
    """Return the local CFL speed ``|u|+c``."""

    return abs(velocity(state)) + wave_speed(state, geometry, gravity=gravity)


def physical_flux(
    state: ConservedVector,
    geometry: SectionGeometryLike,
    *,
    gravity: float = GRAVITY,
) -> NumericalFlux:
    """Evaluate ``F=(Q,Q^2/A+g I1)`` using the section pressure moment."""

    if state.area <= _AREA_EPSILON:
        return NumericalFlux(0.0, 0.0)
    pressure = gravity * pressure_moment_from_area(geometry, state.area)
    return NumericalFlux(
        mass=state.discharge,
        momentum=state.discharge * state.discharge / state.area + pressure,
    )


def hll_flux(
    left: ConservedVector,
    right: ConservedVector,
    left_geometry: SectionGeometryLike,
    right_geometry: SectionGeometryLike,
    *,
    gravity: float = GRAVITY,
) -> NumericalFlux:
    """Evaluate the two-wave Harten-Lax-van Leer numerical flux.

    Both dry returns the exact zero flux.  A one-sided wet/dry interface uses
    the wet characteristic envelope and therefore permits deterministic
    re-wetting without dividing by a dry area.
    """

    if left.area <= _AREA_EPSILON and right.area <= _AREA_EPSILON:
        return NumericalFlux(0.0, 0.0)
    left_velocity = velocity(left)
    right_velocity = velocity(right)
    left_celerity = wave_speed(left, left_geometry, gravity=gravity)
    right_celerity = wave_speed(right, right_geometry, gravity=gravity)
    speed_left = min(left_velocity - left_celerity, right_velocity - right_celerity)
    speed_right = max(left_velocity + left_celerity, right_velocity + right_celerity)
    left_flux = physical_flux(left, left_geometry, gravity=gravity)
    right_flux = physical_flux(right, right_geometry, gravity=gravity)
    if speed_left >= 0.0:
        return left_flux
    if speed_right <= 0.0:
        return right_flux
    denominator = speed_right - speed_left
    if not math.isfinite(denominator) or denominator <= _AREA_EPSILON:
        return rusanov_flux(
            left,
            right,
            left_geometry,
            right_geometry,
            gravity=gravity,
        )
    return NumericalFlux(
        mass=(
            speed_right * left_flux.mass
            - speed_left * right_flux.mass
            + speed_left * speed_right * (right.area - left.area)
        )
        / denominator,
        momentum=(
            speed_right * left_flux.momentum
            - speed_left * right_flux.momentum
            + speed_left * speed_right * (right.discharge - left.discharge)
        )
        / denominator,
    )


def rusanov_flux(
    left: ConservedVector,
    right: ConservedVector,
    left_geometry: SectionGeometryLike,
    right_geometry: SectionGeometryLike,
    *,
    gravity: float = GRAVITY,
) -> NumericalFlux:
    """Evaluate local Lax-Friedrichs flux as a diagnostic reference."""

    left_flux = physical_flux(left, left_geometry, gravity=gravity)
    right_flux = physical_flux(right, right_geometry, gravity=gravity)
    spectral_radius = max(
        maximum_signal_speed(left, left_geometry, gravity=gravity),
        maximum_signal_speed(right, right_geometry, gravity=gravity),
    )
    return NumericalFlux(
        mass=0.5 * (left_flux.mass + right_flux.mass)
        - 0.5 * spectral_radius * (right.area - left.area),
        momentum=0.5 * (left_flux.momentum + right_flux.momentum)
        - 0.5 * spectral_radius * (right.discharge - left.discharge),
    )
