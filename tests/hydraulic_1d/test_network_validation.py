"""Verify centralized solver-neutral network validation and indexed traversal."""

from __future__ import annotations

from time import perf_counter

import pytest

from model.hydraulic_1d import (
    BoundaryCondition,
    CrossSectionPoint,
    Hydraulic1DModel,
    HydraulicBranch,
    HydraulicCrossSection,
    HydraulicNode,
    InitialCondition,
    SimulationSettings,
    TimeValue,
)
from model.hydraulic_1d.errors import Hydraulic1DValidationError
from model.hydraulic_1d.network import HydraulicNetworkGraph, HydraulicNetworkValidator
from tests.benchmark.hydraulic_1d.network.cases import (
    n01_confluence,
    n02_bifurcation,
)


def test_graph_indexes_confluence_and_bifurcation_in_linear_traversals() -> None:
    """Expose stable incoming/outgoing queries for adapters and APIs."""

    confluence = HydraulicNetworkGraph(n01_confluence().model)
    assert [item.id for item in confluence.incoming_branches("junction")] == [
        "branch-a",
        "branch-b",
    ]
    assert [item.id for item in confluence.outgoing_branches("junction")] == [
        "branch-c"
    ]
    bifurcation = HydraulicNetworkValidator().validate(n02_bifurcation().model)
    assert len(bifurcation.incoming_branches("split")) == 1
    assert len(bifurcation.outgoing_branches("split")) == 2


def test_disconnected_branch_is_rejected() -> None:
    """Never submit two accidental components as one solver network."""

    source = n01_confluence().model
    extra = HydraulicBranch(
        id="detached",
        code="DETACHED",
        upstream_node_id="detached-up",
        downstream_node_id="detached-down",
        start_chainage_m=0.0,
        end_chainage_m=1000.0,
    )
    sections = tuple(
        HydraulicCrossSection(
            id=f"detached-{index}",
            branch_id=extra.id,
            code=f"DETACHED-{index}",
            chainage_m=chainage,
            vertical_datum="engineering-benchmark-datum",
            points=(
                CrossSectionPoint(station_m=0.0, elevation_m=8.0),
                CrossSectionPoint(station_m=4.0, elevation_m=0.0),
                CrossSectionPoint(station_m=14.0, elevation_m=0.0),
                CrossSectionPoint(station_m=18.0, elevation_m=8.0),
            ),
            manning_n=0.03,
        )
        for index, chainage in enumerate((0.0, 1000.0), start=1)
    )
    model = source.model_copy(
        update={
            "nodes": (),
            "branches": (*source.branches, extra),
            "cross_sections": (*source.cross_sections, *sections),
        }
    )
    with pytest.raises(Hydraulic1DValidationError, match="NETWORK_DISCONNECTED"):
        HydraulicNetworkValidator().validate(model)


def test_internal_endpoint_boundary_is_rejected() -> None:
    """Endpoint laws may only attach to external graph sources or sinks."""

    source = n01_confluence().model
    internal = BoundaryCondition(
        id="internal-q",
        branch_id="branch-c",
        location="upstream",
        variable="discharge",
        series=(TimeValue(time_seconds=0.0, value=1.0),),
    )
    model = source.model_copy(update={"boundaries": (*source.boundaries, internal)})
    with pytest.raises(Hydraulic1DValidationError, match="NETWORK_BOUNDARY_INTERNAL"):
        HydraulicNetworkValidator().validate(model)


def test_declared_node_role_must_match_directed_incidence() -> None:
    """Reject a bifurcation label on an actual two-in/one-out confluence."""

    source = n01_confluence().model
    nodes = tuple(
        node.model_copy(update={"node_type": "bifurcation"})
        if node.id == "junction"
        else node
        for node in source.nodes
    )
    model = source.model_copy(update={"nodes": nodes})
    with pytest.raises(Hydraulic1DValidationError, match="NETWORK_NODE_ROLE_INVALID"):
        HydraulicNetworkValidator().validate(model)


def _large_synthetic_network(branch_count: int = 120) -> Hydraulic1DModel:
    """Create one long graph with 600 profiles for non-runtime scaling checks."""

    points = (
        CrossSectionPoint(station_m=0.0, elevation_m=8.0),
        CrossSectionPoint(station_m=4.0, elevation_m=0.0),
        CrossSectionPoint(station_m=14.0, elevation_m=0.0),
        CrossSectionPoint(station_m=18.0, elevation_m=8.0),
    )
    branches = tuple(
        HydraulicBranch(
            id=f"branch-{index:03d}",
            code=f"B{index:03d}",
            upstream_node_id=f"node-{index:03d}",
            downstream_node_id=f"node-{index + 1:03d}",
            start_chainage_m=0.0,
            end_chainage_m=1000.0,
        )
        for index in range(branch_count)
    )
    sections = tuple(
        HydraulicCrossSection(
            id=f"{branch.id}-xs-{section_index}",
            branch_id=branch.id,
            code=f"{branch.code}-XS-{section_index}",
            chainage_m=chainage_m,
            vertical_datum="large-network-datum",
            points=points,
            manning_n=0.03,
        )
        for branch in branches
        for section_index, chainage_m in enumerate(
            (0.0, 250.0, 500.0, 750.0, 1000.0), start=1
        )
    )
    nodes = tuple(
        HydraulicNode(
            id=f"node-{index:03d}",
            code=f"N{index:03d}",
            node_type=("boundary" if index in {0, branch_count} else "internal"),
        )
        for index in range(branch_count + 1)
    )
    return Hydraulic1DModel(
        simulation_id="large-synthetic-network",
        scenario_id="large-synthetic-network",
        network_id="large-synthetic-network",
        nodes=nodes,
        branches=branches,
        cross_sections=sections,
        boundaries=(
            BoundaryCondition(
                id="q-up",
                branch_id=branches[0].id,
                location="upstream",
                variable="discharge",
                series=(TimeValue(time_seconds=0.0, value=10.0),),
            ),
            BoundaryCondition(
                id="h-down",
                branch_id=branches[-1].id,
                location="downstream",
                variable="water_level",
                series=(TimeValue(time_seconds=0.0, value=2.5),),
            ),
        ),
        initial_condition=InitialCondition(water_level_m=2.5, discharge_m3s=10.0),
        settings=SimulationSettings(
            duration_seconds=60.0,
            time_step_seconds=2.0,
            output_interval_seconds=10.0,
        ),
        metadata={
            "horizontal_unit": "m",
            "vertical_unit": "m",
            "vertical_datum": "large-network-datum",
        },
    )


def test_large_synthetic_network_validation_and_serialization_scale(tmp_path) -> None:
    """Exercise 120 branches and 600 profiles without a real solver run."""

    model = _large_synthetic_network()
    started = perf_counter()
    graph = HydraulicNetworkValidator().validate(model)
    validation_seconds = perf_counter() - started
    started = perf_counter()
    snapshot = model.model_dump_json()
    serialization_seconds = perf_counter() - started

    assert len(graph.node_ids) == 121
    assert len(snapshot) > 100_000
    # A generous regression tripwire, not a machine benchmark.
    assert validation_seconds < 2.0
    assert serialization_seconds < 2.0
    assert tmp_path.exists()
