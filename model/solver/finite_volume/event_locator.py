"""Pure conservative crossing detection for accepted-state replay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from model.solver.finite_volume.mesh import FiniteVolumeMesh
from model.solver.finite_volume.state import HydraulicState
from model.solver.finite_volume.structures import (
    BracketedOneShotStageThreshold,
    ControlBracketEvidence,
    FixedGate,
    OnOffPump,
)

StructureEventKey = tuple[str, str]


@dataclass(frozen=True)
class BracketedCrossingCandidate:
    """Hold a crossing candidate before its conservative interval is refined."""

    previous_time: float
    previous_observed_water_level: float
    bracket_end_time: float
    bracket_end_observed_water_level: float
    monitored_section_id: int

    def evidence(
        self,
        *,
        event_time_tolerance: float,
        refinement_count: int,
    ) -> ControlBracketEvidence:
        """Materialize evidence only after the bracket satisfies its tolerance."""

        return ControlBracketEvidence(
            previous_time=self.previous_time,
            previous_observed_water_level=self.previous_observed_water_level,
            bracket_end_time=self.bracket_end_time,
            bracket_end_observed_water_level=self.bracket_end_observed_water_level,
            event_time_tolerance=event_time_tolerance,
            refinement_count=refinement_count,
            monitored_section_id=self.monitored_section_id,
        )


def _triggered(state: Mapping[str, object] | None) -> bool:
    """Read one immutable latch without inferring a missing or malformed value."""

    if state is None:
        return False
    value = state.get("triggered")
    if not isinstance(value, bool):
        raise ValueError("bracketed control state requires a boolean triggered flag")
    return value


def _stage(mesh: FiniteVolumeMesh, state: HydraulicState, index: int) -> float:
    """Return the absolute stage at one explicitly bound cell centre."""

    return mesh.cells[index].geometry.stage_from_area(state.area[index])


def detect_bracketed_crossings(
    *,
    mesh: FiniteVolumeMesh,
    previous: HydraulicState,
    candidate: HydraulicState,
    gates: Sequence[FixedGate],
    pumps: Sequence[OnOffPump],
) -> dict[StructureEventKey, BracketedCrossingCandidate]:
    """Return every strict rising crossing bracketed by two conservative states."""

    evidence: dict[StructureEventKey, BracketedCrossingCandidate] = {}
    for gate in gates:
        control = gate.control
        if not isinstance(control, BracketedOneShotStageThreshold):
            continue
        if _triggered(previous.gate_state.get(gate.gate_id)):
            continue
        before = _stage(mesh, previous, gate.face_index)
        after = _stage(mesh, candidate, gate.face_index)
        if before > control.threshold_water_level:
            raise ValueError("bracketed Gate control starts above its threshold")
        if before <= control.threshold_water_level < after:
            evidence[("gate", gate.gate_id)] = BracketedCrossingCandidate(
                previous_time=previous.time,
                previous_observed_water_level=before,
                bracket_end_time=candidate.time,
                bracket_end_observed_water_level=after,
                monitored_section_id=int(mesh.cells[gate.face_index].section_id),
            )
    for pump in pumps:
        control = pump.control
        if not isinstance(control, BracketedOneShotStageThreshold):
            continue
        if _triggered(previous.pump_state.get(pump.pump_id)):
            continue
        before = _stage(mesh, previous, pump.cell_index)
        after = _stage(mesh, candidate, pump.cell_index)
        if before > control.threshold_water_level:
            raise ValueError("bracketed Pump control starts above its threshold")
        if before <= control.threshold_water_level < after:
            evidence[("pump", pump.pump_id)] = BracketedCrossingCandidate(
                previous_time=previous.time,
                previous_observed_water_level=before,
                bracket_end_time=candidate.time,
                bracket_end_observed_water_level=after,
                monitored_section_id=int(mesh.cells[pump.cell_index].section_id),
            )
    return evidence
