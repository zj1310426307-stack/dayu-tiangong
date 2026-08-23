"""Future extension protocols; this module intentionally provides no solvers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from model.solver.finite_volume.state import HydraulicState
from model.solver.finite_volume.structures import StructureStageContext, StructureStageFlow
from model.solver.finite_volume.coupling import InternalStructureStageEvidence
from model.solver.finite_volume.junction import JunctionCharacteristicSolution
from model.solver.finite_volume.mesh import FiniteVolumeMesh
from model.solver.finite_volume.network_foundation import FiniteVolumeNetwork, NodeId
from model.solver.finite_volume.roughness import ZonedRoughnessMesh


@runtime_checkable
class BranchNetworkSolver(Protocol):
    """Future contract for advancing multiple authoritative Branch states."""

    def advance_branches(
        self,
        *,
        states: Mapping[str, HydraulicState],
        target_time: float,
    ) -> Mapping[str, HydraulicState]: ...


@runtime_checkable
class NodeSolver(Protocol):
    """Contract for one converged Junction characteristic stage solve."""

    def solve_node_stage(
        self,
        *,
        network: FiniteVolumeNetwork,
        node_id: NodeId,
        states: Mapping[str, HydraulicState],
    ) -> JunctionCharacteristicSolution: ...


@runtime_checkable
class StructureSolver(Protocol):
    """Future contract for full mass, momentum and device-work coupling."""

    def evaluate_stage(
        self,
        *,
        contexts: Mapping[str, StructureStageContext],
    ) -> Sequence[StructureStageFlow]: ...


@runtime_checkable
class RoughnessZoneSolver(Protocol):
    """Contract for resolving one complete zone partition onto a Branch mesh."""

    def resolve_mesh(
        self,
        *,
        mesh: FiniteVolumeMesh,
        branch_start_chainage_m: float,
    ) -> ZonedRoughnessMesh: ...


@runtime_checkable
class StrongStructureSolver(Protocol):
    """Future contract that may return only fully closed internal transfers."""

    def evaluate_internal_stage(
        self,
        *,
        contexts: Mapping[str, StructureStageContext],
    ) -> Sequence[InternalStructureStageEvidence]: ...


@runtime_checkable
class ExternalComparison(Protocol):
    """Future result-level comparison contract for approved neutral data."""

    def compare(
        self,
        *,
        dayu_result: object,
        external_result: object,
    ) -> Mapping[str, float | str | None]: ...
