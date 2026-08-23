"""Deterministic piecewise-Manning assignment for finite-volume cells."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from model.solver.finite_volume.mesh import FiniteVolumeMesh

_CHAINAGE_TOLERANCE_M = 1.0e-9


def _finite(value: float, label: str) -> float:
    """Return one finite non-boolean float or fail closed."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def _close(left: float, right: float) -> bool:
    """Compare chainages without a scale-dependent relative tolerance."""

    return math.isclose(
        left,
        right,
        rel_tol=0.0,
        abs_tol=_CHAINAGE_TOLERANCE_M,
    )


@dataclass(frozen=True)
class RoughnessZone:
    """Freeze one half-open Branch chainage interval and its Manning value.

    Adjacent zones share their boundary.  The final zone includes the Branch
    end point.  Zone boundaries must later align with finite-volume faces;
    splitting one cell is rejected because a cell owns exactly one Manning n.
    """

    zone_id: str
    branch_id: str
    start_chainage_m: float
    end_chainage_m: float
    manning_n: float

    def __post_init__(self) -> None:
        """Reject invalid identities, extents, or non-physical coefficients."""

        if not self.zone_id or not self.branch_id:
            raise ValueError("roughness zone and Branch identities must not be empty")
        start = _finite(self.start_chainage_m, "roughness zone start_chainage_m")
        end = _finite(self.end_chainage_m, "roughness zone end_chainage_m")
        coefficient = _finite(self.manning_n, "roughness zone manning_n")
        if end <= start:
            raise ValueError("roughness zone end_chainage_m must exceed its start")
        if coefficient < 0.0 or coefficient > 1.0:
            raise ValueError("roughness zone manning_n must be within 0..1")
        object.__setattr__(self, "start_chainage_m", start)
        object.__setattr__(self, "end_chainage_m", end)
        object.__setattr__(self, "manning_n", coefficient)


@dataclass(frozen=True)
class RoughnessAssignment:
    """Record the exact zone used by one immutable control volume."""

    cell_id: str
    section_id: str | int
    zone_id: str
    start_chainage_m: float
    end_chainage_m: float
    manning_n: float

    def __post_init__(self) -> None:
        """Reject evidence that cannot describe one physical control volume."""

        if not self.cell_id or not self.zone_id:
            raise ValueError("roughness assignment identities must not be empty")
        start = _finite(
            self.start_chainage_m,
            "roughness assignment start_chainage_m",
        )
        end = _finite(
            self.end_chainage_m,
            "roughness assignment end_chainage_m",
        )
        coefficient = _finite(
            self.manning_n,
            "roughness assignment manning_n",
        )
        if end <= start:
            raise ValueError("roughness assignment end chainage must exceed its start")
        if coefficient < 0.0 or coefficient > 1.0:
            raise ValueError("roughness assignment manning_n must be within 0..1")
        object.__setattr__(self, "start_chainage_m", start)
        object.__setattr__(self, "end_chainage_m", end)
        object.__setattr__(self, "manning_n", coefficient)


@dataclass(frozen=True)
class ZonedRoughnessMesh:
    """Return a new mesh together with auditable cell-to-zone evidence."""

    mesh: FiniteVolumeMesh
    assignments: tuple[RoughnessAssignment, ...]
    policy: str = "piecewise-manning-cell-face-aligned-v1"

    def __post_init__(self) -> None:
        """Keep evidence aligned one-to-one with the returned mesh."""

        object.__setattr__(self, "assignments", tuple(self.assignments))
        if self.policy != "piecewise-manning-cell-face-aligned-v1":
            raise ValueError("unsupported zoned roughness policy")
        if len(self.assignments) != len(self.mesh.cells):
            raise ValueError("roughness assignments must match the mesh cell count")
        completed_zone_ids: set[str] = set()
        current_zone_id: str | None = None
        coefficient_by_zone: dict[str, float] = {}
        for index, (cell, assignment) in enumerate(
            zip(self.mesh.cells, self.assignments)
        ):
            if cell.cell_id != assignment.cell_id:
                raise ValueError("roughness assignment cell order is inconsistent")
            if cell.section_id != assignment.section_id:
                raise ValueError("roughness assignment section identity is inconsistent")
            if cell.manning_n != assignment.manning_n:
                raise ValueError("roughness assignment contradicts the resolved cell")
            if not _close(
                assignment.end_chainage_m - assignment.start_chainage_m,
                cell.dx,
            ):
                raise ValueError("roughness assignment span must equal the cell dx")
            if index and not _close(
                self.assignments[index - 1].end_chainage_m,
                assignment.start_chainage_m,
            ):
                raise ValueError("roughness assignments must form a contiguous partition")
            previous_coefficient = coefficient_by_zone.setdefault(
                assignment.zone_id,
                assignment.manning_n,
            )
            if previous_coefficient != assignment.manning_n:
                raise ValueError("one roughness zone cannot own multiple coefficients")
            if assignment.zone_id != current_zone_id:
                if current_zone_id is not None:
                    completed_zone_ids.add(current_zone_id)
                if assignment.zone_id in completed_zone_ids:
                    raise ValueError("roughness zone assignments must remain contiguous")
                current_zone_id = assignment.zone_id


