"""Pure platform solver registry for immutable schema-to-runtime routing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final, Literal

from model.core.errors import HydraulicInputError
from model.provenance import snapshot_hash


MODEL_INPUT_V1: Final = "dayu.model-input.v1"
MODEL_INPUT_V2: Final = "dayu.model-input.v2"
MODEL_INPUT_V3: Final = "dayu.model-input.v3"
MODEL_INPUT_V4: Final = "dayu.model-input.v4"

LEGACY_SINGLE_RIVER_SOLVER: Final = "legacy-single-river-rusanov-v1"
LEGACY_NETWORK_SOLVER: Final = "legacy-network-continuity-manning-v1"
D1_SOLVER_ID: Final = "saint-venant-fv-hll-ssp-rk2-d1-v1"
D1_CAPABILITY_ID: Final = "single-branch-gate-external-pump-d1-v1"
D3A_1_CAPABILITY_ID: Final = "single-branch-gate-pump-manning-v1"
D3A_2_CAPABILITY_ID: Final = "single-branch-gate-pump-manning-slope-v1"
D3A_3_CAPABILITY_ID: Final = "single-branch-gate-pump-engineering-profile-v1"
V3_RUNTIME_ADAPTER_ID: Final = "v3-to-v2-v1"
D1_RUNTIME_ADAPTER_ID: Final = "v4-to-v4-lite-7-d1-v1"
D3A_1_RUNTIME_ADAPTER_ID: Final = "v4-to-d3a-1-v1"
D3A_2_RUNTIME_ADAPTER_ID: Final = "v4-to-d3a-2-v1"
REGISTRY_SCHEMA_VERSION: Final = "dayu.solver-registry.v1"
CAPABILITY_CATALOG_SCHEMA_VERSION: Final = "dayu.solver-capability-catalog.v1"


@dataclass(frozen=True, slots=True)
class SolverCapabilityManifest:
    """Freeze one solver's implemented scientific envelope and exclusions."""

    capability_id: str
    scope: tuple[str, ...]
    exclusions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CapabilityCatalogEntry:
    """Describe one explicitly named science envelope and its unlock state.

    Blocked entries are visible to readiness/UI consumers but are deliberately
    absent from executable solver registrations until their independent
    scientific gate has passed.
    """

    capability_id: str
    display_name: str
    status: Literal["supported", "blocked"]
    validation_policy_version: str
    runtime_adapter_id: str
    scope: tuple[str, ...]
    exclusions: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuntimeAdapterRegistration:
    """Describe one explicit authoritative-input to runtime-input projection."""

    runtime_adapter_id: str
    source_schema_version: str
    runtime_schema_version: str
    validation_policy_version: str


@dataclass(frozen=True, slots=True)
class SolverRegistration:
    """Bind one platform input schema to exactly one registered solver route."""

    input_schema_version: str
    solver_id: str
    result_schema_version: str
    engine_route: str
    capability: SolverCapabilityManifest | None = None
    runtime_adapter: RuntimeAdapterRegistration | None = None


D1_CAPABILITY = SolverCapabilityManifest(
    capability_id=D1_CAPABILITY_ID,
    scope=(
        "single-branch",
        "fully-wet",
        "forward-strictly-subcritical",
        "flat-bed",
        "identical-profile",
        "manning-n-zero",
        "one-completed-interface-gate",
        "one-external-qh-qeta-pump",
        "identical-parallel-pump-units",
        "validation-only",
    ),
    exclusions=(
        "multi-branch-or-junction",
        "wetting-drying",
        "reverse-or-supercritical-flow",
        "internal-pump",
        "multiple-gates-or-pumps",
        "calibration-or-production-decision",
    ),
)

# Human-readable compatibility text is registry-owned.  It is kept separate from
# the machine-readable scope/exclusions so clients can present stable warnings
# without allowing a mutable SimulationCase to redefine scientific capability.
D1_KNOWN_LIMITATIONS: Final = (
    "single Branch, fully wet, forward strictly subcritical validation only",
    "flat bed, identical Profile geometry, Manning n=0",
    "one completed-interface Gate and one external Q-H/Q-efficiency Pump",
    "not calibrated and not approved for production water decisions",
)

