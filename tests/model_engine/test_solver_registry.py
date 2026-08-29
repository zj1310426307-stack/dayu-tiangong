"""Platform Solver Registry identity and fail-closed routing tests."""

from types import SimpleNamespace

import pytest

from app.dispatch import service as dispatch_service
from app.model_engine import service
from app.model_engine.schemas import SimulationTaskCreate
from app.optimization import tasks as optimization_tasks
from model.build_identity import current_runtime_build_identity
from model.core.errors import HydraulicInputError
from model.provenance import snapshot_hash
from model.solver.registry import (
    D1_CAPABILITY_ID,
    D1_RUNTIME_ADAPTER_ID,
    D1_SOLVER_ID,
    D3A_1_CAPABILITY_ID,
    D3A_1_RUNTIME_ADAPTER_ID,
    D3A_2_CAPABILITY_ID,
    D3A_3_CAPABILITY_ID,
    LEGACY_NETWORK_SOLVER,
    LEGACY_SINGLE_RIVER_SOLVER,
    MODEL_INPUT_V2,
    MODEL_INPUT_V3,
    V3_RUNTIME_ADAPTER_ID,
    capability_catalog,
    resolve_capability,
    resolve_solver,
    registry_hash,
    task_solver_provenance,
)


class _BuildSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_count = 0
        self.commit_count = 0

    def get(self, _model, _identity):
        return SimpleNamespace(dataset_version_id=17)

    def add(self, entity) -> None:
        entity.id = 101
        self.added.append(entity)

    def flush(self) -> None:
        self.flush_count += 1

    def commit(self) -> None:
        self.commit_count += 1


def _patch_task_freezers(monkeypatch) -> None:
    def freeze_legacy(_session, _case_id, _config, *, schema_version, **_kwargs):
        return {"schema_version": schema_version}, "a" * 64

    def freeze_v4(_session, _case_id, _dispatch_plan_id, **_kwargs):
        return (
            {"schema_version": "dayu.model-input.v4"},
            "b" * 64,
            {
                "runtime_projection_hash": "c" * 64,
                "mesh_hash": "d" * 64,
                "solver_policy_hash": "e" * 64,
                "validation_policy_hash": "f" * 64,
                "registry_hash": registry_hash(),
            },
        )

    monkeypatch.setattr(service, "freeze_task_input", freeze_legacy)
    monkeypatch.setattr(service, "freeze_v4_task_input", freeze_v4)


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
        "da6bae78f460b96ba766e4ed4774d6476ab39d7389714c4bca7781b6d9d05f56"
    )


def test_d3a_catalog_unlocks_only_the_completed_manning_gate() -> None:
    """Expose D3A-1 explicitly while keeping later science envelopes blocked."""

    catalog = capability_catalog()
    assert tuple(item.capability_id for item in catalog) == (
        D1_CAPABILITY_ID,
        D3A_1_CAPABILITY_ID,
        D3A_2_CAPABILITY_ID,
        D3A_3_CAPABILITY_ID,
    )
    assert tuple(item.status for item in catalog) == (
        "supported",
        "supported",
        "blocked",
        "blocked",
    )
    assert resolve_capability(D1_CAPABILITY_ID).status == "supported"
    assert resolve_capability(D3A_1_CAPABILITY_ID).status == "supported"
    d3a = resolve_solver(
        "dayu.model-input.v4",
        capability_id=D3A_1_CAPABILITY_ID,
        runtime_adapter_id=D3A_1_RUNTIME_ADAPTER_ID,
    )
    assert d3a.engine_route == "finite-volume-d3a-1-v4"
    with pytest.raises(HydraulicInputError, match="scientifically blocked"):
        resolve_capability(D3A_2_CAPABILITY_ID)


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


