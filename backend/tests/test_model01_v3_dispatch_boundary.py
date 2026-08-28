"""Focused contracts for HYDRO-MODEL-01 input freezing and v3 envelopes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.dispatch import router as dispatch_router
from app.dispatch import service as dispatch_service
from app.dispatch.schemas import (
    DispatchActionCreate,
    DispatchActionUpdate,
    DispatchPlanCreate,
    DispatchPlanUpdate,
    DispatchRuleCreate,
    DispatchRuleUpdate,
)
from app.hydraulic.model_input import _build_structure_control_envelopes
from app.model_engine import service as model_service
from app.model_engine import provenance as task_provenance
from app.model_engine.schemas import SimulationTaskCreate
from model.build_identity import RuntimeBuildIdentity, current_runtime_build_identity
from model.provenance import snapshot_hash


def _rewritten_payload() -> dict[str, object]:
    """Return public structures after the legacy-to-hydraulic ID rewrite."""

    rule = {
        "id": 91,
        "observation_type": "node_water_level",
        "observation_object_id": 11,
    }
    return {
        "dataset_version": {
            "id": 7,
            "version": "MODEL-01",
            "content_hash": "abc123",
            "source_batch_id": 9,
        },
        "gates": [{
            "id": 31,
            "dataset_version_id": 7,
            "river_id": 101,
            "river_segment_id": 21,
            "station": 2500.0,
            "reach_id": 211,
            "control_mode": "fixed",
            "status": "online",
            "width": 4.0,
            "height": 2.0,
            "minimum_opening": 0.0,
            "maximum_opening": 2.0,
            "geometry": {"type": "Point", "coordinates": [113.0, 23.0]},
        }],
        "pumps": [{
            "id": 32,
            "dataset_version_id": 7,
            "river_id": 101,
            "control_mode": "fixed",
            "status": "online",
            "unit_count": 2,
            "design_flow": 8.0,
            "geometry": {"type": "Point", "coordinates": [113.01, 23.01]},
        }],
        "controls": {"section_geometry": "tabulated"},
        "dispatch_plan": {"rules": [rule]},
    }


def test_v3_structure_envelope_is_canonical_and_does_not_infer_pump_chainage() -> None:
    """Nested structures expose complete identities and frozen, uninitialized state."""

    payload = _rewritten_payload()
    structures, controls = _build_structure_control_envelopes(
        payload,
        legacy_river_to_branch={101: 21},
        legacy_segment_by_branch={21: 2001},
    )

    required = {
        "id",
        "dataset_version_id",
        "branch_id",
        "chainage",
        "geometry",
        "parameters",
        "control_state",
        "provenance",
    }
    gate = structures["gates"][0]
    pump = structures["pumps"][0]
    assert required <= gate.keys()
    assert required <= pump.keys()
    assert gate["branch_id"] == 21
    assert gate["chainage"] == 2500.0
    assert gate["parameters"]["opening_min"] == 0.0
    assert gate["parameters"]["opening_max"] == 2.0
    assert gate["control_state"] == {
        "mode": "dispatch",
        "control_mode": "fixed",
        "status": "uninitialized",
        "availability": "online",
        "opening": None,
        "state_source": "frozen_dispatch_plan",
    }
    assert gate["provenance"]["reach_id"] == 211
    assert pump["branch_id"] == 21
    assert pump["chainage"] is None
    assert pump["parameters"]["pump_count"] == 2
    assert pump["control_state"]["running_units"] is None
    assert pump["provenance"]["chainage_source"] == "unavailable_not_inferred"
    assert controls["rules"] is payload["dispatch_plan"]["rules"]


def test_static_fixed_asset_is_not_promoted_to_initialized_fixed_runtime_state() -> None:
    """Asset control metadata cannot make a baseline solver consume a null target."""

    payload = _rewritten_payload()
    payload.pop("dispatch_plan")
    structures, controls = _build_structure_control_envelopes(
        payload,
        legacy_river_to_branch={101: 21},
        legacy_segment_by_branch={21: 2001},
    )

    gate_state = structures["gates"][0]["control_state"]
    pump_state = structures["pumps"][0]["control_state"]
    assert gate_state["control_mode"] == "fixed"
    assert gate_state["mode"] == "uninitialized"
    assert gate_state["opening"] is None
    assert pump_state["control_mode"] == "fixed"
    assert pump_state["mode"] == "uninitialized"
    assert pump_state["running_units"] is None
    assert controls["rules"] == []


def test_freeze_task_input_passes_plan_before_hash_and_merges_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dispatch plan is rewritten by v3 and existing data provenance survives."""

    dispatch_plan = {"rules": [{"id": 91}]}
    received: dict[str, object] = {}

    def fake_build_model_input_v3(
        session: object,
        case_id: int,
        *,
        controls: dict[str, object],
        dispatch_plan: dict[str, object] | None,
        engine_version: str,
    ) -> dict[str, object]:
        received.update({
            "session": session,
            "case_id": case_id,
            "controls": controls,
            "dispatch_plan": dispatch_plan,
            "engine_version": engine_version,
        })
        return {
            "schema_version": "dayu.model-input.v3",
            "provenance": {
                "source_refs": {"survey_batch": "SURVEY-2026"},
                "validation_report": "quality-report.xlsx",
            },
        }

    monkeypatch.setattr(
        task_provenance, "build_model_input_v3", fake_build_model_input_v3
    )
    monkeypatch.setattr(task_provenance, "adapt_v3_to_v2", lambda snapshot: {})
    fake_session = object()
    build_identity = current_runtime_build_identity()
    snapshot, digest = task_provenance.freeze_task_input(
        fake_session,
        17,
        {"duration_seconds": 3600.0},
        schema_version="dayu.model-input.v3",
        build_identity=build_identity,
        dispatch_plan=dispatch_plan,
    )

    assert received["session"] is fake_session
    assert received["case_id"] == 17
    assert received["dispatch_plan"] is dispatch_plan
    assert snapshot["provenance"] == {
        "source_refs": {"survey_batch": "SURVEY-2026"},
        "validation_report": "quality-report.xlsx",
        **build_identity.provenance(),
        "input_schema_version": "dayu.model-input.v3",
    }
    assert digest == snapshot_hash(snapshot)


