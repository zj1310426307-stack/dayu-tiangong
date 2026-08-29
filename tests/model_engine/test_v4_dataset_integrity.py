"""Fail-closed Dataset Version identity tests for native-v4 results."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from os import getenv
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import ForeignKeyConstraint, delete, func, select
from sqlalchemy.exc import IntegrityError

from app.database.session import SessionLocal
from app.gis.models import (
    DatasetVersion,
    Gate,
    HydraulicTaskControlEvent,
    HydraulicTaskGateResult,
    HydraulicTaskPumpResult,
    HydraulicTaskSectionResult,
    Pump,
    River,
    SimulationCase,
    SimulationTask,
)
from app.hydraulic.models import (
    HydraulicBranch,
    HydraulicCrossSection,
    HydraulicNetwork,
)
from app.model_engine import service as task_service
from app.model_engine.schemas import SimulationTaskCreate
from model.solver.registry import D1_CAPABILITY_ID, D1_SOLVER_ID
from tests.model_engine.rc1_fault_helpers import delete_task, ensure_authoritative_case
from tests.model_engine.test_v4_postgis_worker_integration import (
    BRANCH_ID,
    CASE_ID,
    DATASET_ID,
    GATE_ID,
    PUMP_ID,
    SECTION_IDS,
)


B_DATASET_ID = 9_901_001
B_RIVER_ID = 9_901_002
B_NETWORK_ID = 9_901_003
B_BRANCH_ID = 9_901_004
B_SECTION_ID = 9_901_005
B_GATE_ID = 9_901_006
B_PUMP_ID = 9_901_007


def _foreign_key(model: type[Any], name: str) -> ForeignKeyConstraint:
    return next(
        constraint
        for constraint in model.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name == name
    )


@pytest.mark.parametrize(
    ("model", "name", "local_columns", "remote_columns"),
    (
        (
            SimulationTask,
            "fk_simulation_task_case_dataset",
            ("case_id", "dataset_version_id"),
            ("simulation_case.id", "simulation_case.dataset_version_id"),
        ),
        (
            HydraulicTaskSectionResult,
            "fk_d2_section_result_task_dataset",
            ("task_id", "dataset_version_id"),
            ("simulation_task.id", "simulation_task.dataset_version_id"),
        ),
        (
            HydraulicTaskSectionResult,
            "fk_d2_section_result_section_version",
            ("hydraulic_cross_section_id", "dataset_version_id"),
            (
                "hydraulic.cross_section.id",
                "hydraulic.cross_section.dataset_version_id",
            ),
        ),
        (
            HydraulicTaskSectionResult,
            "fk_d2_section_result_branch_version",
            ("branch_id", "dataset_version_id"),
            ("hydraulic.branch.id", "hydraulic.branch.dataset_version_id"),
        ),
        (
            HydraulicTaskGateResult,
            "fk_d2_gate_result_task_dataset",
            ("task_id", "dataset_version_id"),
            ("simulation_task.id", "simulation_task.dataset_version_id"),
        ),
        (
            HydraulicTaskGateResult,
            "fk_d2_gate_result_gate_version",
            ("canonical_gate_id", "dataset_version_id"),
            ("gate.id", "gate.dataset_version_id"),
        ),
        (
            HydraulicTaskPumpResult,
            "fk_d2_pump_result_task_dataset",
            ("task_id", "dataset_version_id"),
            ("simulation_task.id", "simulation_task.dataset_version_id"),
        ),
        (
            HydraulicTaskPumpResult,
            "fk_d2_pump_result_pump_version",
            ("canonical_pump_id", "dataset_version_id"),
            ("pump.id", "pump.dataset_version_id"),
        ),
        (
            HydraulicTaskControlEvent,
            "fk_d2_control_event_task_dataset",
            ("task_id", "dataset_version_id"),
            ("simulation_task.id", "simulation_task.dataset_version_id"),
        ),
        (
            HydraulicTaskControlEvent,
            "fk_d2_control_event_gate_version",
            ("canonical_gate_id", "dataset_version_id"),
            ("gate.id", "gate.dataset_version_id"),
        ),
        (
            HydraulicTaskControlEvent,
            "fk_d2_control_event_pump_version",
            ("canonical_pump_id", "dataset_version_id"),
            ("pump.id", "pump.dataset_version_id"),
        ),
    ),
    ids=lambda value: getattr(value, "__name__", str(value)),
)
def test_orm_declares_complete_dataset_identity_chain(
    model: type[Any],
    name: str,
    local_columns: tuple[str, ...],
    remote_columns: tuple[str, ...],
) -> None:
    """Keep ORM metadata aligned with the RC1 composite identity chain."""

    constraint = _foreign_key(model, name)
    assert tuple(constraint.column_keys) == local_columns
    assert tuple(element.target_fullname for element in constraint.elements) == (
        remote_columns
    )
    assert model.__table__.c.dataset_version_id.nullable is False


def test_task_create_contract_cannot_accept_a_caller_selected_dataset() -> None:
    """Dataset identity comes from SimulationCase, never from request JSON."""

    with pytest.raises(ValidationError, match="dataset_version_id"):
        SimulationTaskCreate(case_id=123, dataset_version_id=456)  # type: ignore[call-arg]


def test_build_task_entity_derives_dataset_from_authoritative_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove the application assigns the Case Dataset before its first flush."""

    authoritative_dataset_id = 4242

    class FakeSession:
        added: SimulationTask | None = None

        def get(self, model: type[Any], identity: int) -> Any:
            assert model is SimulationCase
            assert identity == 123
            return SimpleNamespace(dataset_version_id=authoritative_dataset_id)

        def add(self, value: SimulationTask) -> None:
            self.added = value

        def flush(self) -> None:
            return None

    monkeypatch.setattr(
        task_service,
        "task_solver_provenance",
        lambda *args, **kwargs: {
            "solver_id": "dataset-integrity-test-v1",
            "capability_id": None,
            "runtime_adapter_id": None,
            "result_schema_version": "dataset-integrity-result-v1",
            "registry_hash": "b" * 64,
        },
    )
    monkeypatch.setattr(
        task_service,
        "freeze_task_input",
        lambda *args, **kwargs: ({"schema_version": "dataset-integrity-input-v1"}, "a" * 64),
    )

    session = FakeSession()
    task = task_service.build_task_entity(  # type: ignore[arg-type]
        session,
        SimulationTaskCreate(case_id=123),
    )

    assert task.dataset_version_id == authoritative_dataset_id
    assert session.added is task