@pytest.mark.parametrize(
    ("schema_version", "requested_solver", "dispatch_plan_id"),
    [
        ("dayu.model-input.v1", None, None),
        ("dayu.model-input.v2", None, None),
        ("dayu.model-input.v3", LEGACY_NETWORK_SOLVER, None),
        ("dayu.model-input.v4", None, 91),
    ],
)
def test_task_builder_persists_only_registry_resolved_provenance(
    monkeypatch,
    schema_version: str,
    requested_solver: str | None,
    dispatch_plan_id: int | None,
) -> None:
    _patch_task_freezers(monkeypatch)
    session = _BuildSession()
    payload = SimulationTaskCreate(
        case_id=71,
        input_schema_version=schema_version,
        solver_id=requested_solver,
        dispatch_plan_id=dispatch_plan_id,
        capability_id=(
            D1_CAPABILITY_ID if schema_version == "dayu.model-input.v4" else None
        ),
        storage_level="full",
    )

    task = service.build_task_entity(session, payload)  # type: ignore[arg-type]
    registration = resolve_solver(
        schema_version,
        capability_id=(
            D1_CAPABILITY_ID if schema_version == "dayu.model-input.v4" else None
        ),
    )

    assert task.solver_id == registration.solver_id
    assert task.capability_id == (
        registration.capability.capability_id
        if registration.capability is not None
        else None
    )
    assert task.runtime_adapter_id == (
        registration.runtime_adapter.runtime_adapter_id
        if registration.runtime_adapter is not None
        else None
    )
    assert task.result_schema_version == registration.result_schema_version
    assert task.registry_hash == registry_hash()
    assert task.dataset_version_id == 17
    assert session.added == [task]
    assert session.flush_count == 1
    assert session.commit_count == 0


@pytest.mark.parametrize(
    ("schema_version", "spoofed_solver"),
    [
        ("dayu.model-input.v1", D1_SOLVER_ID),
        ("dayu.model-input.v2", "arbitrary-client-solver"),
        ("dayu.model-input.v3", LEGACY_SINGLE_RIVER_SOLVER),
    ],
)
def test_task_builder_rejects_spoofed_legacy_solver_ids(
    monkeypatch, schema_version: str, spoofed_solver: str
) -> None:
    _patch_task_freezers(monkeypatch)
    session = _BuildSession()
    payload = SimulationTaskCreate(
        case_id=71,
        input_schema_version=schema_version,
        solver_id=spoofed_solver,
    )

    with pytest.raises(service.TaskStateError, match="not registered"):
        service.build_task_entity(session, payload)  # type: ignore[arg-type]

    assert session.added == []
    assert session.flush_count == 0
    assert session.commit_count == 0


def test_v3_registry_provenance_includes_runtime_adapter() -> None:
    registration = resolve_solver("dayu.model-input.v3")
    assert registration.solver_id == LEGACY_NETWORK_SOLVER
    assert registration.runtime_adapter is not None
    assert registration.runtime_adapter.runtime_adapter_id == V3_RUNTIME_ADAPTER_ID


def _assert_complete_task_provenance(task, schema_version: str) -> None:
    expected = task_solver_provenance(schema_version)
    for field, value in expected.items():
        assert getattr(task, field) == value


def test_dispatch_baseline_and_controlled_tasks_share_registry_authority() -> None:
    """Both internal v3 rows retain their independent frozen input identities."""

    plan = SimpleNamespace(simulation_case_id=23, dataset_version_id=29)
    config = {"storage_level": "full"}
    baseline_snapshot = {"schema_version": MODEL_INPUT_V3, "role": "baseline"}
    controlled_snapshot = {"schema_version": MODEL_INPUT_V3, "role": "controlled"}

    build_identity = current_runtime_build_identity()
    baseline = dispatch_service._build_run_task(  # type: ignore[arg-type]
        plan, config, baseline_snapshot, "1" * 64, build_identity
    )
    controlled = dispatch_service._build_run_task(  # type: ignore[arg-type]
        plan, config, controlled_snapshot, "2" * 64, build_identity
    )

    for task in (baseline, controlled):
        _assert_complete_task_provenance(task, MODEL_INPUT_V3)
        assert task.dataset_version_id == 29
        assert task.config == config
        assert task.solver_build_id == build_identity.solver_build_id
    assert baseline.input_snapshot is baseline_snapshot
    assert baseline.input_snapshot_hash == "1" * 64
    assert controlled.input_snapshot is controlled_snapshot
    assert controlled.input_snapshot_hash == "2" * 64


def test_optimization_candidate_task_uses_complete_registry_provenance() -> None:
    """The internal v2 candidate producer cannot create a provenance-null row."""

    optimization = SimpleNamespace(simulation_case_id=31, dataset_version_id=37)
    snapshot = {
        "schema_version": MODEL_INPUT_V2,
        "provenance": {"engine_commit": "optimization-commit"},
    }
    task = optimization_tasks._build_candidate_simulation_task(  # type: ignore[arg-type]
        optimization,
        snapshot,
        duration=120.0,
        algorithm={"time_step_seconds": 2.0, "output_interval_seconds": 10.0},
    )

    _assert_complete_task_provenance(task, MODEL_INPUT_V2)
    assert task.dataset_version_id == 37
    assert task.input_snapshot is snapshot
    assert task.input_snapshot_hash == snapshot_hash(snapshot)
    assert task.engine_commit == "optimization-commit"