def test_freeze_task_input_rejects_non_object_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even a falsey non-object provenance value may not be silently discarded."""

    monkeypatch.setattr(
        task_provenance,
        "build_model_input_v3",
        lambda *args, **kwargs: {
            "schema_version": "dayu.model-input.v3",
            "provenance": [],
        },
    )
    monkeypatch.setattr(task_provenance, "adapt_v3_to_v2", lambda snapshot: {})
    with pytest.raises(ValueError, match="provenance must be an object"):
        build_identity = current_runtime_build_identity()
        task_provenance.freeze_task_input(
            object(),
            17,
            {},
            schema_version="dayu.model-input.v3",
            build_identity=build_identity,
        )


def test_dispatch_run_freezes_independent_baseline_and_controlled_v3_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The controlled plan enters the builder; no shallow post-freeze mutation remains."""

    plan_snapshot = {"schema_version": "dayu.dispatch-plan.v1", "rules": []}
    plan = SimpleNamespace(simulation_case_id=17, frozen_snapshot=plan_snapshot)
    calls: list[dict[str, object]] = []

    def fake_freeze_task_input(
        session: object,
        case_id: int,
        config: dict[str, object],
        *,
        schema_version: str,
        build_identity: RuntimeBuildIdentity,
        dispatch_plan: dict[str, object] | None = None,
    ) -> tuple[dict[str, object], str]:
        calls.append({
            "session": session,
            "case_id": case_id,
            "config": config,
            "schema_version": schema_version,
            "build_identity": build_identity,
            "dispatch_plan": dispatch_plan,
        })
        label = "controlled" if dispatch_plan is not None else "baseline"
        return {"kind": label}, f"{label}-hash"

    monkeypatch.setattr(
        dispatch_service, "freeze_task_input", fake_freeze_task_input
    )
    build_identity = current_runtime_build_identity()
    result = dispatch_service._freeze_run_snapshots(
        object(), plan, {"duration_seconds": 3600.0}, build_identity
    )

    assert result == (
        {"kind": "baseline"},
        "baseline-hash",
        {"kind": "controlled"},
        "controlled-hash",
    )
    assert [call["schema_version"] for call in calls] == [
        "dayu.model-input.v3",
        "dayu.model-input.v3",
    ]
    assert calls[0]["dispatch_plan"] is None
    assert calls[1]["dispatch_plan"] is plan_snapshot


