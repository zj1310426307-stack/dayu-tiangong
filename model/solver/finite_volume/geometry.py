"""Hydrostatic pressure helpers that adapt the existing section contract."""

from __future__ import annotations

import math

from model.solver.finite_volume.mesh import SectionGeometryLike


def pressure_moment(
    geometry: SectionGeometryLike,
    stage: float,
    *,
    integration_panels: int = 64,
) -> float:
    """Return the positive hydrostatic first moment ``I1`` in cubic metres.

    A geometry that exposes a native ``pressure_moment(stage)`` method remains
    authoritative.  Existing A/T/P/R geometries are supported additively via
    the identity ``I1(H) = integral(A(z), dz)``.  Composite Simpson integration
    is exact for the current piecewise-linear area tables at aligned knots and
    provides a deterministic compatibility path until those tables carry I1.
    """

    if not math.isfinite(stage):
        raise ValueError("pressure-moment stage must be finite")
    minimum = float(geometry.minimum_stage)
    maximum = geometry.maximum_stage
    if stage < minimum - 1.0e-12:
        raise ValueError("pressure-moment stage is below geometry.minimum_stage")
    if maximum is not None and stage > float(maximum) + 1.0e-12:
        raise ValueError("pressure-moment stage is above geometry.maximum_stage")
    if stage <= minimum:
        return 0.0

    native = getattr(geometry, "pressure_moment", None)
    if callable(native):
        value = float(native(stage))
        if not math.isfinite(value) or value < 0.0:
            raise ValueError("geometry pressure_moment must be finite and non-negative")
        return value

    if integration_panels < 2:
        raise ValueError("integration_panels must be at least two")
    panels = integration_panels + integration_panels % 2
    dz = (stage - minimum) / panels
    total = float(geometry.area(minimum)) + float(geometry.area(stage))
    for index in range(1, panels):
        weight = 4.0 if index % 2 else 2.0
        total += weight * float(geometry.area(minimum + index * dz))
    value = dz * total / 3.0
    if not math.isfinite(value) or value < -1.0e-12:
        raise ValueError("integrated pressure moment is invalid")
    return max(value, 0.0)


def pressure_moment_from_area(geometry: SectionGeometryLike, area: float) -> float:
    """Invert area once and evaluate the matching hydrostatic first moment."""

    if not math.isfinite(area) or area < 0.0:
        raise ValueError("pressure-moment area must be finite and non-negative")
    return pressure_moment(geometry, geometry.stage_from_area(area))