@dataclass(frozen=True)
class PiecewiseManningZoneSolver:
    """Resolve a complete ordered zone partition onto one Branch mesh."""

    zones: tuple[RoughnessZone, ...]

    def __post_init__(self) -> None:
        """Freeze zone order and reject identity or ordering ambiguity."""

        object.__setattr__(self, "zones", tuple(self.zones))
        if not self.zones:
            raise ValueError("at least one roughness zone is required")
        if any(not isinstance(zone, RoughnessZone) for zone in self.zones):
            raise TypeError("zones must contain RoughnessZone values")
        zone_ids = tuple(zone.zone_id for zone in self.zones)
        if len(set(zone_ids)) != len(zone_ids):
            raise ValueError("roughness zone identities must be unique")
        branch_ids = {zone.branch_id for zone in self.zones}
        if len(branch_ids) != 1:
            raise ValueError("one zone solver may target only one Branch")
        starts = tuple(zone.start_chainage_m for zone in self.zones)
        if any(right <= left for left, right in zip(starts, starts[1:])):
            raise ValueError("roughness zones must be strictly ordered by start chainage")

    def resolve_mesh(
        self,
        *,
        mesh: FiniteVolumeMesh,
        branch_start_chainage_m: float,
    ) -> ZonedRoughnessMesh:
        """Return a copied mesh after exact coverage and face-alignment checks."""

        branch_start = _finite(
            branch_start_chainage_m,
            "Branch start_chainage_m",
        )
        if self.zones[0].branch_id != mesh.branch_id:
            raise ValueError("roughness zones reference an unknown Branch")

        faces = [branch_start]
        for cell in mesh.cells:
            faces.append(faces[-1] + cell.dx)
        branch_end = faces[-1]

        if not _close(self.zones[0].start_chainage_m, branch_start):
            raise ValueError("roughness zones must start at the Branch boundary")
        if not _close(self.zones[-1].end_chainage_m, branch_end):
            raise ValueError("roughness zones must end at the Branch boundary")
        for left, right in zip(self.zones, self.zones[1:]):
            if not _close(left.end_chainage_m, right.start_chainage_m):
                raise ValueError("roughness zones must have no gaps or overlaps")

        for zone in self.zones:
            for boundary in (zone.start_chainage_m, zone.end_chainage_m):
                if not any(_close(boundary, face) for face in faces):
                    raise ValueError(
                        "roughness zone boundaries must align with finite-volume faces"
                    )

        cells = []
        assignments = []
        for index, cell in enumerate(mesh.cells):
            cell_start = faces[index]
            cell_end = faces[index + 1]
            matches = tuple(
                zone
                for zone in self.zones
                if (
                    cell_start >= zone.start_chainage_m - _CHAINAGE_TOLERANCE_M
                    and cell_end <= zone.end_chainage_m + _CHAINAGE_TOLERANCE_M
                )
            )
            if len(matches) != 1:
                raise ValueError("each finite-volume cell must resolve to exactly one zone")
            zone = matches[0]
            cells.append(replace(cell, manning_n=zone.manning_n))
            assignments.append(
                RoughnessAssignment(
                    cell_id=cell.cell_id,
                    section_id=cell.section_id,
                    zone_id=zone.zone_id,
                    start_chainage_m=cell_start,
                    end_chainage_m=cell_end,
                    manning_n=zone.manning_n,
                )
            )

        return ZonedRoughnessMesh(
            mesh=FiniteVolumeMesh(cells=tuple(cells), branch_id=mesh.branch_id),
            assignments=tuple(assignments),
        )