def test_dispatch_run_reports_v3_readiness_as_a_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unready Dataset Version must become a stable plan-state error, not a 500."""

    plan = SimpleNamespace(simulation_case_id=17, frozen_snapshot={"rules": []})
    monkeypatch.setattr(
        dispatch_service,
        "freeze_task_input",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("engineering CRS is not confirmed")
        ),
    )

    with pytest.raises(
        dispatch_service.DispatchStateError,
        match="model-input.v3 is not ready: engineering CRS is not confirmed",
    ):
        dispatch_service._freeze_run_snapshots(
            object(), plan, {"duration_seconds": 3600.0}, "commit-abc"
        )


def test_dispatch_retry_maps_v3_readiness_failure_to_http_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry uses the same stable readiness-conflict semantics as first creation."""

    class FakeSession:
        @staticmethod
        def get(model: object, run_id: int) -> SimpleNamespace:
            return SimpleNamespace(id=run_id, plan_id=23, status="failed")

        @staticmethod
        def rollback() -> None:
            """Match the router's transactional cleanup on readiness failure."""

    monkeypatch.setattr(
        dispatch_router.service,
        "create_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            dispatch_service.DispatchStateError(
                "model-input.v3 is not ready: engineering CRS is not confirmed"
            )
        ),
    )

    with pytest.raises(HTTPException) as raised:
        dispatch_router.retry_run(5, FakeSession())

    assert raised.value.status_code == 409
    assert raised.value.detail == (
        "model-input.v3 is not ready: engineering CRS is not confirmed"
    )


def test_v3_result_persistence_uses_frozen_public_identity_bridge() -> None:
    """Result foreign keys must not rely on hydraulic/public sequences matching."""

    task = SimpleNamespace(
        input_schema_version="dayu.model-input.v3",
        input_snapshot={
            "schema_version": "dayu.model-input.v3",
            "branches": [{"id": 21, "legacy_river_id": 101}],
            "compatibility_mapping": {
                "river_nodes": [{
                    "legacy_river_node_id": 1001,
                    "hydraulic_node_id": 11,
                }],
                "cross_sections": [{
                    "legacy_cross_section_id": 3001,
                    "hydraulic_cross_section_id": 31,
                }],
            },
        },
    )

    sections, nodes, rivers = model_service._v3_result_identity_maps(task)

    assert sections == {31: 3001}
    assert nodes == {11: 1001}
    assert rivers == {101}
    assert model_service._public_result_id(31, sections, "cross-section") == 3001
    with pytest.raises(ValueError, match="cross-section 32 has no verified public mapping"):
        model_service._public_result_id(32, sections, "cross-section")


