"""Central graph and topology validation for solver-neutral hydraulic networks."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from model.hydraulic_1d.contracts import (
    BoundaryCondition,
    Hydraulic1DModel,
    HydraulicBranch,
    HydraulicNode,
    HydraulicStructure,
)
from model.hydraulic_1d.errors import Hydraulic1DValidationError


@dataclass(frozen=True)
class HydraulicNetworkGraph:
    """Index one immutable network once for adapters, APIs, and validators."""

    model: Hydraulic1DModel

    def __post_init__(self) -> None:
        """Build linear-time indexes without changing the frozen input snapshot."""

        upstream: dict[str, list[HydraulicBranch]] = defaultdict(list)
        downstream: dict[str, list[HydraulicBranch]] = defaultdict(list)
        sections: dict[str, list[object]] = defaultdict(list)
        boundaries: dict[str, list[BoundaryCondition]] = defaultdict(list)
        structures: dict[str, list[HydraulicStructure]] = defaultdict(list)
        for branch in self.model.branches:
            upstream[branch.downstream_node_id].append(branch)
            downstream[branch.upstream_node_id].append(branch)
        for section in self.model.cross_sections:
            sections[section.branch_id].append(section)
        for boundary in self.model.boundaries:
            boundaries[boundary.branch_id].append(boundary)
        for structure in self.model.structures:
            structures[structure.branch_id].append(structure)
        for values in (*upstream.values(), *downstream.values()):
            values.sort(key=lambda item: (item.code, item.id))
        for values in sections.values():
            values.sort(key=lambda item: item.chainage_m)
        for values in boundaries.values():
            values.sort(
                key=lambda item: (item.location, float(item.chainage_m or -1), item.id)
            )
        for values in structures.values():
            values.sort(key=lambda item: (item.chainage_m, item.id))
        object.__setattr__(self, "_upstream", upstream)
        object.__setattr__(self, "_downstream", downstream)
        object.__setattr__(self, "_sections", sections)
        object.__setattr__(self, "_boundaries", boundaries)
        object.__setattr__(self, "_structures", structures)

    @property
    def node_ids(self) -> tuple[str, ...]:
        """Return explicit and referenced node identities in stable order."""

        referenced = {
            node_id
            for branch in self.model.branches
            for node_id in (branch.upstream_node_id, branch.downstream_node_id)
        }
        referenced.update(item.id for item in self.model.nodes)
        return tuple(sorted(referenced))

    def incoming_branches(self, node_id: str) -> tuple[HydraulicBranch, ...]:
        """Return branches entering a connected node."""

        return tuple(self._upstream.get(node_id, ()))

    def outgoing_branches(self, node_id: str) -> tuple[HydraulicBranch, ...]:
        """Return branches leaving a connected node."""

        return tuple(self._downstream.get(node_id, ()))

    def connected_branches(self, node_id: str) -> tuple[HydraulicBranch, ...]:
        """Return every branch incident on a node without duplicates."""

        values = {item.id: item for item in self.incoming_branches(node_id)}
        values.update({item.id: item for item in self.outgoing_branches(node_id)})
        return tuple(sorted(values.values(), key=lambda item: (item.code, item.id)))

    def branch_sections(self, branch_id: str) -> tuple[object, ...]:
        """Return authoritative sections in increasing upstream-downstream chainage."""

        return tuple(self._sections.get(branch_id, ()))

    def branch_boundaries(self, branch_id: str) -> tuple[BoundaryCondition, ...]:
        """Return endpoint and lateral conditions attached to a branch."""

        return tuple(self._boundaries.get(branch_id, ()))

    def branch_structures(self, branch_id: str) -> tuple[HydraulicStructure, ...]:
        """Return structures in increasing chainage."""

        return tuple(self._structures.get(branch_id, ()))

    def connected_components(self) -> tuple[tuple[str, ...], ...]:
        """Return undirected node components to prevent accidental multi-model runs."""

        unseen = set(self.node_ids)
        components: list[tuple[str, ...]] = []
        while unseen:
            start = min(unseen)
            unseen.remove(start)
            queue = deque([start])
            component = {start}
            while queue:
                node_id = queue.popleft()
                for branch in self.connected_branches(node_id):
                    other = (
                        branch.downstream_node_id
                        if branch.upstream_node_id == node_id
                        else branch.upstream_node_id
                    )
                    if other not in component:
                        component.add(other)
                        unseen.discard(other)
                        queue.append(other)
            components.append(tuple(sorted(component)))
        return tuple(sorted(components, key=lambda item: item[0]))


class HydraulicNetworkValidator:
    """Own all topology, direction, chainage, boundary, and location checks."""

    def validate(self, model: Hydraulic1DModel) -> HydraulicNetworkGraph:
        """Fail with stable domain codes before any engine-specific mapping starts."""

        graph = HydraulicNetworkGraph(model)
        self._validate_topology(model, graph)
        self._validate_nodes(model, graph)
        self._validate_boundaries(model, graph)
        self._validate_locations(model, graph)
        return graph

    def _validate_topology(
        self, model: Hydraulic1DModel, graph: HydraulicNetworkGraph
    ) -> None:
        """Reject duplicate, disconnected, dangling, or directionless topology."""

        pairs: dict[tuple[str, str], str] = {}
        for branch in model.branches:
            if branch.end_chainage_m <= branch.start_chainage_m:
                self._reject(
                    "INVALID_BRANCH_DIRECTION",
                    f"branch {branch.id} must increase chainage upstream to downstream",
                    "branches",
                )
            key = branch.upstream_node_id, branch.downstream_node_id
            duplicate = pairs.get(key)
            if duplicate is not None:
                self._reject(
                    "NETWORK_DUPLICATE_TOPOLOGY",
                    f"branches {duplicate} and {branch.id} repeat the same directed edge",
                    "branches",
                )
            pairs[key] = branch.id
        components = graph.connected_components()
        if len(components) != 1:
            self._reject(
                "NETWORK_DISCONNECTED",
                f"simulation network resolves to {len(components)} connected components",
                "branches",
            )

    def _validate_nodes(
        self, model: Hydraulic1DModel, graph: HydraulicNetworkGraph
    ) -> None:
        """Check explicit node roles against actual directed branch incidence."""

        if not model.nodes:
            return
        for node in model.nodes:
            incoming = len(graph.incoming_branches(node.id))
            outgoing = len(graph.outgoing_branches(node.id))
            degree = incoming + outgoing
            if degree == 0:
                self._reject(
                    "NETWORK_ISOLATED_NODE",
                    f"node {node.id} is not connected to a branch",
                    "nodes",
                )
            if not self._role_matches(node, incoming, outgoing):
                self._reject(
                    "NETWORK_NODE_ROLE_INVALID",
                    (
                        f"node {node.id} role {node.node_type} conflicts with "
                        f"{incoming} incoming and {outgoing} outgoing branches"
                    ),
                    "nodes",
                )

    @staticmethod
    def _role_matches(node: HydraulicNode, incoming: int, outgoing: int) -> bool:
        """Allow a generic junction at mixed nodes while keeping strict common roles."""

        if node.node_type == "storage_connection":
            return incoming + outgoing >= 1
        if node.node_type == "boundary":
            return (incoming, outgoing) in {(0, 1), (1, 0)}
        if node.node_type == "internal":
            return incoming == 1 and outgoing == 1
        if node.node_type == "bifurcation":
            return incoming >= 1 and outgoing >= 2
        return incoming >= 2 and outgoing >= 1

    def _validate_boundaries(
        self, model: Hydraulic1DModel, graph: HydraulicNetworkGraph
    ) -> None:
        """Require every free source/sink endpoint to have exactly one external boundary."""

        endpoint_keys: set[tuple[str, str]] = set()
        upstream_count = 0
        downstream_count = 0
        branch_map = {item.id: item for item in model.branches}
        for boundary in model.boundaries:
            branch = branch_map[boundary.branch_id]
            if boundary.location == "lateral":
                continue
            node_id = (
                branch.upstream_node_id
                if boundary.location == "upstream"
                else branch.downstream_node_id
            )
            incoming = len(graph.incoming_branches(node_id))
            outgoing = len(graph.outgoing_branches(node_id))
            is_free = (
                incoming == 0 if boundary.location == "upstream" else outgoing == 0
            )
            if not is_free:
                self._reject(
                    "NETWORK_BOUNDARY_INTERNAL",
                    f"boundary {boundary.id} is attached to internal node {node_id}",
                    "boundaries",
                )
            key = boundary.location, node_id
            if key in endpoint_keys:
                self._reject(
                    "NETWORK_BOUNDARY_DUPLICATE",
                    f"node {node_id} has more than one {boundary.location} boundary",
                    "boundaries",
                )
            endpoint_keys.add(key)
            if boundary.location == "upstream":
                upstream_count += 1
            else:
                downstream_count += 1
        if upstream_count == 0 or downstream_count == 0:
            self._reject(
                "NETWORK_BOUNDARY_MISSING",
                "network requires at least one upstream and one downstream boundary",
                "boundaries",
            )
        source_nodes = {
            node_id
            for node_id in graph.node_ids
            if not graph.incoming_branches(node_id) and graph.outgoing_branches(node_id)
        }
        sink_nodes = {
            node_id
            for node_id in graph.node_ids
            if graph.incoming_branches(node_id) and not graph.outgoing_branches(node_id)
        }
        missing_sources = sorted(
            source_nodes.difference(
                node for location, node in endpoint_keys if location == "upstream"
            )
        )
        missing_sinks = sorted(
            sink_nodes.difference(
                node for location, node in endpoint_keys if location == "downstream"
            )
        )
        if missing_sources or missing_sinks:
            self._reject(
                "NETWORK_BOUNDARY_MISSING",
                f"unbounded source nodes={missing_sources}; sink nodes={missing_sinks}",
                "boundaries",
            )

    def _validate_locations(
        self, model: Hydraulic1DModel, graph: HydraulicNetworkGraph
    ) -> None:
        """Keep lateral inflows and structures on a resolvable branch location."""

        branch_map = {item.id: item for item in model.branches}
        for boundary in model.boundaries:
            if boundary.location != "lateral":
                continue
            branch = branch_map[boundary.branch_id]
            assert boundary.chainage_m is not None
            if (
                not branch.start_chainage_m
                < boundary.chainage_m
                < branch.end_chainage_m
            ):
                self._reject(
                    "INVALID_LATERAL_INFLOW",
                    f"lateral boundary {boundary.id} must lie inside its branch",
                    "boundaries",
                )
        for structure in model.structures:
            branch = branch_map[structure.branch_id]
            if branch.start_chainage_m < structure.chainage_m < branch.end_chainage_m:
                continue
            node_id = structure.metadata.get("node_id")
            endpoint_nodes = {branch.upstream_node_id, branch.downstream_node_id}
            if not isinstance(node_id, str) or node_id not in endpoint_nodes:
                self._reject(
                    "STRUCTURE_LOCATION_INVALID",
                    f"structure {structure.id} at an endpoint requires a connected node_id",
                    "structures",
                )

    @staticmethod
    def _reject(code: str, message: str, field_path: str) -> None:
        """Raise the common machine-readable validation error."""

        raise Hydraulic1DValidationError(code, message, field_path=field_path)
