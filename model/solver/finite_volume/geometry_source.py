"""Versioned hydraulic-function path for non-prismatic section geometry.

The original hydrostatic reconstruction remains the default finite-volume
operator.  This module provides an explicit first-order path-conservative
reference for neighbouring sections whose hydraulic functions differ.  It
uses one linearly interpolated hydraulic geometry per face and a matching
cell-centred pressure source.  The pair exactly preserves a fully wet
lake-at-rest state while keeping unsupported higher-order geometry claims out
of the MVP contract.
"""

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
from model.solver.finite_volume.geometry import pressure_moment
from model.solver.finite_volume.mesh import (
    FiniteVolumeCell,
    FiniteVolumeMesh,
    SectionGeometryLike,
)
from model.solver.finite_volume.reconstruction import InterfaceFlux

_AREA_TOLERANCE = 1.0e-12
_STAGE_TOLERANCE = 1.0e-12


def _maximum_stage(geometry: SectionGeometryLike) -> float | None:
    """Return a finite optional geometry ceiling and reject invalid metadata."""

    maximum = geometry.maximum_stage
    if maximum is None:
        return None
    value = float(maximum)
    if not math.isfinite(value):
        raise NumericalStateError("section maximum_stage must be finite or None")
    return value


def _bounded_value(
    geometry: SectionGeometryLike,
    method_name: str,
    stage: float,
) -> float:
    """Evaluate one hydraulic function, treating stages below its bed as dry."""

    minimum = float(geometry.minimum_stage)
    if stage <= minimum + _STAGE_TOLERANCE:
        return 0.0
    maximum = _maximum_stage(geometry)
    if maximum is not None and stage > maximum + _STAGE_TOLERANCE:
        raise NumericalStateError(
            f"face stage {stage} exceeds section maximum_stage {maximum}"
        )
    bounded = min(stage, maximum) if maximum is not None else stage
    method = getattr(geometry, method_name, None)
    if not callable(method):
        if method_name == "pressure_moment":
            value = pressure_moment(geometry, bounded)
        else:
            raise TypeError(f"section geometry does not provide {method_name}")
    else:
        value = float(method(bounded))
    if not math.isfinite(value) or value < 0.0:
        raise NumericalStateError(
            f"section {method_name} must be finite and non-negative"
        )
    return value


@dataclass(frozen=True)
class LinearHydraulicFaceGeometry:
    """Interpolate neighbouring hydraulic functions along one numerical path.

    The object is a face quadrature rule, not a new surveyed cross-section.  A
    value of ``right_weight`` equal to 0.5 is the midpoint path for equal cell
    lengths.  Non-uniform cells use the physical face position between cell
    centres.  All evaluations remain on the shared absolute vertical datum.
    """

    left: SectionGeometryLike
    right: SectionGeometryLike
    right_weight: float
    geometry_type: str = "hydraulic-function-linear-face-v1"

    def __post_init__(self) -> None:
        """Require a valid interpolation weight and overlapping stage domain."""

        if not 0.0 <= self.right_weight <= 1.0:
            raise ValueError("right_weight must lie in [0, 1]")
        if self.maximum_stage is not None and self.maximum_stage <= self.minimum_stage:
            raise ValueError("face geometries do not share a positive stage domain")

    @property
    def minimum_stage(self) -> float:
        """Return the lowest bed represented by either endpoint function."""

        return min(float(self.left.minimum_stage), float(self.right.minimum_stage))

    @property
    def maximum_stage(self) -> float | None:
        """Return the common no-extrapolation bank ceiling."""

        values = tuple(
            value
            for value in (_maximum_stage(self.left), _maximum_stage(self.right))
            if value is not None
        )
        return min(values) if values else None

    def _blend(self, method_name: str, stage: float) -> float:
        """Linearly combine endpoint hydraulic functions at an absolute stage."""

        if not math.isfinite(stage):
            raise NumericalStateError("face stage must be finite")
        if stage < self.minimum_stage - _STAGE_TOLERANCE:
            raise NumericalStateError("face stage lies below the hydraulic path")
        left = _bounded_value(self.left, method_name, stage)
        right = _bounded_value(self.right, method_name, stage)
        value = (1.0 - self.right_weight) * left + self.right_weight * right
        if not math.isfinite(value) or value < 0.0:
            raise NumericalStateError("interpolated face geometry is invalid")
        return value

    def area(self, stage: float) -> float:
        """Return linearly interpolated wetted area in square metres."""

        return self._blend("area", stage)

    def top_width(self, stage: float) -> float:
        """Return linearly interpolated wetted top width in metres."""

        return self._blend("top_width", stage)

    def wetted_perimeter(self, stage: float) -> float:
        """Return linearly interpolated wetted perimeter in metres."""

        return self._blend("wetted_perimeter", stage)

    def hydraulic_radius(self, stage: float) -> float:
        """Return the face hydraulic radius for protocol completeness."""

        area = self.area(stage)
        perimeter = self.wetted_perimeter(stage)
        return area / max(perimeter, _AREA_TOLERANCE)

    def pressure_moment(self, stage: float) -> float:
        """Return linearly interpolated hydrostatic first moment ``I1``."""

        return self._blend("pressure_moment", stage)

    def stage_from_area(self, area: float) -> float:
        """Invert the monotone interpolated area relation without extrapolation."""

        if not math.isfinite(area) or area < 0.0:
            raise NumericalStateError("face area must be finite and non-negative")
        if area <= _AREA_TOLERANCE:
            return self.minimum_stage
        lower = self.minimum_stage
        upper = self.maximum_stage
        if upper is None:
            upper = lower + 1.0
            for _ in range(80):
                if self.area(upper) >= area:
                    break
                upper = lower + 2.0 * (upper - lower)
            else:
                raise NumericalStateError("could not bracket interpolated face area")
        maximum_area = self.area(upper)
        if area > maximum_area + _AREA_TOLERANCE:
            raise NumericalStateError(
                f"face area {area} exceeds the shared hydraulic range {maximum_area}"
            )
        for _ in range(80):
            middle = 0.5 * (lower + upper)
            if self.area(middle) < area:
                lower = middle
            else:
                upper = middle
        return 0.5 * (lower + upper)


