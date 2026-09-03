"""Synthetic-only tests for dispatch hydraulic asset normalization."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.dispatch.hydraulic_assets import normalize_plan_hydraulic_assets
from model.control.compiler import HydraulicControlCompiler, InitialActuatorState
from model.control.replay import ReplayAsset
from model.control.schedule import ScheduledAction
from model.hydraulic_1d.structures import HydraulicDataStatus


class _ScalarRows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeSession:
    def __init__(self, **rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self, statement: Any) -> _ScalarRows:
        entity = statement.column_descriptions[0]["entity"]
        return _ScalarRows(self._rows.get(entity.__name__, []))


def _plan() -> SimpleNamespace:
    return SimpleNamespace(id=41, dataset_version_id=7, simulation_case_id=73)


def _action(*, asset_id: int, kind: str, command_type: str, sequence: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=100 + sequence,
        plan_id=41,
        sequence=sequence,
        structure_type=kind,
        gate_id=asset_id if kind == "gate" else None,
        pump_id=asset_id if kind == "pump" else None,
        command_type=command_type,
    )


def _gate(asset_id: int, *, coefficient: float | None = 0.72) -> SimpleNamespace:
    return SimpleNamespace(
        id=asset_id,
        dataset_version_id=7,
        gate_type="vertical_underflow_gate",
        width=3.2,
        height=2.4,
        crest_elevation=5.0,
        minimum_opening=0.1,
        maximum_opening=2.0,
        opening_rate_limit=0.2,
        minimum_hold_seconds=5.0,
        discharge_coefficient=coefficient,
        status="online",
    )


def _pump(asset_id: int, *, unit_count: int = 3) -> SimpleNamespace:
    return SimpleNamespace(
        id=asset_id,
        dataset_version_id=7,
        transfer_type="inline_branch",
        intake_node_id=801,
        outlet_node_id=802,
        unit_count=unit_count,
        minimum_running_units=1,
        maximum_running_units=unit_count,
        minimum_run_seconds=30.0,
        minimum_stop_seconds=45.0,
        maximum_starts_per_run=4,
        design_flow=4.0,
        status="online",
        # This legacy Q-H payload must never be consumed as a D-Flow
        # head/reduction-factor curve.
        head_curve={"qh": [[0.0, 8.0], [4.0, 2.0]]},
    )


def _gate_structure(
    legacy_id: int,
    *,
    row_id: int | None = None,
    subtype: str = "vertical_underflow_gate",
    operation_parameters: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=row_id or 1000 + legacy_id,
        dataset_version_id=7,
        network_id=1,
        branch_id=501,
        structure_code=f"gate-{legacy_id}",
        structure_name=f"Synthetic gate {legacy_id}",
        structure_type="gate",
        chainage_m=float(legacy_id),
        crest_elevation_m=5.0,
        width_m=3.2,
        height_m=2.4,
        hydraulic_law_type=subtype,
        hydraulic_parameters={
            "allowed_flow_direction": "both",
            "use_velocity_height": False,
            "maximum_opening_axis": "vertical",
        },
        operation_parameters=operation_parameters or {},
        status="active",
        metadata_json={},
        legacy_gate_id=legacy_id,
        legacy_pump_id=None,
    )


def _pump_structure(legacy_id: int, *, include_curve: bool = True) -> SimpleNamespace:
    parameters: dict[str, Any] = {
        "orientation": "positive",
    }
    if include_curve:
        parameters["head_reduction_curve"] = {
            "provenance": "SYNTHETIC_ASSUMPTION",
            "points": [
                {"head_m": 0.0, "reduction_factor": 1.0},
                {"head_m": 6.0, "reduction_factor": 0.65},
            ],
        }
    return SimpleNamespace(
        id=2000 + legacy_id,
        dataset_version_id=7,
        network_id=1,
        branch_id=501,
        structure_code=f"pump-{legacy_id}",
        structure_name=f"Synthetic pump {legacy_id}",
        structure_type="pump",
        chainage_m=40.0 + legacy_id,
        crest_elevation_m=None,
        width_m=None,
        height_m=None,
        hydraulic_law_type="pump",
        hydraulic_parameters=parameters,
        operation_parameters={},
        status="active",
        metadata_json={},
        legacy_gate_id=None,
        legacy_pump_id=legacy_id,
    )


def _branch() -> SimpleNamespace:
    return SimpleNamespace(
        id=501,
        dataset_version_id=7,
        branch_code="synthetic-branch",
    )


def _gate_state(asset_id: int) -> InitialActuatorState:
    return InitialActuatorState(
        structure_type="gate",
        structure_id=asset_id,
        gate_opening_m=0.8,
        evidence="SYNTHETIC_INITIAL_STATE",
    )


def _pump_state(asset_id: int) -> InitialActuatorState:
    return InitialActuatorState(
        structure_type="pump",
        structure_id=asset_id,
        pump_enabled=False,
        running_units=0,
        stop_seconds=60.0,
        evidence="SYNTHETIC_INITIAL_STATE",
    )


def _session(
    *,
    actions: list[Any],
    gates: list[Any] | None = None,
    pumps: list[Any] | None = None,
    structures: list[Any],
) -> _FakeSession:
    return _FakeSession(
        DispatchAction=actions,
        DispatchRule=[],
        Gate=gates or [],
        Pump=pumps or [],
        HydraulicStructure=structures,
        HydraulicStructureScenario=[],
        HydraulicBranch=[_branch()],
    )


def test_successful_fixture_builds_typed_specs_and_exact_bmi_bindings() -> None:
    gate_id, pump_id = 11, 22
    session = _session(
        actions=[
            _action(
                asset_id=pump_id,
                kind="pump",
                command_type="pump_target_flow",
                sequence=2,
            ),
            _action(
                asset_id=gate_id,
                kind="gate",
                command_type="gate_opening_m",
                sequence=1,
            ),
        ],
        gates=[_gate(gate_id)],
        pumps=[_pump(pump_id)],
        structures=[_pump_structure(pump_id), _gate_structure(gate_id)],
    )

    result = normalize_plan_hydraulic_assets(
        session, _plan(), (_pump_state(pump_id), _gate_state(gate_id))
    )

    assert result.ready is True
    assert [item.structure_id for item in result.gate_specs] == ["gate-11"]
    assert [item.structure_id for item in result.pump_specs] == ["pump-22"]
    assert [item.bmi_variable for item in result.control_bindings] == [
        "orifices/gate-11/gateLowerEdgeLevel",
        "pumps/pump-22/capacity",
    ]
    assert [item.structure_id for item in result.control_assets] == [gate_id, pump_id]
    assert result.control_assets[0].constraints["maximum_opening_m"] == 2.0
    assert result.gate_specs[0].opening_m.status == HydraulicDataStatus.SYNTHETIC_ASSUMPTION
    assert (
        result.pump_specs[0].head_reduction_curve.status == HydraulicDataStatus.SYNTHETIC_ASSUMPTION
    )


def test_missing_gate_coefficient_stays_unknown_and_blocks_mapping() -> None:
    gate_id = 12
    result = normalize_plan_hydraulic_assets(
        _session(
            actions=[
                _action(
                    asset_id=gate_id,
                    kind="gate",
                    command_type="gate_opening_m",
                    sequence=1,
                )
            ],
            gates=[_gate(gate_id, coefficient=None)],
            structures=[_gate_structure(gate_id)],
        ),
        _plan(),
        (_gate_state(gate_id),),
    )

    assert result.ready is False
    assert result.gate_specs[0].correction_coefficient.status == HydraulicDataStatus.UNKNOWN
    assert "GATE_COEFFICIENT_UNKNOWN" in {item.code for item in result.issues}
    assert result.control_bindings == ()


def test_unknown_gate_subtype_is_preserved_but_never_bound() -> None:
    gate_id = 13
    result = normalize_plan_hydraulic_assets(
        _session(
            actions=[
                _action(
                    asset_id=gate_id,
                    kind="gate",
                    command_type="gate_opening_m",
                    sequence=1,
                )
            ],
            gates=[_gate(gate_id)],
            structures=[_gate_structure(gate_id, subtype="radial_gate")],
        ),
        _plan(),
        (_gate_state(gate_id),),
    )

    assert result.gate_specs[0].gate_subtype == "radial_gate"
    assert "GATE_SUBTYPE_UNSUPPORTED" in {item.code for item in result.issues}
    assert result.control_bindings == ()


def test_missing_named_pump_curve_does_not_consume_legacy_qh_curve() -> None:
    pump_id = 23
    result = normalize_plan_hydraulic_assets(
        _session(
            actions=[
                _action(
                    asset_id=pump_id,
                    kind="pump",
                    command_type="pump_target_flow",
                    sequence=1,
                )
            ],
            pumps=[_pump(pump_id)],
            structures=[_pump_structure(pump_id, include_curve=False)],
        ),
        _plan(),
        (_pump_state(pump_id),),
    )

    assert result.pump_specs[0].head_reduction_curve.status == HydraulicDataStatus.UNKNOWN
    assert "PUMP_HEAD_REDUCTION_CURVE_UNKNOWN" in {item.code for item in result.issues}
    assert result.control_bindings == ()


def test_legacy_design_flow_is_aggregate_and_unit_count_is_not_a_multiplier() -> None:
    pump_id = 24
    result = normalize_plan_hydraulic_assets(
        _session(
            actions=[
                _action(
                    asset_id=pump_id,
                    kind="pump",
                    command_type="pump_target_flow",
                    sequence=1,
                )
            ],
            pumps=[_pump(pump_id, unit_count=3)],
            structures=[_pump_structure(pump_id)],
        ),
        _plan(),
        (_pump_state(pump_id),),
    )

    spec = result.pump_specs[0]
    assert spec.unit_count == 3
    assert spec.aggregate_capacity_m3s.value == 4.0
    assert spec.aggregate_capacity_m3s.evidence == "pump[24].design_flow"
    assert spec.capacity_is_actual_discharge is False


def test_v3_control_constraints_use_the_same_override_as_gate_spec() -> None:
    gate_id = 25
    result = normalize_plan_hydraulic_assets(
        _session(
            actions=[
                _action(
                    asset_id=gate_id,
                    kind="gate",
                    command_type="gate_opening_m",
                    sequence=1,
                )
            ],
            gates=[_gate(gate_id)],
            structures=[
                _gate_structure(
                    gate_id,
                    operation_parameters={"maximum_opening_m": 1.0},
                )
            ],
        ),
        _plan(),
        (_gate_state(gate_id),),
    )

    assert result.ready is True
    assert result.gate_specs[0].maximum_opening_m.value == 1.0
    assert result.control_assets[0].constraints["maximum_opening_m"] == 1.0
    assert (
        "operation_parameters.maximum_opening_m"
        in (result.control_assets[0].provenance["maximum_opening_m"])
    )
    compiled = HydraulicControlCompiler().compile(
        actions=(
            ScheduledAction(
                id=701,
                time_seconds=10.0,
                structure_type="gate",
                structure_id=gate_id,
                command_type="gate_opening_m",
                target_value=1.5,
                interpolation="step",
                priority=1,
            ),
        ),
        assets=(
            ReplayAsset(
                structure_type="gate",
                structure_id=gate_id,
                constraints=dict(result.control_assets[0].constraints),
            ),
        ),
        initial_states=(_gate_state(gate_id),),
        bindings=result.control_bindings,
        duration_seconds=60.0,
    )
    assert compiled.status == "UNSUPPORTED"
    assert {item.code for item in compiled.issues} == {"CONTROL_CONSTRAINT_REJECTED"}
    assert compiled.commands == ()


def test_missing_operating_limit_is_not_defaulted_for_hydraulic_v3() -> None:
    gate_id = 26
    gate = _gate(gate_id)
    gate.opening_rate_limit = None
    result = normalize_plan_hydraulic_assets(
        _session(
            actions=[
                _action(
                    asset_id=gate_id,
                    kind="gate",
                    command_type="gate_opening_m",
                    sequence=1,
                )
            ],
            gates=[gate],
            structures=[_gate_structure(gate_id)],
        ),
        _plan(),
        (_gate_state(gate_id),),
    )

    assert result.ready is False
    assert result.control_assets == ()
    assert "CONTROL_CONSTRAINT_UNKNOWN" in {item.code for item in result.issues}


def test_specs_and_issues_are_stable_when_database_rows_are_unsorted() -> None:
    first_id, second_id = 3, 20
    actions = [
        _action(
            asset_id=second_id,
            kind="gate",
            command_type="gate_opening_m",
            sequence=2,
        ),
        _action(
            asset_id=first_id,
            kind="gate",
            command_type="gate_opening_m",
            sequence=1,
        ),
    ]
    first = normalize_plan_hydraulic_assets(
        _session(
            actions=actions,
            gates=[_gate(second_id), _gate(first_id)],
            structures=[_gate_structure(second_id), _gate_structure(first_id)],
        ),
        _plan(),
        (_gate_state(second_id), _gate_state(first_id)),
    )
    second = normalize_plan_hydraulic_assets(
        _session(
            actions=list(reversed(actions)),
            gates=[_gate(first_id), _gate(second_id)],
            structures=[_gate_structure(first_id), _gate_structure(second_id)],
        ),
        _plan(),
        (_gate_state(first_id), _gate_state(second_id)),
    )

    expected = ["gate-3", "gate-20"]
    assert [item.structure_id for item in first.gate_specs] == expected
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
