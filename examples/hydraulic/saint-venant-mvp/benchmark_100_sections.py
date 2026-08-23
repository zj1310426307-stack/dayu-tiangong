"""Reproduce the HYDRO-MODEL-02-B 100-section throughput smoke gate.

The case is a fully wet, non-rectangular lake at rest.  It measures solver
throughput at the task-book scale without claiming transient-wave accuracy,
Gate/Pump capacity, or production sizing.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from typing import Sequence

from model.geometry import TabulatedSectionGeometry
from model.solver.finite_volume import (
    BoundaryPair,
    BoundarySeries,
    DownstreamStageBoundary,
    FiniteVolumeCell,
    FiniteVolumeMesh,
    HydraulicState,
    SingleBranchConfig,
    UpstreamDischargeBoundary,
    solve_single_branch,
)


def _positive_number(value: str) -> float:
    """Parse one finite positive command-line number."""

    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise argparse.ArgumentTypeError("value must be finite and positive")
    return parsed


def _positive_integer(value: str) -> int:
    """Parse one positive section count."""

    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def build_case(
    *,
    section_count: int,
    duration_seconds: float,
) -> tuple[FiniteVolumeMesh, HydraulicState, BoundaryPair, SingleBranchConfig]:
    """Build the frozen non-rectangular lake-at-rest performance case."""

    if section_count <= 0:
        raise ValueError("section_count must be positive")
    if not math.isfinite(duration_seconds) or duration_seconds <= 0.0:
        raise ValueError("duration_seconds must be finite and positive")

    stage = 5.0
    profile = ((0.0, 8.0), (10.0, 0.0), (20.0, 8.0))
    cells = tuple(
        FiniteVolumeCell(
            cell_id=f"cell-{index:03d}",
            dx=100.0,
            section_id=f"section-{index:03d}",
            bed_elevation=0.0,
            geometry=TabulatedSectionGeometry.from_points(profile),
            manning_n=0.0,
        )
        for index in range(section_count)
    )
    mesh = FiniteVolumeMesh(cells)
    initial_area = mesh.cells[0].geometry.area(stage)
    initial_state = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=(initial_area,) * section_count,
        discharge=(0.0,) * section_count,
        dry_depth=1.0e-3,
    )
    boundaries = BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries(
                (0.0, duration_seconds),
                (0.0, 0.0),
                "discharge",
            )
        ),
        downstream=DownstreamStageBoundary(
            BoundarySeries(
                (0.0, duration_seconds),
                (stage, stage),
                "stage",
            )
        ),
    )
    config = SingleBranchConfig(
        end_time=duration_seconds,
        maximum_dt=30.0,
        output_interval=min(3600.0, duration_seconds),
        cfl_number=0.7,
        maximum_steps=1_000_000,
        water_balance_tolerance=0.01,
    )
    return mesh, initial_state, boundaries, config


def run_benchmark(
    *,
    section_count: int = 100,
    duration_seconds: float = 86_400.0,
    target_seconds: float = 60.0,
) -> dict[str, object]:
    """Run the smoke case and return machine-readable timing and quality evidence."""

    if not math.isfinite(target_seconds) or target_seconds <= 0.0:
        raise ValueError("target_seconds must be finite and positive")
    mesh, initial_state, boundaries, config = build_case(
        section_count=section_count,
        duration_seconds=duration_seconds,
    )
    started = time.perf_counter()
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial_state,
        boundaries=boundaries,
        config=config,
    )
    elapsed = time.perf_counter() - started
    diagnostics = result.diagnostics
    quality_passed = (
        diagnostics.water_balance_status == "pass"
        and diagnostics.retry_count == 0
        and diagnostics.maximum_cfl <= config.cfl_number + 1.0e-12
        and result.states[-1].time == duration_seconds
    )
    return {
        "accepted_steps": diagnostics.step_count,
        "benchmark_scope": (
            "fully-wet non-rectangular lake-at-rest throughput smoke; "
            "not a general transient or production capacity claim"
        ),
        "duration_seconds": duration_seconds,
        "elapsed_seconds": elapsed,
        "maximum_cfl": diagnostics.maximum_cfl,
        "minimum_dt": diagnostics.minimum_dt,
        "output_states": len(result.states),
        "quality_passed": quality_passed,
        "relative_water_balance_error": diagnostics.relative_water_balance_error,
        "retry_count": diagnostics.retry_count,
        "section_count": section_count,
        "section_type": "tabulated-v-shape",
        "target_passed": quality_passed and elapsed < target_seconds,
        "target_seconds": target_seconds,
        "water_balance_status": diagnostics.water_balance_status,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line benchmark and fail when its explicit gate fails."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections", type=_positive_integer, default=100)
    parser.add_argument("--duration-seconds", type=_positive_number, default=86_400.0)
    parser.add_argument("--target-seconds", type=_positive_number, default=60.0)
    args = parser.parse_args(argv)
    evidence = run_benchmark(
        section_count=args.sections,
        duration_seconds=args.duration_seconds,
        target_seconds=args.target_seconds,
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["target_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
