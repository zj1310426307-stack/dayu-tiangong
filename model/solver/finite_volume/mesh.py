"""Static cell-centred mesh contracts for one ordered river branch."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class SectionGeometryLike(Protocol):
    """Describe the reversible SI geometry required by the FV kernel."""

    minimum_stage: float
    maximum_stage: float | None

    def area(self, stage: float) -> float:
        """Return wetted area in square metres at an absolute stage."""

    def top_width(self, stage: float) -> float:
        """Return wetted top width in metres at an absolute stage."""

    def hydraulic_radius(self, stage: float) -> float:
        """Return hydraulic radius in metres at an absolute stage."""

    def stage_from_area(self, area: float) -> float:
        """Invert a non-negative wetted area to an absolute stage."""


@dataclass(frozen=True)
class FiniteVolumeCell:
    """Hold immutable geometry and material data for one control volume."""

    cell_id: str
    dx: float
    section_id: str | int
    bed_elevation: float
    geometry: SectionGeometryLike
    manning_n: float = 0.0

    def __post_init__(self) -> None:
        """Reject an invalid cell before it can contaminate a time step."""

        if not self.cell_id:
            raise ValueError("cell_id must not be empty")
        if not math.isfinite(self.dx) or self.dx <= 0.0:
            raise ValueError(f"cell {self.cell_id} dx must be finite and positive")
        if not math.isfinite(self.bed_elevation):
            raise ValueError(f"cell {self.cell_id} bed elevation must be finite")
        if not math.isfinite(self.manning_n) or self.manning_n < 0.0:
            raise ValueError(f"cell {self.cell_id} Manning n must be finite and non-negative")
        if not isinstance(self.geometry, SectionGeometryLike):
            raise TypeError(f"cell {self.cell_id} geometry does not satisfy SectionGeometryLike")
        if not math.isclose(
            self.bed_elevation,
            float(self.geometry.minimum_stage),
            rel_tol=0.0,
            abs_tol=1.0e-9,
        ):
            raise ValueError(
                f"cell {self.cell_id} bed elevation must equal geometry.minimum_stage"
            )


@dataclass(frozen=True)
class FiniteVolumeFace:
    """Identify one face by the adjacent cell indices.

    Boundary faces use ``None`` for the outside cell.  Internal face index
    ``i`` lies between cells ``i`` and ``i + 1``.
    """

    face_id: str
    left_cell: int | None
    right_cell: int | None


@dataclass(frozen=True)
class FiniteVolumeMesh:
    """Store an ordered, single-branch mesh separately from HydraulicState."""

    cells: tuple[FiniteVolumeCell, ...]
    branch_id: str = "single-branch"

    def __post_init__(self) -> None:
        """Freeze cells and ensure identities remain deterministic and unique."""

        object.__setattr__(self, "cells", tuple(self.cells))
        if not self.branch_id:
            raise ValueError("branch_id must not be empty")
        if not self.cells:
            raise ValueError("a finite-volume mesh needs at least one cell")
        identifiers = [cell.cell_id for cell in self.cells]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("finite-volume cell_id values must be unique")

    @property
    def faces(self) -> tuple[FiniteVolumeFace, ...]:
        """Return deterministic boundary and internal face connectivity."""

        faces = [FiniteVolumeFace("upstream", None, 0)]
        faces.extend(
            FiniteVolumeFace(f"face-{index}", index, index + 1)
            for index in range(len(self.cells) - 1)
        )
        faces.append(FiniteVolumeFace("downstream", len(self.cells) - 1, None))
        return tuple(faces)

    @property
    def minimum_dx(self) -> float:
        """Return the smallest control-volume length in metres."""

        return min(cell.dx for cell in self.cells)