def _point(longitude: float, latitude: float) -> Any:
    return func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4490)


def _line() -> Any:
    return func.ST_GeomFromText("LINESTRING(114.00 24.00, 114.01 24.01)", 4490)


def _cleanup_dataset_b() -> None:
    """Remove only this module's isolated high-ID Dataset B namespace."""

    with SessionLocal() as session:
        for model in (
            HydraulicTaskControlEvent,
            HydraulicTaskPumpResult,
            HydraulicTaskGateResult,
            HydraulicTaskSectionResult,
        ):
            session.execute(
                delete(model).where(model.dataset_version_id == B_DATASET_ID)
            )
        session.execute(delete(Pump).where(Pump.id == B_PUMP_ID))
        session.execute(delete(Gate).where(Gate.id == B_GATE_ID))
        session.execute(
            delete(HydraulicCrossSection).where(
                HydraulicCrossSection.id == B_SECTION_ID
            )
        )
        session.execute(
            delete(HydraulicBranch).where(HydraulicBranch.id == B_BRANCH_ID)
        )
        session.execute(
            delete(HydraulicNetwork).where(HydraulicNetwork.id == B_NETWORK_ID)
        )
        session.execute(delete(River).where(River.id == B_RIVER_ID))
        session.execute(
            delete(DatasetVersion).where(DatasetVersion.id == B_DATASET_ID)
        )
        session.commit()