@pytest.mark.parametrize(
    ("water_balance", "payload", "message"),
    [
        (
            {"status": "fail", "relative_balance_residual": 1.0},
            {"flow": [0.0]},
            "failed the water-balance persistence gate",
        ),
        (
            {"status": "pass", "relative_balance_residual": 0.0},
            {"flow": [float("nan")]},
            "contains non-finite value",
        ),
    ],
)
def test_result_persistence_rejects_failed_balance_and_nonfinite_values(
    water_balance: dict[str, object],
    payload: dict[str, object],
    message: str,
) -> None:
    """A numerically invalid engine result can never become a successful task."""

    result = SimpleNamespace(
        schema_version="dayu.hydraulic-result.v2",
        water_balance=water_balance,
        to_dict=lambda: {**payload, "water_balance": water_balance},
    )

    with pytest.raises(ValueError, match=message):
        model_service._validate_engine_result_for_persistence(result)


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
def test_dispatch_contract_rejects_nonfinite_control_values(nonfinite: float) -> None:
    """NaN and infinities cannot enter a plan, action, or rule snapshot."""

    with pytest.raises(ValidationError):
        DispatchPlanCreate(
            dataset_version_id=1,
            simulation_case_id=1,
            name="invalid duration",
            duration_seconds=nonfinite,
        )
    with pytest.raises(ValidationError):
        DispatchActionCreate(
            sequence=0,
            time_seconds=0.0,
            structure_type="gate",
            gate_id=1,
            command_type="gate_opening_m",
            target_value=nonfinite,
        )
    with pytest.raises(ValidationError):
        DispatchRuleCreate(
            name="invalid threshold",
            observation_type="elapsed_time",
            operator=">=",
            threshold=nonfinite,
            action_template={
                "structure_type": "pump",
                "structure_id": 1,
                "command_type": "pump_target_flow",
                "target_value": 1.0,
            },
        )
    with pytest.raises(ValidationError):
        DispatchRuleCreate(
            name="invalid target",
            observation_type="elapsed_time",
            operator=">=",
            threshold=0.0,
            action_template={
                "structure_type": "pump",
                "structure_id": 1,
                "command_type": "pump_target_flow",
                "target_value": nonfinite,
            },
        )
    with pytest.raises(ValidationError):
        SimulationTaskCreate(case_id=1, duration_seconds=nonfinite)


@pytest.mark.parametrize(
    ("evaluation_config", "expected_path"),
    [
        (
            {"levels": {"warning": float("nan")}},
            "evaluation_config.levels.warning",
        ),
        (
            {"objectives": [1.0, float("inf")]},
            "evaluation_config.objectives[1]",
        ),
        (
            {"weights": (1.0, {"penalty": float("-inf")})},
            "evaluation_config.weights[1].penalty",
        ),
    ],
)
def test_plan_contract_rejects_nested_nonfinite_evaluation_config_with_path(
    evaluation_config: dict[str, object], expected_path: str
) -> None:
    """Create and update reject NaN/infinities inside dict, list, and tuple paths."""

    with pytest.raises(ValidationError) as create_error:
        DispatchPlanCreate(
            dataset_version_id=1,
            simulation_case_id=1,
            name="invalid evaluation config",
            duration_seconds=3600.0,
            evaluation_config=evaluation_config,
        )
    assert expected_path in str(create_error.value)

    with pytest.raises(ValidationError) as update_error:
        DispatchPlanUpdate(evaluation_config=evaluation_config)
    assert expected_path in str(update_error.value)


def test_plan_contract_accepts_nested_finite_evaluation_config() -> None:
    """Finite JSON-like evaluation settings retain their nested container values."""

    evaluation_config = {
        "levels": {"warning": 10.5},
        "objectives": [1.0, 2.0],
        "weights": (0.25, {"penalty": -3.0}),
    }

    created = DispatchPlanCreate(
        dataset_version_id=1,
        simulation_case_id=1,
        name="finite evaluation config",
        duration_seconds=3600.0,
        evaluation_config=evaluation_config,
    )
    updated = DispatchPlanUpdate(evaluation_config=evaluation_config)

    assert created.evaluation_config == evaluation_config
    assert updated.evaluation_config == evaluation_config


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "abc", None, True])
def test_plan_contract_rejects_nonnumeric_consumed_levels(invalid: object) -> None:
    """Known flood-risk level settings cannot fail later inside float()."""

    with pytest.raises(ValidationError, match="warning_level must be a finite number"):
        DispatchPlanCreate(
            dataset_version_id=1,
            simulation_case_id=1,
            name="invalid warning level",
            duration_seconds=3600.0,
            evaluation_config={"warning_level": invalid},
        )