D3A_1_CAPABILITY = SolverCapabilityManifest(
    capability_id=D3A_1_CAPABILITY_ID,
    scope=(
        "single-branch",
        "fully-wet",
        "forward-strictly-subcritical",
        "flat-bed",
        "identical-profile",
        "positive-section-effective-manning",
        "one-completed-interface-gate",
        "one-external-qh-qeta-pump",
        "validation-only",
    ),
    exclusions=(
        "nonzero-bed-slope",
        "nonidentical-profile",
        "lateral-compound-roughness",
        "multi-branch-or-junction",
        "wetting-drying",
        "reverse-or-supercritical-flow",
        "calibration-or-production-decision",
    ),
)

D3A_1_KNOWN_LIMITATIONS: Final = (
    "single Branch, fully wet, forward strictly subcritical validation only",
    "flat bed and identical Profile geometry",
    "one effective Manning scalar per Section/cell in (0, 0.10]",
    "one completed-interface Gate and one external Q-H/Q-efficiency Pump",
    "not calibrated and not approved for production water decisions",
)

D3A_2_CAPABILITY = SolverCapabilityManifest(
    capability_id=D3A_2_CAPABILITY_ID,
    scope=(
        "single-branch",
        "fully-wet",
        "forward-strictly-subcritical",
        "positive-section-effective-manning",
        "explicit-nonzero-linear-bed-slope",
        "identical-local-profile-shape",
        "one-completed-interface-gate",
        "one-external-qh-qeta-pump",
        "validation-only",
    ),
    exclusions=(
        "unconfirmed-or-inferred-bed-elevation",
        "nonidentical-profile-shape",
        "lateral-compound-roughness",
        "multi-branch-or-junction",
        "wetting-drying",
        "reverse-or-supercritical-flow",
        "calibration-or-production-decision",
    ),
)

D3A_2_KNOWN_LIMITATIONS: Final = (
    "single Branch, fully wet, forward strictly subcritical validation only",
    "explicit confirmed descending linear bed and identical local Profile shape",
    "one effective Manning scalar per Section/cell in (0, 0.10]",
    "one completed-interface Gate and one external Q-H/Q-efficiency Pump",
    "not calibrated and not approved for production water decisions",
)


_CAPABILITY_CATALOG: tuple[CapabilityCatalogEntry, ...] = (
    CapabilityCatalogEntry(
        capability_id=D1_CAPABILITY_ID,
        display_name="D1 validation",
        status="supported",
        validation_policy_version="v4-lite-7",
        runtime_adapter_id=D1_RUNTIME_ADAPTER_ID,
        scope=D1_CAPABILITY.scope,
        exclusions=D1_CAPABILITY.exclusions,
        warnings=D1_KNOWN_LIMITATIONS,
    ),
    CapabilityCatalogEntry(
        capability_id=D3A_1_CAPABILITY_ID,
        display_name="D3A-1 Manning",
        status="supported",
        validation_policy_version="d3a-1-v1",
        runtime_adapter_id=D3A_1_RUNTIME_ADAPTER_ID,
        scope=D3A_1_CAPABILITY.scope,
        exclusions=D3A_1_CAPABILITY.exclusions,
        warnings=D3A_1_KNOWN_LIMITATIONS,
    ),
    CapabilityCatalogEntry(
        capability_id=D3A_2_CAPABILITY_ID,
        display_name="D3A-2 Manning + Slope",
        status="supported",
        validation_policy_version="d3a-2-v1",
        runtime_adapter_id=D3A_2_RUNTIME_ADAPTER_ID,
        scope=D3A_2_CAPABILITY.scope,
        exclusions=D3A_2_CAPABILITY.exclusions,
        warnings=D3A_2_KNOWN_LIMITATIONS,
    ),
    CapabilityCatalogEntry(
        capability_id=D3A_3_CAPABILITY_ID,
        display_name="D3A-3 Engineering Profiles",
        status="blocked",
        validation_policy_version="d3a-3-v1",
        runtime_adapter_id="v4-to-d3a-3-v1",
        scope=(
            "single-branch",
            "fully-wet",
            "forward-strictly-subcritical",
            "positive-section-effective-manning",
            "explicit-nonzero-bed-slope",
            "continuous-nonidentical-tabulated-profiles",
            "one-completed-interface-gate",
            "one-external-qh-qeta-pump",
            "validation-only",
        ),
        exclusions=(
            "abrupt-or-disconnected-section-topology",
            "lateral-compound-roughness",
            "multi-branch-or-junction",
            "wetting-drying",
            "reverse-or-supercritical-flow",
            "calibration-or-production-decision",
        ),
        warnings=(
            "blocked until D3A-1/2 and P1/P2/P3 independent gates pass",
            "not a general one-dimensional river-network capability",
        ),
    ),
)


