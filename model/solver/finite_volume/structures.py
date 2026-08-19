"""Minimal per-stage Gate and Pump mass-flow contracts for the MVP."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping

from model.solver.finite_volume.flux import GRAVITY


@dataclass(frozen=True)
class StructureStageContext:
    """Provide the current RK-stage heads and conservative neighbour values."""

    time: float
    dt: float
    upstream_stage: float
    downstream_stage: float
    upstream_area: float
    downstream_area: float
    upstream_discharge: float
    downstream_discharge: float

    def __post_init__(self) -> None:
        """Reject a non-finite stage context before device evaluation."""

        values = (
            self.time,
            self.dt,
            self.upstream_stage,
            self.downstream_stage,
            self.upstream_area,
            self.downstream_area,
            self.upstream_discharge,
            self.downstream_discharge,
        )
        if not all(math.isfinite(item) for item in values):
            raise ValueError("structure stage context must contain only finite values")
        if self.time < 0.0 or self.dt <= 0.0:
            raise ValueError("structure stage time must be non-negative and dt positive")
        if self.upstream_area < 0.0 or self.downstream_area < 0.0:
            raise ValueError("structure neighbour areas must be non-negative")


@dataclass(frozen=True)
class StructureStageFlow:
    """Return a signed volume flow and an auditable simplified closure label."""

    structure_id: str
    structure_type: str
    flow: float
    state: Mapping[str, object] = field(default_factory=dict)
    momentum_closure: str = "mass_only_mvp_not_strongly_coupled"

    def __post_init__(self) -> None:
        """Keep invalid device outputs from entering the conservative update."""

        if not self.structure_id or not self.structure_type:
            raise ValueError("structure identity and type must not be empty")
        if not math.isfinite(self.flow):
            raise ValueError("structure flow must be finite")


@dataclass(frozen=True)
class FixedGate:
    """Bind a fixed-opening orifice Gate to one internal face.

    Positive flow is from the lower face index cell to the higher one.  The
    formula implements only the task-book ``Cd*A*sqrt(2*g*deltaH)`` mass-flow
    relation; the orchestrator must retain an explicit diagnostic that a full
    momentum/energy closure is not yet implemented.
    """

    gate_id: str
    face_index: int
    opening: float
    width: float
    height: float
    discharge_coefficient: float = 0.62
    allow_reverse: bool = False

    def __post_init__(self) -> None:
        """Validate fixed Gate geometry and its internal-face binding."""

        values = (self.opening, self.width, self.height, self.discharge_coefficient)
        if self.face_index < 0:
            raise ValueError("gate face_index must be non-negative")
        if not all(math.isfinite(item) for item in values):
            raise ValueError("gate parameters must be finite")
        if self.opening < 0.0 or self.width <= 0.0 or self.height <= 0.0:
            raise ValueError("gate opening must be non-negative and dimensions positive")
        if self.discharge_coefficient <= 0.0:
            raise ValueError("gate discharge coefficient must be positive")

    def evaluate_stage(self, context: StructureStageContext) -> StructureStageFlow:
        """Evaluate Gate flow from the current stage heads on both sides."""

        head_difference = context.upstream_stage - context.downstream_stage
        direction = 1.0
        if head_difference < 0.0:
            if not self.allow_reverse:
                head_difference = 0.0
            else:
                direction = -1.0
                head_difference = abs(head_difference)
        opening_area = self.width * min(self.opening, self.height)
        flow = (
            direction
            * self.discharge_coefficient
            * opening_area
            * math.sqrt(2.0 * GRAVITY * max(head_difference, 0.0))
        )
        return StructureStageFlow(
            structure_id=self.gate_id,
            structure_type="gate",
            flow=flow,
            state={"opening": self.opening},
        )


@dataclass(frozen=True)
class OnOffPump:
    """Bind a fixed ON/OFF external pump sink to one cell."""

    pump_id: str
    cell_index: int
    design_flow: float
    enabled: bool

    def __post_init__(self) -> None:
        """Validate the fixed pump binding without inventing a Q-H curve."""

        if self.cell_index < 0:
            raise ValueError("pump cell_index must be non-negative")
        if not math.isfinite(self.design_flow) or self.design_flow < 0.0:
            raise ValueError("pump design_flow must be finite and non-negative")

    def evaluate_stage(self, context: StructureStageContext) -> StructureStageFlow:
        """Return design flow when ON and exact zero when OFF."""

        del context
        return StructureStageFlow(
            structure_id=self.pump_id,
            structure_type="pump",
            flow=self.design_flow if self.enabled else 0.0,
            state={"enabled": self.enabled},
        )
