"""Fail-closed numerical and conservation quality gates for FV states."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from model.solver.finite_volume.mesh import FiniteVolumeMesh
    from model.solver.finite_volume.state import HydraulicState


class FiniteVolumeError(RuntimeError):
    """Base error for a rejected finite-volume calculation."""


class NumericalStateError(FiniteVolumeError):
    """Signal a non-finite, negative or otherwise invalid hydraulic state."""


class BoundaryCoverageError(FiniteVolumeError):
    """Signal that a boundary request would require time extrapolation."""


class StabilityError(FiniteVolumeError):
    """Signal that CFL or retry controls cannot produce an acceptable step."""


@dataclass(frozen=True)
class QualityGateResult:
    """Expose every failed gate instead of reducing validation to a boolean."""

    passed: bool
    issues: tuple[str, ...]


def inspect_state(
    state: "HydraulicState",
    mesh: "FiniteVolumeMesh",
    *,
    maximum_cfl: float | None = None,
    cfl_limit: float | None = None,
    relative_water_balance_error: float | None = None,
    water_balance_tolerance: float = 0.01,
) -> QualityGateResult:
    """Check finite values, positivity, CFL and optional water balance."""

    issues: list[str] = []
    if len(state.area) != len(mesh.cells):
        issues.append("state_length_mismatch")
    for index, (area, discharge, depth, velocity) in enumerate(
        zip(state.area, state.discharge, state.water_depth, state.velocity)
    ):
        if not all(math.isfinite(item) for item in (area, discharge, depth, velocity)):
            issues.append(f"cell_{index}_non_finite")
        if area < 0.0:
            issues.append(f"cell_{index}_negative_area")
        if depth < -1.0e-12:
            issues.append(f"cell_{index}_negative_depth")
        if index < len(state.wet_mask) and not state.wet_mask[index] and abs(discharge) > 1.0e-12:
            issues.append(f"cell_{index}_dry_discharge")
    if maximum_cfl is not None:
        if not math.isfinite(maximum_cfl) or maximum_cfl < 0.0:
            issues.append("invalid_cfl")
        elif cfl_limit is not None and maximum_cfl > cfl_limit + 1.0e-12:
            issues.append("cfl_limit_exceeded")
    if relative_water_balance_error is not None:
        if not math.isfinite(relative_water_balance_error) or relative_water_balance_error < 0.0:
            issues.append("invalid_water_balance")
        elif relative_water_balance_error >= water_balance_tolerance:
            issues.append("water_balance_failed")
    return QualityGateResult(passed=not issues, issues=tuple(issues))


def require_quality(*args: object, **kwargs: object) -> QualityGateResult:
    """Return a passing gate or raise before a result can be marked successful."""

    result = inspect_state(*args, **kwargs)  # type: ignore[arg-type]
    if not result.passed:
        raise NumericalStateError(", ".join(result.issues))
    return result
