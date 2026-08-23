"""Restricted synchronized Branch advance for the C3b-J2 Junction gate.

This module deliberately advances only one acyclic 1-in/2-out network.  Every
SSP-RK2 stage solves the J1 characteristic Junction again, then applies the
completed Branch-end traces as physical boundary fluxes.  The implementation
does not claim vector-momentum compatibility, wet/dry support, structures,
roughness, or a general network solver.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping

from model.solver.finite_volume.boundary import (
    SUBCRITICAL_CHARACTERISTIC_V1,
    BoundaryPair,
    DownstreamStageBoundary,
    UpstreamDischargeBoundary,
    subcritical_characteristic_properties,
)
from model.solver.finite_volume.diagnostics import (
    NumericalStateError,
    StabilityError,
    require_quality,
)
from model.solver.finite_volume.flux import ConservedVector
from model.solver.finite_volume.integrator import (
    StageBudget,
    cfl_number_for_step,
    estimate_cfl_time_step,
    forward_euler_stage,
)
from model.solver.finite_volume.junction import (
    JunctionBoundaryState,
    JunctionCharacteristicSolution,
    JunctionSolverConfig,
    OneInTwoOutJunctionSolver,
)
from model.solver.finite_volume.mesh import FiniteVolumeCell
from model.solver.finite_volume.network_foundation import (
    FiniteVolumeNetwork,
    NodeId,
)
from model.solver.finite_volume.solver import storage
from model.solver.finite_volume.state import HydraulicState, SolverDiagnostics

_TIME_TOLERANCE = 1.0e-9
_FLOW_TOLERANCE = 1.0e-12


def _frozen_states(
    states: Mapping[str, HydraulicState],
) -> Mapping[str, HydraulicState]:
    """Copy one Branch-state mapping into deterministic immutable storage."""

    return MappingProxyType(dict(sorted(states.items())))


@dataclass(frozen=True)
class BranchDownstreamBoundary:
    """Bind one external H(t) boundary to its exact outgoing Branch."""

    branch_id: str
    boundary: DownstreamStageBoundary

    def __post_init__(self) -> None:
        """Reject an unidentified or non-characteristic external sink."""

        if not self.branch_id:
            raise ValueError("downstream boundary Branch identity must not be empty")
        if not isinstance(self.boundary, DownstreamStageBoundary):
            raise TypeError("downstream Branch boundary must prescribe stage")
        if self.boundary.boundary_closure != SUBCRITICAL_CHARACTERISTIC_V1:
            raise ValueError("C3b-J2 requires characteristic downstream boundaries")


@dataclass(frozen=True)
class OneInTwoOutBoundarySet:
    """Own the one source Q(t) and two sink H(t) external boundaries."""

    upstream: UpstreamDischargeBoundary
    downstream: tuple[BranchDownstreamBoundary, ...]

    def __post_init__(self) -> None:
        """Freeze identities and require one versioned characteristic closure."""

        object.__setattr__(self, "downstream", tuple(self.downstream))
        if not isinstance(self.upstream, UpstreamDischargeBoundary):
            raise TypeError("network upstream boundary must prescribe discharge")
        if self.upstream.boundary_closure != SUBCRITICAL_CHARACTERISTIC_V1:
            raise ValueError("C3b-J2 requires a characteristic upstream boundary")
        if len(self.downstream) != 2:
            raise ValueError("C3b-J2 requires exactly two downstream boundaries")
        branch_ids = tuple(item.branch_id for item in self.downstream)
        if len(set(branch_ids)) != 2:
            raise ValueError("downstream boundary Branch identities must be unique")

    def downstream_for(self, branch_id: str) -> DownstreamStageBoundary:
        """Resolve one H(t) boundary by exact outgoing Branch identity."""

        matches = tuple(
            item.boundary for item in self.downstream if item.branch_id == branch_id
        )
        if len(matches) != 1:
            raise ValueError(f"no unique downstream boundary for Branch {branch_id!r}")
        return matches[0]

    def validate_coverage(self, start_time: float, end_time: float) -> None:
        """Reject a run that would extrapolate any external process."""

        self.upstream.series.validate_coverage(start_time, end_time)
        for item in self.downstream:
            item.boundary.series.validate_coverage(start_time, end_time)

    def next_breakpoint_after(self, time: float) -> float | None:
        """Return the next Q/H knot across all three external boundaries."""

        candidates = [self.upstream.series.next_breakpoint_after(time)]
        candidates.extend(
            item.boundary.series.next_breakpoint_after(time)
            for item in self.downstream
        )
        available = tuple(item for item in candidates if item is not None)
        return min(available) if available else None


@dataclass(frozen=True)
class OneInTwoOutNetworkConfig:
    """Freeze the restricted network time, CFL, retry, and quality controls."""

    end_time: float
    maximum_dt: float
    output_interval: float
    cfl_number: float = 0.7
    dry_depth: float = 1.0e-3
    minimum_dt: float = 1.0e-6
    maximum_retries: int = 8
    maximum_steps: int = 1_000_000
    water_balance_tolerance: float = 1.0e-8

    def __post_init__(self) -> None:
        """Reject controls outside the C3b-J2 numerical contract."""

        positive = (
            self.end_time,
            self.maximum_dt,
            self.output_interval,
            self.minimum_dt,
        )
        if not all(math.isfinite(value) and value > 0.0 for value in positive):
            raise ValueError("network end/max/output/min times must be positive")
        if not 0.0 < self.cfl_number <= 1.0:
            raise ValueError("network cfl_number must lie in (0, 1]")
        if not math.isfinite(self.dry_depth) or self.dry_depth < 0.0:
            raise ValueError("network dry_depth must be finite and non-negative")
        if isinstance(self.maximum_retries, bool) or self.maximum_retries < 0:
            raise ValueError("network maximum_retries must be non-negative")
        if isinstance(self.maximum_steps, bool) or self.maximum_steps <= 0:
            raise ValueError("network maximum_steps must be positive")
        if not 0.0 < self.water_balance_tolerance < 1.0:
            raise ValueError("network water_balance_tolerance must lie in (0, 1)")


@dataclass(frozen=True)
class NetworkCflEstimate:
    """Expose the globally limiting Branch, cell, speed, and stable dt."""

    time_step: float
    maximum_signal_speed: float
    limiting_branch_id: str | None
    limiting_cell: int | None


@dataclass(frozen=True)
class NetworkStageBudget:
    """Record instantaneous external fluxes and internal Junction closure."""

    upstream_flux: float
    downstream_fluxes: tuple[tuple[str, float], ...]
    junction_inflow: float
    junction_outflows: tuple[tuple[str, float], ...]
    junction_mass_residual: float

    def __post_init__(self) -> None:
        """Keep stage accounting finite, unique, and algebraically consistent."""

        object.__setattr__(self, "downstream_fluxes", tuple(self.downstream_fluxes))
        object.__setattr__(self, "junction_outflows", tuple(self.junction_outflows))
        values = (
            self.upstream_flux,
            self.junction_inflow,
            self.junction_mass_residual,
            *(value for _, value in self.downstream_fluxes),
            *(value for _, value in self.junction_outflows),
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("network stage budget values must be finite")
        if self.upstream_flux <= _FLOW_TOLERANCE:
            raise ValueError("C3b-J2 external upstream trace must remain forward")
        if self.junction_inflow <= _FLOW_TOLERANCE:
            raise ValueError("C3b-J2 Junction incoming trace must remain forward")
        if any(value <= _FLOW_TOLERANCE for _, value in self.downstream_fluxes):
            raise ValueError("C3b-J2 external downstream traces must remain forward")
        if any(value <= _FLOW_TOLERANCE for _, value in self.junction_outflows):
            raise ValueError("C3b-J2 Junction outgoing traces must remain forward")
        for entries, label in (
            (self.downstream_fluxes, "downstream"),
            (self.junction_outflows, "Junction outgoing"),
        ):
            identities = tuple(branch_id for branch_id, _ in entries)
            if len(identities) != 2 or len(set(identities)) != 2:
                raise ValueError(f"network stage requires two unique {label} Branches")
        expected = self.junction_inflow - sum(
            value for _, value in self.junction_outflows
        )
        if not math.isclose(
            self.junction_mass_residual,
            expected,
            rel_tol=0.0,
            abs_tol=1.0e-12 * max(abs(self.junction_inflow), 1.0),
        ):
            raise ValueError("Junction stage mass residual is inconsistent")


@dataclass(frozen=True)
class NetworkEulerStageResult:
    """Return one simultaneous Euler state set and its node-stage evidence."""

    states: Mapping[str, HydraulicState]
    budget: NetworkStageBudget
    junction: JunctionCharacteristicSolution

    def __post_init__(self) -> None:
        """Detach the stage state mapping from mutable caller ownership."""

        object.__setattr__(self, "states", _frozen_states(self.states))


@dataclass(frozen=True)
class NetworkStepBudget:
    """Store SSP-RK2 trapezoidal external and internal transfer volumes."""

    upstream_volume: float
    downstream_volumes: tuple[tuple[str, float], ...]
    junction_transfer_volumes: tuple[tuple[str, float], ...]
    junction_mass_residual_volume: float

    def __post_init__(self) -> None:
        """Freeze and validate the accepted volume ledger."""

        object.__setattr__(self, "downstream_volumes", tuple(self.downstream_volumes))
        object.__setattr__(
            self,
            "junction_transfer_volumes",
            tuple(self.junction_transfer_volumes),
        )
        values = (
            self.upstream_volume,
            self.junction_mass_residual_volume,
            *(value for _, value in self.downstream_volumes),
            *(value for _, value in self.junction_transfer_volumes),
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("network step budget values must be finite")
        if self.upstream_volume <= 0.0:
            raise ValueError("network step upstream volume must be positive")
        if len(self.downstream_volumes) != 2 or any(
            value <= 0.0 for _, value in self.downstream_volumes
        ):
            raise ValueError("network step requires two positive sink volumes")
        if len(self.junction_transfer_volumes) != 3 or any(
            value <= 0.0 for _, value in self.junction_transfer_volumes
        ):
            raise ValueError("network step requires three positive Junction transfers")

    @property
    def total_downstream_volume(self) -> float:
        """Return the sum of the two accepted sink outflow volumes."""

        return sum(value for _, value in self.downstream_volumes)

    @property
    def external_net_volume(self) -> float:
        """Return source inflow minus both sink outflows."""

        return self.upstream_volume - self.total_downstream_volume


@dataclass(frozen=True)
class NetworkStepResult:
    """Hold one accepted synchronized SSP-RK2 network step."""

    states: Mapping[str, HydraulicState]
    dt: float
    maximum_cfl: float
    budget: NetworkStepBudget
    junction_stages: tuple[JunctionCharacteristicSolution, ...]

    def __post_init__(self) -> None:
        """Freeze the accepted Branch mapping and require both RK node solves."""

        object.__setattr__(self, "states", _frozen_states(self.states))
        object.__setattr__(self, "junction_stages", tuple(self.junction_stages))
        if not math.isfinite(self.dt) or self.dt <= 0.0:
            raise ValueError("network step dt must be finite and positive")
        if not math.isfinite(self.maximum_cfl) or self.maximum_cfl < 0.0:
            raise ValueError("network step CFL must be finite and non-negative")
        if len(self.junction_stages) != 2:
            raise ValueError("network SSP-RK2 step requires two Junction solves")


@dataclass(frozen=True)
class NetworkSnapshot:
    """Expose one output-aligned accepted state for every Branch."""

    time: float
    states: Mapping[str, HydraulicState]

    def __post_init__(self) -> None:
        """Freeze the snapshot and require a common authoritative time."""

        object.__setattr__(self, "states", _frozen_states(self.states))
        if not self.states:
            raise ValueError("network snapshot requires Branch states")
        if any(
            not math.isclose(state.time, self.time, rel_tol=0.0, abs_tol=1.0e-12)
            for state in self.states.values()
        ):
            raise ValueError("network snapshot states do not share its time")


@dataclass(frozen=True)
class OneInTwoOutNetworkDiagnostics:
    """Report unified storage, external volume, CFL, retry, and scope evidence."""

    initial_storage: float
    final_storage: float
    upstream_boundary_volume: float
    downstream_boundary_volumes: tuple[tuple[str, float], ...]
    junction_mass_residual_volume: float
    water_balance_residual: float
    closure_adjusted_residual: float
    relative_water_balance_error: float
    maximum_cfl: float
    minimum_dt: float
    retry_count: int
    step_count: int
    junction_stage_count: int
    water_balance_status: str
    diagnostic_flags: tuple[str, ...]


@dataclass(frozen=True)
class OneInTwoOutNetworkResult:
    """Return output snapshots, accepted steps, and restricted J2 diagnostics."""

    snapshots: tuple[NetworkSnapshot, ...]
    steps: tuple[NetworkStepResult, ...]
    diagnostics: OneInTwoOutNetworkDiagnostics

    def __post_init__(self) -> None:
        """Freeze result sequences so they cannot become runtime state."""

        object.__setattr__(self, "snapshots", tuple(self.snapshots))
        object.__setattr__(self, "steps", tuple(self.steps))


@dataclass(frozen=True)
class _NetworkScope:
    """Hold identities derived from the one accepted topology shape."""

    junction_node_id: NodeId
    incoming_branch_id: str
    outgoing_branch_ids: tuple[str, str]


@dataclass(frozen=True)
class _CompletedTraceBoundary:
    """Adapt a completed Junction trace to the existing physical-flux path."""

    trace: JunctionBoundaryState
    time: float
    boundary_closure: str = SUBCRITICAL_CHARACTERISTIC_V1

    def __post_init__(self) -> None:
        """Reject a trace adapter without one finite matching solve time."""

        if not math.isfinite(self.time) or self.time < 0.0:
            raise ValueError("Junction trace time must be finite and non-negative")

    def ghost_state(
        self,
        *,
        time: float,
        interior: ConservedVector,
        cell: FiniteVolumeCell,
    ) -> ConservedVector:
        """Return the exact stage-owned trace without mixing it through HLL."""

        del interior
        if not math.isclose(time, self.time, rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError("Junction trace time does not match the Branch stage")
        if cell.cell_id != self.trace.cell_id:
            raise ValueError("Junction trace is bound to the wrong Branch-end cell")
        return ConservedVector(self.trace.area, self.trace.discharge)

def _trace_boundary(
    trace: JunctionBoundaryState,
    time: float,
) -> _CompletedTraceBoundary:
    """Construct one immutable trace adapter with an explicit stage time."""

    return _CompletedTraceBoundary(trace, float(time))


def _network_scope(network: FiniteVolumeNetwork) -> _NetworkScope:
    """Resolve and validate the exact connected 1-in/2-out C3b-J2 graph."""

    if len(network.branches) != 3:
        raise ValueError("C3b-J2 requires exactly three Branches")
    internal = tuple(item for item in network.incidences if item.is_internal)
    if len(internal) != 1:
        raise ValueError("C3b-J2 requires exactly one internal Junction")
    incidence = internal[0]
    if len(incidence.incoming_branch_ids) != 1 or len(
        incidence.outgoing_branch_ids
    ) != 2:
        raise ValueError(
            "C3b-J2 requires exactly one incoming and two outgoing Branches"
        )
    sources = tuple(item for item in network.incidences if item.is_external_source)
    sinks = tuple(item for item in network.incidences if item.is_external_sink)
    if len(sources) != 1 or len(sinks) != 2:
        raise ValueError("C3b-J2 requires one source node and two sink nodes")
    incoming = incidence.incoming_branch_ids[0]
    if sources[0].outgoing_branch_ids != (incoming,):
        raise ValueError("C3b-J2 source must feed the incoming Junction Branch")
    outgoing = tuple(sorted(incidence.outgoing_branch_ids))
    if {item.incoming_branch_ids[0] for item in sinks} != set(outgoing):
        raise ValueError("C3b-J2 sinks must terminate both outgoing Branches")
    return _NetworkScope(incidence.node_id, incoming, (outgoing[0], outgoing[1]))


def _common_diagnostics(
    states: Mapping[str, HydraulicState],
) -> SolverDiagnostics:
    """Require one unified diagnostic history across all Branch owners."""

    diagnostics = tuple(state.diagnostics for state in states.values())
    reference = diagnostics[0]
    if any(value != reference for value in diagnostics[1:]):
        raise ValueError("network Branch diagnostics must remain synchronized")
    return reference


def _validate_stage_scope(
    *,
    network: FiniteVolumeNetwork,
    states: Mapping[str, HydraulicState],
    dry_depth: float,
) -> tuple[float, _NetworkScope]:
    """Enforce fully wet, positive, subcritical, flat-prismatic zero-n scope."""

    time = network.validate_synchronized_states(states)
    scope = _network_scope(network)
    _common_diagnostics(states)
    for branch in network.branches:
        state = states[branch.branch_id]
        first_cell = branch.mesh.cells[0]
        if any(cell.manning_n != 0.0 for cell in branch.mesh.cells):
            raise ValueError("C3b-J2 supports only zero-friction Branches")
        if any(
            cell.bed_elevation != first_cell.bed_elevation
            or cell.geometry != first_cell.geometry
            for cell in branch.mesh.cells[1:]
        ):
            raise ValueError("C3b-J2 supports only flat prismatic geometry per Branch")
        if state.gate_state or state.pump_state:
            raise ValueError("C3b-J2 does not accept Gate or Pump runtime state")
        if not all(state.wet_mask):
            raise ValueError("C3b-J2 requires every Branch cell to remain fully wet")
        for index, (cell, area, discharge) in enumerate(
            zip(branch.mesh.cells, state.area, state.discharge)
        ):
            depth = float(cell.geometry.stage_from_area(area)) - cell.bed_elevation
            if depth <= dry_depth:
                raise ValueError("C3b-J2 cell depth must exceed dry_depth")
            properties = subcritical_characteristic_properties(
                state=ConservedVector(area, discharge),
                cell=cell,
                label=f"C3b-J2 Branch {branch.branch_id} cell {index}",
            )
            tolerance = max(
                _FLOW_TOLERANCE,
                _FLOW_TOLERANCE * area * properties.celerity,
            )
            if discharge <= tolerance:
                raise ValueError(
                    "C3b-J2 requires positive forward discharge in every cell"
                )
    return time, scope


def network_storage(
    network: FiniteVolumeNetwork,
    states: Mapping[str, HydraulicState],
) -> float:
    """Return total dynamic Branch storage without counting a zero-volume node."""

    network.validate_synchronized_states(states)
    value = sum(
        storage(branch.mesh, states[branch.branch_id]) for branch in network.branches
    )
    if not math.isfinite(value) or value < 0.0:
        raise NumericalStateError("network storage must be finite and non-negative")
    return value


def estimate_network_cfl_time_step(
    *,
    network: FiniteVolumeNetwork,
    states: Mapping[str, HydraulicState],
    cfl_number: float,
    maximum_dt: float,
) -> NetworkCflEstimate:
    """Return one time step limited by the most restrictive Branch cell."""

    network.validate_synchronized_states(states)
    estimates = []
    maximum_speed = 0.0
    for branch in network.branches:
        estimate = estimate_cfl_time_step(
            mesh=branch.mesh,
            state=states[branch.branch_id],
            cfl_number=cfl_number,
            maximum_dt=maximum_dt,
        )
        estimates.append((estimate.time_step, branch.branch_id, estimate.limiting_cell))
        maximum_speed = max(maximum_speed, estimate.maximum_signal_speed)
    time_step, branch_id, cell_index = min(estimates, key=lambda item: item[0])
    return NetworkCflEstimate(time_step, maximum_speed, branch_id, cell_index)


def _branch_boundaries(
    *,
    scope: _NetworkScope,
    branch_id: str,
    external: OneInTwoOutBoundarySet,
    junction: JunctionCharacteristicSolution,
) -> BoundaryPair:
    """Compose one external end and one completed Junction physical trace."""

    traces = {state.branch_id: state for state in junction.boundary_states}
    trace_boundary = _trace_boundary(traces[branch_id], junction.time)
    if branch_id == scope.incoming_branch_id:
        return BoundaryPair(  # type: ignore[arg-type]
            upstream=external.upstream,
            downstream=trace_boundary,
        )
    return BoundaryPair(  # type: ignore[arg-type]
        upstream=trace_boundary,
        downstream=external.downstream_for(branch_id),
    )


def _network_euler_stage(
    *,
    network: FiniteVolumeNetwork,
    states: Mapping[str, HydraulicState],
    dt: float,
    dry_depth: float,
    boundaries: OneInTwoOutBoundarySet,
    junction_solver: OneInTwoOutJunctionSolver,
) -> NetworkEulerStageResult:
    """Advance all Branches from one shared stage-owned Junction solution."""

    _, scope = _validate_stage_scope(
        network=network,
        states=states,
        dry_depth=dry_depth,
    )
    junction = junction_solver.solve_node_stage(
        network=network,
        node_id=scope.junction_node_id,
        states=states,
    )
    advanced: dict[str, HydraulicState] = {}
    budgets: dict[str, StageBudget] = {}
    for branch_id in network.topological_branch_order:
        branch = network.branch(branch_id)
        result = forward_euler_stage(
            mesh=branch.mesh,
            state=states[branch_id],
            dt=dt,
            dry_depth=dry_depth,
            boundaries=_branch_boundaries(
                scope=scope,
                branch_id=branch_id,
                external=boundaries,
                junction=junction,
            ),
            scheme="hll",
            geometry_source_mode="hydrostatic-reconstruction-v1",
        )
        advanced[branch_id] = result.state
        budgets[branch_id] = result.budget
    network.validate_synchronized_states(advanced)
    traces = {state.branch_id: state for state in junction.boundary_states}
    junction_outflows = tuple(
        (branch_id, traces[branch_id].discharge)
        for branch_id in scope.outgoing_branch_ids
    )
    junction_inflow = traces[scope.incoming_branch_id].discharge
    return NetworkEulerStageResult(
        states=advanced,
        budget=NetworkStageBudget(
            upstream_flux=budgets[scope.incoming_branch_id].upstream_flux,
            downstream_fluxes=tuple(
                (branch_id, budgets[branch_id].downstream_flux)
                for branch_id in scope.outgoing_branch_ids
            ),
            junction_inflow=junction_inflow,
            junction_outflows=junction_outflows,
            junction_mass_residual=junction_inflow
            - sum(value for _, value in junction_outflows),
        ),
        junction=junction,
    )


def one_in_two_out_network_ssp_rk2_step(
    *,
    network: FiniteVolumeNetwork,
    states: Mapping[str, HydraulicState],
    dt: float,
    dry_depth: float,
    boundaries: OneInTwoOutBoundarySet,
    cfl_limit: float,
    junction_solver: OneInTwoOutJunctionSolver | None = None,
) -> NetworkStepResult:
    """Advance one synchronized RK2 step and recompute Junction traces twice."""

    _, scope = _validate_stage_scope(
        network=network,
        states=states,
        dry_depth=dry_depth,
    )
    solver = junction_solver or OneInTwoOutJunctionSolver()
    initial_cfl = max(
        cfl_number_for_step(
            mesh=branch.mesh,
            state=states[branch.branch_id],
            dt=dt,
        )
        for branch in network.branches
    )
    if initial_cfl > cfl_limit + 1.0e-12:
        raise StabilityError("requested network step exceeds the configured CFL limit")
    first = _network_euler_stage(
        network=network,
        states=states,
        dt=dt,
        dry_depth=dry_depth,
        boundaries=boundaries,
        junction_solver=solver,
    )
    stage_cfl = max(
        cfl_number_for_step(
            mesh=branch.mesh,
            state=first.states[branch.branch_id],
            dt=dt,
        )
        for branch in network.branches
    )
    maximum_cfl = max(initial_cfl, stage_cfl)
    if maximum_cfl > cfl_limit + 1.0e-12:
        raise StabilityError("network RK2 intermediate stage exceeds the CFL limit")
    second = _network_euler_stage(
        network=network,
        states=first.states,
        dt=dt,
        dry_depth=dry_depth,
        boundaries=boundaries,
        junction_solver=solver,
    )

    accepted: dict[str, HydraulicState] = {}
    diagnostics = _common_diagnostics(states).accepted_step(
        dt=dt,
        cfl=maximum_cfl,
    )
    for branch in network.branches:
        branch_id = branch.branch_id
        original = states[branch_id]
        evolved = second.states[branch_id]
        try:
            accepted[branch_id] = HydraulicState.from_conserved(
                mesh=branch.mesh,
                time=original.time + dt,
                area=tuple(
                    0.5 * (left + right)
                    for left, right in zip(original.area, evolved.area)
                ),
                discharge=tuple(
                    0.5 * (left + right)
                    for left, right in zip(original.discharge, evolved.discharge)
                ),
                dry_depth=dry_depth,
                diagnostics=diagnostics,
            )
        except ValueError as exc:
            raise NumericalStateError(str(exc)) from exc
    _validate_stage_scope(
        network=network,
        states=accepted,
        dry_depth=dry_depth,
    )

    def trapezoidal(
        left: tuple[tuple[str, float], ...],
        right: tuple[tuple[str, float], ...],
    ) -> tuple[tuple[str, float], ...]:
        """Integrate matching Branch flows across the two RK stages."""

        left_map = dict(left)
        right_map = dict(right)
        if left_map.keys() != right_map.keys():
            raise NumericalStateError(
                "network stage Branch identities changed inside RK2"
            )
        return tuple(
            (branch_id, 0.5 * dt * (left_map[branch_id] + right_map[branch_id]))
            for branch_id in sorted(left_map)
        )

    junction_left = (
        (scope.incoming_branch_id, first.budget.junction_inflow),
        *first.budget.junction_outflows,
    )
    junction_right = (
        (scope.incoming_branch_id, second.budget.junction_inflow),
        *second.budget.junction_outflows,
    )
    return NetworkStepResult(
        states=accepted,
        dt=dt,
        maximum_cfl=maximum_cfl,
        budget=NetworkStepBudget(
            upstream_volume=0.5
            * dt
            * (first.budget.upstream_flux + second.budget.upstream_flux),
            downstream_volumes=trapezoidal(
                first.budget.downstream_fluxes,
                second.budget.downstream_fluxes,
            ),
            junction_transfer_volumes=trapezoidal(junction_left, junction_right),
            junction_mass_residual_volume=0.5
            * dt
            * (
                first.budget.junction_mass_residual
                + second.budget.junction_mass_residual
            ),
        ),
        junction_stages=(first.junction, second.junction),
    )


def advance_network_with_retries(
    *,
    network: FiniteVolumeNetwork,
    states: Mapping[str, HydraulicState],
    requested_dt: float,
    dry_depth: float,
    boundaries: OneInTwoOutBoundarySet,
    cfl_limit: float,
    minimum_dt: float,
    maximum_retries: int,
    junction_solver: OneInTwoOutJunctionSolver | None = None,
) -> NetworkStepResult:
    """Apply one global CFL choice and discard every Branch on any rejection."""

    _validate_stage_scope(network=network, states=states, dry_depth=dry_depth)
    estimate = estimate_network_cfl_time_step(
        network=network,
        states=states,
        cfl_number=cfl_limit,
        maximum_dt=requested_dt,
    )
    dt = estimate.time_step
    working = _frozen_states(states)
    if dt < requested_dt - 1.0e-12:
        working = _frozen_states(
            {
                branch_id: state.with_diagnostics(
                    state.diagnostics.reduced_time_step()
                )
                for branch_id, state in working.items()
            }
        )
    retries = 0
    while True:
        if dt < minimum_dt - 1.0e-15:
            raise StabilityError("required network retry step is below minimum_dt")
        try:
            return one_in_two_out_network_ssp_rk2_step(
                network=network,
                states=working,
                dt=dt,
                dry_depth=dry_depth,
                boundaries=boundaries,
                cfl_limit=cfl_limit,
                junction_solver=junction_solver,
            )
        except (NumericalStateError, StabilityError, ValueError) as exc:
            if retries >= maximum_retries:
                raise StabilityError(
                    "network step exhausted the unified retry budget"
                ) from exc
            retries += 1
            working = _frozen_states(
                {
                    branch_id: state.with_diagnostics(
                        state.diagnostics.rejected_step()
                    )
                    for branch_id, state in working.items()
                }
            )
            dt *= 0.5


def _validate_run_scope(
    *,
    network: FiniteVolumeNetwork,
    initial_states: Mapping[str, HydraulicState],
    boundaries: OneInTwoOutBoundarySet,
    config: OneInTwoOutNetworkConfig,
) -> _NetworkScope:
    """Perform non-retryable topology, state, and boundary preflight checks."""

    start_time, scope = _validate_stage_scope(
        network=network,
        states=initial_states,
        dry_depth=config.dry_depth,
    )
    if config.end_time <= start_time + _TIME_TOLERANCE:
        raise ValueError("network end_time must be later than the initial time")
    if {item.branch_id for item in boundaries.downstream} != set(
        scope.outgoing_branch_ids
    ):
        raise ValueError("network downstream boundaries must match outgoing Branches")
    boundaries.validate_coverage(start_time, config.end_time)
    return scope


def solve_one_in_two_out_network(
    *,
    network: FiniteVolumeNetwork,
    initial_states: Mapping[str, HydraulicState],
    boundaries: OneInTwoOutBoundarySet,
    config: OneInTwoOutNetworkConfig,
    junction_config: JunctionSolverConfig | None = None,
) -> OneInTwoOutNetworkResult:
    """Run the restricted C3b-J2 network and close one external water ledger."""

    _validate_run_scope(
        network=network,
        initial_states=initial_states,
        boundaries=boundaries,
        config=config,
    )
    solver = OneInTwoOutJunctionSolver(junction_config or JunctionSolverConfig())
    current = _frozen_states(initial_states)
    start_time = network.validate_synchronized_states(current)
    initial_storage = network_storage(network, current)
    snapshots = [NetworkSnapshot(start_time, current)]
    steps: list[NetworkStepResult] = []
    next_output = min(start_time + config.output_interval, config.end_time)
    upstream_volume = 0.0
    downstream_volumes = {
        item.branch_id: 0.0 for item in boundaries.downstream
    }
    junction_residual_volume = 0.0

    while (
        network.validate_synchronized_states(current)
        < config.end_time - _TIME_TOLERANCE
    ):
        if len(steps) >= config.maximum_steps:
            raise NumericalStateError("network run exceeded maximum_steps")
        time = network.validate_synchronized_states(current)
        candidates = [config.end_time, next_output]
        breakpoint = boundaries.next_breakpoint_after(time)
        if breakpoint is not None:
            candidates.append(breakpoint)
        next_event = min(
            value for value in candidates if value > time + _TIME_TOLERANCE
        )
        step = advance_network_with_retries(
            network=network,
            states=current,
            requested_dt=min(config.maximum_dt, next_event - time),
            dry_depth=config.dry_depth,
            boundaries=boundaries,
            cfl_limit=config.cfl_number,
            minimum_dt=config.minimum_dt,
            maximum_retries=config.maximum_retries,
            junction_solver=solver,
        )
        current = step.states
        steps.append(step)
        upstream_volume += step.budget.upstream_volume
        for branch_id, value in step.budget.downstream_volumes:
            downstream_volumes[branch_id] += value
        junction_residual_volume += step.budget.junction_mass_residual_volume
        time = network.validate_synchronized_states(current)
        if time >= next_output - _TIME_TOLERANCE:
            snapshots.append(NetworkSnapshot(time, current))
            next_output = min(next_output + config.output_interval, config.end_time)

    final_time = network.validate_synchronized_states(current)
    if snapshots[-1].time < final_time - _TIME_TOLERANCE:
        snapshots.append(NetworkSnapshot(final_time, current))
    final_storage = network_storage(network, current)
    storage_change = final_storage - initial_storage
    downstream_items = tuple(sorted(downstream_volumes.items()))
    external_net = upstream_volume - sum(value for _, value in downstream_items)
    residual = storage_change - external_net
    closure_adjusted = residual + junction_residual_volume
    scale = max(
        abs(initial_storage),
        abs(storage_change),
        abs(upstream_volume) + sum(abs(value) for _, value in downstream_items),
        1.0,
    )
    relative_error = abs(residual) / scale
    if relative_error >= config.water_balance_tolerance:
        raise NumericalStateError("network external water balance failed")
    if abs(closure_adjusted) / scale >= 1.0e-10:
        raise NumericalStateError("network Junction/storage ledger is inconsistent")

    diagnostics = _common_diagnostics(current)
    if diagnostics.minimum_dt is None:
        raise NumericalStateError("completed network run has no accepted dt")
    for branch in network.branches:
        require_quality(
            current[branch.branch_id],
            branch.mesh,
            maximum_cfl=diagnostics.maximum_cfl,
            cfl_limit=config.cfl_number,
            relative_water_balance_error=relative_error,
            water_balance_tolerance=config.water_balance_tolerance,
        )
    flags = (
        "network_1in2out_fully_wet_forward_subcritical_zero_friction_v1",
        "network_flat_prismatic_branch_hll_hydrostatic_reconstruction_v1",
        "junction_characteristic_recomputed_each_ssp_rk2_stage_v1",
        "junction_physical_trace_flux_v1",
        "network_synchronized_cfl_retry_v1",
        "network_external_boundary_water_balance_v1",
        "junction_vector_momentum_not_evaluated_no_branch_angle_v1",
        "gate_pump_wetdry_roughness_and_v4_backend_not_supported",
    )
    return OneInTwoOutNetworkResult(
        snapshots=tuple(snapshots),
        steps=tuple(steps),
        diagnostics=OneInTwoOutNetworkDiagnostics(
            initial_storage=initial_storage,
            final_storage=final_storage,
            upstream_boundary_volume=upstream_volume,
            downstream_boundary_volumes=downstream_items,
            junction_mass_residual_volume=junction_residual_volume,
            water_balance_residual=residual,
            closure_adjusted_residual=closure_adjusted,
            relative_water_balance_error=relative_error,
            maximum_cfl=diagnostics.maximum_cfl,
            minimum_dt=diagnostics.minimum_dt,
            retry_count=diagnostics.retry_count,
            step_count=diagnostics.step_count,
            junction_stage_count=2 * diagnostics.step_count,
            water_balance_status="pass",
            diagnostic_flags=flags,
        ),
    )


@dataclass(frozen=True)
class OneInTwoOutNetworkSolver:
    """Bind the restricted graph and policies behind a Branch solver contract."""

    network: FiniteVolumeNetwork
    boundaries: OneInTwoOutBoundarySet
    config: OneInTwoOutNetworkConfig
    junction_config: JunctionSolverConfig = JunctionSolverConfig()

    def __post_init__(self) -> None:
        """Require authoritative typed owners before any state is advanced."""

        if not isinstance(self.network, FiniteVolumeNetwork):
            raise TypeError("network solver requires FiniteVolumeNetwork")
        if not isinstance(self.boundaries, OneInTwoOutBoundarySet):
            raise TypeError("network solver requires OneInTwoOutBoundarySet")
        if not isinstance(self.config, OneInTwoOutNetworkConfig):
            raise TypeError("network solver requires OneInTwoOutNetworkConfig")
        if not isinstance(self.junction_config, JunctionSolverConfig):
            raise TypeError("network solver requires JunctionSolverConfig")

    def solve(
        self,
        *,
        initial_states: Mapping[str, HydraulicState],
    ) -> OneInTwoOutNetworkResult:
        """Run through the configured end time and return auditable evidence."""

        return solve_one_in_two_out_network(
            network=self.network,
            initial_states=initial_states,
            boundaries=self.boundaries,
            config=self.config,
            junction_config=self.junction_config,
        )

    def advance_branches(
        self,
        *,
        states: Mapping[str, HydraulicState],
        target_time: float,
    ) -> Mapping[str, HydraulicState]:
        """Advance all authoritative Branches to one exact requested time."""

        start_time = self.network.validate_synchronized_states(states)
        if (
            not math.isfinite(target_time)
            or target_time <= start_time + _TIME_TOLERANCE
        ):
            raise ValueError(
                "target_time must be finite and later than Branch state time"
            )
        if target_time > self.config.end_time + _TIME_TOLERANCE:
            raise ValueError("target_time exceeds the configured network horizon")
        run_config = replace(
            self.config,
            end_time=target_time,
            output_interval=target_time - start_time,
        )
        result = solve_one_in_two_out_network(
            network=self.network,
            initial_states=states,
            boundaries=self.boundaries,
            config=run_config,
            junction_config=self.junction_config,
        )
        return result.snapshots[-1].states