def _seed_dataset_b_assets() -> None:
    """Create one minimal but valid Gate/Pump/Branch/Section identity set."""

    with SessionLocal() as session:
        session.add(
            DatasetVersion(
                id=B_DATASET_ID,
                version="D2-RC1-FK-B",
                name="D2 RC1 Dataset B FK evidence",
                creator="pytest",
                status="approved",
                content_hash="b" * 64,
            )
        )
        session.flush()
        session.add_all(
            [
                River(
                    id=B_RIVER_ID,
                    dataset_version_id=B_DATASET_ID,
                    name="D2 RC1 Dataset B river",
                    code="D2-RC1-B-RIVER",
                    length=100.0,
                    level="validation",
                    status="active",
                    geometry=_line(),
                ),
                HydraulicNetwork(
                    id=B_NETWORK_ID,
                    dataset_version_id=B_DATASET_ID,
                    code="D2-RC1-B-NETWORK",
                    name="D2 RC1 Dataset B network",
                    engineering_crs="EPSG:4547",
                    vertical_datum="1985 National Height Datum",
                ),
            ]
        )
        session.flush()
        session.add(
            HydraulicBranch(
                id=B_BRANCH_ID,
                dataset_version_id=B_DATASET_ID,
                network_id=B_NETWORK_ID,
                branch_code="D2-RC1-B-BRANCH",
                river_name="D2 RC1 Dataset B river",
                branch_name="D2 RC1 Dataset B branch",
                start_chainage=0.0,
                end_chainage=100.0,
                length_m=100.0,
                direction_status="confirmed",
                geometry=_line(),
            )
        )
        session.flush()
        session.add(
            HydraulicCrossSection(
                id=B_SECTION_ID,
                dataset_version_id=B_DATASET_ID,
                branch_id=B_BRANCH_ID,
                section_code="D2-RC1-B-SECTION",
                section_name="D2 RC1 Dataset B section",
                chainage=50.0,
                chainage_source="imported",
                location_geometry=_point(114.005, 24.005),
                orientation_status="confirmed",
            )
        )
        session.flush()
        session.add_all(
            [
                Gate(
                    id=B_GATE_ID,
                    dataset_version_id=B_DATASET_ID,
                    name="D2 RC1 Dataset B gate",
                    gate_code="D2-RC1-B-GATE",
                    river_id=B_RIVER_ID,
                    gate_type="sluice",
                    opening_direction="vertical",
                    control_mode="automatic",
                    width=2.0,
                    height=2.0,
                    max_flow=10.0,
                    bottom_elevation=0.0,
                    hydraulic_upstream_section_id=B_SECTION_ID,
                    hydraulic_downstream_section_id=B_SECTION_ID,
                    status="online",
                    geometry=_point(114.004, 24.004),
                ),
                Pump(
                    id=B_PUMP_ID,
                    dataset_version_id=B_DATASET_ID,
                    name="D2 RC1 Dataset B pump",
                    pump_code="D2-RC1-B-PUMP",
                    river_id=B_RIVER_ID,
                    design_flow=1.0,
                    head=2.0,
                    power=10.0,
                    efficiency_curve={"flow_efficiency": [[0.0, 0.8], [1.0, 0.8]]},
                    hydraulic_section_id=B_SECTION_ID,
                    control_mode="automatic",
                    status="online",
                    geometry=_point(114.006, 24.006),
                ),
            ]
        )
        session.commit()


@dataclass(frozen=True)
class DatasetIntegrityContext:
    task_id: int


@pytest.fixture(scope="module")
def pg_dataset_integrity_context() -> Iterator[DatasetIntegrityContext]:
    if getenv("RUN_D2_FAULT_INTEGRATION") != "1":
        pytest.skip("requires migrated PostGIS with RUN_D2_FAULT_INTEGRATION=1")

    plan_id = ensure_authoritative_case()
    _cleanup_dataset_b()
    _seed_dataset_b_assets()
    task_id: int | None = None
    try:
        with SessionLocal() as session:
            record = task_service.create_task(
                session,
                SimulationTaskCreate(
                    case_id=CASE_ID,
                    input_schema_version="dayu.model-input.v4",
                    solver_id=D1_SOLVER_ID,
                    capability_id=D1_CAPABILITY_ID,
                    dispatch_plan_id=plan_id,
                    execution_mode="validation",
                    storage_level="full",
                ),
            )
            task_id = record.id
            task = session.get(SimulationTask, task_id)
            assert task is not None
            assert task.dataset_version_id == DATASET_ID
        yield DatasetIntegrityContext(task_id=task_id)
    finally:
        if task_id is not None:
            delete_task(task_id)
        _cleanup_dataset_b()


def _section_result(
    context: DatasetIntegrityContext,
    *,
    dataset_version_id: int,
    section_id: int,
    branch_id: int,
    time_seconds: float,
) -> HydraulicTaskSectionResult:
    return HydraulicTaskSectionResult(
        task_id=context.task_id,
        dataset_version_id=dataset_version_id,
        hydraulic_cross_section_id=section_id,
        section_code="dataset-integrity",
        branch_id=branch_id,
        chainage_m=0.0,
        time_seconds=time_seconds,
        water_level_m=1.0,
        flow_m3s=1.0,
        velocity_m_s=1.0,
        control_volume_m3=1.0,
    )


