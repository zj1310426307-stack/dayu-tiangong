"""Semi-implicit Manning friction for a cell-centred conserved state."""

from __future__ import annotations

import math

from model.solver.finite_volume.diagnostics import NumericalStateError
from model.solver.finite_volume.flux import GRAVITY
from model.solver.finite_volume.mesh import FiniteVolumeMesh, SectionGeometryLike

_EPSILON = 1.0e-12


def semi_implicit_manning(
    *,
    area: float,
    discharge: float,
    geometry: SectionGeometryLike,
    manning_n: float,
    dt: float,
    gravity: float = GRAVITY,
) -> float:
    """Apply the sign-preserving linearised Manning momentum sink.

    For the cell ODE ``dQ/dt=-k Q|Q|``, the accepted MVP update is
    ``Q_new=Q_star/(1+dt*k*|Q_star|)``.  Friction is recomputed in every
    forward-Euler stage used by SSP-RK2.  This is deliberately described as a
    semi-implicit stage update, not as a proven globally second-order IMEX
    discretisation.
    """

    if not all(math.isfinite(value) for value in (area, discharge, manning_n, dt)):
        raise NumericalStateError("Manning update inputs must be finite")
    if area < 0.0 or manning_n < 0.0 or dt <= 0.0:
        raise NumericalStateError("Manning update requires A>=0, n>=0 and dt>0")
    if area <= _EPSILON:
        if abs(discharge) > _EPSILON:
            raise NumericalStateError("dry cell cannot discard non-zero discharge in friction")
        return 0.0
    if manning_n == 0.0 or discharge == 0.0:
        return discharge
    stage = geometry.stage_from_area(area)
    radius = float(geometry.hydraulic_radius(stage))
    if not math.isfinite(radius) or radius <= 0.0:
        raise NumericalStateError("wet cell hydraulic radius must be finite and positive")
    coefficient = gravity * manning_n * manning_n / (area * radius ** (4.0 / 3.0))
    denominator = 1.0 + dt * coefficient * abs(discharge)
    result = discharge / denominator
    if not math.isfinite(result):
        raise NumericalStateError("semi-implicit Manning update produced a non-finite Q")
    return result


def apply_manning_friction(
    *,
    mesh: FiniteVolumeMesh,
    area: tuple[float, ...] | list[float],
    discharge: tuple[float, ...] | list[float],
    dt: float,
) -> tuple[float, ...]:
    """Apply the cell-local semi-implicit update to one complete branch."""

    if len(area) != len(mesh.cells) or len(discharge) != len(mesh.cells):
        raise ValueError("friction arrays must match the mesh cell count")
    return tuple(
        semi_implicit_manning(
            area=float(cell_area),
            discharge=float(cell_discharge),
            geometry=cell.geometry,
            manning_n=cell.manning_n,
            dt=dt,
        )
        for cell, cell_area, cell_discharge in zip(mesh.cells, area, discharge)
    )
