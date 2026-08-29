"""Versioned dynamic science-envelope checks for D3A finite-volume runs."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from model.provenance import snapshot_hash
from model.solver.finite_volume.diagnostics import StabilityError
from model.solver.finite_volume.flux import GRAVITY
from model.solver.finite_volume.mesh import FiniteVolumeMesh
from model.solver.finite_volume.state import HydraulicState


RUNTIME_ENVELOPE_SCHEMA_VERSION = "dayu.runtime-envelope.v1"
D3A_RUNTIME_ENVELOPE_ID = "fully-wet-forward-fr08-v1"


class RuntimeEnvelopeStabilityError(StabilityError):
    """Reject a retriable D3A stage that leaves its frozen science envelope."""


@dataclass(frozen=True, slots=True)
class CapabilityRuntimeEnvelope:
    """Freeze the dynamic hydraulic limits attached to one capability."""

    schema_version: str
    runtime_envelope_id: str
    minimum_water_depth_m: float
    require_fully_wet: bool
    require_forward_flow: bool
    reverse_flow_tolerance_m3s: float
    maximum_froude_number: float

    def __post_init__(self) -> None:
        """Reject an incomplete or non-physical envelope definition."""

        if self.schema_version != RUNTIME_ENVELOPE_SCHEMA_VERSION:
            raise ValueError("unsupported runtime-envelope schema")
        if not self.runtime_envelope_id:
            raise ValueError("runtime_envelope_id must not be empty")
        if (
            not math.isfinite(self.minimum_water_depth_m)
            or self.minimum_water_depth_m < 0.0
        ):
            raise ValueError("minimum_water_depth_m must be finite and non-negative")
        if (
            not math.isfinite(self.reverse_flow_tolerance_m3s)
            or self.reverse_flow_tolerance_m3s < 0.0
        ):
            raise ValueError(
                "reverse_flow_tolerance_m3s must be finite and non-negative"
            )
        if (
            not math.isfinite(self.maximum_froude_number)
            or not 0.0 < self.maximum_froude_number < 1.0
        ):
            raise ValueError("maximum_froude_number must lie in (0, 1)")

    def manifest(self) -> dict[str, object]:
        """Return the canonical JSON-shaped policy manifest."""

        return asdict(self)

    @property
    def manifest_hash(self) -> str:
        """Return the deterministic identity of this exact envelope."""

        return snapshot_hash(self.manifest())


@dataclass(frozen=True, slots=True)
class RuntimeEnvelopeObservation:
    """Summarize extrema and violations observed at one state checkpoint."""

    minimum_water_depth_m: float
    minimum_discharge_m3s: float
    maximum_froude_number: float
    status: str
    violations: tuple[str, ...] = ()

    def merged(self, other: "RuntimeEnvelopeObservation") -> "RuntimeEnvelopeObservation":
        """Combine two checkpoint observations without losing extrema."""

        violations = tuple(dict.fromkeys((*self.violations, *other.violations)))
        return RuntimeEnvelopeObservation(
            minimum_water_depth_m=min(
                self.minimum_water_depth_m,
                other.minimum_water_depth_m,
            ),
            minimum_discharge_m3s=min(
                self.minimum_discharge_m3s,
                other.minimum_discharge_m3s,
            ),
            maximum_froude_number=max(
                self.maximum_froude_number,
                other.maximum_froude_number,
            ),
            status="pass" if not violations else "fail",
            violations=violations,
        )


_D3A_RUNTIME_ENVELOPE = CapabilityRuntimeEnvelope(
    schema_version=RUNTIME_ENVELOPE_SCHEMA_VERSION,
    runtime_envelope_id=D3A_RUNTIME_ENVELOPE_ID,
    minimum_water_depth_m=1.0e-3,
    require_fully_wet=True,
    require_forward_flow=True,
    reverse_flow_tolerance_m3s=1.0e-12,
    maximum_froude_number=0.8,
)

_RUNTIME_ENVELOPES = {
    _D3A_RUNTIME_ENVELOPE.runtime_envelope_id: _D3A_RUNTIME_ENVELOPE,
}


def resolve_runtime_envelope(runtime_envelope_id: str) -> CapabilityRuntimeEnvelope:
    """Resolve a versioned envelope instead of reconstructing it in callers."""

    try:
        return _RUNTIME_ENVELOPES[runtime_envelope_id]
    except KeyError as exc:
        raise ValueError(
            f"unregistered runtime envelope: {runtime_envelope_id!r}"
        ) from exc


def runtime_envelope_manifest_hash(runtime_envelope_id: str) -> str:
    """Return the canonical manifest hash for one registered envelope."""

    return resolve_runtime_envelope(runtime_envelope_id).manifest_hash


def observe_runtime_envelope(
    *,
    mesh: FiniteVolumeMesh,
    state: HydraulicState,
    envelope: CapabilityRuntimeEnvelope,
) -> RuntimeEnvelopeObservation:
    """Measure every cell against the fully-wet, forward, subcritical limits."""

    depths = tuple(state.water_depth)
    discharges = tuple(state.discharge)
    froude_numbers: list[float] = []
    violations: list[str] = []
    for index, (cell, area, discharge, depth) in enumerate(
        zip(mesh.cells, state.area, discharges, depths)
    ):
        if envelope.require_fully_wet and depth <= envelope.minimum_water_depth_m:
            violations.append(f"cell {index} is not fully wet")
        if (
            envelope.require_forward_flow
            and discharge < -envelope.reverse_flow_tolerance_m3s
        ):
            violations.append(
                f"cell {index} has reverse flow Q={discharge:.17g} m3/s"
            )
        if area <= 0.0:
            froude = math.inf
        else:
            stage = cell.geometry.stage_from_area(area)
            top_width = float(cell.geometry.top_width(stage))
            if not math.isfinite(top_width) or top_width <= 0.0:
                froude = math.inf
            else:
                wave_celerity = math.sqrt(GRAVITY * area / top_width)
                froude = abs(discharge / area) / wave_celerity
        froude_numbers.append(froude)
        if (
            not math.isfinite(froude)
            or froude > envelope.maximum_froude_number + 1.0e-12
        ):
            violations.append(
                f"cell {index} exceeds maximum Froude number Fr={froude:.17g}"
            )
    return RuntimeEnvelopeObservation(
        minimum_water_depth_m=min(depths),
        minimum_discharge_m3s=min(discharges),
        maximum_froude_number=max(froude_numbers),
        status="pass" if not violations else "fail",
        violations=tuple(violations),
    )


def require_runtime_envelope(
    *,
    mesh: FiniteVolumeMesh,
    state: HydraulicState,
    envelope: CapabilityRuntimeEnvelope,
    checkpoint: str,
) -> RuntimeEnvelopeObservation:
    """Return checkpoint evidence or raise the dedicated retriable error."""

    observation = observe_runtime_envelope(mesh=mesh, state=state, envelope=envelope)
    if observation.status != "pass":
        summary = "; ".join(observation.violations[:3])
        raise RuntimeEnvelopeStabilityError(
            f"D3A runtime envelope failed at {checkpoint} t={state.time:.17g}: "
            f"{summary}"
        )
    return observation


__all__ = [
    "CapabilityRuntimeEnvelope",
    "D3A_RUNTIME_ENVELOPE_ID",
    "RUNTIME_ENVELOPE_SCHEMA_VERSION",
    "RuntimeEnvelopeObservation",
    "RuntimeEnvelopeStabilityError",
    "observe_runtime_envelope",
    "require_runtime_envelope",
    "resolve_runtime_envelope",
    "runtime_envelope_manifest_hash",
]
