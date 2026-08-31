"""Deterministic benchmark inputs expressed only through the Dayu unified model."""

from __future__ import annotations

from dataclasses import dataclass

from model.hydraulic_1d import (
    BoundaryCondition,
    CrossSectionPoint,
    Hydraulic1DModel,
    HydraulicBranch,
    HydraulicCrossSection,
    InitialCondition,
    SectionInitialState,
    SimulationSettings,
    TimeValue,
    rectangular_manning_discharge,
)


@dataclass(frozen=True, slots=True)
class HydraulicBenchmarkCase:
    """Pair a stable benchmark identity with its executable Dayu input."""

    benchmark_id: str
    model: Hydraulic1DModel
    reference_velocity_m_s: float | None = None
    comparison_model: Hydraulic1DModel | None = None


def _profile(*, bed_m: float = 0.0, natural: bool = False) -> tuple[CrossSectionPoint, ...]:
    """Return either a trapezoidal or an asymmetric natural profile."""

    if natural:
        return (
            CrossSectionPoint(station_m=0.0, elevation_m=bed_m + 8.0),
            CrossSectionPoint(station_m=4.0, elevation_m=bed_m + 2.0),
            CrossSectionPoint(station_m=9.0, elevation_m=bed_m),
            CrossSectionPoint(station_m=15.0, elevation_m=bed_m + 0.4),
            CrossSectionPoint(station_m=23.0, elevation_m=bed_m + 7.5),
        )
    return (
        CrossSectionPoint(station_m=0.0, elevation_m=bed_m + 10.0),
        CrossSectionPoint(station_m=5.0, elevation_m=bed_m),
        CrossSectionPoint(station_m=15.0, elevation_m=bed_m),
        CrossSectionPoint(station_m=20.0, elevation_m=bed_m + 10.0),
    )


def _case(
    benchmark_id: str,
    *,
    manning: tuple[float, ...] = (0.03, 0.03),
    natural: bool = False,
    upstream: tuple[TimeValue, ...] = (TimeValue(time_seconds=0.0, value=11.0),),
    downstream: tuple[TimeValue, ...] = (TimeValue(time_seconds=0.0, value=2.5),),
) -> HydraulicBenchmarkCase:
    """Build a complete single-Branch benchmark with endpoint coverage."""

    count = len(manning)
    chainages = [1000.0 * index / (count - 1) for index in range(count)]
    sections = tuple(
        HydraulicCrossSection(
            id=f"section-{index + 1}",
            branch_id="branch-1",
            code=f"XS-{index + 1:02d}",
            chainage_m=chainage,
            vertical_datum="benchmark-local-datum",
            points=_profile(bed_m=-0.0001 * chainage, natural=natural),
            manning_n=manning[index],
        )
        for index, chainage in enumerate(chainages)
    )
    model = Hydraulic1DModel(
        simulation_id=benchmark_id,
        scenario_id=benchmark_id,
        network_id="benchmark-network",
        branches=(
            HydraulicBranch(
                id="branch-1",
                code="B1",
                upstream_node_id="upstream",
                downstream_node_id="downstream",
                start_chainage_m=0.0,
                end_chainage_m=1000.0,
            ),
        ),
        cross_sections=sections,
        boundaries=(
            BoundaryCondition(
                id="upstream-q",
                branch_id="branch-1",
                location="upstream",
                variable="discharge",
                series=upstream,
            ),
            BoundaryCondition(
                id="downstream-h",
                branch_id="branch-1",
                location="downstream",
                variable="water_level",
                series=downstream,
            ),
        ),
        initial_condition=InitialCondition(
            by_section=tuple(
                SectionInitialState(
                    cross_section_id=section.id,
                    # Start from a bed-parallel water surface instead of an
                    # artificial flat-stage transient before the benchmark load.
                    water_level_m=(
                        downstream[0].value + 0.0001 * (1000.0 - section.chainage_m)
                    ),
                    discharge_m3s=upstream[0].value,
                )
                for section in sections
            )
        ),
        settings=SimulationSettings(
            duration_seconds=3600.0,
            time_step_seconds=10.0,
            output_interval_seconds=60.0,
        ),
        metadata={
            "horizontal_unit": "m",
            "vertical_unit": "m",
            "vertical_datum": "benchmark-local-datum",
        },
    )
    return HydraulicBenchmarkCase(benchmark_id=benchmark_id, model=model)