_REGISTRATIONS: tuple[SolverRegistration, ...] = (
    SolverRegistration(
        input_schema_version=MODEL_INPUT_V1,
        solver_id=LEGACY_SINGLE_RIVER_SOLVER,
        result_schema_version="dayu.hydraulic-result.v1",
        engine_route="legacy-v1",
    ),
    SolverRegistration(
        input_schema_version=MODEL_INPUT_V2,
        solver_id=LEGACY_NETWORK_SOLVER,
        result_schema_version="dayu.hydraulic-result.v2",
        engine_route="legacy-v2",
    ),
    SolverRegistration(
        input_schema_version=MODEL_INPUT_V3,
        solver_id=LEGACY_NETWORK_SOLVER,
        result_schema_version="dayu.hydraulic-result.v2",
        engine_route="legacy-v2",
        runtime_adapter=RuntimeAdapterRegistration(
            runtime_adapter_id=V3_RUNTIME_ADAPTER_ID,
            source_schema_version=MODEL_INPUT_V3,
            runtime_schema_version=MODEL_INPUT_V2,
            validation_policy_version="legacy-v3-to-v2-v1",
        ),
    ),
    SolverRegistration(
        input_schema_version=MODEL_INPUT_V4,
        solver_id=D1_SOLVER_ID,
        result_schema_version="dayu.hydraulic-result.v3",
        engine_route="finite-volume-d1-v4",
        capability=D1_CAPABILITY,
        runtime_adapter=RuntimeAdapterRegistration(
            runtime_adapter_id=D1_RUNTIME_ADAPTER_ID,
            source_schema_version=MODEL_INPUT_V4,
            runtime_schema_version="dayu.model-input.v4-lite",
            validation_policy_version="v4-lite-7",
        ),
    ),
    SolverRegistration(
        input_schema_version=MODEL_INPUT_V4,
        solver_id=D1_SOLVER_ID,
        result_schema_version="dayu.hydraulic-result.v3",
        engine_route="finite-volume-d3a-1-v4",
        capability=D3A_1_CAPABILITY,
        runtime_adapter=RuntimeAdapterRegistration(
            runtime_adapter_id=D3A_1_RUNTIME_ADAPTER_ID,
            source_schema_version=MODEL_INPUT_V4,
            runtime_schema_version="dayu.model-input.v4-lite",
            validation_policy_version="d3a-1-v1",
        ),
    ),
    SolverRegistration(
        input_schema_version=MODEL_INPUT_V4,
        solver_id=D1_SOLVER_ID,
        result_schema_version="dayu.hydraulic-result.v3",
        engine_route="finite-volume-d3a-2-v4",
        capability=D3A_2_CAPABILITY,
        runtime_adapter=RuntimeAdapterRegistration(
            runtime_adapter_id=D3A_2_RUNTIME_ADAPTER_ID,
            source_schema_version=MODEL_INPUT_V4,
            runtime_schema_version="dayu.model-input.v4-lite",
            validation_policy_version="d3a-2-v1",
        ),
    ),
)


def registry_manifest() -> dict[str, object]:
    """Return the canonical JSON-shaped registry without runtime callables."""

    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "capability_catalog_schema_version": CAPABILITY_CATALOG_SCHEMA_VERSION,
        "capability_catalog": [asdict(item) for item in _CAPABILITY_CATALOG],
        "known_limitations": list(D1_KNOWN_LIMITATIONS),
        "registrations": [asdict(item) for item in _REGISTRATIONS],
    }


