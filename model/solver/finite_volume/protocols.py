"""Future extension protocols; this module intentionally provides no solvers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from model.solver.finite_volume.state import HydraulicState
from model.solver.finite_volume.structures import StructureStageContext, StructureStageFlow


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
    """Future contract for a converged Junction compatibility solve."""

    def solve_node_stage(
        self,
        *,
        node_id: str,
        connected_states: Sequence[object],
        time: float,
        dt: float,
    ) -> object: ...


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
    """Future contract for consuming frozen zone conveyance ``K(h)``."""

    def conveyance(self, *, section_id: str | int, area: float) -> float: ...


@runtime_checkable
class ExternalComparison(Protocol):
    """Future result-level comparison contract for approved neutral data."""

    def compare(
        self,
        *,
        dayu_result: object,
        external_result: object,
    ) -> Mapping[str, float | str | None]: ...
