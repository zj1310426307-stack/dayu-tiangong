"""Verify successful task results can be summarized for the scheme-results page."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.model_engine import service
from model.hydraulic_1d.contracts import HYDRAULIC_1D_INPUT_SCHEMA
from model.hydraulic_1d.registry import CONTROLLED_HYDRAULIC_1D_RUN_SCHEMA


def _row(section_id: int, chainage: float, time: float, water_level: float) -> SimpleNamespace:
    """Build one solver-neutral persisted result row for overview tests."""

    return SimpleNamespace(
        hydraulic_cross_section_id=section_id,
        section_code=f"DM{section_id}",
        branch_id=11,
        chainage_m=chainage,
        time_seconds=time,
        water_level_m=water_level,
        depth_m=2.0,
        flow_m3s=405.43,
        velocity_m_s=1.2,
        flow_area_m2=337.858,
        top_width_m=80.0,
        froude_number=0.13,
    )


def test_result_overview_uses_complete_final_time_and_upstream_order(monkeypatch) -> None:
    """Return one final row per Section without mixing earlier output times."""

    task = SimpleNamespace(
        id=437,
        case_id=14,
        dataset_version_id=78,
        status="success",
        input_schema_version=HYDRAULIC_1D_INPUT_SCHEMA,
        config={"calculation_mode": "steady"},
        evidence_class="UNCALIBRATED_SCENARIO",
        created_time="2026-09-09T09:57:22Z",
        end_time="2026-09-09T09:57:25Z",
        diagnostics={"boundary_control_warnings": []},
    )
    rows = [
        _row(2, 274.173, 0.0, 39.0),
        _row(1, 0.0, 3600.0, 40.302),
        _row(1, 0.0, 0.0, 40.0),
        _row(2, 274.173, 3600.0, 39.7),
    ]
    session = MagicMock()
    session.get.return_value = task
    session.scalars.return_value.all.return_value = rows
    monkeypatch.setattr(
        service,
        "parse_result_task_model",
        lambda _task: SimpleNamespace(simulation_id="sim-14", scenario_id="14"),
    )

    overview = service.get_result_overview(session, task.id)

    assert overview.final_time_seconds == 3600.0
    assert [item.section_id for item in overview.section_summary] == [1, 2]
    assert [item.water_level_m for item in overview.section_summary] == [40.302, 39.7]
    assert overview.section_summary[0].bed_elevation_m == 38.302
    assert overview.calculation_mode == "steady"


def test_result_overview_rejects_incomplete_final_section_axis(monkeypatch) -> None:
    """Fail closed when the last output time does not cover every Section."""

    task = SimpleNamespace(
        id=438,
        status="success",
        input_schema_version=HYDRAULIC_1D_INPUT_SCHEMA,
    )
    session = MagicMock()
    session.get.return_value = task
    session.scalars.return_value.all.return_value = [
        _row(1, 0.0, 3600.0, 40.0),
        _row(2, 274.173, 3540.0, 39.5),
    ]
    monkeypatch.setattr(
        service,
        "parse_result_task_model",
        lambda _task: SimpleNamespace(simulation_id="sim-14", scenario_id="14"),
    )

    try:
        service.get_result_overview(session, task.id)
    except service.TaskStateError as exc:
        assert "complete final Section time" in str(exc)
    else:
        raise AssertionError("incomplete final Section axis must be rejected")


def test_controlled_result_overview_includes_final_gate_and_pump_response(monkeypatch) -> None:
    """Expose H/Q and native structure response from the same final model time."""

    task = SimpleNamespace(
        id=439,
        case_id=17,
        dataset_version_id=79,
        status="success",
        task_kind="controlled_hydraulic_preview",
        input_schema_version=CONTROLLED_HYDRAULIC_1D_RUN_SCHEMA,
        engine_version="DIMRset_2026.02",
        config={"runtime_mode": "container"},
        evidence_class="SYNTHETIC_NUMERICAL_ONLY",
        created_time="2026-09-10T08:00:00Z",
        end_time="2026-09-10T08:01:00Z",
        diagnostics={},
    )
    structure_row = SimpleNamespace(
        structure_type="pump",
        structure_id=31,
        time_seconds=120.0,
        requested_value=8.0,
        resolved_value=8.0,
        actual_value=7.5,
        flow=6.9,
        upstream_level=12.5,
        downstream_level=15.1,
        head_difference=2.6,
        native_applied_capacity=7.5,
        actual_discharge=6.9,
        pump_head=2.7,
        pump_reduction_factor=0.92,
        pump_actual_stage=None,
        regime="operating",
    )
    section_scalars = MagicMock()
    section_scalars.all.return_value = [_row(1, 0.0, 120.0, 40.0)]
    structure_scalars = MagicMock()
    structure_scalars.all.return_value = [structure_row]
    session = MagicMock()
    session.get.return_value = task
    session.scalars.side_effect = [section_scalars, structure_scalars]
    monkeypatch.setattr(
        service,
        "parse_result_task_model",
        lambda _task: SimpleNamespace(simulation_id="controlled-17", scenario_id="17"),
    )

    overview = service.get_result_overview(session, task.id)

    assert overview.task_kind == "controlled_hydraulic_preview"
    assert overview.engine == "d-flow-fm"
    assert overview.calculation_mode == "unsteady"
    assert overview.structure_summary[0].actual_discharge_m3s == 6.9
    assert overview.structure_summary[0].pump_head_m == 2.7


def test_controlled_result_overview_rejects_missing_structure_result(monkeypatch) -> None:
    """A successful controlled task cannot omit its authoritative Gate/Pump trace."""

    task = SimpleNamespace(
        id=440,
        status="success",
        input_schema_version=CONTROLLED_HYDRAULIC_1D_RUN_SCHEMA,
        engine_version="DIMRset_2026.02",
    )
    section_scalars = MagicMock()
    section_scalars.all.return_value = [_row(1, 0.0, 120.0, 40.0)]
    structure_scalars = MagicMock()
    structure_scalars.all.return_value = []
    session = MagicMock()
    session.get.return_value = task
    session.scalars.side_effect = [section_scalars, structure_scalars]
    monkeypatch.setattr(
        service,
        "parse_result_task_model",
        lambda _task: SimpleNamespace(simulation_id="controlled-18", scenario_id="18"),
    )

    try:
        service.get_result_overview(session, task.id)
    except service.TaskStateError as exc:
        assert "no authoritative Gate/Pump result" in str(exc)
    else:
        raise AssertionError("controlled task without Structure Result must be rejected")
