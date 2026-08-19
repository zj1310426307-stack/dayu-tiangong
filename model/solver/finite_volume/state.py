"""Immutable conservative state for the native finite-volume solver.

The runtime state intentionally owns no mesh or section geometry.  Derived
hydraulic fields are cached alongside ``U=(A, Q)`` so output and diagnostics
do not need to reinterpret a result object as solver state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from model.solver.finite_volume.mesh import FiniteVolumeMesh


def _freeze_state_value(value: object) -> object:
    """Recursively freeze structure-state containers stored beside U=(A,Q)."""

    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_state_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_state_value(item) for item in value)
    return value


@dataclass(frozen=True)
class SolverDiagnostics:
    """Accumulate accepted-step stability evidence without hiding retries."""

    step_count: int = 0
    stage_count: int = 0
    maximum_cfl: float = 0.0
    minimum_dt: float | None = None
    retry_count: int = 0
    rejected_step_count: int = 0
    time_step_reduction_count: int = 0

    def accepted_step(self, *, dt: float, cfl: float, stages: int = 2) -> "SolverDiagnostics":
        """Return a new record containing one accepted time step."""

        if not math.isfinite(dt) or dt <= 0.0:
            raise ValueError("accepted dt must be a finite positive number")
        if not math.isfinite(cfl) or cfl < 0.0:
            raise ValueError("accepted CFL must be a finite non-negative number")
        return replace(
            self,
            step_count=self.step_count + 1,
            stage_count=self.stage_count + stages,
            maximum_cfl=max(self.maximum_cfl, cfl),
            minimum_dt=dt if self.minimum_dt is None else min(self.minimum_dt, dt),
        )

    def rejected_step(self) -> "SolverDiagnostics":
        """Return a record that exposes one failed attempt and its retry."""

        return replace(
            self,
            retry_count=self.retry_count + 1,
            rejected_step_count=self.rejected_step_count + 1,
        )

    def reduced_time_step(self) -> "SolverDiagnostics":
        """Record an automatic CFL/event reduction before an attempt."""

        return replace(
            self,
            time_step_reduction_count=self.time_step_reduction_count + 1,
        )


@dataclass(frozen=True)
class HydraulicState:
    """Store one accepted cell-centred state independently of the static mesh.

    ``area`` and ``discharge`` are the authoritative conserved variables.  The
    remaining per-cell arrays are deterministic views calculated against a
    particular mesh by :meth:`from_conserved`.
    """

    time: float
    area: tuple[float, ...]
    discharge: tuple[float, ...]
    water_depth: tuple[float, ...]
    velocity: tuple[float, ...]
    wet_mask: tuple[bool, ...]
    gate_state: Mapping[str, object] = field(default_factory=dict)
    pump_state: Mapping[str, object] = field(default_factory=dict)
    diagnostics: SolverDiagnostics = field(default_factory=SolverDiagnostics)

    def __post_init__(self) -> None:
        """Enforce finite, non-negative and shape-consistent state invariants."""

        object.__setattr__(self, "area", tuple(self.area))
        object.__setattr__(self, "discharge", tuple(self.discharge))
        object.__setattr__(self, "water_depth", tuple(self.water_depth))
        object.__setattr__(self, "velocity", tuple(self.velocity))
        object.__setattr__(self, "wet_mask", tuple(self.wet_mask))
        object.__setattr__(self, "gate_state", _freeze_state_value(self.gate_state))
        object.__setattr__(self, "pump_state", _freeze_state_value(self.pump_state))
        if not math.isfinite(self.time) or self.time < 0.0:
            raise ValueError("state time must be a finite non-negative number")
        sizes = {
            len(self.area),
            len(self.discharge),
            len(self.water_depth),
            len(self.velocity),
            len(self.wet_mask),
        }
        if len(sizes) != 1 or not self.area:
            raise ValueError("all HydraulicState cell arrays must have the same non-zero length")
        if any(not math.isfinite(value) or value < 0.0 for value in self.area):
            raise ValueError("cell area must be finite and non-negative")
        for label, values in (
            ("discharge", self.discharge),
            ("water_depth", self.water_depth),
            ("velocity", self.velocity),
        ):
            if any(not math.isfinite(value) for value in values):
                raise ValueError(f"{label} must contain only finite values")
        if any(value < -1.0e-12 for value in self.water_depth):
            raise ValueError("water depth must be non-negative")

    @classmethod
    def from_conserved(
        cls,
        *,
        mesh: "FiniteVolumeMesh",
        time: float,
        area: tuple[float, ...] | list[float],
        discharge: tuple[float, ...] | list[float],
        dry_depth: float,
        gate_state: Mapping[str, object] | None = None,
        pump_state: Mapping[str, object] | None = None,
        diagnostics: SolverDiagnostics | None = None,
    ) -> "HydraulicState":
        """Build derived depth, velocity and wet masks from conservative data.

        A dry cell carrying material discharge is rejected instead of silently
        deleting momentum.  That fail-closed rule lets the caller retry with a
        smaller time step and keeps all positivity corrections auditable.
        """

        if not math.isfinite(dry_depth) or dry_depth < 0.0:
            raise ValueError("dry_depth must be a finite non-negative number")
        areas = tuple(float(value) for value in area)
        discharges = tuple(float(value) for value in discharge)
        if len(areas) != len(mesh.cells) or len(discharges) != len(mesh.cells):
            raise ValueError("conservative state length must match the finite-volume mesh")
        depths: list[float] = []
        velocities: list[float] = []
        wet: list[bool] = []
        for index, (cell, cell_area, cell_discharge) in enumerate(
            zip(mesh.cells, areas, discharges)
        ):
            if not math.isfinite(cell_area) or cell_area < 0.0:
                raise ValueError(f"cell {index} area must be finite and non-negative")
            if not math.isfinite(cell_discharge):
                raise ValueError(f"cell {index} discharge must be finite")
            stage = cell.geometry.stage_from_area(cell_area)
            depth = max(stage - cell.bed_elevation, 0.0)
            is_wet = depth > dry_depth and cell_area > 1.0e-12
            if not is_wet and abs(cell_discharge) > 1.0e-12:
                raise ValueError(f"dry cell {index} cannot carry non-zero discharge")
            depths.append(depth)
            wet.append(is_wet)
            velocities.append(cell_discharge / cell_area if is_wet else 0.0)
        return cls(
            time=float(time),
            area=areas,
            discharge=discharges,
            water_depth=tuple(depths),
            velocity=tuple(velocities),
            wet_mask=tuple(wet),
            gate_state=gate_state or {},
            pump_state=pump_state or {},
            diagnostics=diagnostics or SolverDiagnostics(),
        )

    def with_diagnostics(self, diagnostics: SolverDiagnostics) -> "HydraulicState":
        """Return the same physical state with updated accepted-step evidence."""

        return replace(self, diagnostics=diagnostics)
