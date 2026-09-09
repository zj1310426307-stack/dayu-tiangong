"""Verify the public task contract cannot select a retired solver route."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.model_engine.schemas import SimulationTaskCreate
from app.model_engine.hydraulic_1d_service import (
    _boundary_derived_initial_condition,
    _vertical_bank_extended_sections,
    _with_simulation_identity,
)
from app.model_engine.service import _validate_result, parse_frozen_task_model, retry_block_reason
from model.hydraulic_1d.contracts import (
    HYDRAULIC_1D_INPUT_SCHEMA,
    Hydraulic1DModel,
    HydraulicResult,
    HydraulicResultRecord,
)
from model.hydraulic_1d.errors import Hydraulic1DValidationError
from model.hydraulic_1d.registry import (
    DEFAULT_HYDRAULIC_1D_ENGINE_ID,
    DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
    engine_registry_payload,
    task_engine_provenance,
)
from model.provenance import snapshot_hash
from tests.hydraulic_1d.helpers import model_fixture


def test_task_creation_has_one_engine_and_one_input_schema() -> None:
    """Clients cannot submit v1-v4, a custom solver ID, or fallback controls."""

    payload = SimulationTaskCreate(case_id=7)
    assert payload.engine == DEFAULT_HYDRAULIC_1D_ENGINE_ID
    assert payload.input_schema_version == HYDRAULIC_1D_INPUT_SCHEMA
    with pytest.raises(ValidationError):
        SimulationTaskCreate.model_validate(
            {"case_id": 7, "input_schema_version": "dayu.model-input.v4"}
        )
    with pytest.raises(ValidationError):
        SimulationTaskCreate.model_validate({"case_id": 7, "solver_id": "internal"})


def test_initial_state_overrides_are_atomic() -> None:
    """A partial override cannot combine live values with a frozen Case value."""

    with pytest.raises(ValidationError, match="must be supplied together"):
        SimulationTaskCreate(case_id=7, initial_water_level=2.0)


def test_endpoint_chainage_accepts_millimetre_import_rounding_only() -> None:
    """Decimal import drift must not reject a topologically coincident end profile."""

    payload = model_fixture().model_dump(mode="json")
    payload["cross_sections"][-1]["chainage_m"] = 999.9995
    accepted = Hydraulic1DModel.model_validate(payload)
    assert accepted.cross_sections[-1].chainage_m == 999.9995

    payload["cross_sections"][-1]["chainage_m"] = 999.998
    with pytest.raises(ValidationError, match="last cross section must coincide"):
        Hydraulic1DModel.model_validate(payload)


def test_single_branch_boundaries_derive_a_wet_section_initial_state() -> None:
    """Optional initial fields use a traceable wet-bed envelope, not downstream H uniformly."""

    source = model_fixture()
    raised_upstream = source.cross_sections[0].model_copy(
        update={
            "points": tuple(
                point.model_copy(update={"elevation_m": point.elevation_m + 3.0})
                for point in source.cross_sections[0].points
            )
        }
    )
    initial = _boundary_derived_initial_condition(
        source.branches,
        (raised_upstream, source.cross_sections[1]),
        source.boundaries,
    )

    assert initial is not None
    assert initial.water_level_m is None
    assert initial.by_section[0].water_level_m == 3.5
    assert initial.by_section[-1].water_level_m == 2.0
    assert {item.discharge_m3s for item in initial.by_section} == {11.0}


def test_high_discharge_boundary_derives_a_subcritical_cold_start() -> None:
    """A design flood must not reuse the fixed minimum depth at a narrow profile."""

    source = model_fixture()
    high_flow_boundaries = tuple(
        boundary.model_copy(
            update={
                "series": (
                    boundary.series[0].model_copy(update={"value": 405.43}),
                )
            }
        )
        if boundary.variable == "discharge"
        else boundary
        for boundary in source.boundaries
    )

    initial = _boundary_derived_initial_condition(
        source.branches,
        source.cross_sections,
        high_flow_boundaries,
    )

    assert initial is not None
    assert initial.by_section[0].water_level_m > 5.0
    assert initial.by_section[-1].water_level_m > 5.0


def test_full_channel_extension_adds_rebuildable_walls_without_changing_raw_profile() -> None:
    """Derived walls use the hydraulic envelope and preserve source Station/Elevation."""

    source = model_fixture()
    raw_points = source.cross_sections[0].points
    initial = _boundary_derived_initial_condition(
        source.branches,
        source.cross_sections,
        source.boundaries,
    )
    assert initial is not None

    extended, top = _vertical_bank_extended_sections(
        source.cross_sections,
        initial,
        source.boundaries,
    )

    first = extended[0]
    assert first.points[0].station_m == raw_points[0].station_m
    assert first.points[1:-1] == raw_points
    assert first.points[0].elevation_m == top
    assert first.points[-1].station_m == raw_points[-1].station_m
    assert first.points[-1].elevation_m == top
    assert source.cross_sections[0].points == raw_points
    assert top >= max(item.water_level_m for item in initial.by_section) + 1.0


def test_historical_custom_solver_task_is_never_retryable() -> None:
    """Old immutable rows remain auditable but cannot call deleted code."""

    task = SimpleNamespace(
        input_schema_version="dayu.model-input.v3",
        status="failed",
        active_execution_token=None,
    )
    assert retry_block_reason(task).startswith("LEGACY_ENGINE_RETIRED")


def test_registry_names_external_engine_and_reserved_future_adapter() -> None:
    """The Registry contains no internal numerical implementation."""

    registry = engine_registry_payload()
    engine = registry["engines"][0]
    assert engine["engine_id"] == DEFAULT_HYDRAULIC_1D_ENGINE_ID
    assert engine["engine_version"] == DEFAULT_HYDRAULIC_1D_ENGINE_VERSION
    assert registry["reserved"] == ["d-flow-fm"]
    provenance = task_engine_provenance()
    assert provenance["solver_id"] == (
        f"{DEFAULT_HYDRAULIC_1D_ENGINE_ID}-{DEFAULT_HYDRAULIC_1D_ENGINE_VERSION}"
    )


def test_worker_fails_closed_when_frozen_snapshot_digest_drifts() -> None:
    """A mutated persisted snapshot must never reach the external executable."""

    snapshot = model_fixture().model_dump(mode="json")
    task = SimpleNamespace(
        input_snapshot=snapshot,
        input_snapshot_hash=snapshot_hash(snapshot),
    )
    assert parse_frozen_task_model(task).simulation_id == snapshot["simulation_id"]

    snapshot["settings"]["duration_seconds"] = 1200.0
    with pytest.raises(
        Hydraulic1DValidationError,
        match="SNAPSHOT_INTEGRITY_ERROR",
    ):
        parse_frozen_task_model(task)


def test_simulation_identity_changes_with_physical_configuration() -> None:
    """Different duration/settings cannot share one unified simulation identity."""

    source = model_fixture().model_copy(update={"simulation_id": "pending-identity"})
    changed = source.model_copy(
        update={
            "settings": source.settings.model_copy(update={"duration_seconds": 1200.0})
        }
    )

    assert _with_simulation_identity(source).simulation_id != (
        _with_simulation_identity(changed).simulation_id
    )


def test_persistence_rejects_record_identity_and_incomplete_time_axes() -> None:
    """The result envelope cannot hide a wrong Section identity or partial output."""

    model = model_fixture()
    snapshot = model.model_dump(mode="json")
    task = SimpleNamespace(
        input_snapshot=snapshot,
        input_snapshot_hash=snapshot_hash(snapshot),
    )
    records = tuple(
        HydraulicResultRecord(
            simulation_id=model.simulation_id,
            scenario_id=model.scenario_id,
            engine=DEFAULT_HYDRAULIC_1D_ENGINE_ID,
            engine_version=DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
            branch_id=section.branch_id,
            chainage_m=section.chainage_m,
            cross_section_id=section.id,
            timestamp=timestamp,
            water_level_m=2.0,
            depth_m=2.0,
            discharge_m3s=11.0,
            velocity_m_s=1.0,
            flow_area_m2=11.0,
        )
        for timestamp in model.settings.expected_output_times()
        for section in model.cross_sections
    )
    result = HydraulicResult(
        simulation_id=model.simulation_id,
        scenario_id=model.scenario_id,
        engine=DEFAULT_HYDRAULIC_1D_ENGINE_ID,
        engine_version=DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
        records=records,
    )
    _validate_result(task, result)

    wrong_identity = result.model_copy(
        update={
            "records": (
                records[0].model_copy(update={"simulation_id": "another-simulation"}),
                *records[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="record identity"):
        _validate_result(task, wrong_identity)

    incomplete = result.model_copy(update={"records": records[:-1]})
    with pytest.raises(ValueError, match="every Section"):
        _validate_result(task, incomplete)

    truncated = result.model_copy(update={"records": records[:-2]})
    with pytest.raises(ValueError, match="truncated or irregular"):
        _validate_result(task, truncated)
