"""HTTP/OpenAPI boundaries for isolated synthetic hydraulic dispatch."""

from fastapi.testclient import TestClient

from app.dispatch import hydraulic_service
from app.dispatch.hydraulic_assets import HydraulicAssetNormalization
from app.dispatch.hydraulic_schemas import HydraulicPlanCompileRequest, HydraulicPreviewJobRecord
from app.main import app
from model.control.observation_bridge import ObservationBinding
from tests.hydraulic_1d.helpers import model_fixture


def test_openapi_separates_static_and_hydraulic_preview_routes() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/dispatch/plans/{plan_id}/schedule-preview" in paths
    assert "/api/v1/dispatch/plans/{plan_id}/hydraulic-clone" in paths
    assert "/api/v1/dispatch/plans/{plan_id}/hydraulic-compile-check" in paths
    assert "/api/v1/dispatch/plans/{plan_id}/hydraulic-freeze" in paths
    assert "/api/v1/dispatch/plans/{plan_id}/hydraulic-preview" in paths
    assert "/api/v1/dispatch/plans/{plan_id}/hydraulic-run" in paths
    assert paths["/api/v1/dispatch/plans/{plan_id}/hydraulic-preview"]["post"]["responses"]["202"]
    assert paths["/api/v1/dispatch/plans/{plan_id}/hydraulic-run"]["post"]["responses"]["202"]


def test_hydraulic_preview_returns_machine_readable_fail_closed_detail(
    monkeypatch,
) -> None:
    def blocked(*_args, **_kwargs):
        raise hydraulic_service.HydraulicDispatchStateError(
            "DFLOW_RUNTIME_BLOCKED: disabled",
            code="DFLOW_RUNTIME_BLOCKED",
        )

    monkeypatch.setattr(hydraulic_service, "start_hydraulic_preview", blocked)
    response = TestClient(app).post(
        "/api/v1/dispatch/plans/7/hydraulic-preview",
        json={
            "initial_actuator_state": [],
            "observation_bindings": [],
            "observation_sampling_interval_seconds": 10,
            "runtime_mode": "container",
            "timeout_seconds": 120,
            "synthetic_fixture": True,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "DFLOW_RUNTIME_BLOCKED",
        "message": "DFLOW_RUNTIME_BLOCKED: disabled",
    }


def test_frozen_hydraulic_run_uses_the_server_side_immutable_contract(monkeypatch) -> None:
    """The convenience run route accepts no mutable actuator or runtime fields."""

    def queued(_session, plan_id: int) -> HydraulicPreviewJobRecord:
        assert plan_id == 7
        return HydraulicPreviewJobRecord(job_id=41, run_id=12, status="QUEUED")

    monkeypatch.setattr(hydraulic_service, "start_frozen_hydraulic_calculation", queued)
    response = TestClient(app).post("/api/v1/dispatch/plans/7/hydraulic-run")

    assert response.status_code == 202
    assert response.json() == {
        "job_id": 41,
        "run_id": 12,
        "evidence_class": "SYNTHETIC_NUMERICAL_ONLY",
        "engine": "d-flow-fm",
        "control_runtime": "d-rtc/fbc",
        "status": "QUEUED",
        "real_engineering_validation": False,
        "real_equipment_command": False,
        "plc_scada_connected": False,
    }


def test_frozen_hydraulic_run_replays_only_snapshot_bound_execution_fields(monkeypatch) -> None:
    """Reconstruct initial states and runtime settings from the frozen envelope only."""

    plan = type("Plan", (), {"frozen_snapshot": {}})()
    session = type("Session", (), {"get": lambda *_args: plan})()
    envelope = type(
        "Envelope",
        (),
        {
            "initial_actuator_state": (),
            "control_observation_contract": type(
                "Observations", (), {"bindings": (), "sampling_interval_seconds": 15.0}
            )(),
            "plan_payload_json": (
                '{"execution_settings":{"runtime_mode":"container","timeout_seconds":120}}'
            ),
        },
    )()
    captured: dict[str, HydraulicPlanCompileRequest] = {}

    monkeypatch.setattr(hydraulic_service, "hydraulic_snapshot_integrity", lambda _plan: (True, None))
    monkeypatch.setattr(
        hydraulic_service.DispatchPlanSnapshot,
        "model_validate",
        lambda _snapshot: envelope,
    )
    monkeypatch.setattr(
        hydraulic_service,
        "start_hydraulic_preview",
        lambda _session, _plan_id, request: captured.setdefault("request", request),
    )

    hydraulic_service.start_frozen_hydraulic_calculation(session, 9)

    assert captured["request"].runtime_mode == "container"
    assert captured["request"].timeout_seconds == 120.0
    assert captured["request"].observation_sampling_interval_seconds == 15.0
    assert captured["request"].synthetic_fixture is True


def test_observation_source_must_be_emitted_by_the_frozen_adapter_model() -> None:
    request = HydraulicPlanCompileRequest(
        initial_actuator_state=(),
        observation_bindings=(
            ObservationBinding(
                observation_type="node_water_level",
                observation_object_id=91,
                source_kind="observation_point",
                source_id="not-emitted",
                binding_evidence="SYNTHETIC_ASSUMPTION",
            ),
        ),
        observation_sampling_interval_seconds=10.0,
    )

    issues = hydraulic_service._observation_inventory_issues(
        model_fixture(),
        HydraulicAssetNormalization(),
        request,
    )

    assert [item.code for item in issues] == ["CONTROL_OBSERVATION_SOURCE_NOT_EMITTED"]
