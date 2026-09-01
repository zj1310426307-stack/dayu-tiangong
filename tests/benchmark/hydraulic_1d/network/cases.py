"""Deterministic engineering cases for branched networks and native structures."""

from __future__ import annotations

from dataclasses import dataclass

from model.hydraulic_1d import (
    BoundaryCondition,
    CrossSectionPoint,
    Hydraulic1DModel,
    HydraulicBranch,
    HydraulicCrossSection,
    HydraulicNode,
    HydraulicStructure,
    InitialCondition,
    SectionInitialState,
    SimulationSettings,
    TimeValue,
)


@dataclass(frozen=True, slots=True)
class EngineeringNetworkCase:
    """Describe one stable real-runtime engineering acceptance case."""

    case_id: str
    model: Hydraulic1DModel
    expected_internal_nodes: tuple[str, ...]


_DURATION_SECONDS = 7200.0
_DEPTH_M = 2.5


def _node(node_id: str, node_type: str) -> HydraulicNode:
    """Create an explicit node with a stable human-readable code."""

    return HydraulicNode(id=node_id, code=node_id.upper(), node_type=node_type)


def _branch(
    branch_id: str,
    upstream_node_id: str,
    downstream_node_id: str,
) -> HydraulicBranch:
    """Create one kilometre-long directed branch."""

    return HydraulicBranch(
        id=branch_id,
        code=branch_id.upper(),
        upstream_node_id=upstream_node_id,
        downstream_node_id=downstream_node_id,
        start_chainage_m=0.0,
        end_chainage_m=1000.0,
    )


def _sections(
    branch: HydraulicBranch,
    *,
    upstream_bed_m: float,
    downstream_bed_m: float,
    width_m: float,
) -> tuple[HydraulicCrossSection, ...]:
    """Create three profiles whose bed and water surface meet at shared nodes."""

    result: list[HydraulicCrossSection] = []
    for index in range(11):
        chainage_m = index * 100.0
        fraction = chainage_m / 1000.0
        bed_m = upstream_bed_m + fraction * (downstream_bed_m - upstream_bed_m)
        result.append(
            HydraulicCrossSection(
                id=f"{branch.id}-xs-{index}",
                branch_id=branch.id,
                code=f"{branch.code}-XS-{index}",
                chainage_m=chainage_m,
                vertical_datum="engineering-benchmark-datum",
                points=(
                    CrossSectionPoint(station_m=0.0, elevation_m=bed_m + 8.0),
                    CrossSectionPoint(station_m=4.0, elevation_m=bed_m),
                    CrossSectionPoint(
                        station_m=4.0 + width_m,
                        elevation_m=bed_m,
                    ),
                    CrossSectionPoint(
                        station_m=8.0 + width_m,
                        elevation_m=bed_m + 8.0,
                    ),
                ),
                manning_n=0.03,
            )
        )
    return tuple(result)


def _constant_boundary(
    boundary_id: str,
    branch_id: str,
    location: str,
    variable: str,
    value: float,
) -> BoundaryCondition:
    """Create one explicit constant endpoint condition."""

    return BoundaryCondition(
        id=boundary_id,
        branch_id=branch_id,
        location=location,
        variable=variable,
        series=(TimeValue(time_seconds=0.0, value=value),),
    )


def _model(
    case_id: str,
    *,
    nodes: tuple[HydraulicNode, ...],
    branch_specs: tuple[tuple[HydraulicBranch, float, float, float, float], ...],
    boundaries: tuple[BoundaryCondition, ...],
    structures: tuple[HydraulicStructure, ...] = (),
) -> Hydraulic1DModel:
    """Assemble one graph while keeping initial branch discharge explicit."""

    sections = tuple(
        section
        for branch, upstream_bed, downstream_bed, width, _ in branch_specs
        for section in _sections(
            branch,
            upstream_bed_m=upstream_bed,
            downstream_bed_m=downstream_bed,
            width_m=width,
        )
    )
    flow_by_branch = {branch.id: flow for branch, _, _, _, flow in branch_specs}
    return Hydraulic1DModel(
        simulation_id=case_id,
        scenario_id=case_id,
        network_id=f"{case_id}-network",
        nodes=nodes,
        branches=tuple(item[0] for item in branch_specs),
        cross_sections=sections,
        boundaries=boundaries,
        initial_condition=InitialCondition(
            by_section=tuple(
                SectionInitialState(
                    cross_section_id=section.id,
                    water_level_m=min(point.elevation_m for point in section.points)
                    + _DEPTH_M,
                    discharge_m3s=flow_by_branch[section.branch_id],
                )
                for section in sections
            )
        ),
        settings=SimulationSettings(
            duration_seconds=_DURATION_SECONDS,
            time_step_seconds=0.5,
            output_interval_seconds=20.0,
        ),
        structures=structures,
        metadata={
            "horizontal_unit": "m",
            "vertical_unit": "m",
            "vertical_datum": "engineering-benchmark-datum",
            "benchmark_family": "HYDRO-1D-ENGINEERING-03",
        },
    )


