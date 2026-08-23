"""Hydrostatic reconstruction and well-balanced face flux corrections."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from model.solver.finite_volume.diagnostics import NumericalStateError
from model.solver.finite_volume.flux import (
    GRAVITY,
    ConservedVector,
    hll_flux,
    rusanov_flux,
)
from model.solver.finite_volume.geometry import pressure_moment_from_area
from model.solver.finite_volume.mesh import FiniteVolumeCell

_EPSILON = 1.0e-12


@dataclass(frozen=True)
class HydrostaticReconstruction:
    """Hold reconstructed face states and side-specific pressure corrections."""

    left: ConservedVector
    right: ConservedVector
    left_pressure_correction: float
    right_pressure_correction: float


@dataclass(frozen=True)
class InterfaceFlux:
    """Expose common mass flux and momentum flux seen by each adjacent cell."""

    mass: float
    momentum_left: float
    momentum_right: float

    def __post_init__(self) -> None:
        """Reject any interface contribution that is not finite."""

        if not all(
            math.isfinite(value)
            for value in (self.mass, self.momentum_left, self.momentum_right)
        ):
            raise NumericalStateError("hydrostatic interface flux must be finite")


def _area_above_interface(
    cell: FiniteVolumeCell,
    state: ConservedVector,
    interface_bed: float,
) -> float:
    """Remove the hydrostatic area below the higher adjacent bed elevation."""

    if state.area <= _EPSILON:
        return 0.0
    # ``interface_bed`` is selected from one of the two cell beds.  On the
    # higher side (and on every flat-bed face) reconstruction is the identity,
    # so avoid repeating geometry inversion and area evaluation at every RK
    # stage.  Exact equality keeps this as a numerical no-op, not a tolerance-
    # based change to the frozen hydrostatic reconstruction semantics.
    if (
        interface_bed == cell.bed_elevation
        and cell.bed_elevation == float(cell.geometry.minimum_stage)
    ):
        return state.area
    stage = cell.geometry.stage_from_area(state.area)
    if stage <= interface_bed + _EPSILON:
        return 0.0
    clipped_bed = max(interface_bed, cell.geometry.minimum_stage)
    base_area = float(cell.geometry.area(clipped_bed))
    result = max(state.area - base_area, 0.0)
    if not math.isfinite(result):
        raise NumericalStateError("reconstructed area is non-finite")
    return result


def _pressure_correction(
    cell: FiniteVolumeCell,
    original_area: float,
    reconstructed_area: float,
    *,
    gravity: float,
) -> float:
    """Return the bed-step pressure source, skipping an exact identity."""

    if reconstructed_area == original_area:
        return 0.0
    return gravity * (
        pressure_moment_from_area(cell.geometry, original_area)
        - pressure_moment_from_area(cell.geometry, reconstructed_area)
    )


def hydrostatic_reconstruct(
    left_state: ConservedVector,
    right_state: ConservedVector,
    left_cell: FiniteVolumeCell,
    right_cell: FiniteVolumeCell,
    *,
    gravity: float = GRAVITY,
) -> HydrostaticReconstruction:
    """Build non-negative interface states over the higher neighbouring bed.

    The discharge is scaled with reconstructed area to preserve the original
    velocity.  Side-specific pressure corrections provide the matching bed
    source for the first-order lake-at-rest baseline.
    """

    interface_bed = max(left_cell.bed_elevation, right_cell.bed_elevation)
    left_area = _area_above_interface(left_cell, left_state, interface_bed)
    right_area = _area_above_interface(right_cell, right_state, interface_bed)
    left_discharge = (
        left_state.discharge * left_area / left_state.area
        if left_state.area > _EPSILON and left_area > _EPSILON
        else 0.0
    )
    right_discharge = (
        right_state.discharge * right_area / right_state.area
        if right_state.area > _EPSILON and right_area > _EPSILON
        else 0.0
    )
    left_star = ConservedVector(left_area, left_discharge)
    right_star = ConservedVector(right_area, right_discharge)

    left_correction = _pressure_correction(
        left_cell,
        left_state.area,
        left_area,
        gravity=gravity,
    )
    right_correction = _pressure_correction(
        right_cell,
        right_state.area,
        right_area,
        gravity=gravity,
    )
    return HydrostaticReconstruction(
        left=left_star,
        right=right_star,
        left_pressure_correction=left_correction,
        right_pressure_correction=right_correction,
    )


def hydrostatic_interface_flux(
    left_state: ConservedVector,
    right_state: ConservedVector,
    left_cell: FiniteVolumeCell,
    right_cell: FiniteVolumeCell,
    *,
    scheme: Literal["hll", "rusanov"] = "hll",
    gravity: float = GRAVITY,
) -> InterfaceFlux:
    """Return a well-balanced face flux using HLL or the Rusanov reference."""

    reconstruction = hydrostatic_reconstruct(
        left_state,
        right_state,
        left_cell,
        right_cell,
        gravity=gravity,
    )
    if scheme == "hll":
        common = hll_flux(
            reconstruction.left,
            reconstruction.right,
            left_cell.geometry,
            right_cell.geometry,
            gravity=gravity,
        )
    elif scheme == "rusanov":
        common = rusanov_flux(
            reconstruction.left,
            reconstruction.right,
            left_cell.geometry,
            right_cell.geometry,
            gravity=gravity,
        )
    else:
        raise ValueError(f"unsupported finite-volume flux scheme: {scheme}")
    return InterfaceFlux(
        mass=common.mass,
        momentum_left=common.momentum + reconstruction.left_pressure_correction,
        momentum_right=common.momentum + reconstruction.right_pressure_correction,
    )