def capability_catalog() -> tuple[CapabilityCatalogEntry, ...]:
    """Return the immutable ordered science catalog for readiness consumers."""

    return _CAPABILITY_CATALOG


def resolve_capability(
    capability_id: str,
    *,
    include_blocked: bool = False,
) -> CapabilityCatalogEntry:
    """Resolve an explicit capability without inferring it from case data."""

    entry = next(
        (item for item in _CAPABILITY_CATALOG if item.capability_id == capability_id),
        None,
    )
    if entry is None:
        raise HydraulicInputError(f"unregistered capability: {capability_id!r}")
    if entry.status == "blocked" and not include_blocked:
        raise HydraulicInputError(
            f"capability {capability_id!r} is registered but scientifically blocked"
        )
    return entry


def registry_hash() -> str:
    """Return the deterministic registry identity used by task provenance."""

    return snapshot_hash(registry_manifest())


def task_solver_provenance(
    input_schema_version: str,
    *,
    solver_id: str | None = None,
    capability_id: str | None = None,
) -> dict[str, str | None]:
    """Return the complete Registry-owned identity persisted on a task row.

    Internal task producers use the same helper as the public task builder so
    no caller can accidentally omit an adapter, capability, result schema, or
    Registry hash while preserving its independently frozen input snapshot.
    """

    registration = resolve_solver(
        input_schema_version,
        solver_id=solver_id,
        capability_id=capability_id,
    )
    return {
        "solver_id": registration.solver_id,
        "capability_id": (
            registration.capability.capability_id
            if registration.capability is not None
            else None
        ),
        "runtime_adapter_id": (
            registration.runtime_adapter.runtime_adapter_id
            if registration.runtime_adapter is not None
            else None
        ),
        "result_schema_version": registration.result_schema_version,
        "registry_hash": registry_hash(),
    }


def resolve_solver(
    input_schema_version: str,
    *,
    solver_id: str | None = None,
    capability_id: str | None = None,
    runtime_adapter_id: str | None = None,
) -> SolverRegistration:
    """Resolve and verify one route, rejecting every unknown or mismatched identity."""

    candidates = tuple(
        item
        for item in _REGISTRATIONS
        if item.input_schema_version == input_schema_version
    )
    if not candidates:
        raise HydraulicInputError(
            f"unregistered model input schema: {input_schema_version!r}"
        )
    if solver_id is not None:
        candidates = tuple(item for item in candidates if item.solver_id == solver_id)
    if capability_id is not None:
        candidates = tuple(
            item
            for item in candidates
            if item.capability is not None
            and item.capability.capability_id == capability_id
        )
    if runtime_adapter_id is not None:
        candidates = tuple(
            item
            for item in candidates
            if item.runtime_adapter is not None
            and item.runtime_adapter.runtime_adapter_id == runtime_adapter_id
        )
    if not candidates:
        label = (
            "runtime adapter"
            if runtime_adapter_id is not None
            else "capability"
            if capability_id is not None
            else "solver"
        )
        raise HydraulicInputError(
            f"{label} selection is not registered for {input_schema_version}"
        )
    if len(candidates) != 1:
        raise HydraulicInputError(
            f"{input_schema_version} requires an explicit unambiguous capability_id"
        )
    registration = candidates[0]
    expected_capability = (
        registration.capability.capability_id
        if registration.capability is not None
        else None
    )
    if capability_id is not None and capability_id != expected_capability:
        raise HydraulicInputError(
            f"capability {capability_id!r} is not registered for {input_schema_version}"
        )
    expected_adapter = (
        registration.runtime_adapter.runtime_adapter_id
        if registration.runtime_adapter is not None
        else None
    )
    if runtime_adapter_id is not None and runtime_adapter_id != expected_adapter:
        raise HydraulicInputError(
            f"runtime adapter {runtime_adapter_id!r} is not registered for "
            f"{input_schema_version}"
        )
    return registration


def registered_solver_ids() -> tuple[str, ...]:
    """List unique solver IDs for Worker capability declarations."""

    return tuple(dict.fromkeys(item.solver_id for item in _REGISTRATIONS))
