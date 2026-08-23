"""Restricted 1-in/2-out subcritical characteristic Junction closure."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from model.solver.finite_volume.boundary import (
    SUBCRITICAL_CHARACTERISTIC_V1,
    characteristic_potential,
    subcritical_characteristic_properties,
)
from model.solver.finite_volume.flux import ConservedVector, physical_flux
from model.solver.finite_volume.mesh import FiniteVolumeCell
from model.solver.finite_volume.network_foundation import (
    FiniteVolumeNetwork,
    JunctionPreclosureEvidence,
    JunctionTrace,
    NodeId,
    inspect_junction_preclosure,
)
from model.solver.finite_volume.state import HydraulicState

_FORWARD_FLOW_RELATIVE_TOLERANCE = 1.0e-12
_FORWARD_FLOW_ABSOLUTE_TOLERANCE = 1.0e-12
_JUNCTION_POLICY = "one-in-two-out-common-stage-characteristic-v1"
_MOMENTUM_POLICY = "not-evaluated-no-branch-angle-v1"


@dataclass(frozen=True)
class JunctionSolverConfig:
    """Freeze numerical tolerances for the restricted Junction root solve."""

    stage_tolerance_m: float = 1.0e-10
    normalized_mass_tolerance: float = 1.0e-10
    invariant_tolerance: float = 1.0e-10
    minimum_wet_depth_m: float = 1.0e-6
    maximum_iterations: int = 160

    def __post_init__(self) -> None:
        """Reject non-finite, non-positive, or boolean tolerance values."""

        values = (
            self.stage_tolerance_m,
            self.normalized_mass_tolerance,
            self.invariant_tolerance,
            self.minimum_wet_depth_m,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0.0
            for value in values
        ):
            raise ValueError("Junction solver tolerances must be finite and positive")
        if (
            isinstance(self.maximum_iterations, bool)
            or not isinstance(self.maximum_iterations, int)
            or self.maximum_iterations <= 0
        ):
            raise ValueError("Junction maximum_iterations must be a positive integer")


@dataclass(frozen=True)
class JunctionBoundaryState:
    """Store one completed Branch-end state and its invariant evidence."""

    node_id: NodeId
    branch_id: str
    cell_id: str
    endpoint: Literal["upstream", "downstream"]
    invariant_family: Literal["R+", "R-"]
    stage: float
    area: float
    discharge: float
    velocity: float
    celerity: float
    froude: float
    interior_invariant: float
    completed_invariant: float
    normalized_invariant_residual: float
    momentum_flux_per_density: float

    def __post_init__(self) -> None:
        """Require a wet forward subcritical state with the correct invariant side."""

        if not self.branch_id or not self.cell_id:
            raise ValueError("Junction boundary identities must not be empty")
        if self.endpoint not in {"upstream", "downstream"}:
            raise ValueError("Junction boundary endpoint is unsupported")
        expected_family = "R+" if self.endpoint == "downstream" else "R-"
        if self.invariant_family != expected_family:
            raise ValueError("Junction invariant family contradicts its Branch endpoint")
        values = (
            self.stage,
            self.area,
            self.discharge,
            self.velocity,
            self.celerity,
            self.froude,
            self.interior_invariant,
            self.completed_invariant,
            self.normalized_invariant_residual,
            self.momentum_flux_per_density,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Junction boundary state values must be finite")
        if self.area <= 0.0 or self.discharge <= 0.0 or self.celerity <= 0.0:
            raise ValueError("Junction boundary state must be fully wet and forward flowing")
        if self.froude < 0.0 or self.froude >= 1.0:
            raise ValueError("Junction boundary state must be strictly subcritical")
        if self.normalized_invariant_residual < 0.0:
            raise ValueError("Junction invariant residual must be non-negative")
        if not math.isclose(
            self.velocity,
            self.discharge / self.area,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        ):
            raise ValueError("Junction boundary velocity contradicts A and Q")
        if not math.isclose(
            self.froude,
            abs(self.velocity) / self.celerity,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        ):
            raise ValueError("Junction boundary Froude number is inconsistent")
        expected_residual = abs(
            self.completed_invariant - self.interior_invariant
        ) / max(
            abs(self.interior_invariant),
            abs(self.completed_invariant),
            1.0,
        )
        if not math.isclose(
            self.normalized_invariant_residual,
            expected_residual,
            rel_tol=0.0,
            abs_tol=1.0e-15,
        ):
            raise ValueError("Junction normalized invariant residual is inconsistent")

    @property
    def conserved(self) -> ConservedVector:
        """Return the completed conservative face trace ``U=(A,Q)``."""

        return ConservedVector(self.area, self.discharge)


@dataclass(frozen=True)
class JunctionCharacteristicEvidence:
    """Expose root, mass, invariant, and regime evidence without vector momentum."""

    node_id: NodeId
    time: float
    common_stage: float
    bracket_start_stage: float
    bracket_end_stage: float
    bracket_start_mass_residual: float
    bracket_end_mass_residual: float
    final_bracket_width: float
    iterations: int
    absolute_mass_residual: float
    normalized_mass_residual: float
    maximum_normalized_invariant_residual: float
    maximum_froude: float
    mass_residual_stage_derivative: float
    stage_tolerance_m: float
    normalized_mass_tolerance: float
    invariant_tolerance: float
    solution_policy: str = _JUNCTION_POLICY
    boundary_characteristic_policy: str = SUBCRITICAL_CHARACTERISTIC_V1
    characteristic_compatibility_ready: bool = True
    momentum_compatibility: str = _MOMENTUM_POLICY
    strong_coupling_ready: bool = False

    def __post_init__(self) -> None:
        """Prevent incomplete or relabelled evidence from passing as a node solve."""

        values = (
            self.time,
            self.common_stage,
            self.bracket_start_stage,
            self.bracket_end_stage,
            self.bracket_start_mass_residual,
            self.bracket_end_mass_residual,
            self.final_bracket_width,
            self.absolute_mass_residual,
            self.normalized_mass_residual,
            self.maximum_normalized_invariant_residual,
            self.maximum_froude,
            self.mass_residual_stage_derivative,
            self.stage_tolerance_m,
            self.normalized_mass_tolerance,
            self.invariant_tolerance,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Junction characteristic evidence must be finite")
        if self.time < 0.0:
            raise ValueError("Junction characteristic evidence time must be non-negative")
        if self.bracket_end_stage < self.bracket_start_stage:
            raise ValueError("Junction final stage bracket must be ordered")
        if self.bracket_start_mass_residual < 0.0:
            raise ValueError("Junction lower bracket must have non-negative residual")
        if self.bracket_end_mass_residual > 0.0:
            raise ValueError("Junction upper bracket must have non-positive residual")
        expected_width = self.bracket_end_stage - self.bracket_start_stage
        if not math.isclose(
            self.final_bracket_width,
            expected_width,
            rel_tol=0.0,
            abs_tol=max(self.stage_tolerance_m * 1.0e-6, 1.0e-15),
        ):
            raise ValueError("Junction final bracket width is inconsistent")
        if not self.bracket_start_stage <= self.common_stage <= self.bracket_end_stage:
            raise ValueError("Junction common stage must lie inside its final bracket")
        if isinstance(self.iterations, bool) or self.iterations <= 0:
            raise ValueError("Junction evidence iterations must be positive")
        if min(
            self.final_bracket_width,
            self.absolute_mass_residual,
            self.normalized_mass_residual,
            self.maximum_normalized_invariant_residual,
            self.maximum_froude,
        ) < 0.0:
            raise ValueError("Junction residuals and regime metrics must be non-negative")
        if min(
            self.stage_tolerance_m,
            self.normalized_mass_tolerance,
            self.invariant_tolerance,
        ) <= 0.0:
            raise ValueError("Junction evidence tolerances must be positive")
        if self.final_bracket_width > self.stage_tolerance_m:
            raise ValueError("Junction stage bracket exceeds its tolerance")
        if self.normalized_mass_residual > self.normalized_mass_tolerance:
            raise ValueError("Junction mass residual exceeds its tolerance")
        if self.maximum_normalized_invariant_residual > self.invariant_tolerance:
            raise ValueError("Junction invariant residual exceeds its tolerance")
        if self.maximum_froude >= 1.0:
            raise ValueError("Junction solution is not strictly subcritical")
        if self.mass_residual_stage_derivative >= 0.0:
            raise ValueError("Junction mass residual must decrease locally with stage")
        if self.solution_policy != _JUNCTION_POLICY:
            raise ValueError("unsupported Junction solution policy")
        if self.boundary_characteristic_policy != SUBCRITICAL_CHARACTERISTIC_V1:
            raise ValueError("unsupported Junction characteristic policy")
        if not isinstance(self.characteristic_compatibility_ready, bool):
            raise ValueError("Junction characteristic readiness must be boolean")
        if not isinstance(self.strong_coupling_ready, bool):
            raise ValueError("Junction strong-coupling readiness must be boolean")
        if not self.characteristic_compatibility_ready:
            raise ValueError("accepted Junction evidence must close its characteristics")
        if self.momentum_compatibility != _MOMENTUM_POLICY:
            raise ValueError("C3b-J1 must not claim vector momentum compatibility")
        if self.strong_coupling_ready:
            raise ValueError("C3b-J1 is not a full momentum-coupled Junction")


@dataclass(frozen=True)
class JunctionCharacteristicSolution:
    """Return three Branch-end traces plus independently checkable evidence."""

    node_id: NodeId
    time: float
    boundary_states: tuple[JunctionBoundaryState, ...]
    preclosure: JunctionPreclosureEvidence
    evidence: JunctionCharacteristicEvidence

    def __post_init__(self) -> None:
        """Keep solution identities, common stage, and evidence synchronized."""

        object.__setattr__(self, "boundary_states", tuple(self.boundary_states))
        if len(self.boundary_states) != 3:
            raise ValueError("C3b-J1 solution requires exactly three Branch traces")
        branch_ids = tuple(state.branch_id for state in self.boundary_states)
        if len(set(branch_ids)) != 3:
            raise ValueError("C3b-J1 solution Branch identities must be unique")
        if any(state.node_id != self.node_id for state in self.boundary_states):
            raise ValueError("Junction solution boundary state references the wrong node")
        if self.preclosure.node_id != self.node_id or self.evidence.node_id != self.node_id:
            raise ValueError("Junction solution evidence references the wrong node")
        if not math.isclose(self.time, self.evidence.time, rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError("Junction solution time contradicts its evidence")
        if not math.isclose(
            self.time,
            self.preclosure.time,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            raise ValueError("Junction solution time contradicts its pre-closure")
        if not self.preclosure.preliminary_passed:
            raise ValueError("Junction characteristic solution must pass pre-closure")
        if sum(state.endpoint == "downstream" for state in self.boundary_states) != 1:
            raise ValueError("C3b-J1 solution requires one downstream-end incoming trace")
        if sum(state.endpoint == "upstream" for state in self.boundary_states) != 2:
            raise ValueError("C3b-J1 solution requires two upstream-end outgoing traces")
        if any(
            not math.isclose(
                state.stage,
                self.evidence.common_stage,
                rel_tol=0.0,
                abs_tol=self.evidence.stage_tolerance_m,
            )
            for state in self.boundary_states
        ):
            raise ValueError("Junction boundary states do not share the solved stage")
        if not math.isclose(
            self.preclosure.common_stage,
            self.evidence.common_stage,
            rel_tol=0.0,
            abs_tol=self.evidence.stage_tolerance_m,
        ):
            raise ValueError("Junction pre-closure common stage is inconsistent")
        if not math.isclose(
            abs(self.preclosure.net_flow_into_node),
            self.evidence.absolute_mass_residual,
            rel_tol=0.0,
            abs_tol=1.0e-12
            * max(
                sum(abs(state.discharge) for state in self.boundary_states),
                1.0,
            ),
        ):
            raise ValueError("Junction absolute mass evidence is inconsistent")
        if not math.isclose(
            self.preclosure.normalized_mass_residual,
            self.evidence.normalized_mass_residual,
            rel_tol=0.0,
            abs_tol=1.0e-15,
        ):
            raise ValueError("Junction normalized mass evidence is inconsistent")
        if not math.isclose(
            max(state.froude for state in self.boundary_states),
            self.evidence.maximum_froude,
            rel_tol=0.0,
            abs_tol=1.0e-15,
        ):
            raise ValueError("Junction maximum Froude evidence is inconsistent")
        if not math.isclose(
            max(
                state.normalized_invariant_residual
                for state in self.boundary_states
            ),
            self.evidence.maximum_normalized_invariant_residual,
            rel_tol=0.0,
            abs_tol=1.0e-15,
        ):
            raise ValueError("Junction maximum invariant evidence is inconsistent")


@dataclass(frozen=True)
class OneInTwoOutJunctionSolver:
    """Solve one source-free 1-in/2-out node using characteristic compatibility."""

    config: JunctionSolverConfig = JunctionSolverConfig()

    def __post_init__(self) -> None:
        """Require the exact frozen configuration contract."""

        if not isinstance(self.config, JunctionSolverConfig):
            raise TypeError("Junction solver config must be JunctionSolverConfig")

    def solve_node_stage(
        self,
        *,
        network: FiniteVolumeNetwork,
        node_id: NodeId,
        states: Mapping[str, HydraulicState],
    ) -> JunctionCharacteristicSolution:
        """Complete Branch-end traces at one synchronized accepted/stage state.

        Incoming Branches preserve ``R+=u+Phi`` at their downstream end.
        Outgoing Branches preserve ``R-=u-Phi`` at their upstream end.  A
        scalar bisection finds the common absolute water level satisfying
        ``sum(Q_in)-sum(Q_out)=0``.  Vector momentum is not evaluated because
        C3b-J1 has no Branch-angle contract.
        """

        time = network.validate_synchronized_states(states)
        incidence = network.incidence(node_id)
        if len(incidence.incoming_branch_ids) != 1 or len(
            incidence.outgoing_branch_ids
        ) != 2:
            raise ValueError("C3b-J1 requires exactly one incoming and two outgoing Branches")

        endpoint_data: list[
            tuple[str, Literal["upstream", "downstream"], FiniteVolumeCell, ConservedVector]
        ] = []
        for branch_id in incidence.incoming_branch_ids:
            branch = network.branch(branch_id)
            endpoint_data.append(
                (
                    branch_id,
                    "downstream",
                    branch.mesh.cells[-1],
                    ConservedVector(
                        states[branch_id].area[-1],
                        states[branch_id].discharge[-1],
                    ),
                )
            )
        for branch_id in incidence.outgoing_branch_ids:
            branch = network.branch(branch_id)
            endpoint_data.append(
                (
                    branch_id,
                    "upstream",
                    branch.mesh.cells[0],
                    ConservedVector(
                        states[branch_id].area[0],
                        states[branch_id].discharge[0],
                    ),
                )
            )

        invariants: dict[str, float] = {}
        interior_stages: list[float] = []
        for branch_id, endpoint, cell, state in endpoint_data:
            if cell.manning_n != 0.0:
                raise ValueError("C3b-J1 supports only zero-friction endpoint cells")
            properties = subcritical_characteristic_properties(
                state=state,
                cell=cell,
                label=f"Junction interior Branch {branch_id}",
            )
            flow_tolerance = max(
                _FORWARD_FLOW_ABSOLUTE_TOLERANCE,
                _FORWARD_FLOW_RELATIVE_TOLERANCE * state.area * properties.celerity,
            )
            if state.discharge <= flow_tolerance:
                raise ValueError("C3b-J1 requires positive forward interior discharge")
            invariants[branch_id] = (
                properties.velocity + properties.potential
                if endpoint == "downstream"
                else properties.velocity - properties.potential
            )
            interior_stages.append(float(cell.geometry.stage_from_area(state.area)))

        minimum_stage = max(
            float(cell.geometry.minimum_stage) for _, _, cell, _ in endpoint_data
        )
        lower_offset = max(
            self.config.minimum_wet_depth_m,
            8.0 * math.ulp(minimum_stage),
        )
        lower = minimum_stage + lower_offset
        finite_maxima = tuple(
            float(cell.geometry.maximum_stage)
            for _, _, cell, _ in endpoint_data
            if cell.geometry.maximum_stage is not None
        )
        finite_upper = min(finite_maxima) if finite_maxima else None
        if finite_upper is not None and lower >= finite_upper:
            raise ValueError("C3b-J1 Branch sections have no common wet stage domain")

        def flows_at(stage: float) -> tuple[tuple[float, ...], tuple[float, ...]]:
            """Return incoming and outgoing positive-or-signed candidate flows."""

            incoming = []
            outgoing = []
            for branch_id, endpoint, cell, _ in endpoint_data:
                area = float(cell.geometry.area(stage))
                potential = characteristic_potential(cell=cell, area=area)
                invariant = invariants[branch_id]
                flow = (
                    area * (invariant - potential)
                    if endpoint == "downstream"
                    else area * (invariant + potential)
                )
                (incoming if endpoint == "downstream" else outgoing).append(flow)
            return tuple(incoming), tuple(outgoing)

        def residual(stage: float) -> tuple[float, float]:
            """Return absolute and normalized node mass residual at one stage."""

            incoming, outgoing = flows_at(stage)
            value = sum(incoming) - sum(outgoing)
            scale = max(
                sum(abs(flow) for flow in (*incoming, *outgoing)),
                1.0,
            )
            return value, abs(value) / scale

        lower_value, _ = residual(lower)
        if lower_value <= 0.0:
            raise ValueError("C3b-J1 has no positive forward root above the common bed")
        if finite_upper is not None:
            upper = finite_upper
            upper_value, _ = residual(upper)
            if upper_value >= 0.0:
                raise ValueError("C3b-J1 root lies outside the common section domain")
        else:
            maximum_depth = max(
                stage - minimum_stage for stage in interior_stages
            )
            upper_depth = max(2.0 * maximum_depth, 1.0)
            upper = minimum_stage + upper_depth
            upper_value, _ = residual(upper)
            for _ in range(128):
                if upper_value < 0.0:
                    break
                upper_depth *= 2.0
                upper = minimum_stage + upper_depth
                if not math.isfinite(upper):
                    break
                upper_value, _ = residual(upper)
            else:
                raise ValueError("C3b-J1 root was not bracketed")
            if not math.isfinite(upper) or upper_value >= 0.0:
                raise ValueError("C3b-J1 root is non-finite or unbracketed")

        left = lower
        right = upper
        iterations = 0
        for iterations in range(1, self.config.maximum_iterations + 1):
            midpoint = 0.5 * (left + right)
            value, normalized = residual(midpoint)
            if midpoint == left or midpoint == right:
                break
            if value > 0.0:
                left = midpoint
            else:
                right = midpoint
            if (
                right - left <= self.config.stage_tolerance_m
                and normalized <= self.config.normalized_mass_tolerance
            ):
                break
        else:
            raise ValueError("C3b-J1 common-stage equation did not converge")

        final_width = right - left
        left_mass_residual, _ = residual(left)
        right_mass_residual, _ = residual(right)
        root_candidates = []
        for candidate_stage in (left, 0.5 * (left + right), right):
            candidate_value, candidate_normalized = residual(candidate_stage)
            root_candidates.append(
                (candidate_normalized, abs(candidate_value), candidate_stage)
            )
        normalized_mass, absolute_mass, common_stage = min(root_candidates)
        if final_width > self.config.stage_tolerance_m:
            raise ValueError("C3b-J1 common-stage bracket did not reach tolerance")
        if normalized_mass > self.config.normalized_mass_tolerance:
            raise ValueError("C3b-J1 normalized mass residual exceeds tolerance")

        boundary_states = []
        traces = []
        mass_stage_derivative = 0.0
        for branch_id, endpoint, cell, _ in endpoint_data:
            area = float(cell.geometry.area(common_stage))
            potential = characteristic_potential(cell=cell, area=area)
            interior_invariant = invariants[branch_id]
            discharge = (
                area * (interior_invariant - potential)
                if endpoint == "downstream"
                else area * (interior_invariant + potential)
            )
            candidate = ConservedVector(area, discharge)
            properties = subcritical_characteristic_properties(
                state=candidate,
                cell=cell,
                label=f"completed Junction Branch {branch_id}",
            )
            flow_tolerance = max(
                _FORWARD_FLOW_ABSOLUTE_TOLERANCE,
                _FORWARD_FLOW_RELATIVE_TOLERANCE * area * properties.celerity,
            )
            if discharge <= flow_tolerance:
                raise ValueError("C3b-J1 completed trace is not positive forward flow")
            completed_invariant = (
                properties.velocity + properties.potential
                if endpoint == "downstream"
                else properties.velocity - properties.potential
            )
            invariant_scale = max(
                abs(interior_invariant),
                abs(completed_invariant),
                1.0,
            )
            invariant_residual = abs(
                completed_invariant - interior_invariant
            ) / invariant_scale
            if invariant_residual > self.config.invariant_tolerance:
                raise ValueError("C3b-J1 completed invariant residual exceeds tolerance")
            state_result = JunctionBoundaryState(
                node_id=node_id,
                branch_id=branch_id,
                cell_id=cell.cell_id,
                endpoint=endpoint,
                invariant_family="R+" if endpoint == "downstream" else "R-",
                stage=common_stage,
                area=area,
                discharge=discharge,
                velocity=properties.velocity,
                celerity=properties.celerity,
                froude=properties.froude,
                interior_invariant=interior_invariant,
                completed_invariant=completed_invariant,
                normalized_invariant_residual=invariant_residual,
                momentum_flux_per_density=physical_flux(
                    candidate,
                    cell.geometry,
                ).momentum,
            )
            boundary_states.append(state_result)
            top_width = float(cell.geometry.top_width(common_stage))
            mass_stage_derivative += (
                top_width * (properties.velocity - properties.celerity)
                if endpoint == "downstream"
                else -top_width * (properties.velocity + properties.celerity)
            )
            traces.append(
                JunctionTrace(
                    node_id=node_id,
                    branch_id=branch_id,
                    endpoint=endpoint,
                    stage=common_stage,
                    area=area,
                    discharge=discharge,
                )
            )

        preclosure = inspect_junction_preclosure(
            network=network,
            node_id=node_id,
            traces=traces,
            time=time,
            stage_tolerance=self.config.stage_tolerance_m,
            mass_tolerance=self.config.normalized_mass_tolerance,
        )
        evidence = JunctionCharacteristicEvidence(
            node_id=node_id,
            time=time,
            common_stage=common_stage,
            bracket_start_stage=left,
            bracket_end_stage=right,
            bracket_start_mass_residual=left_mass_residual,
            bracket_end_mass_residual=right_mass_residual,
            final_bracket_width=final_width,
            iterations=iterations,
            absolute_mass_residual=absolute_mass,
            normalized_mass_residual=normalized_mass,
            maximum_normalized_invariant_residual=max(
                state.normalized_invariant_residual for state in boundary_states
            ),
            maximum_froude=max(state.froude for state in boundary_states),
            mass_residual_stage_derivative=mass_stage_derivative,
            stage_tolerance_m=self.config.stage_tolerance_m,
            normalized_mass_tolerance=self.config.normalized_mass_tolerance,
            invariant_tolerance=self.config.invariant_tolerance,
        )
        return JunctionCharacteristicSolution(
            node_id=node_id,
            time=time,
            boundary_states=tuple(boundary_states),
            preclosure=preclosure,
            evidence=evidence,
        )


def solve_one_in_two_out_junction(
    *,
    network: FiniteVolumeNetwork,
    node_id: NodeId,
    states: Mapping[str, HydraulicState],
    config: JunctionSolverConfig | None = None,
) -> JunctionCharacteristicSolution:
    """Solve the restricted Junction with one explicit functional entry point."""

    return OneInTwoOutJunctionSolver(config or JunctionSolverConfig()).solve_node_stage(
        network=network,
        node_id=node_id,
        states=states,
    )