def internal_face_geometry(
    left_cell: FiniteVolumeCell,
    right_cell: FiniteVolumeCell,
) -> LinearHydraulicFaceGeometry:
    """Build the deterministic linear hydraulic path at one cell face."""

    weight = left_cell.dx / (left_cell.dx + right_cell.dx)
    return LinearHydraulicFaceGeometry(
        left=left_cell.geometry,
        right=right_cell.geometry,
        right_weight=weight,
    )


def mesh_face_geometries(
    mesh: FiniteVolumeMesh,
) -> tuple[SectionGeometryLike, ...]:
    """Return boundary and internal face geometries in mesh-face order."""

    geometries: list[SectionGeometryLike] = [mesh.cells[0].geometry]
    geometries.extend(
        internal_face_geometry(left, right)
        for left, right in zip(mesh.cells, mesh.cells[1:])
    )
    geometries.append(mesh.cells[-1].geometry)
    return tuple(geometries)


def hydraulic_path_interface_flux(
    left_state: ConservedVector,
    right_state: ConservedVector,
    left_cell: FiniteVolumeCell,
    right_cell: FiniteVolumeCell,
    *,
    scheme: Literal["hll", "rusanov"] = "hll",
    gravity: float = GRAVITY,
) -> InterfaceFlux:
    """Evaluate a common-geometry face flux for non-prismatic neighbours.

    Both cell stages are projected to the same face hydraulic geometry while
    discharge is retained.  Equal absolute stage and zero discharge therefore
    become identical face states even when endpoint areas differ, eliminating
    the artificial HLL mass diffusion that otherwise destroys lake at rest.
    """

    geometry = internal_face_geometry(left_cell, right_cell)
    left_stage = left_cell.geometry.stage_from_area(left_state.area)
    right_stage = right_cell.geometry.stage_from_area(right_state.area)
    left_area = geometry.area(left_stage)
    right_area = geometry.area(right_stage)
    left = ConservedVector(
        left_area,
        left_state.discharge if left_area > _AREA_TOLERANCE else 0.0,
    )
    right = ConservedVector(
        right_area,
        right_state.discharge if right_area > _AREA_TOLERANCE else 0.0,
    )
    if scheme == "hll":
        flux = hll_flux(left, right, geometry, geometry, gravity=gravity)
    elif scheme == "rusanov":
        flux = rusanov_flux(left, right, geometry, geometry, gravity=gravity)
    else:
        raise ValueError(f"unsupported finite-volume flux scheme: {scheme}")
    return InterfaceFlux(
        mass=flux.mass,
        momentum_left=flux.momentum,
        momentum_right=flux.momentum,
    )


def geometry_pressure_source(
    *,
    cell: FiniteVolumeCell,
    state: ConservedVector,
    left_face_geometry: SectionGeometryLike,
    right_face_geometry: SectionGeometryLike,
    gravity: float = GRAVITY,
) -> float:
    """Return the matching hydrostatic geometry source for one control volume."""

    if state.area <= _AREA_TOLERANCE:
        return 0.0
    stage = cell.geometry.stage_from_area(state.area)
    left_moment = pressure_moment(left_face_geometry, stage)
    right_moment = pressure_moment(right_face_geometry, stage)
    source = gravity * (right_moment - left_moment) / cell.dx
    if not math.isfinite(source):
        raise NumericalStateError("non-prismatic geometry source is non-finite")
    return source


__all__ = [
    "LinearHydraulicFaceGeometry",
    "geometry_pressure_source",
    "hydraulic_path_interface_flux",
    "internal_face_geometry",
    "mesh_face_geometries",
]