def n01_confluence() -> EngineeringNetworkCase:
    """Two upstream branches merge into one downstream branch."""

    a = _branch("branch-a", "source-a", "junction")
    b = _branch("branch-b", "source-b", "junction")
    c = _branch("branch-c", "junction", "sink")
    model = _model(
        "N01-confluence",
        nodes=(
            _node("source-a", "boundary"),
            _node("source-b", "boundary"),
            _node("junction", "junction"),
            _node("sink", "boundary"),
        ),
        branch_specs=(
            (a, 0.20, 0.10, 10.0, 4.0),
            (b, 0.20, 0.10, 12.0, 6.0),
            (c, 0.10, 0.00, 15.0, 10.0),
        ),
        boundaries=(
            _constant_boundary("q-a", a.id, "upstream", "discharge", 4.0),
            _constant_boundary("q-b", b.id, "upstream", "discharge", 6.0),
            _constant_boundary("h-c", c.id, "downstream", "water_level", _DEPTH_M),
        ),
    )
    return EngineeringNetworkCase("N01", model, ("junction",))


def n02_bifurcation() -> EngineeringNetworkCase:
    """One upstream branch splits into hydraulically unequal outlets."""

    a = _branch("branch-a", "source", "split")
    b = _branch("branch-b", "split", "sink-b")
    c = _branch("branch-c", "split", "sink-c")
    model = _model(
        "N02-bifurcation",
        nodes=(
            _node("source", "boundary"),
            _node("split", "bifurcation"),
            _node("sink-b", "boundary"),
            _node("sink-c", "boundary"),
        ),
        branch_specs=(
            (a, 0.20, 0.10, 15.0, 10.0),
            (b, 0.10, 0.00, 12.0, 6.0),
            (c, 0.10, 0.00, 8.0, 4.0),
        ),
        boundaries=(
            _constant_boundary("q-a", a.id, "upstream", "discharge", 10.0),
            _constant_boundary("h-b", b.id, "downstream", "water_level", _DEPTH_M),
            _constant_boundary("h-c", c.id, "downstream", "water_level", _DEPTH_M),
        ),
    )
    return EngineeringNetworkCase("N02", model, ("split",))


def n03_branched_network() -> EngineeringNetworkCase:
    """A five-branch graph combines confluence and bifurcation nodes."""

    a = _branch("branch-a", "source-a", "join")
    b = _branch("branch-b", "source-b", "join")
    c = _branch("branch-c", "join", "split")
    d = _branch("branch-d", "split", "sink-d")
    e = _branch("branch-e", "split", "sink-e")
    model = _model(
        "N03-branched-network",
        nodes=(
            _node("source-a", "boundary"),
            _node("source-b", "boundary"),
            _node("join", "junction"),
            _node("split", "bifurcation"),
            _node("sink-d", "boundary"),
            _node("sink-e", "boundary"),
        ),
        branch_specs=(
            (a, 0.25, 0.15, 10.0, 4.0),
            (b, 0.25, 0.15, 12.0, 6.0),
            (c, 0.15, 0.08, 15.0, 10.0),
            (d, 0.08, 0.00, 11.0, 6.0),
            (e, 0.08, 0.00, 8.0, 4.0),
        ),
        boundaries=(
            _constant_boundary("q-a", a.id, "upstream", "discharge", 4.0),
            _constant_boundary("q-b", b.id, "upstream", "discharge", 6.0),
            _constant_boundary("h-d", d.id, "downstream", "water_level", _DEPTH_M),
            _constant_boundary("h-e", e.id, "downstream", "water_level", _DEPTH_M),
        ),
    )
    return EngineeringNetworkCase("N03", model, ("join", "split"))


