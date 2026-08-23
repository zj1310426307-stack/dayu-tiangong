"""Fail-closed topology and Junction pre-closure contracts for MODEL-02-C3."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from model.solver.finite_volume.mesh import FiniteVolumeMesh
from model.solver.finite_volume.state import HydraulicState

NodeId = str | int


def _validate_node_id(value: NodeId, label: str) -> None:
    """Accept public positive integers or stable non-empty string identities."""

    if isinstance(value, bool):
        raise ValueError(f"{label} must not be boolean")
    if isinstance(value, int):
        if value <= 0:
            raise ValueError(f"{label} integer identity must be positive")
        return
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a positive integer or non-empty string")


def _node_sort_key(value: NodeId) -> tuple[str, str]:
    """Return a deterministic key even when public and internal IDs coexist."""

    return type(value).__name__, str(value)


@dataclass(frozen=True)
class NetworkBranch:
    """Bind one authoritative finite-volume mesh to directed endpoint nodes."""

    mesh: FiniteVolumeMesh
    upstream_node_id: NodeId
    downstream_node_id: NodeId

    def __post_init__(self) -> None:
        """Reject a Branch without an oriented, distinct endpoint pair."""

        if not isinstance(self.mesh, FiniteVolumeMesh):
            raise TypeError("NetworkBranch mesh must be a FiniteVolumeMesh")
        _validate_node_id(self.upstream_node_id, "upstream_node_id")
        _validate_node_id(self.downstream_node_id, "downstream_node_id")
        if self.upstream_node_id == self.downstream_node_id:
            raise ValueError("Branch endpoint identities must be distinct")

    @property
    def branch_id(self) -> str:
        """Return the mesh-owned Branch identity."""

        return self.mesh.branch_id


@dataclass(frozen=True)
class JunctionIncidence:
    """Describe directed Branch incidence at one topology node."""

    node_id: NodeId
    incoming_branch_ids: tuple[str, ...]
    outgoing_branch_ids: tuple[str, ...]

    @property
    def is_external_source(self) -> bool:
        """Return whether the node has only outgoing Branches."""

        return not self.incoming_branch_ids and bool(self.outgoing_branch_ids)

    @property
    def is_external_sink(self) -> bool:
        """Return whether the node has only incoming Branches."""

        return bool(self.incoming_branch_ids) and not self.outgoing_branch_ids

    @property
    def is_internal(self) -> bool:
        """Return whether two or more Branch ends require compatibility."""

        return len(self.incoming_branch_ids) + len(self.outgoing_branch_ids) >= 2


@dataclass(frozen=True)
class FiniteVolumeNetwork:
    """Freeze one connected acyclic graph of authoritative Branch meshes.

    This object intentionally does not advance states.  It supplies the exact
    topology and synchronization gates required before a future network
    Saint-Venant orchestrator may call Branch and Junction solvers.
    """

    branches: tuple[NetworkBranch, ...]

    def __post_init__(self) -> None:
        """Reject duplicate identities, disconnected graphs, and directed cycles."""

        object.__setattr__(self, "branches", tuple(self.branches))
        if not self.branches:
            raise ValueError("a finite-volume network requires at least one Branch")
        branch_ids = tuple(branch.branch_id for branch in self.branches)
        if len(set(branch_ids)) != len(branch_ids):
            raise ValueError("finite-volume network Branch identities must be unique")
        cell_ids = tuple(
            cell.cell_id for branch in self.branches for cell in branch.mesh.cells
        )
        if len(set(cell_ids)) != len(cell_ids):
            raise ValueError("finite-volume network cell identities must be globally unique")
        self._require_connected()
        self._require_acyclic()

    @property
    def incidences(self) -> tuple[JunctionIncidence, ...]:
        """Derive deterministic incoming and outgoing Branch memberships."""

        incoming: dict[NodeId, list[str]] = defaultdict(list)
        outgoing: dict[NodeId, list[str]] = defaultdict(list)
        for branch in self.branches:
            outgoing[branch.upstream_node_id].append(branch.branch_id)
            incoming[branch.downstream_node_id].append(branch.branch_id)
        node_ids = sorted(set(incoming) | set(outgoing), key=_node_sort_key)
        return tuple(
            JunctionIncidence(
                node_id=node_id,
                incoming_branch_ids=tuple(sorted(incoming[node_id])),
                outgoing_branch_ids=tuple(sorted(outgoing[node_id])),
            )
            for node_id in node_ids
        )

    @property
    def topological_branch_order(self) -> tuple[str, ...]:
        """Return a deterministic upstream-to-downstream Branch order."""

        indegree: dict[NodeId, int] = {
            incidence.node_id: len(incidence.incoming_branch_ids)
            for incidence in self.incidences
        }
        outgoing: dict[NodeId, list[NetworkBranch]] = defaultdict(list)
        for branch in self.branches:
            outgoing[branch.upstream_node_id].append(branch)
        ready = sorted(
            (node_id for node_id, value in indegree.items() if value == 0),
            key=_node_sort_key,
        )
        order: list[str] = []
        while ready:
            node_id = ready.pop(0)
            for branch in sorted(outgoing[node_id], key=lambda item: item.branch_id):
                order.append(branch.branch_id)
                target = branch.downstream_node_id
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
                    ready.sort(key=_node_sort_key)
        if len(order) != len(self.branches):
            raise ValueError("finite-volume network contains a directed cycle")
        return tuple(order)

    def branch(self, branch_id: str) -> NetworkBranch:
        """Resolve one Branch by exact identity without nearest-neighbour logic."""

        matches = tuple(item for item in self.branches if item.branch_id == branch_id)
        if len(matches) != 1:
            raise ValueError(f"unknown finite-volume Branch identity {branch_id!r}")
        return matches[0]

    def incidence(self, node_id: NodeId) -> JunctionIncidence:
        """Resolve one node by exact identity."""

        matches = tuple(item for item in self.incidences if item.node_id == node_id)
        if len(matches) != 1:
            raise ValueError(f"unknown finite-volume node identity {node_id!r}")
        return matches[0]

    def validate_synchronized_states(
        self,
        states: Mapping[str, HydraulicState],
    ) -> float:
        """Require one exact-length accepted state per Branch at a common time."""

        expected = {branch.branch_id for branch in self.branches}
        if set(states) != expected:
            raise ValueError("network state mapping must exactly cover all Branch identities")
        times = []
        for branch in self.branches:
            state = states[branch.branch_id]
            if not isinstance(state, HydraulicState):
                raise TypeError("network states must contain HydraulicState values")
            if len(state.area) != len(branch.mesh.cells):
                raise ValueError("network Branch state length must match its mesh")
            times.append(state.time)
        reference_time = times[0]
        if any(
            not math.isclose(time, reference_time, rel_tol=0.0, abs_tol=1.0e-12)
            for time in times[1:]
        ):
            raise ValueError("network Branch states must share one accepted time")
        return reference_time

    def _require_connected(self) -> None:
        """Require one weakly connected hydraulic graph."""

        adjacency: dict[NodeId, set[NodeId]] = defaultdict(set)
        for branch in self.branches:
            adjacency[branch.upstream_node_id].add(branch.downstream_node_id)
            adjacency[branch.downstream_node_id].add(branch.upstream_node_id)
        start = next(iter(adjacency))
        visited = {start}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for neighbour in adjacency[node] - visited:
                visited.add(neighbour)
                queue.append(neighbour)
        if visited != set(adjacency):
            raise ValueError("finite-volume network must be weakly connected")

    def _require_acyclic(self) -> None:
        """Materialize the topological order to enforce the MVP DAG boundary."""

        self.topological_branch_order


@dataclass(frozen=True)
class JunctionTrace:
    """Provide one fully wet oriented Branch-end trace at a node."""

    node_id: NodeId
    branch_id: str
    endpoint: Literal["upstream", "downstream"]
    stage: float
    area: float
    discharge: float

    def __post_init__(self) -> None:
        """Reject incomplete or non-finite node evidence."""

        _validate_node_id(self.node_id, "Junction trace node_id")
        if not self.branch_id:
            raise ValueError("Junction trace branch_id must not be empty")
        if self.endpoint not in {"upstream", "downstream"}:
            raise ValueError("Junction trace endpoint must be upstream or downstream")
        values = (self.stage, self.area, self.discharge)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Junction trace values must be finite")
        if self.area <= 0.0:
            raise ValueError("Junction trace requires a fully wet positive area")

    @property
    def signed_flow_into_node(self) -> float:
        """Return positive flow into the node under Branch orientation."""

        return self.discharge if self.endpoint == "downstream" else -self.discharge


@dataclass(frozen=True)
class JunctionPreclosureEvidence:
    """Expose mass/common-stage checks without claiming momentum closure."""

    node_id: NodeId
    time: float
    trace_count: int
    common_stage: float
    maximum_stage_spread: float
    net_flow_into_node: float
    normalized_mass_residual: float
    stage_tolerance: float
    mass_tolerance: float
    preliminary_passed: bool
    momentum_compatibility: str = "not-implemented"
    strong_coupling_ready: bool = False

    def __post_init__(self) -> None:
        """Prevent preliminary evidence from being relabelled as a full solve."""

        _validate_node_id(self.node_id, "Junction evidence node_id")
        values = (
            self.time,
            self.common_stage,
            self.maximum_stage_spread,
            self.net_flow_into_node,
            self.normalized_mass_residual,
            self.stage_tolerance,
            self.mass_tolerance,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Junction pre-closure evidence values must be finite")
        if self.time < 0.0:
            raise ValueError("Junction pre-closure time must be non-negative")
        if isinstance(self.trace_count, bool) or self.trace_count < 2:
            raise ValueError("Junction pre-closure requires at least two traces")
        if min(
            self.maximum_stage_spread,
            self.normalized_mass_residual,
            self.stage_tolerance,
            self.mass_tolerance,
        ) < 0.0:
            raise ValueError("Junction pre-closure spreads and tolerances must be non-negative")
        expected_pass = (
            self.maximum_stage_spread <= self.stage_tolerance
            and self.normalized_mass_residual <= self.mass_tolerance
        )
        if self.preliminary_passed is not expected_pass:
            raise ValueError("Junction preliminary_passed contradicts its residuals")
        if self.momentum_compatibility != "not-implemented":
            raise ValueError("C3a Junction evidence must not claim momentum closure")
        if self.strong_coupling_ready:
            raise ValueError("C3a Junction pre-closure is not a strong coupling solve")


def inspect_junction_preclosure(
    *,
    network: FiniteVolumeNetwork,
    node_id: NodeId,
    traces: Sequence[JunctionTrace],
    time: float,
    stage_tolerance: float,
    mass_tolerance: float,
) -> JunctionPreclosureEvidence:
    """Check exact incidence, common stage, and signed mass balance at one node."""

    if not math.isfinite(time) or time < 0.0:
        raise ValueError("Junction evidence time must be finite and non-negative")
    if not math.isfinite(stage_tolerance) or stage_tolerance < 0.0:
        raise ValueError("Junction stage_tolerance must be finite and non-negative")
    if not math.isfinite(mass_tolerance) or mass_tolerance < 0.0:
        raise ValueError("Junction mass_tolerance must be finite and non-negative")
    incidence = network.incidence(node_id)
    if not incidence.is_internal:
        raise ValueError("Junction pre-closure requires an internal multi-end node")
    frozen_traces = tuple(traces)
    expected = {
        **{branch_id: "downstream" for branch_id in incidence.incoming_branch_ids},
        **{branch_id: "upstream" for branch_id in incidence.outgoing_branch_ids},
    }
    if {trace.branch_id for trace in frozen_traces} != set(expected):
        raise ValueError("Junction traces must exactly cover incident Branch identities")
    if len(frozen_traces) != len(expected):
        raise ValueError("Junction traces must contain one value per incident Branch")
    for trace in frozen_traces:
        if trace.node_id != node_id:
            raise ValueError("Junction trace references the wrong node")
        if trace.endpoint != expected[trace.branch_id]:
            raise ValueError("Junction trace endpoint contradicts Branch orientation")

    stages = tuple(trace.stage for trace in frozen_traces)
    common_stage = sum(stages) / len(stages)
    stage_spread = max(stages) - min(stages)
    signed_flows = tuple(trace.signed_flow_into_node for trace in frozen_traces)
    net_flow = sum(signed_flows)
    normalizer = max(sum(abs(value) for value in signed_flows), 1.0)
    normalized = abs(net_flow) / normalizer
    passed = stage_spread <= stage_tolerance and normalized <= mass_tolerance
    return JunctionPreclosureEvidence(
        node_id=node_id,
        time=float(time),
        trace_count=len(frozen_traces),
        common_stage=common_stage,
        maximum_stage_spread=stage_spread,
        net_flow_into_node=net_flow,
        normalized_mass_residual=normalized,
        stage_tolerance=stage_tolerance,
        mass_tolerance=mass_tolerance,
        preliminary_passed=passed,
    )