def benchmark_01_uniform_rectangular() -> HydraulicBenchmarkCase:
    """Return a hydraulically closed near-vertical rectangular uniform-flow case."""

    benchmark_id = "benchmark-01-uniform-rectangular"
    width_m = 10.0
    depth_m = 2.0
    slope = 0.0001
    manning_n = 0.03
    discharge = rectangular_manning_discharge(
        width_m=width_m,
        depth_m=depth_m,
        manning_n=manning_n,
        slope=slope,
    )
    chainages = (0.0, 500.0, 1000.0)
    sections = tuple(
        HydraulicCrossSection(
            id=f"section-{index + 1}",
            branch_id="branch-1",
            code=f"XS-{index + 1:02d}",
            chainage_m=chainage,
            vertical_datum="benchmark-local-datum",
            # MASCARET's profile grammar requires strictly ordered stations;
            # one micrometre side widths represent the vertical rectangle walls.
            points=(
                CrossSectionPoint(
                    station_m=0.0,
                    elevation_m=-slope * chainage + 10.0,
                ),
                CrossSectionPoint(
                    station_m=1.0e-6,
                    elevation_m=-slope * chainage,
                ),
                CrossSectionPoint(
                    station_m=width_m + 1.0e-6,
                    elevation_m=-slope * chainage,
                ),
                CrossSectionPoint(
                    station_m=width_m + 2.0e-6,
                    elevation_m=-slope * chainage + 10.0,
                ),
            ),
            manning_n=manning_n,
        )
        for index, chainage in enumerate(chainages)
    )
    stages = tuple(-slope * chainage + depth_m for chainage in chainages)
    model = Hydraulic1DModel(
        simulation_id=benchmark_id,
        scenario_id=benchmark_id,
        network_id="benchmark-network",
        branches=(
            HydraulicBranch(
                id="branch-1",
                code="B1",
                upstream_node_id="upstream",
                downstream_node_id="downstream",
                start_chainage_m=chainages[0],
                end_chainage_m=chainages[-1],
            ),
        ),
        cross_sections=sections,
        boundaries=(
            BoundaryCondition(
                id="upstream-q",
                branch_id="branch-1",
                location="upstream",
                variable="discharge",
                series=(TimeValue(time_seconds=0.0, value=discharge),),
            ),
            BoundaryCondition(
                id="downstream-h",
                branch_id="branch-1",
                location="downstream",
                variable="water_level",
                series=(TimeValue(time_seconds=0.0, value=stages[-1]),),
            ),
        ),
        initial_condition=InitialCondition(
            by_section=tuple(
                SectionInitialState(
                    cross_section_id=section.id,
                    water_level_m=stage,
                    discharge_m3s=discharge,
                )
                for section, stage in zip(sections, stages)
            )
        ),
        settings=SimulationSettings(
            duration_seconds=3600.0,
            time_step_seconds=10.0,
            output_interval_seconds=60.0,
        ),
        metadata={
            "horizontal_unit": "m",
            "vertical_unit": "m",
            "vertical_datum": "benchmark-local-datum",
        },
    )
    return HydraulicBenchmarkCase(
        benchmark_id=benchmark_id,
        model=model,
        reference_velocity_m_s=discharge / (width_m * depth_m),
    )


def benchmark_02_roughness_sensitivity() -> HydraulicBenchmarkCase:
    """Return otherwise-identical low/high Manning cases for a paired run."""

    low = _case(
        "benchmark-02-roughness-low",
        manning=(0.025, 0.025, 0.025),
    )
    high = _case(
        "benchmark-02-roughness-high",
        manning=(0.045, 0.045, 0.045),
    )
    return HydraulicBenchmarkCase(
        benchmark_id="benchmark-02-roughness-sensitivity",
        model=low.model,
        comparison_model=high.model,
    )


def benchmark_03_flood_hydrograph() -> HydraulicBenchmarkCase:
    """Return a non-steady hydrograph with an explicit peak and arrival time."""

    return _case(
        "benchmark-03-flood-hydrograph",
        # Interior profiles provide a downstream observation point that is not
        # the prescribed H(t) boundary itself.
        manning=(0.03, 0.03, 0.03, 0.03, 0.03),
        upstream=(
            TimeValue(time_seconds=0.0, value=11.0),
            TimeValue(time_seconds=1200.0, value=35.0),
            TimeValue(time_seconds=2400.0, value=18.0),
            TimeValue(time_seconds=3600.0, value=11.0),
        ),
    )


def benchmark_04_natural_sections() -> HydraulicBenchmarkCase:
    """Return three asymmetric surveyed-style profiles with ordered chainage."""

    return _case(
        "benchmark-04-natural-sections",
        manning=(0.032, 0.034, 0.036),
        natural=True,
    )


def benchmark_05_boundary_series() -> HydraulicBenchmarkCase:
    """Return independently varying upstream Q(t) and downstream H(t)."""

    return _case(
        "benchmark-05-boundary-series",
        upstream=(
            TimeValue(time_seconds=0.0, value=10.0),
            TimeValue(time_seconds=1800.0, value=20.0),
            TimeValue(time_seconds=3600.0, value=15.0),
        ),
        downstream=(
            TimeValue(time_seconds=0.0, value=2.5),
            TimeValue(time_seconds=1800.0, value=2.8),
            TimeValue(time_seconds=3600.0, value=2.6),
        ),
    )


ALL_BENCHMARKS = (
    benchmark_01_uniform_rectangular,
    benchmark_02_roughness_sensitivity,
    benchmark_03_flood_hydrograph,
    benchmark_04_natural_sections,
    benchmark_05_boundary_series,
)
