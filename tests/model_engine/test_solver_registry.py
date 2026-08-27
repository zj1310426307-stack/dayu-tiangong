"""Platform Solver Registry identity and fail-closed routing tests."""

import pytest

from model.core.errors import HydraulicInputError
from model.solver.registry import (
    D1_CAPABILITY_ID,
    D1_RUNTIME_ADAPTER_ID,
    D1_SOLVER_ID,
    LEGACY_NETWORK_SOLVER,
    resolve_solver,
    registry_hash,
)


def test_v1_v2_v3_routes_remain_legacy_and_v4_is_native() -> None:
    """Keep established routes while proving v4 has no v3/v2 adapter path."""

    assert resolve_solver("dayu.model-input.v2").solver_id == LEGACY_NETWORK_SOLVER
    assert resolve_solver("dayu.model-input.v3").runtime_adapter.runtime_schema_version == (
        "dayu.model-input.v2"
    )
    native = resolve_solver(
        "dayu.model-input.v4",
        solver_id=D1_SOLVER_ID,
        capability_id=D1_CAPABILITY_ID,
        runtime_adapter_id=D1_RUNTIME_ADAPTER_ID,
    )
    assert native.engine_route == "finite-volume-d1-v4"
    assert native.runtime_adapter.runtime_schema_version == "dayu.model-input.v4-lite"
    assert native.runtime_adapter.runtime_schema_version != "dayu.model-input.v2"
    assert registry_hash() == (
        "c9c674c9f2130e5d87a715f4663f820365dfb13e6833dace404e46f55b5b6f5e"
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"solver_id": "unknown"}, "solver"),
        ({"capability_id": "unknown"}, "capability"),
        ({"runtime_adapter_id": "v3-to-v2-v1"}, "runtime adapter"),
    ],
)
def test_v4_registry_rejects_mismatched_identity(kwargs: dict, message: str) -> None:
    """Never silently repair an unregistered solver/capability/adapter selection."""

    with pytest.raises(HydraulicInputError, match=message):
        resolve_solver("dayu.model-input.v4", **kwargs)


def test_unknown_schema_fails_closed() -> None:
    """Prevent unknown future schemas from falling back to a legacy route."""

    with pytest.raises(HydraulicInputError, match="unregistered"):
        resolve_solver("dayu.model-input.v99")
