"""Small immutable registry for externally integrated hydraulic engines."""

from __future__ import annotations

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