def n04_lateral_inflow() -> EngineeringNetworkCase:
    """A time-varying lateral hydrograph enters one main river branch."""

    main = _branch("branch-main", "source", "sink")
    lateral = BoundaryCondition(
        id="q-lateral",
        branch_id=main.id,
        location="lateral",
        variable="discharge",
        chainage_m=700.0,
        series=(
            TimeValue(time_seconds=0.0, value=0.0),
            TimeValue(time_seconds=600.0, value=3.0),
            TimeValue(time_seconds=1200.0, value=1.0),
            TimeValue(time_seconds=1800.0, value=0.0),
            TimeValue(time_seconds=_DURATION_SECONDS, value=0.0),
        ),
    )
    model = _model(
        "N04-lateral-inflow",
        nodes=(_node("source", "boundary"), _node("sink", "boundary")),
        branch_specs=((main, 0.10, 0.00, 12.0, 8.0),),
        boundaries=(
            _constant_boundary("q-main", main.id, "upstream", "discharge", 8.0),
            _constant_boundary(
                "h-main", main.id, "downstream", "water_level", _DEPTH_M
            ),
            lateral,
        ),
    )
    return EngineeringNetworkCase("N04", model, ())


def n05_combined_boundaries() -> EngineeringNetworkCase:
    """Combine two Q(t) sources, one H(t) sink, and a lateral hydrograph."""

    case = n01_confluence()
    dynamic: list[BoundaryCondition] = []
    for boundary in case.model.boundaries:
        if boundary.location == "upstream":
            factor = 1.0 if boundary.id == "q-a" else 1.5
            dynamic.append(
                boundary.model_copy(
                    update={
                        "series": (
                            TimeValue(time_seconds=0.0, value=4.0 * factor),
                            TimeValue(time_seconds=600.0, value=7.0 * factor),
                            TimeValue(time_seconds=1800.0, value=4.0 * factor),
                            TimeValue(
                                time_seconds=_DURATION_SECONDS, value=4.0 * factor
                            ),
                        )
                    }
                )
            )
        else:
            dynamic.append(boundary)
    dynamic.append(
        BoundaryCondition(
            id="q-lateral",
            branch_id="branch-c",
            location="lateral",
            variable="discharge",
            chainage_m=700.0,
            series=(
                TimeValue(time_seconds=0.0, value=0.0),
                TimeValue(time_seconds=600.0, value=2.0),
                TimeValue(time_seconds=1800.0, value=0.0),
                TimeValue(time_seconds=_DURATION_SECONDS, value=0.0),
            ),
        )
    )
    model = case.model.model_copy(
        update={
            "simulation_id": "N05-combined-boundaries",
            "scenario_id": "N05-combined-boundaries",
            "network_id": "N05-combined-boundaries-network",
            "boundaries": tuple(dynamic),
        }
    )
    return EngineeringNetworkCase("N05", model, ("junction",))


def s01_broad_crested_weir() -> EngineeringNetworkCase:
    """Place one fixed native geometric broad-crested weir on a single branch."""

    main = _branch("branch-main", "source", "sink")
    weir = HydraulicStructure(
        id="weir-01",
        name="S01 fixed broad-crested weir",
        branch_id=main.id,
        kind="weir",
        chainage_m=500.0,
        geometry={"crest_elevation_m": 2.45, "crest_width_m": 12.0},
        hydraulic_law_type="broad_crested_weir",
        hydraulic_law_parameters={"discharge_coefficient": 0.435},
        operation_rule_type="fixed",
    )
    model = _model(
        "S01-broad-crested-weir",
        nodes=(_node("source", "boundary"), _node("sink", "boundary")),
        branch_specs=((main, 0.10, 0.00, 12.0, 8.0),),
        boundaries=(
            _constant_boundary("q-main", main.id, "upstream", "discharge", 8.0),
            _constant_boundary(
                "h-main", main.id, "downstream", "water_level", _DEPTH_M
            ),
        ),
        structures=(weir,),
    )
    model = model.model_copy(
        update={"metadata": {**model.metadata, "mascaret_kernel": "rezo"}}
    )
    return EngineeringNetworkCase("S01", model, ())


NETWORK_CASES = (
    n01_confluence,
    n02_bifurcation,
    n03_branched_network,
    n04_lateral_inflow,
    n05_combined_boundaries,
)

STRUCTURE_CASES = (s01_broad_crested_weir,)
