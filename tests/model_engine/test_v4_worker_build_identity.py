"""Worker execution is pinned to the build that froze each queued task."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.worker.tasks import validate_worker_build_identity
from model.build_identity import RuntimeBuildIdentity, solver_build_id
from model.core.errors import HydraulicInputError
from model.solver.registry import registry_hash


def _identity(commit: str) -> RuntimeBuildIdentity:
    return RuntimeBuildIdentity(
        engine_version="dayu-hydraulic-4.0.0",
        engine_commit=commit,
        solver_build_id=solver_build_id(
            engine_version="dayu-hydraulic-4.0.0",
            engine_commit=commit,
            registry_hash=registry_hash(),
        ),
        build_mode="ci",
        verified=True,
    )


def _queued_task(identity: RuntimeBuildIdentity) -> SimpleNamespace:
    return SimpleNamespace(
        status="queued",
        engine_version=identity.engine_version,
        engine_commit=identity.engine_commit,
        solver_build_id=identity.solver_build_id,
        build_mode=identity.build_mode,
        build_verified=identity.verified,
        registry_hash=registry_hash(),
    )


def test_matching_worker_build_is_allowed() -> None:
    identity = _identity("a" * 40)
    assert validate_worker_build_identity(_queued_task(identity), identity) is identity


def test_old_build_queued_task_cannot_run_on_new_build_worker() -> None:
    task_build = _identity("a" * 40)
    worker_build = _identity("b" * 40)
    with pytest.raises(HydraulicInputError, match="D2_RUNTIME_BUILD_MISMATCH") as error:
        validate_worker_build_identity(_queued_task(task_build), worker_build)
    assert "engine_commit" in str(error.value)
    assert "solver_build_id" in str(error.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("engine_version", "dayu-hydraulic-4.0.1"),
        ("solver_build_id", "dayu.solver-build.v1:" + "f" * 64),
        ("registry_hash", "f" * 64),
    ],
)
def test_worker_rejects_each_build_identity_domain(field: str, value: object) -> None:
    identity = _identity("a" * 40)
    task = _queued_task(identity)
    setattr(task, field, value)
    with pytest.raises(HydraulicInputError, match=field):
        validate_worker_build_identity(task, identity)
