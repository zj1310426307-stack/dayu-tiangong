"""Small deterministic Dayu models shared by adapter and parser tests."""

from __future__ import annotations

from model.hydraulic_1d import (
    BoundaryCondition,
    CrossSectionPoint,
    Hydraulic1DModel,
    HydraulicBranch,
    HydraulicCrossSection,
    InitialCondition,
    SimulationSettings,
    TimeValue,
)


def model_fixture(*, lateral: bool = False, manning_downstream: float = 0.03) -> Hydraulic1DModel:
    """Return a two-profile trapezoidal river with Q(t)/H(t) boundaries."""

    points = (
        CrossSectionPoint(station_m=0.0, elevation_m=10.0),
        CrossSectionPoint(station_m=5.0, elevation_m=0.0),
        CrossSectionPoint(station_m=15.0, elevation_m=0.0),
        CrossSectionPoint(station_m=20.0, elevation_m=10.0),
    )
    boundaries = [
        BoundaryCondition(
            id="upstream-q",
            branch_id="branch-1",
            location="upstream",
            variable="discharge",
            series=(TimeValue(time_seconds=0.0, value=11.0),),
        ),
        BoundaryCondition(
            id="downstream-h",
            branch_id="branch-1",
            location="downstream",
            variable="water_level",
            series=(TimeValue(time_seconds=0.0, value=2.0),),
        ),
    ]
    if lateral:
        boundaries.append(
            BoundaryCondition(
                id="lateral-q",
                branch_id="branch-1",
                location="lateral",
                variable="discharge",
                chainage_m=500.0,
                series=(
                    TimeValue(time_seconds=0.0, value=0.5),
                    TimeValue(time_seconds=600.0, value=0.5),
                ),
            )
        )
    return Hydraulic1DModel(
        simulation_id="simulation-1",
        scenario_id="scenario-1",
        network_id="network-1",
        branches=(
            HydraulicBranch(
                id="branch-1",
                code="B1",
                upstream_node_id="node-up",
                downstream_node_id="node-down",
                start_chainage_m=0.0,
                end_chainage_m=1000.0,
            ),
        ),
        cross_sections=(
            HydraulicCrossSection(
                id="section-up",
                branch_id="branch-1",
                code="XS-UP",
                chainage_m=0.0,
                vertical_datum="1985-national-height-datum",
                points=points,
                manning_n=0.03,
            ),
            HydraulicCrossSection(
                id="section-down",
                branch_id="branch-1",
                code="XS-DOWN",
                chainage_m=1000.0,
                vertical_datum="1985-national-height-datum",
                points=points,
                manning_n=manning_downstream,
            ),
        ),
        boundaries=tuple(boundaries),
        initial_condition=InitialCondition(water_level_m=2.0, discharge_m3s=11.0),
        settings=SimulationSettings(
            duration_seconds=600.0,
            time_step_seconds=10.0,
            output_interval_seconds=60.0,
        ),
        metadata={
            "horizontal_unit": "m",
            "vertical_unit": "m",
            "vertical_datum": "1985-national-height-datum",
        },
    )