def _gate_result(
    context: DatasetIntegrityContext,
    *,
    dataset_version_id: int,
    gate_id: int,
    time_seconds: float,
) -> HydraulicTaskGateResult:
    return HydraulicTaskGateResult(
        task_id=context.task_id,
        dataset_version_id=dataset_version_id,
        canonical_gate_id=gate_id,
        time_seconds=time_seconds,
        opening_m=1.0,
        flow_m3s=1.0,
        upstream_stage_m=2.0,
        downstream_stage_m=1.0,
    )


def _pump_result(
    context: DatasetIntegrityContext,
    *,
    dataset_version_id: int,
    pump_id: int,
    time_seconds: float,
) -> HydraulicTaskPumpResult:
    return HydraulicTaskPumpResult(
        task_id=context.task_id,
        dataset_version_id=dataset_version_id,
        canonical_pump_id=pump_id,
        time_seconds=time_seconds,
        control_state="on",
        running_units=1,
        flow_m3s=1.0,
        source_stage_m=1.0,
        outlet_stage_m=2.0,
        pump_head_m=1.0,
        system_head_m=1.0,
        efficiency=0.8,
        input_power_kw=10.0,
        cumulative_energy_kwh=1.0,
        iterations=1,
    )


def _gate_event(
    context: DatasetIntegrityContext,
    *,
    dataset_version_id: int,
    gate_id: int,
    time_seconds: float,
) -> HydraulicTaskControlEvent:
    return HydraulicTaskControlEvent(
        task_id=context.task_id,
        dataset_version_id=dataset_version_id,
        time_seconds=time_seconds,
        structure_type="gate",
        canonical_structure_id=gate_id,
        canonical_gate_id=gate_id,
        canonical_pump_id=None,
        event_type="dataset_integrity_test",
    )


def _pump_event(
    context: DatasetIntegrityContext,
    *,
    dataset_version_id: int,
    pump_id: int,
    time_seconds: float,
) -> HydraulicTaskControlEvent:
    return HydraulicTaskControlEvent(
        task_id=context.task_id,
        dataset_version_id=dataset_version_id,
        time_seconds=time_seconds,
        structure_type="pump",
        canonical_structure_id=pump_id,
        canonical_gate_id=None,
        canonical_pump_id=pump_id,
        event_type="dataset_integrity_test",
    )


InvalidRowFactory = Callable[[DatasetIntegrityContext], Any]


INVALID_ASSET_ROWS: tuple[tuple[str, InvalidRowFactory, str], ...] = (
    (
        "gate",
        lambda context: _gate_result(
            context,
            dataset_version_id=DATASET_ID,
            gate_id=B_GATE_ID,
            time_seconds=101.0,
        ),
        "fk_d2_gate_result_gate_version",
    ),
    (
        "pump",
        lambda context: _pump_result(
            context,
            dataset_version_id=DATASET_ID,
            pump_id=B_PUMP_ID,
            time_seconds=102.0,
        ),
        "fk_d2_pump_result_pump_version",
    ),
    (
        "branch",
        lambda context: _section_result(
            context,
            dataset_version_id=DATASET_ID,
            section_id=SECTION_IDS[0],
            branch_id=B_BRANCH_ID,
            time_seconds=103.0,
        ),
        "fk_d2_section_result_branch_version",
    ),
    (
        "section",
        lambda context: _section_result(
            context,
            dataset_version_id=DATASET_ID,
            section_id=B_SECTION_ID,
            branch_id=BRANCH_ID,
            time_seconds=104.0,
        ),
        "fk_d2_section_result_section_version",
    ),
    (
        "gate-event",
        lambda context: _gate_event(
            context,
            dataset_version_id=DATASET_ID,
            gate_id=B_GATE_ID,
            time_seconds=105.0,
        ),
        "fk_d2_control_event_gate_version",
    ),
    (
        "pump-event",
        lambda context: _pump_event(
            context,
            dataset_version_id=DATASET_ID,
            pump_id=B_PUMP_ID,
            time_seconds=106.0,
        ),
        "fk_d2_control_event_pump_version",
    ),
)


