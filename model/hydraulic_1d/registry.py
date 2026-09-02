"""Small immutable registry for externally integrated hydraulic engines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from model.hydraulic_1d.contracts import (
    HYDRAULIC_1D_INPUT_SCHEMA,
    HYDRAULIC_RESULT_SCHEMA,
)
from model.hydraulic_1d.capabilities import capabilities_for
from model.provenance import snapshot_hash


DEFAULT_HYDRAULIC_1D_ENGINE_ID: Final = "mascaret"
DEFAULT_HYDRAULIC_1D_ENGINE_VERSION: Final = "v9.1.1"
MASCARET_SOLVER_ID: Final = (
    f"{DEFAULT_HYDRAULIC_1D_ENGINE_ID}-{DEFAULT_HYDRAULIC_1D_ENGINE_VERSION}"
)
MASCARET_ADAPTER_ID: Final = "dayu-mascaret-adapter-v2"
STANDARD_1D_CAPABILITY_ID: Final = "engineering-1d-mascaret-v2"

DFLOW_FM_ENGINE_ID: Final = "d-flow-fm"
DFLOW_FM_ENGINE_VERSION: Final = "DIMRset_2026.02"
DFLOW_FM_SOLVER_ID: Final = f"{DFLOW_FM_ENGINE_ID}-{DFLOW_FM_ENGINE_VERSION}"
DFLOW_FM_ADAPTER_ID: Final = "dayu-dflow-fm-adapter-v1"
DFLOW_FM_CAPABILITY_ID: Final = "synthetic-controlled-1d-dflow-fm-v1"
DFLOW_FM_UPSTREAM_TAG: Final = "DIMRset_2026.02"
DFLOW_FM_UPSTREAM_COMMIT: Final = "5a4649830b1e5072caf019fb4850bbdefd9ad431"

CONTROLLED_HYDRAULIC_1D_RUN_SCHEMA: Final = "dayu.controlled-hydraulic-1d.run.v1"
CONTROLLED_HYDRAULIC_RESULT_SCHEMA: Final = "dayu.controlled-hydraulic-result.v1"


@dataclass(frozen=True, slots=True)
class HydraulicEngineRegistration:
    """Describe one selectable adapter without importing its numerical runtime."""

    engine_id: str
    engine_version: str
    solver_id: str
    adapter_id: str
    capability_id: str
    input_schema_version: str
    result_schema_version: str
    runtime_modes: tuple[str, ...]
    upstream_tag: str
    upstream_commit: str
    license_classification: str
    license_review_required: bool
    production_eligible: bool
    controlled_input_schema_version: str | None = None
    controlled_result_schema_version: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic catalog row with explicit license boundaries."""

        return {
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
            "solver_id": self.solver_id,
            "adapter_id": self.adapter_id,
            "capability_id": self.capability_id,
            "input_schema_version": self.input_schema_version,
            "result_schema_version": self.result_schema_version,
            "runtime_modes": self.runtime_modes,
            "upstream_tag": self.upstream_tag,
            "upstream_commit": self.upstream_commit,
            "license": {
                "classification": self.license_classification,
                "review_required": self.license_review_required,
                "distribution_mode": "external-runtime",
            },
            "production_eligible": self.production_eligible,
            "controlled_input_schema_version": self.controlled_input_schema_version,
            "controlled_result_schema_version": self.controlled_result_schema_version,
        }


_ENGINE_REGISTRATIONS: Final = (
    HydraulicEngineRegistration(
        engine_id=DEFAULT_HYDRAULIC_1D_ENGINE_ID,
        engine_version=DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
        solver_id=MASCARET_SOLVER_ID,
        adapter_id=MASCARET_ADAPTER_ID,
        capability_id=STANDARD_1D_CAPABILITY_ID,
        input_schema_version=HYDRAULIC_1D_INPUT_SCHEMA,
        result_schema_version=HYDRAULIC_RESULT_SCHEMA,
        runtime_modes=("external", "container"),
        upstream_tag="v9.1.1",
        upstream_commit="1fe3b5141f7d9c9fa8fe6d6d0316c994a39c2d95",
        license_classification="GPL-3.0-only",
        license_review_required=True,
        production_eligible=True,
    ),
    HydraulicEngineRegistration(
        engine_id=DFLOW_FM_ENGINE_ID,
        engine_version=DFLOW_FM_ENGINE_VERSION,
        solver_id=DFLOW_FM_SOLVER_ID,
        adapter_id=DFLOW_FM_ADAPTER_ID,
        capability_id=DFLOW_FM_CAPABILITY_ID,
        input_schema_version=HYDRAULIC_1D_INPUT_SCHEMA,
        result_schema_version=HYDRAULIC_RESULT_SCHEMA,
        runtime_modes=("external", "container"),
        upstream_tag=DFLOW_FM_UPSTREAM_TAG,
        upstream_commit=DFLOW_FM_UPSTREAM_COMMIT,
        license_classification="UPSTREAM-COMPONENT-SPECIFIC",
        license_review_required=True,
        production_eligible=False,
        controlled_input_schema_version=CONTROLLED_HYDRAULIC_1D_RUN_SCHEMA,
        controlled_result_schema_version=CONTROLLED_HYDRAULIC_RESULT_SCHEMA,
    ),
)


