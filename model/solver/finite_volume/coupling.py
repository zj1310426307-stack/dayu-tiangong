"""Structure placement and strong internal-transfer evidence foundations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from model.solver.finite_volume.network_foundation import FiniteVolumeNetwork


@dataclass(frozen=True)
class GatePlacement:
    """Bind a Gate identity to one ordered adjacent-cell interface."""

    structure_id: str
    branch_id: str
    upstream_cell_id: str
    downstream_cell_id: str

    def __post_init__(self) -> None:
        """Reject an incomplete identity-based binding."""

        if not all(
            (
                self.structure_id,
                self.branch_id,
                self.upstream_cell_id,
                self.downstream_cell_id,
            )
        ):
            raise ValueError("Gate placement identities must not be empty")
        if self.upstream_cell_id == self.downstream_cell_id:
            raise ValueError("Gate placement cells must be distinct")


@dataclass(frozen=True)
class PumpPlacement:
    """Bind a Pump source to either an external outlet or a target network cell."""

    structure_id: str
    source_branch_id: str
    source_cell_id: str
    outlet_kind: Literal["external", "network-cell"]
    target_branch_id: str | None = None
    target_cell_id: str | None = None

    def __post_init__(self) -> None:
        """Require a complete and unambiguous Pump transfer target."""

        if not self.structure_id or not self.source_branch_id or not self.source_cell_id:
            raise ValueError("Pump placement source identities must not be empty")
        if self.outlet_kind not in {"external", "network-cell"}:
            raise ValueError("Pump outlet_kind must be external or network-cell")
        if self.outlet_kind == "external":
            if self.target_branch_id is not None or self.target_cell_id is not None:
                raise ValueError("external Pump placement must not declare a target cell")
            return
        if not self.target_branch_id or not self.target_cell_id:
            raise ValueError("network-cell Pump placement requires a complete target")
        if (
            self.source_branch_id == self.target_branch_id
            and self.source_cell_id == self.target_cell_id
        ):
            raise ValueError("Pump source and target cells must be distinct")


@dataclass(frozen=True)
class StructurePlacementPlan:
    """Validate stable Gate/Pump placements against one frozen network."""

    network: FiniteVolumeNetwork
    gates: tuple[GatePlacement, ...] = ()
    pumps: tuple[PumpPlacement, ...] = ()
    policy: str = "identity-bound-structure-placement-v1"

    def __post_init__(self) -> None:
        """Resolve all cells exactly and reject duplicate structure identities."""

        object.__setattr__(self, "gates", tuple(self.gates))
        object.__setattr__(self, "pumps", tuple(self.pumps))
        if not isinstance(self.network, FiniteVolumeNetwork):
            raise TypeError("structure placement plan requires a FiniteVolumeNetwork")
        if any(not isinstance(gate, GatePlacement) for gate in self.gates):
            raise TypeError("gates must contain GatePlacement values")
        if any(not isinstance(pump, PumpPlacement) for pump in self.pumps):
            raise TypeError("pumps must contain PumpPlacement values")
        if self.policy != "identity-bound-structure-placement-v1":
            raise ValueError("unsupported structure placement policy")
        identities = tuple(item.structure_id for item in (*self.gates, *self.pumps))
        if len(set(identities)) != len(identities):
            raise ValueError("Gate and Pump identities must be globally unique")
        for gate in self.gates:
            branch = self.network.branch(gate.branch_id)
            cells = tuple(cell.cell_id for cell in branch.mesh.cells)
            pair = (gate.upstream_cell_id, gate.downstream_cell_id)
            if pair not in set(zip(cells, cells[1:])):
                raise ValueError("Gate must bind an ordered adjacent-cell interface")
        for pump in self.pumps:
            source = self.network.branch(pump.source_branch_id)
            if pump.source_cell_id not in {cell.cell_id for cell in source.mesh.cells}:
                raise ValueError("Pump source references an unknown network cell")
            if pump.outlet_kind == "network-cell":
                assert pump.target_branch_id is not None
                assert pump.target_cell_id is not None
                target = self.network.branch(pump.target_branch_id)
                if pump.target_cell_id not in {cell.cell_id for cell in target.mesh.cells}:
                    raise ValueError("Pump target references an unknown network cell")

    @property
    def requires_internal_pump_coupling(self) -> bool:
        """Return whether any Pump must add water to another network cell."""

        return any(pump.outlet_kind == "network-cell" for pump in self.pumps)


@dataclass(frozen=True)
class InternalStructureStageEvidence:
    """Prove one internal Gate/Pump stage closed mass, energy, and momentum.

    This DTO is an acceptance gate, not a device equation.  A future Gate or
    Pump solver must first compute a common transfer, device head/work, and
    both side-specific momentum fluxes, then construct this evidence.  The
    current single-Branch integrator does not yet consume this object.
    """

    structure_id: str
    structure_type: Literal["gate", "pump"]
    evaluation_time: float
    source_outflow: float
    target_inflow: float
    source_area: float
    target_area: float
    source_total_head: float
    target_total_head: float
    device_head_gain: float
    hydraulic_head_loss: float
    source_momentum_flux: float
    target_momentum_flux: float
    reaction_force_per_density: float
    equation_iterations: int
    mass_tolerance: float = 1.0e-10
    equation_tolerance: float = 1.0e-10
    closure_policy: str = "internal-mass-energy-momentum-device-work-v1"

    def __post_init__(self) -> None:
        """Require converged, self-consistent strong-coupling evidence."""

        if not self.structure_id:
            raise ValueError("internal structure evidence identity must not be empty")
        if self.structure_type not in {"gate", "pump"}:
            raise ValueError("internal structure evidence type must be Gate or Pump")
        values = (
            self.evaluation_time,
            self.source_outflow,
            self.target_inflow,
            self.source_area,
            self.target_area,
            self.source_total_head,
            self.target_total_head,
            self.device_head_gain,
            self.hydraulic_head_loss,
            self.source_momentum_flux,
            self.target_momentum_flux,
            self.reaction_force_per_density,
            self.mass_tolerance,
            self.equation_tolerance,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("internal structure evidence values must be finite")
        if self.evaluation_time < 0.0:
            raise ValueError("internal structure evidence time must be non-negative")
        if self.source_outflow < 0.0 or self.target_inflow < 0.0:
            raise ValueError("internal structure transfer rates must be non-negative")
        if self.source_area <= 0.0 or self.target_area <= 0.0:
            raise ValueError("internal structure evidence requires fully wet cells")
        if self.device_head_gain < 0.0 or self.hydraulic_head_loss < 0.0:
            raise ValueError("device head gain and hydraulic loss must be non-negative")
        if self.mass_tolerance <= 0.0 or self.equation_tolerance <= 0.0:
            raise ValueError("internal structure tolerances must be positive")
        if isinstance(self.equation_iterations, bool) or self.equation_iterations <= 0:
            raise ValueError("internal structure equation_iterations must be positive")
        if self.closure_policy != "internal-mass-energy-momentum-device-work-v1":
            raise ValueError("unsupported internal structure closure policy")
        if self.structure_type == "gate" and self.device_head_gain != 0.0:
            raise ValueError("Gate evidence must not invent positive device head gain")
        if (
            self.structure_type == "pump"
            and self.source_outflow > self.mass_tolerance
            and self.device_head_gain <= 0.0
        ):
            raise ValueError("an operating Pump requires positive device head gain")
        if abs(self.mass_residual) > self.mass_tolerance:
            raise ValueError("internal structure mass closure exceeds tolerance")
        if abs(self.energy_residual) > self.equation_tolerance:
            raise ValueError("internal structure energy closure exceeds tolerance")
        if abs(self.momentum_residual) > self.equation_tolerance:
            raise ValueError("internal structure momentum closure exceeds tolerance")

    @property
    def mass_residual(self) -> float:
        """Return target inflow minus source outflow."""

        return self.target_inflow - self.source_outflow

    @property
    def energy_residual(self) -> float:
        """Return the target-minus-source total-head equation residual."""

        return (
            self.target_total_head
            - self.source_total_head
            - self.device_head_gain
            + self.hydraulic_head_loss
        )

    @property
    def momentum_residual(self) -> float:
        """Return the reaction inconsistency under target-minus-source convention."""

        return self.reaction_force_per_density - (
            self.target_momentum_flux - self.source_momentum_flux
        )

    @property
    def strong_coupling_ready(self) -> bool:
        """Return true only because construction already enforced every closure."""

        return True