@pytest.mark.parametrize(
    ("identity", "factory", "expected_constraint"),
    INVALID_ASSET_ROWS,
    ids=[row[0] for row in INVALID_ASSET_ROWS],
)
def test_postgres_rejects_dataset_b_asset_for_dataset_a_task(
    pg_dataset_integrity_context: DatasetIntegrityContext,
    identity: str,
    factory: InvalidRowFactory,
    expected_constraint: str,
) -> None:
    """A Task cannot consume a Gate/Pump/Branch/Section/Event from Dataset B."""

    with SessionLocal() as session:
        session.add(factory(pg_dataset_integrity_context))
        with pytest.raises(IntegrityError) as caught:
            session.flush()
        diagnostic = getattr(caught.value.orig, "diag", None)
        assert diagnostic is not None, identity
        assert diagnostic.constraint_name == expected_constraint
        session.rollback()


INVALID_TASK_DATASET_ROWS: tuple[tuple[str, InvalidRowFactory, str], ...] = (
    (
        "section-result",
        lambda context: _section_result(
            context,
            dataset_version_id=B_DATASET_ID,
            section_id=B_SECTION_ID,
            branch_id=B_BRANCH_ID,
            time_seconds=201.0,
        ),
        "fk_d2_section_result_task_dataset",
    ),
    (
        "gate-result",
        lambda context: _gate_result(
            context,
            dataset_version_id=B_DATASET_ID,
            gate_id=B_GATE_ID,
            time_seconds=202.0,
        ),
        "fk_d2_gate_result_task_dataset",
    ),
    (
        "pump-result",
        lambda context: _pump_result(
            context,
            dataset_version_id=B_DATASET_ID,
            pump_id=B_PUMP_ID,
            time_seconds=203.0,
        ),
        "fk_d2_pump_result_task_dataset",
    ),
    (
        "control-event",
        lambda context: _gate_event(
            context,
            dataset_version_id=B_DATASET_ID,
            gate_id=B_GATE_ID,
            time_seconds=204.0,
        ),
        "fk_d2_control_event_task_dataset",
    ),
)


@pytest.mark.parametrize(
    ("row_kind", "factory", "expected_constraint"),
    INVALID_TASK_DATASET_ROWS,
    ids=[row[0] for row in INVALID_TASK_DATASET_ROWS],
)
def test_postgres_rejects_dataset_b_row_for_dataset_a_task(
    pg_dataset_integrity_context: DatasetIntegrityContext,
    row_kind: str,
    factory: InvalidRowFactory,
    expected_constraint: str,
) -> None:
    """Every result/event table independently binds its row Dataset to its Task."""

    with SessionLocal() as session:
        session.add(factory(pg_dataset_integrity_context))
        with pytest.raises(IntegrityError) as caught:
            session.flush()
        diagnostic = getattr(caught.value.orig, "diag", None)
        assert diagnostic is not None, row_kind
        assert diagnostic.constraint_name == expected_constraint
        session.rollback()


def test_postgres_accepts_legal_dataset_a_rows(
    pg_dataset_integrity_context: DatasetIntegrityContext,
) -> None:
    """The fail-closed constraints must not reject a fully consistent A chain."""

    task_id = pg_dataset_integrity_context.task_id
    with SessionLocal() as session:
        session.add_all(
            [
                _section_result(
                    pg_dataset_integrity_context,
                    dataset_version_id=DATASET_ID,
                    section_id=SECTION_IDS[0],
                    branch_id=BRANCH_ID,
                    time_seconds=301.0,
                ),
                _gate_result(
                    pg_dataset_integrity_context,
                    dataset_version_id=DATASET_ID,
                    gate_id=GATE_ID,
                    time_seconds=302.0,
                ),
                _pump_result(
                    pg_dataset_integrity_context,
                    dataset_version_id=DATASET_ID,
                    pump_id=PUMP_ID,
                    time_seconds=303.0,
                ),
                _gate_event(
                    pg_dataset_integrity_context,
                    dataset_version_id=DATASET_ID,
                    gate_id=GATE_ID,
                    time_seconds=304.0,
                ),
                _pump_event(
                    pg_dataset_integrity_context,
                    dataset_version_id=DATASET_ID,
                    pump_id=PUMP_ID,
                    time_seconds=305.0,
                ),
            ]
        )
        session.commit()

        for model, expected_count in (
            (HydraulicTaskSectionResult, 1),
            (HydraulicTaskGateResult, 1),
            (HydraulicTaskPumpResult, 1),
            (HydraulicTaskControlEvent, 2),
        ):
            count = session.scalar(
                select(func.count()).select_from(model).where(model.task_id == task_id)
            )
            assert count == expected_count