def engine_registry_payload() -> dict[str, object]:
    """Return the canonical adapter registration without importing numerical code."""

    return {
        "schema_version": "dayu.hydraulic-engine-registry.v1",
        "engines": [
            {
                "engine_id": DEFAULT_HYDRAULIC_1D_ENGINE_ID,
                "engine_version": DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
                "solver_id": MASCARET_SOLVER_ID,
                "capability_id": STANDARD_1D_CAPABILITY_ID,
                "runtime_adapter_id": MASCARET_ADAPTER_ID,
                "input_schema_version": HYDRAULIC_1D_INPUT_SCHEMA,
                "result_schema_version": HYDRAULIC_RESULT_SCHEMA,
                "runtime": ("cli", "container"),
            }
        ],
        "capabilities": [
            item.to_dict()
            for item in capabilities_for(
                DEFAULT_HYDRAULIC_1D_ENGINE_ID,
                DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
            )
        ],
        "reserved": ["d-flow-fm"],
    }


def registry_hash() -> str:
    """Bind task build identity to the external-engine adapter registration."""

    return snapshot_hash(engine_registry_payload())


def task_engine_provenance() -> dict[str, str]:
    """Return the existing task columns populated by the unified 1D route."""

    return {
        "solver_id": MASCARET_SOLVER_ID,
        "capability_id": STANDARD_1D_CAPABILITY_ID,
        "runtime_adapter_id": MASCARET_ADAPTER_ID,
        "result_schema_version": HYDRAULIC_RESULT_SCHEMA,
        "registry_hash": registry_hash(),
    }


def controlled_task_engine_provenance() -> dict[str, str]:
    """Return the D-Flow identity for an isolated controlled preview task."""

    return {
        "solver_id": DFLOW_FM_SOLVER_ID,
        "capability_id": DFLOW_FM_CAPABILITY_ID,
        "runtime_adapter_id": DFLOW_FM_ADAPTER_ID,
        "result_schema_version": CONTROLLED_HYDRAULIC_RESULT_SCHEMA,
        "registry_hash": selected_engine_hash(DFLOW_FM_ENGINE_ID),
    }


def engine_registrations() -> tuple[HydraulicEngineRegistration, ...]:
    """Return the immutable multi-engine catalog registrations."""

    return _ENGINE_REGISTRATIONS


def engine_registration(engine_id: str) -> HydraulicEngineRegistration:
    """Resolve one explicit engine ID without falling back to another solver."""

    for registration in _ENGINE_REGISTRATIONS:
        if registration.engine_id == engine_id:
            return registration
    raise KeyError(f"hydraulic engine is not registered: {engine_id}")


def _catalog_engine_payload(
    registration: HydraulicEngineRegistration,
) -> dict[str, object]:
    """Bind one registration to its versioned capability evidence."""

    return {
        **registration.to_dict(),
        "capabilities": [
            item.to_dict()
            for item in capabilities_for(
                registration.engine_id,
                registration.engine_version,
            )
        ],
    }


def engine_catalog_payload() -> dict[str, object]:
    """Return the additive multi-engine catalog without changing legacy task identity."""

    return {
        "schema_version": "dayu.hydraulic-engine-catalog.v1",
        "default_engine_id": DEFAULT_HYDRAULIC_1D_ENGINE_ID,
        "engines": [
            _catalog_engine_payload(registration)
            for registration in _ENGINE_REGISTRATIONS
        ],
    }


def engine_catalog_hash() -> str:
    """Hash the complete additive catalog independently of the legacy Registry."""

    return snapshot_hash(engine_catalog_payload())


def selected_engine_hash(engine_id: str) -> str:
    """Hash only the explicitly selected registration and capability matrix."""

    return snapshot_hash(_catalog_engine_payload(engine_registration(engine_id)))
