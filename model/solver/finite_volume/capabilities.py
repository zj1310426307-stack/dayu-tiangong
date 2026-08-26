"""Versioned numerical capability manifests for opt-in finite-volume routes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NumericalPolicyManifest:
    """Name every numerical policy that changes a solver capability."""

    schema_version: str
    solver_id: str
    geometry_policy: str
    boundary_policy: str
    friction_policy: str
    gate_coupling_policy: str
    pump_coupling_policy: str
    pump_curve_policy: str
    pump_efficiency_policy: str
    pump_control_policy: str
    supported_scope: tuple[str, ...]


@dataclass(frozen=True)
class SolverCapability:
    """Bind one public validation version to its immutable policy manifest."""

    capability_id: str
    validation_policy_version: str
    manifest: NumericalPolicyManifest


D1_PUMP_STRONG_COUPLING = SolverCapability(
    capability_id="hydro-model-02-d1-pump-strong-coupling",
    validation_policy_version="v4-lite-7",
    manifest=NumericalPolicyManifest(
        schema_version="dayu.model-input.v4-lite",
        solver_id="saint-venant-finite-volume-hll-ssp-rk2",
        geometry_policy="absolute-prismatic-v1",
        boundary_policy="subcritical-characteristic-v1",
        friction_policy="manning-semi-implicit-zero-coefficient-v1",
        gate_coupling_policy="submerged-orifice-energy-momentum-v1",
        pump_coupling_policy="qh-operating-point-external-sink-v1",
        pump_curve_policy="piecewise-linear-qh-v1",
        pump_efficiency_policy="piecewise-linear-q-efficiency-v1",
        pump_control_policy="stage-hysteresis-min-runtime-v1",
        supported_scope=(
            "single-branch",
            "fully-wet",
            "forward-subcritical",
            "one-completed-interface-gate",
            "one-external-sink-pump",
            "identical-parallel-pump-units",
            "strictly-positive-upstream-hydrograph",
            "wet-non-rising-downstream-stage-process",
            "water-balance-tolerance-at-most-1e-10",
        ),
    ),
)

_CAPABILITIES = {
    D1_PUMP_STRONG_COUPLING.validation_policy_version: D1_PUMP_STRONG_COUPLING,
}


def require_solver_capability(validation_policy_version: str) -> SolverCapability:
    """Return a registered capability or fail instead of inferring policies."""

    try:
        return _CAPABILITIES[validation_policy_version]
    except KeyError as exc:
        raise ValueError(
            f"unregistered solver capability: {validation_policy_version}"
        ) from exc


__all__ = [
    "D1_PUMP_STRONG_COUPLING",
    "NumericalPolicyManifest",
    "SolverCapability",
    "require_solver_capability",
]
