"""Minimal single-branch orchestrator for the Dayu Saint-Venant MVP."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Sequence

from model.solver.finite_volume.boundary import BoundaryPair
from model.solver.finite_volume.diagnostics import NumericalStateError, require_quality
from model.solver.finite_volume.integrator import StepResult, advance_with_retries
from model.solver.finite_volume.mesh import FiniteVolumeMesh
from model.solver.finite_volume.state import HydraulicState
from model.solver.finite_volume.structures import FixedGate, OnOffPump

_TIME_TOLERANCE = 1.0e-9


@dataclass(frozen=True)
class SingleBranchConfig:
    """Freeze the MVP time, stability, wet/dry and output controls."""

    end_time: float
    maximum_dt: float
    output_interval: float
    cfl_number: float = 0.7
    dry_depth: float = 1.0e-3
    minimum_dt: float = 1.0e-6
    maximum_retries: int = 8
    maximum_steps: int = 1_000_000
    water_balance_tolerance: float = 0.01
    scheme: Literal["hll", "rusanov"] = "hll"

    def __post_init__(self) -> None:
        """Reject unsafe controls before any boundary or state evaluation."""

        positive = (self.end_time, self.maximum_dt, self.output_interval, self.minimum_dt)
        if not all(math.isfinite(item) and item > 0.0 for item in positive):
            raise ValueError("end/max/output/min time controls must be finite and positive")
        if not 0.0 < self.cfl_number <= 1.0:
            raise ValueError("cfl_number must lie in (0, 1]")
        if not math.isfinite(self.dry_depth) or self.dry_depth < 0.0:
            raise ValueError("dry_depth must be finite and non-negative")
        if self.maximum_retries < 0 or self.maximum_steps <= 0:
            raise ValueError("retry count must be non-negative and maximum_steps positive")
        if not 0.0 < self.water_balance_tolerance < 1.0:
            raise ValueError("water_balance_tolerance must lie in (0, 1)")


@dataclass(frozen=True)
class SingleBranchDiagnostics:
    """Report dynamic storage, signed boundaries, pump outflow and limitations."""

    initial_storage: float
    final_storage: float
    upstream_boundary_volume: float
    downstream_boundary_volume: float
    pump_outflow_volume: float
    water_balance_residual: float
    relative_water_balance_error: float
    water_balance_status: Literal["pass", "fail"]
    maximum_cfl: float
    minimum_dt: float
    retry_count: int
    step_count: int
    diagnostic_flags: tuple[str, ...]


@dataclass(frozen=True)
class SingleBranchResult:
    """Return output-aligned accepted states, step evidence and diagnostics."""

    states: tuple[HydraulicState, ...]
    steps: tuple[StepResult, ...]
    diagnostics: SingleBranchDiagnostics


def storage(mesh: FiniteVolumeMesh, state: HydraulicState) -> float:
    """Return dynamic branch storage ``sum(A_i*dx_i)`` in cubic metres."""

    value = sum(area * cell.dx for area, cell in zip(state.area, mesh.cells))
    if not math.isfinite(value) or value < 0.0:
        raise NumericalStateError("branch storage must be finite and non-negative")
    return value


def solve_single_branch(
    *,
    mesh: FiniteVolumeMesh,
    initial_state: HydraulicState,
    boundaries: BoundaryPair,
    config: SingleBranchConfig,
    gates: Sequence[FixedGate] = (),
    pumps: Sequence[OnOffPump] = (),
) -> SingleBranchResult:
    """Run the composable single-river MVP and enforce its numerical gates.

    Every accepted step lands exactly on the next boundary knot, output time or
    simulation end.  Internal Gate transfer is excluded from the external
    water balance; an ON Pump is an explicit external outflow.
    """

    if config.end_time <= initial_state.time + _TIME_TOLERANCE:
        raise ValueError("end_time must be later than the initial-state time")
    if len(initial_state.area) != len(mesh.cells):
        raise ValueError("initial_state cell count must match the mesh")
    boundaries.validate_coverage(initial_state.time, config.end_time)
    require_quality(initial_state, mesh)

    current = initial_state
    initial_storage = storage(mesh, initial_state)
    output_states = [initial_state]
    steps: list[StepResult] = []
    next_output = min(initial_state.time + config.output_interval, config.end_time)
    upstream_volume = 0.0
    downstream_volume = 0.0
    pump_volume = 0.0
    flags: set[str] = {
        "boundary_closure_subcritical_mvp_zero_gradient_companion",
        "friction_semi_implicit_per_ssp_stage_not_full_imex",
    }

    while current.time < config.end_time - _TIME_TOLERANCE:
        if len(steps) >= config.maximum_steps:
            raise NumericalStateError("single-branch run exceeded maximum_steps")
        event_candidates = [config.end_time, next_output]
        breakpoint = boundaries.next_breakpoint_after(current.time)
        if breakpoint is not None:
            event_candidates.append(breakpoint)
        next_event = min(
            item for item in event_candidates if item > current.time + _TIME_TOLERANCE
        )
        requested_dt = min(config.maximum_dt, next_event - current.time)
        step = advance_with_retries(
            mesh=mesh,
            state=current,
            requested_dt=requested_dt,
            dry_depth=config.dry_depth,
            boundaries=boundaries,
            cfl_limit=config.cfl_number,
            minimum_dt=config.minimum_dt,
            maximum_retries=config.maximum_retries,
            gates=gates,
            pumps=pumps,
            scheme=config.scheme,
        )
        current = step.state
        steps.append(step)
        upstream_volume += step.budget.upstream_volume
        downstream_volume += step.budget.downstream_volume
        pump_volume += step.budget.pump_outflow_volume
        flags.update(step.diagnostic_flags)
        if current.time >= next_output - _TIME_TOLERANCE:
            output_states.append(current)
            next_output = min(next_output + config.output_interval, config.end_time)

    if output_states[-1].time < config.end_time - _TIME_TOLERANCE:
        output_states.append(current)
    final_storage = storage(mesh, current)
    storage_change = final_storage - initial_storage
    expected_change = upstream_volume - downstream_volume - pump_volume
    residual = storage_change - expected_change
    scale = max(
        abs(initial_storage),
        abs(storage_change),
        abs(upstream_volume) + abs(downstream_volume) + abs(pump_volume),
        1.0,
    )
    relative_error = abs(residual) / scale
    require_quality(
        current,
        mesh,
        maximum_cfl=current.diagnostics.maximum_cfl,
        cfl_limit=config.cfl_number,
        relative_water_balance_error=relative_error,
        water_balance_tolerance=config.water_balance_tolerance,
    )
    minimum_used = current.diagnostics.minimum_dt
    if minimum_used is None:
        raise NumericalStateError("completed run has no accepted time-step diagnostic")
    return SingleBranchResult(
        states=tuple(output_states),
        steps=tuple(steps),
        diagnostics=SingleBranchDiagnostics(
            initial_storage=initial_storage,
            final_storage=final_storage,
            upstream_boundary_volume=upstream_volume,
            downstream_boundary_volume=downstream_volume,
            pump_outflow_volume=pump_volume,
            water_balance_residual=residual,
            relative_water_balance_error=relative_error,
            water_balance_status="pass",
            maximum_cfl=current.diagnostics.maximum_cfl,
            minimum_dt=minimum_used,
            retry_count=current.diagnostics.retry_count,
            step_count=current.diagnostics.step_count,
            diagnostic_flags=tuple(sorted(flags)),
        ),
    )