@pytest.mark.parametrize(
    "payload",
    [
        lambda: DispatchPlanUpdate(name=None),
        lambda: DispatchActionUpdate(command_type=None),
        lambda: DispatchRuleUpdate(threshold=None),
    ],
)
def test_patch_contract_rejects_explicit_null_for_nonnullable_fields(payload: object) -> None:
    """Omitted fields remain optional, but explicit null cannot reach non-null columns."""

    with pytest.raises(ValidationError, match="explicit null is not allowed"):
        payload()


def test_task_creation_maps_v3_preflight_failure_to_state_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A not-ready v3 Dataset Version is a 409-style state error, never a 500."""

    session = SimpleNamespace(get=lambda *args: object())
    monkeypatch.setattr(
        model_service,
        "freeze_task_input",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("gate target reach is ambiguous")
        ),
    )

    with pytest.raises(
        model_service.TaskStateError,
        match="model input is not ready: gate target reach is ambiguous",
    ):
        model_service.create_task(
            session,
            SimulationTaskCreate(
                case_id=1,
                input_schema_version="dayu.model-input.v3",
            ),
        )


def _queued_dispatch_objects() -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    """Create the persisted lifecycle shape consumed by the queue helper."""

    common = {
        "status": "queued",
        "progress": 0,
        "queue_job_id": None,
        "delivery_attempt_count": 0,
        "last_delivery_time": None,
        "last_infrastructure_error": None,
        "error_message": None,
        "end_time": None,
    }
    baseline = SimpleNamespace(id=101, **common)
    controlled = SimpleNamespace(id=102, **common)
    run = SimpleNamespace(id=201, **common)
    return run, baseline, controlled


class _CommitCounter:
    """Minimal session double that proves each external delivery is durable."""

    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def test_dispatch_queue_failure_before_first_delivery_remains_recoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broker outage leaves durable queued intent for periodic recovery."""

    run, baseline, controlled = _queued_dispatch_objects()
    session = _CommitCounter()
    monkeypatch.setattr(
        dispatch_service.run_hydraulic_task,
        "delay",
        lambda task_id: (_ for _ in ()).throw(ConnectionError("broker down")),
    )

    with pytest.raises(dispatch_service.DispatchQueueError) as raised:
        dispatch_service._enqueue_run_tasks(session, run, baseline, controlled)

    assert "recovery pending" in str(raised.value)
    assert session.commits == 2
    assert {baseline.status, controlled.status, run.status} == {"queued"}
    assert baseline.delivery_attempt_count == 1
    assert controlled.delivery_attempt_count == 0
    assert baseline.last_delivery_time is not None
    assert "recovery pending" in baseline.last_infrastructure_error
    assert dispatch_router._error(raised.value).status_code == 503


def test_dispatch_queue_failure_after_baseline_records_recoverable_partial_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second failure preserves both queued intents and the first job marker."""

    run, baseline, controlled = _queued_dispatch_objects()
    session = _CommitCounter()
    calls: list[int] = []

    def deliver(task_id: int) -> SimpleNamespace:
        calls.append(task_id)
        if len(calls) == 1:
            return SimpleNamespace(id="baseline-job")
        raise ConnectionError("broker failed on second delivery")

    monkeypatch.setattr(dispatch_service.run_hydraulic_task, "delay", deliver)

    with pytest.raises(dispatch_service.DispatchQueueError) as raised:
        dispatch_service._enqueue_run_tasks(session, run, baseline, controlled)

    assert calls == [101, 102]
    assert session.commits == 4
    assert baseline.status == "queued"
    assert baseline.queue_job_id == "baseline-job"
    assert controlled.status == "queued"
    assert controlled.progress == 0
    assert controlled.queue_job_id is None
    assert controlled.delivery_attempt_count == 1
    assert controlled.last_delivery_time is not None
    assert run.status == "queued"
    assert run.queue_job_id == "baseline-job"
    assert "baseline_job_id=baseline-job" in str(raised.value)
    assert "durable recovery pending" in run.error_message
    assert dispatch_router._error(raised.value).status_code == 503
