"""First-order HLL flux with a Rusanov reference implementation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from threading import local

from model.solver.finite_volume.diagnostics import NumericalStateError
from model.solver.finite_volume.geometry import pressure_moment, pressure_moment_from_area
from model.solver.finite_volume.mesh import SectionGeometryLike

GRAVITY = 9.81
_AREA_EPSILON = 1.0e-12
_FLUX_PROPERTY_CACHE_LIMIT = 4096
_FLUX_PROPERTY_CACHE = local()


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


def _evaluate_flux_state_properties(
    state: ConservedVector,
    geometry: SectionGeometryLike,
    *,
    gravity: float,
) -> tuple[float, float, NumericalFlux]:
    """Evaluate velocity, celerity and physical flux with one area inversion."""

    if state.area <= _AREA_EPSILON:
        return 0.0, 0.0, NumericalFlux(0.0, 0.0)
    stage = geometry.stage_from_area(state.area)
    width = float(geometry.top_width(stage))
    if not math.isfinite(width) or width <= 0.0:
        raise NumericalStateError("a wet section must have finite positive top width")
    local_velocity = state.discharge / state.area
    celerity = math.sqrt(gravity * state.area / width)
    pressure = gravity * pressure_moment(geometry, stage)
    flux = NumericalFlux(
        mass=state.discharge,
        momentum=state.discharge * state.discharge / state.area + pressure,
    )
    if not math.isfinite(celerity):
        raise NumericalStateError("local gravity-wave speed is non-finite")
    return local_velocity, celerity, flux


def _flux_state_properties(
    state: ConservedVector,
    geometry: SectionGeometryLike,
    *,
    gravity: float,
) -> tuple[float, float, NumericalFlux]:
    """Return combined face properties with a bounded exact-value cache.

    HLL and Rusanov consume all three quantities for each side of a face.  The
    public helpers remain independent, while this internal combined path avoids
    repeating ``stage_from_area`` for wave speed and hydrostatic pressure.  A
    cell state is also consumed by its left and right faces, so a small
    thread-local exact-key cache reuses that evaluation.  The key uses geometry
    identity rather than hashing all tabulated points; the cached value retains
    the object and checks identity to make Python object-id reuse harmless.
    """

    dataclass_parameters = getattr(type(geometry), "__dataclass_params__", None)
    if dataclass_parameters is None or not dataclass_parameters.frozen:
        return _evaluate_flux_state_properties(state, geometry, gravity=gravity)
    cache = getattr(_FLUX_PROPERTY_CACHE, "values", None)
    if cache is None:
        cache = {}
        _FLUX_PROPERTY_CACHE.values = cache
    key = (id(geometry), state.area, state.discharge, gravity)
    cached = cache.get(key)
    if cached is not None and cached[0] is geometry:
        return cached[1]
    evaluated = _evaluate_flux_state_properties(state, geometry, gravity=gravity)
    if len(cache) >= _FLUX_PROPERTY_CACHE_LIMIT:
        cache.clear()
    cache[key] = (geometry, evaluated)
    return evaluated


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
    left_velocity, left_celerity, left_flux = _flux_state_properties(
        left,
        left_geometry,
        gravity=gravity,
    )
    right_velocity, right_celerity, right_flux = _flux_state_properties(
        right,
        right_geometry,
        gravity=gravity,
    )
    speed_left = min(left_velocity - left_celerity, right_velocity - right_celerity)
    speed_right = max(left_velocity + left_celerity, right_velocity + right_celerity)
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

    left_velocity, left_celerity, left_flux = _flux_state_properties(
        left,
        left_geometry,
        gravity=gravity,
    )
    right_velocity, right_celerity, right_flux = _flux_state_properties(
        right,
        right_geometry,
        gravity=gravity,
    )
    spectral_radius = max(
        abs(left_velocity) + left_celerity,
        abs(right_velocity) + right_celerity,
    )
    return NumericalFlux(
        mass=0.5 * (left_flux.mass + right_flux.mass)
        - 0.5 * spectral_radius * (right.area - left.area),
        momentum=0.5 * (left_flux.momentum + right_flux.momentum)
        - 0.5 * spectral_radius * (right.discharge - left.discharge),
    )
