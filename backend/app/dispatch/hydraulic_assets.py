"""Normalize dispatch Gate/Pump rows into fail-closed hydraulic contracts.

This module is the only backend boundary that combines legacy dispatch assets,
the unified hydraulic structure row, scenario overrides, and an explicit initial
actuator state.  It deliberately does not invent solver defaults or reinterpret a
legacy Pump Q-H curve as a D-Flow head/reduction curve.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.dispatch.assets import AssetKey, dispatch_asset_keys
from app.gis.models import DispatchAction, DispatchPlan, DispatchRule, Gate, Pump
from app.hydraulic.models import (
    HydraulicBranch,
    HydraulicStructure,
    HydraulicStructureScenario,
)
from model.control.compiler import ActuatorControlBinding, InitialActuatorState
from model.hydraulic_1d.structures import (
    GateHydraulicSpec,
    GateOpeningHorizontalDirection,
    GeneralOpeningCoefficients,
    GeneralOpeningGeometry,
    HydraulicDataStatus,
    PumpControlMode,
    PumpHeadReductionCurve,
    PumpHeadReductionPoint,
    PumpHydraulicSpec,
    PumpOrientation,
    PumpTransferType,
    SourcedHydraulicBoolean,
    SourcedHydraulicScalar,
    StructureFlowDirection,
)


class HydraulicAssetMappingIssue(BaseModel):
    """One deterministic blocker found while freezing a dispatch hydraulic asset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=96)
    message: str = Field(min_length=1, max_length=512)
    structure_type: Literal["gate", "pump"] | None = None
    legacy_asset_id: int | None = Field(default=None, gt=0)
    hydraulic_structure_id: int | None = Field(default=None, gt=0)
    field_path: str | None = Field(default=None, min_length=1, max_length=512)
    blocking: bool = True


class HydraulicControlAsset(BaseModel):
    """Freeze one strict v3 actuator constraint record and every value source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    structure_type: Literal["gate", "pump"]
    structure_id: int = Field(gt=0)
    constraints: dict[str, str | int | float | bool]
    provenance: dict[str, str]

    @model_validator(mode="after")
    def validate_complete_constraint_authority(self) -> "HydraulicControlAsset":
        """Reject extra, missing, or unproven v3 operating constraints."""

        expected = (
            {
                "availability",
                "height_m",
                "minimum_opening_m",
                "maximum_opening_m",
                "opening_rate_limit_m_per_s",
                "minimum_hold_seconds",
            }
            if self.structure_type == "gate"
            else {
                "availability",
                "unit_count",
                "minimum_running_units",
                "maximum_running_units",
                "design_flow_capacity_m3s",
                "minimum_run_seconds",
                "minimum_stop_seconds",
                "maximum_starts_per_replay",
            }
        )
        if set(self.constraints) != expected:
            raise ValueError("hydraulic v3 control constraints must be complete")
        if set(self.provenance) != expected or not all(self.provenance.values()):
            raise ValueError("every hydraulic v3 control constraint requires provenance")
        availability = self.constraints["availability"]
        if availability not in {"online", "offline", "maintenance", "fault"}:
            raise ValueError("hydraulic v3 availability is invalid")

        def number(field_name: str) -> float:
            value = self.constraints[field_name]
            if isinstance(value, bool):
                raise ValueError(f"{field_name} must not be boolean")
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field_name} must be numeric") from exc
            if not isfinite(numeric):
                raise ValueError(f"{field_name} must be finite")
            return numeric

        if self.structure_type == "gate":
            height = number("height_m")
            minimum = number("minimum_opening_m")
            maximum = number("maximum_opening_m")
            rate = number("opening_rate_limit_m_per_s")
            hold = number("minimum_hold_seconds")
            if not (height > 0 and 0 <= minimum <= maximum <= height):
                raise ValueError("hydraulic v3 Gate opening constraints are invalid")
            if rate < 0 or hold < 0:
                raise ValueError("hydraulic v3 Gate rate/hold constraints are invalid")
            return self

        integer_fields = (
            "unit_count",
            "minimum_running_units",
            "maximum_running_units",
            "maximum_starts_per_replay",
        )
        integer_values = {field: number(field) for field in integer_fields}
        if any(not value.is_integer() for value in integer_values.values()):
            raise ValueError("hydraulic v3 Pump count constraints must be integers")
        units = int(integer_values["unit_count"])
        minimum_units = int(integer_values["minimum_running_units"])
        maximum_units = int(integer_values["maximum_running_units"])
        starts = int(integer_values["maximum_starts_per_replay"])
        if not (units > 0 and 0 <= minimum_units <= maximum_units <= units):
            raise ValueError("hydraulic v3 Pump unit constraints are invalid")
        if (
            starts < 0
            or number("design_flow_capacity_m3s") < 0
            or number("minimum_run_seconds") < 0
            or number("minimum_stop_seconds") < 0
        ):
            raise ValueError("hydraulic v3 Pump operating constraints are invalid")
        return self


class HydraulicAssetNormalization(BaseModel):
    """Immutable, stable-order inputs for the solver adapter and control compiler."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_specs: tuple[GateHydraulicSpec, ...] = ()
    pump_specs: tuple[PumpHydraulicSpec, ...] = ()
    control_assets: tuple[HydraulicControlAsset, ...] = ()
    control_bindings: tuple[ActuatorControlBinding, ...] = ()
    issues: tuple[HydraulicAssetMappingIssue, ...] = ()

    @property
    def ready(self) -> bool:
        """Return true only when every asset can enter the audited mapper."""

        return not any(issue.blocking for issue in self.issues)


@dataclass(frozen=True)
class _ParameterSource:
    values: Mapping[str, Any]
    evidence_prefix: str
    synthetic: bool


@dataclass(frozen=True)
class _LocatedValue:
    value: Any
    evidence: str
    status: HydraulicDataStatus
    invalid_provenance: str | None = None


_GENERAL_GEOMETRY_FIELDS = (
    "upstream_1_width_m",
    "upstream_1_level_m",
    "upstream_2_width_m",
    "upstream_2_level_m",
    "crest_length_m",
    "downstream_1_width_m",
    "downstream_1_level_m",
    "downstream_2_width_m",
    "downstream_2_level_m",
    "gate_lower_edge_level_m",
    "gate_height_m",
    "gate_opening_width_m",
)
_GENERAL_COEFFICIENT_FIELDS = tuple(GeneralOpeningCoefficients.model_fields)
_SUPPORTED_GATE_SUBTYPES = {"vertical_underflow_gate", "general_opening"}


def normalize_plan_hydraulic_assets(
    session: Session,
    plan: DispatchPlan,
    initial_states: Iterable[InitialActuatorState],
) -> HydraulicAssetNormalization:
    """Query and freeze every Gate/Pump referenced by a dispatch plan.

    Unknown engineering values remain UNKNOWN and produce blocking issues.  The
    returned partial specs are useful for QA, but callers must check ``ready``
    before invoking a solver adapter or the hydraulic control compiler.
    """

    actions = list(
        session.scalars(
            select(DispatchAction)
            .where(DispatchAction.plan_id == plan.id)
            .order_by(DispatchAction.sequence, DispatchAction.id)
        ).all()
    )
    rules = list(
        session.scalars(
            select(DispatchRule).where(DispatchRule.plan_id == plan.id).order_by(DispatchRule.id)
        ).all()
    )
    # Keep the Python-side filter as a defensive boundary for test doubles and
    # accidentally reused ORM collections.
    actions = [item for item in actions if item.plan_id == plan.id]
    rules = [item for item in rules if item.plan_id == plan.id]
    keys = dispatch_asset_keys(actions, rules)

    gate_ids = [asset_id for kind, asset_id in keys if kind == "gate"]
    pump_ids = [asset_id for kind, asset_id in keys if kind == "pump"]
    gates = _load_legacy_rows(session, Gate, gate_ids, plan.dataset_version_id)
    pumps = _load_legacy_rows(session, Pump, pump_ids, plan.dataset_version_id)

    mapping_filters = []
    if gate_ids:
        mapping_filters.append(HydraulicStructure.legacy_gate_id.in_(gate_ids))
    if pump_ids:
        mapping_filters.append(HydraulicStructure.legacy_pump_id.in_(pump_ids))
    structures: list[HydraulicStructure] = []
    if mapping_filters:
        structures = list(
            session.scalars(
                select(HydraulicStructure)
                .where(
                    HydraulicStructure.dataset_version_id == plan.dataset_version_id,
                    or_(*mapping_filters),
                )
                .order_by(HydraulicStructure.id)
            ).all()
        )
        structures = [
            row for row in structures if row.dataset_version_id == plan.dataset_version_id
        ]

    structure_ids = sorted({int(row.id) for row in structures})
    scenarios: list[HydraulicStructureScenario] = []
    if structure_ids:
        scenarios = list(
            session.scalars(
                select(HydraulicStructureScenario)
                .where(
                    HydraulicStructureScenario.dataset_version_id == plan.dataset_version_id,
                    HydraulicStructureScenario.case_id == plan.simulation_case_id,
                    HydraulicStructureScenario.structure_id.in_(structure_ids),
                )
                .order_by(HydraulicStructureScenario.structure_id)
            ).all()
        )
        scenarios = [
            row
            for row in scenarios
            if row.dataset_version_id == plan.dataset_version_id
            and row.case_id == plan.simulation_case_id
        ]

    branch_ids = sorted({int(row.branch_id) for row in structures})
    branches: list[HydraulicBranch] = []
    if branch_ids:
        branches = list(
            session.scalars(
                select(HydraulicBranch)
                .where(
                    HydraulicBranch.dataset_version_id == plan.dataset_version_id,
                    HydraulicBranch.id.in_(branch_ids),
                )
                .order_by(HydraulicBranch.id)
            ).all()
        )
        branches = [row for row in branches if row.dataset_version_id == plan.dataset_version_id]

    return _normalize_loaded_assets(
        plan=plan,
        actions=actions,
        rules=rules,
        keys=keys,
        gates=gates,
        pumps=pumps,
        structures=structures,
        scenarios=scenarios,
        branches=branches,
        initial_states=tuple(initial_states),
    )


def _load_legacy_rows(
    session: Session,
    model: type[Gate] | type[Pump],
    ids: list[int],
    dataset_version_id: int,
) -> list[Gate] | list[Pump]:
    if not ids:
        return []
    rows = list(
        session.scalars(
            select(model)
            .where(
                model.dataset_version_id == dataset_version_id,
                model.id.in_(ids),
            )
            .order_by(model.id)
        ).all()
    )
    return [row for row in rows if row.dataset_version_id == dataset_version_id]


def _normalize_loaded_assets(
    *,
    plan: DispatchPlan,
    actions: Iterable[DispatchAction],
    rules: Iterable[DispatchRule],
    keys: tuple[AssetKey, ...],
    gates: Iterable[Gate],
    pumps: Iterable[Pump],
    structures: Iterable[HydraulicStructure],
    scenarios: Iterable[HydraulicStructureScenario],
    branches: Iterable[HydraulicBranch],
    initial_states: tuple[InitialActuatorState, ...],
) -> HydraulicAssetNormalization:
    issues: list[HydraulicAssetMappingIssue] = []
    specs_gate: list[tuple[AssetKey, GateHydraulicSpec]] = []
    specs_pump: list[tuple[AssetKey, PumpHydraulicSpec]] = []
    control_assets: list[tuple[AssetKey, HydraulicControlAsset]] = []
    bindings: list[ActuatorControlBinding] = []

    legacy_rows: dict[AssetKey, list[Gate | Pump]] = defaultdict(list)
    for row in gates:
        legacy_rows[("gate", int(row.id))].append(row)
    for row in pumps:
        legacy_rows[("pump", int(row.id))].append(row)

    mapped_rows: dict[AssetKey, list[HydraulicStructure]] = defaultdict(list)
    for row in structures:
        if row.legacy_gate_id is not None:
            mapped_rows[("gate", int(row.legacy_gate_id))].append(row)
        if row.legacy_pump_id is not None:
            mapped_rows[("pump", int(row.legacy_pump_id))].append(row)

    scenario_rows: dict[int, list[HydraulicStructureScenario]] = defaultdict(list)
    for row in scenarios:
        scenario_rows[int(row.structure_id)].append(row)
    branch_rows: dict[int, list[HydraulicBranch]] = defaultdict(list)
    for row in branches:
        branch_rows[int(row.id)].append(row)
    state_rows: dict[AssetKey, list[InitialActuatorState]] = defaultdict(list)
    for state in initial_states:
        state_rows[(state.structure_type, state.structure_id)].append(state)

    command_types = _command_types(actions, rules)
    for state_key in sorted(set(state_rows) - set(keys)):
        _add_issue(
            issues,
            "INITIAL_ACTUATOR_STATE_UNKNOWN",
            "initial state references an actuator absent from this dispatch plan",
            state_key,
            field_path="initial_states",
        )

    for key in keys:
        issue_start = len(issues)
        legacy_matches = legacy_rows.get(key, [])
        if len(legacy_matches) != 1:
            _add_issue(
                issues,
                "DISPATCH_ASSET_MISSING" if not legacy_matches else "DISPATCH_ASSET_DUPLICATE",
                "legacy asset must exist exactly once in the plan dataset version",
                key,
                field_path=f"{key[0]}[{key[1]}]",
            )
            continue
        legacy = legacy_matches[0]

        unified_matches = mapped_rows.get(key, [])
        if len(unified_matches) != 1:
            _add_issue(
                issues,
                "HYDRAULIC_STRUCTURE_MAPPING",
                "legacy asset must map to exactly one unified HydraulicStructure",
                key,
                field_path=f"hydraulic_structure.legacy_{key[0]}_id",
            )
            continue
        unified = unified_matches[0]
        if unified.structure_type != key[0] or unified.status != "active":
            _add_issue(
                issues,
                "HYDRAULIC_STRUCTURE_STATE",
                "unified structure type must match and its base status must be active",
                key,
                unified,
                "hydraulic_structure.structure_type/status",
            )
            continue

        scenario_matches = scenario_rows.get(int(unified.id), [])
        if len(scenario_matches) > 1:
            _add_issue(
                issues,
                "HYDRAULIC_SCENARIO_DUPLICATE",
                "a structure may have at most one override for the plan simulation case",
                key,
                unified,
                "hydraulic_structure_scenario",
            )
            continue
        scenario = scenario_matches[0] if scenario_matches else None
        if scenario is not None and scenario.status_override not in {None, "active"}:
            _add_issue(
                issues,
                "HYDRAULIC_STRUCTURE_SCENARIO_INACTIVE",
                "the plan scenario explicitly disables this hydraulic structure",
                key,
                unified,
                "hydraulic_structure_scenario.status_override",
            )
            continue

        branch_matches = branch_rows.get(int(unified.branch_id), [])
        if len(branch_matches) != 1:
            _add_issue(
                issues,
                "HYDRAULIC_BRANCH_MAPPING",
                "unified structure must reference exactly one branch in the plan dataset",
                key,
                unified,
                "hydraulic_structure.branch_id",
            )
            continue
        branch = branch_matches[0]

        states = state_rows.get(key, [])
        state = states[0] if len(states) == 1 else None
        if len(states) != 1:
            _add_issue(
                issues,
                "INITIAL_ACTUATOR_STATE_MISSING"
                if not states
                else "INITIAL_ACTUATOR_STATE_DUPLICATE",
                "each hydraulic actuator requires exactly one explicit initial state",
                key,
                unified,
                "initial_states",
            )

        hydraulic_sources, operation_sources = _parameter_sources(unified, scenario)
        if key[0] == "gate":
            spec = _gate_spec(
                legacy,
                unified,
                branch,
                state,
                hydraulic_sources,
                operation_sources,
                issues,
            )
            if spec is not None:
                specs_gate.append((key, spec))
                control_asset = _gate_control_asset(
                    legacy,
                    unified,
                    spec,
                    operation_sources,
                    issues,
                )
                if control_asset is not None:
                    control_assets.append((key, control_asset))
                if len(issues) == issue_start:
                    bindings.extend(
                        _gate_bindings(
                            key,
                            spec,
                            legacy,
                            unified,
                            command_types.get(key, ()),
                            issues,
                        )
                    )
        else:
            spec = _pump_spec(
                legacy,
                unified,
                branch,
                hydraulic_sources,
                operation_sources,
                issues,
            )
            if spec is not None:
                specs_pump.append((key, spec))
                control_asset = _pump_control_asset(
                    legacy,
                    unified,
                    spec,
                    operation_sources,
                    issues,
                )
                if control_asset is not None:
                    control_assets.append((key, control_asset))
                if len(issues) == issue_start:
                    bindings.extend(_pump_bindings(key, spec, command_types.get(key, ()), issues))

    issues.sort(
        key=lambda item: (
            item.structure_type or "",
            item.legacy_asset_id or 0,
            item.code,
            item.field_path or "",
            item.message,
        )
    )
    bindings.sort(
        key=lambda item: (
            item.structure_type,
            item.structure_id,
            item.supported_command_type,
        )
    )
    return HydraulicAssetNormalization(
        gate_specs=tuple(spec for _, spec in sorted(specs_gate, key=lambda item: item[0])),
        pump_specs=tuple(spec for _, spec in sorted(specs_pump, key=lambda item: item[0])),
        control_assets=tuple(
            asset for _, asset in sorted(control_assets, key=lambda item: item[0])
        ),
        control_bindings=tuple(bindings),
        issues=tuple(issues),
    )


def _command_types(
    actions: Iterable[DispatchAction], rules: Iterable[DispatchRule]
) -> dict[AssetKey, tuple[str, ...]]:
    values: dict[AssetKey, set[str]] = defaultdict(set)
    for action in actions:
        asset_id = action.gate_id if action.structure_type == "gate" else action.pump_id
        if asset_id is not None:
            values[(action.structure_type, int(asset_id))].add(str(action.command_type))
    for rule in rules:
        template = rule.action_template
        if not isinstance(template, dict):
            continue
        kind = template.get("structure_type")
        asset_id = template.get("structure_id")
        command_type = template.get("command_type")
        if kind in {"gate", "pump"} and isinstance(asset_id, int) and isinstance(command_type, str):
            values[(kind, asset_id)].add(command_type)
    return {key: tuple(sorted(item)) for key, item in values.items()}


def _parameter_sources(
    unified: HydraulicStructure,
    scenario: HydraulicStructureScenario | None,
) -> tuple[tuple[_ParameterSource, ...], tuple[_ParameterSource, ...]]:
    hydraulic: list[_ParameterSource] = []
    operation: list[_ParameterSource] = []
    if scenario is not None:
        synthetic = _explicitly_synthetic(scenario.metadata_json)
        hydraulic.append(
            _ParameterSource(
                scenario.hydraulic_parameters_override or {},
                f"hydraulic_structure_scenario[{scenario.id}].hydraulic_parameters_override",
                synthetic,
            )
        )
        operation.append(
            _ParameterSource(
                scenario.operation_parameters_override or {},
                f"hydraulic_structure_scenario[{scenario.id}].operation_parameters_override",
                synthetic,
            )
        )
    synthetic = _explicitly_synthetic(unified.metadata_json)
    hydraulic.append(
        _ParameterSource(
            unified.hydraulic_parameters or {},
            f"hydraulic_structure[{unified.id}].hydraulic_parameters",
            synthetic,
        )
    )
    operation.append(
        _ParameterSource(
            unified.operation_parameters or {},
            f"hydraulic_structure[{unified.id}].operation_parameters",
            synthetic,
        )
    )
    return tuple(hydraulic), tuple(operation)


def _explicitly_synthetic(metadata: Any) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    if metadata.get("synthetic_fixture") is True or metadata.get("synthetic") is True:
        return True
    classification = metadata.get("data_classification")
    return isinstance(classification, str) and classification.upper() in {
        "SYNTHETIC",
        "SYNTHETIC_ASSUMPTION",
        "DEMO",
    }


def _located_parameter(
    sources: Iterable[_ParameterSource], field_name: str
) -> _LocatedValue | None:
    for source in sources:
        if field_name not in source.values:
            continue
        raw = source.values[field_name]
        status = (
            HydraulicDataStatus.SYNTHETIC_ASSUMPTION
            if source.synthetic
            else HydraulicDataStatus.SOURCE_DATA
        )
        invalid: str | None = None
        value = raw
        if isinstance(raw, Mapping) and ({"value", "status", "provenance"} & set(raw)):
            value = raw.get("value")
            declared = raw.get("provenance", raw.get("status"))
            if declared is not None:
                try:
                    status = HydraulicDataStatus(str(declared).upper())
                except ValueError:
                    invalid = str(declared)
        return _LocatedValue(value, f"{source.evidence_prefix}.{field_name}", status, invalid)
    return None


def _database_value(value: Any, evidence: str, *, synthetic: bool = False) -> _LocatedValue:
    return _LocatedValue(
        value,
        evidence,
        HydraulicDataStatus.SYNTHETIC_ASSUMPTION if synthetic else HydraulicDataStatus.SOURCE_DATA,
    )


def _scalar(
    located: _LocatedValue | None,
    *,
    issues: list[HydraulicAssetMappingIssue],
    code: str,
    message: str,
    key: AssetKey,
    unified: HydraulicStructure,
    field_path: str,
) -> SourcedHydraulicScalar:
    if located is None or located.status == HydraulicDataStatus.UNKNOWN or located.value is None:
        _add_issue(issues, code, message, key, unified, field_path)
        return SourcedHydraulicScalar()
    if located.invalid_provenance is not None:
        _add_issue(
            issues,
            "HYDRAULIC_PROVENANCE_INVALID",
            f"unsupported provenance {located.invalid_provenance!r}",
            key,
            unified,
            located.evidence,
        )
        return SourcedHydraulicScalar()
    if isinstance(located.value, bool):
        value: float | None = None
    else:
        try:
            value = float(located.value)
        except (TypeError, ValueError):
            value = None
    if value is None or not isfinite(value):
        _add_issue(
            issues,
            "HYDRAULIC_VALUE_INVALID",
            f"{field_path} must be a finite number",
            key,
            unified,
            located.evidence,
        )
        return SourcedHydraulicScalar()
    if located.status == HydraulicDataStatus.SYNTHETIC_ASSUMPTION:
        return SourcedHydraulicScalar.synthetic(value, located.evidence)
    return SourcedHydraulicScalar.source_data(value, located.evidence)


def _boolean(
    located: _LocatedValue | None,
    *,
    issues: list[HydraulicAssetMappingIssue],
    code: str,
    message: str,
    key: AssetKey,
    unified: HydraulicStructure,
    field_path: str,
) -> SourcedHydraulicBoolean:
    if located is None or located.status == HydraulicDataStatus.UNKNOWN or located.value is None:
        _add_issue(issues, code, message, key, unified, field_path)
        return SourcedHydraulicBoolean()
    if located.invalid_provenance is not None or not isinstance(located.value, bool):
        _add_issue(
            issues,
            "HYDRAULIC_VALUE_INVALID",
            f"{field_path} must be an explicitly sourced boolean",
            key,
            unified,
            located.evidence,
        )
        return SourcedHydraulicBoolean()
    if located.status == HydraulicDataStatus.SYNTHETIC_ASSUMPTION:
        return SourcedHydraulicBoolean.synthetic(located.value, located.evidence)
    return SourcedHydraulicBoolean.source_data(located.value, located.evidence)


def _plain_value(located: _LocatedValue | None) -> Any:
    if located is None or located.status == HydraulicDataStatus.UNKNOWN:
        return None
    if located.invalid_provenance is not None:
        return None
    return located.value


def _legacy_or_operation_value(
    operation_sources: tuple[_ParameterSource, ...],
    field_name: str,
    legacy: Gate | Pump,
    legacy_attribute: str,
) -> _LocatedValue | None:
    """Locate an explicit v3 operating limit without manufacturing a fallback."""

    located = _located_parameter(operation_sources, field_name)
    legacy_value = getattr(legacy, legacy_attribute, None)
    if located is None and legacy_value is not None:
        entity = "gate" if getattr(legacy, "gate_type", None) is not None else "pump"
        return _database_value(
            legacy_value,
            f"{entity}[{legacy.id}].{legacy_attribute}",
        )
    return located


def _control_number(
    located: _LocatedValue | None,
    *,
    key: AssetKey,
    unified: HydraulicStructure,
    field_name: str,
    issues: list[HydraulicAssetMappingIssue],
    minimum: float = 0.0,
    integer: bool = False,
) -> tuple[float | int, str] | None:
    """Parse one sourced operating value and preserve its exact provenance."""

    if located is None or located.status == HydraulicDataStatus.UNKNOWN or located.value is None:
        _add_issue(
            issues,
            "CONTROL_CONSTRAINT_UNKNOWN",
            f"{field_name} must be explicitly sourced for hydraulic v3",
            key,
            unified,
            field_name,
        )
        return None
    if located.invalid_provenance is not None or isinstance(located.value, bool):
        _add_issue(
            issues,
            "CONTROL_CONSTRAINT_INVALID",
            f"{field_name} has invalid value or provenance",
            key,
            unified,
            located.evidence,
        )
        return None
    try:
        numeric = float(located.value)
    except (TypeError, ValueError):
        numeric = float("nan")
    if not isfinite(numeric) or numeric < minimum or (integer and not numeric.is_integer()):
        kind = "integer" if integer else "finite number"
        _add_issue(
            issues,
            "CONTROL_CONSTRAINT_INVALID",
            f"{field_name} must be a {kind} greater than or equal to {minimum:g}",
            key,
            unified,
            located.evidence,
        )
        return None
    value: float | int = int(numeric) if integer else numeric
    provenance = f"{located.status.value}:{located.evidence}"
    return value, provenance


def _known_scalar_location(value: SourcedHydraulicScalar) -> _LocatedValue | None:
    """Convert a normalized sourced scalar back into a generic located value."""

    if value.value is None or value.evidence is None:
        return None
    return _LocatedValue(value.value, value.evidence, value.status)


def _gate_control_asset(
    legacy: Gate | Pump,
    unified: HydraulicStructure,
    spec: GateHydraulicSpec,
    operation_sources: tuple[_ParameterSource, ...],
    issues: list[HydraulicAssetMappingIssue],
) -> HydraulicControlAsset | None:
    """Build Gate replay limits from the same normalized authority as D-Flow."""

    key: AssetKey = ("gate", int(legacy.id))
    if spec.general_geometry is not None:
        height_location = _known_scalar_location(spec.general_geometry.gate_height_m)
    elif unified.height_m is not None:
        height_location = _database_value(
            unified.height_m,
            f"hydraulic_structure[{unified.id}].height_m",
            synthetic=_explicitly_synthetic(unified.metadata_json),
        )
    elif getattr(legacy, "height", None) is not None:
        height_location = _database_value(
            legacy.height,
            f"gate[{legacy.id}].height",
        )
    else:
        height_location = None
    located = {
        "height_m": height_location,
        "minimum_opening_m": _legacy_or_operation_value(
            operation_sources,
            "minimum_opening_m",
            legacy,
            "minimum_opening",
        ),
        "maximum_opening_m": _known_scalar_location(spec.maximum_opening_m),
        "opening_rate_limit_m_per_s": _legacy_or_operation_value(
            operation_sources,
            "opening_rate_limit_m_per_s",
            legacy,
            "opening_rate_limit",
        ),
        "minimum_hold_seconds": _legacy_or_operation_value(
            operation_sources,
            "minimum_hold_seconds",
            legacy,
            "minimum_hold_seconds",
        ),
    }
    values: dict[str, str | int | float | bool] = {}
    provenance: dict[str, str] = {}
    for field_name, location in located.items():
        parsed = _control_number(
            location,
            key=key,
            unified=unified,
            field_name=field_name,
            issues=issues,
            minimum=(1.0e-12 if field_name == "height_m" else 0.0),
        )
        if parsed is not None:
            values[field_name], provenance[field_name] = parsed
    status = getattr(legacy, "status", None)
    if status not in {"online", "offline", "maintenance", "fault"}:
        _add_issue(
            issues,
            "CONTROL_CONSTRAINT_UNKNOWN",
            "Gate availability status must be explicitly sourced",
            key,
            unified,
            "availability",
        )
    else:
        values["availability"] = status
        provenance["availability"] = f"SOURCE_DATA:gate[{legacy.id}].status"
    if len(values) != 6:
        return None
    minimum_opening = float(values["minimum_opening_m"])
    maximum_opening = float(values["maximum_opening_m"])
    height = float(values["height_m"])
    if minimum_opening > maximum_opening or maximum_opening > height:
        _add_issue(
            issues,
            "CONTROL_CONSTRAINT_INVALID",
            "Gate opening limits must satisfy 0 <= minimum <= maximum <= height",
            key,
            unified,
            "minimum_opening_m/maximum_opening_m/height_m",
        )
        return None
    return HydraulicControlAsset(
        structure_type="gate",
        structure_id=key[1],
        constraints=values,
        provenance=provenance,
    )


def _pump_control_asset(
    legacy: Gate | Pump,
    unified: HydraulicStructure,
    spec: PumpHydraulicSpec,
    operation_sources: tuple[_ParameterSource, ...],
    issues: list[HydraulicAssetMappingIssue],
) -> HydraulicControlAsset | None:
    """Build Pump replay limits from the same normalized authority as D-Flow."""

    key: AssetKey = ("pump", int(legacy.id))
    unit_location = _located_parameter(operation_sources, "unit_count")
    if unit_location is None and getattr(legacy, "unit_count", None) is not None:
        unit_location = _database_value(
            legacy.unit_count,
            f"pump[{legacy.id}].unit_count",
        )
    starts_location = _located_parameter(
        operation_sources,
        "maximum_starts_per_replay",
    )
    if starts_location is None:
        starts_location = _legacy_or_operation_value(
            operation_sources,
            "maximum_starts_per_run",
            legacy,
            "maximum_starts_per_run",
        )
    located: dict[str, _LocatedValue | None] = {
        "unit_count": unit_location,
        "minimum_running_units": _legacy_or_operation_value(
            operation_sources,
            "minimum_running_units",
            legacy,
            "minimum_running_units",
        ),
        "maximum_running_units": _legacy_or_operation_value(
            operation_sources,
            "maximum_running_units",
            legacy,
            "maximum_running_units",
        ),
        "design_flow_capacity_m3s": _known_scalar_location(spec.aggregate_capacity_m3s),
        "minimum_run_seconds": _legacy_or_operation_value(
            operation_sources,
            "minimum_run_seconds",
            legacy,
            "minimum_run_seconds",
        ),
        "minimum_stop_seconds": _legacy_or_operation_value(
            operation_sources,
            "minimum_stop_seconds",
            legacy,
            "minimum_stop_seconds",
        ),
        "maximum_starts_per_replay": starts_location,
    }
    values: dict[str, str | int | float | bool] = {}
    provenance: dict[str, str] = {}
    integer_fields = {
        "unit_count",
        "minimum_running_units",
        "maximum_running_units",
        "maximum_starts_per_replay",
    }
    for field_name, location in located.items():
        parsed = _control_number(
            location,
            key=key,
            unified=unified,
            field_name=field_name,
            issues=issues,
            minimum=(1.0 if field_name == "unit_count" else 0.0),
            integer=field_name in integer_fields,
        )
        if parsed is not None:
            values[field_name], provenance[field_name] = parsed
    if spec.availability.value is None or spec.availability.evidence is None:
        _add_issue(
            issues,
            "CONTROL_CONSTRAINT_UNKNOWN",
            "Pump availability must be explicitly sourced",
            key,
            unified,
            "availability",
        )
    else:
        values["availability"] = "online" if spec.availability.value else "offline"
        provenance["availability"] = (
            f"{spec.availability.status.value}:{spec.availability.evidence}"
        )
    if len(values) != 8:
        return None
    unit_count = int(values["unit_count"])
    minimum_units = int(values["minimum_running_units"])
    maximum_units = int(values["maximum_running_units"])
    if minimum_units > maximum_units or maximum_units > unit_count:
        _add_issue(
            issues,
            "CONTROL_CONSTRAINT_INVALID",
            "Pump unit limits must satisfy 0 <= minimum <= maximum <= unit_count",
            key,
            unified,
            "minimum_running_units/maximum_running_units/unit_count",
        )
        return None
    return HydraulicControlAsset(
        structure_type="pump",
        structure_id=key[1],
        constraints=values,
        provenance=provenance,
    )


def _gate_spec(
    legacy: Gate | Pump,
    unified: HydraulicStructure,
    branch: HydraulicBranch,
    state: InitialActuatorState | None,
    hydraulic_sources: tuple[_ParameterSource, ...],
    operation_sources: tuple[_ParameterSource, ...],
    issues: list[HydraulicAssetMappingIssue],
) -> GateHydraulicSpec | None:
    key: AssetKey = ("gate", int(legacy.id))
    subtype_location = _located_parameter(hydraulic_sources, "gate_subtype")
    subtype = _plain_value(subtype_location)
    if not isinstance(subtype, str) or not subtype:
        law = getattr(unified, "hydraulic_law_type", None)
        legacy_type = getattr(legacy, "gate_type", None)
        subtype = (
            law
            if isinstance(law, str) and law not in {"", "none", "legacy_gate"}
            else legacy_type
            if isinstance(legacy_type, str) and legacy_type
            else "unknown"
        )
    if subtype not in _SUPPORTED_GATE_SUBTYPES:
        _add_issue(
            issues,
            "GATE_SUBTYPE_UNSUPPORTED",
            f"gate subtype {subtype!r} has no audited D-Flow mapping",
            key,
            unified,
            "gate_subtype",
        )

    structure_synthetic = _explicitly_synthetic(unified.metadata_json)
    crest_location = _located_parameter(hydraulic_sources, "crest_level_m")
    if crest_location is None and unified.crest_elevation_m is not None:
        crest_location = _database_value(
            unified.crest_elevation_m,
            f"hydraulic_structure[{unified.id}].crest_elevation_m",
            synthetic=structure_synthetic,
        )
    if crest_location is None and getattr(legacy, "crest_elevation", None) is not None:
        crest_location = _database_value(
            legacy.crest_elevation, f"gate[{legacy.id}].crest_elevation"
        )
    crest = _scalar(
        crest_location,
        issues=issues,
        code="GATE_REQUIRED_FIELD_UNKNOWN",
        message="gate crest/sill level is required and may not be defaulted",
        key=key,
        unified=unified,
        field_path="crest_level_m",
    )

    width_location = _located_parameter(hydraulic_sources, "crest_width_m")
    if width_location is None and unified.width_m is not None:
        width_location = _database_value(
            unified.width_m,
            f"hydraulic_structure[{unified.id}].width_m",
            synthetic=structure_synthetic,
        )
    if width_location is None and getattr(legacy, "width", None) is not None:
        width_location = _database_value(legacy.width, f"gate[{legacy.id}].width")
    width = _scalar(
        width_location,
        issues=issues,
        code="GATE_REQUIRED_FIELD_UNKNOWN",
        message="gate crest width is required and may not be defaulted",
        key=key,
        unified=unified,
        field_path="crest_width_m",
    )

    opening_location: _LocatedValue | None = None
    if state is not None and state.structure_type == "gate":
        opening_location = _database_value(
            state.gate_opening_m,
            f"initial_actuator_state[gate:{legacy.id}].gate_opening_m",
            synthetic=state.evidence == "SYNTHETIC_INITIAL_STATE",
        )
    opening = _scalar(
        opening_location,
        issues=issues,
        code="GATE_REQUIRED_FIELD_UNKNOWN",
        message="gate opening requires an explicit InitialActuatorState",
        key=key,
        unified=unified,
        field_path="opening_m",
    )

    maximum_location = _located_parameter(operation_sources, "maximum_opening_m")
    if maximum_location is None:
        maximum_location = _located_parameter(hydraulic_sources, "maximum_opening_m")
    if maximum_location is None and getattr(legacy, "maximum_opening", None) is not None:
        maximum_location = _database_value(
            legacy.maximum_opening, f"gate[{legacy.id}].maximum_opening"
        )
    maximum = _scalar(
        maximum_location,
        issues=issues,
        code="GATE_MAXIMUM_OPENING_UNKNOWN",
        message="maximum opening must be explicitly sourced; gate height is not a default",
        key=key,
        unified=unified,
        field_path="maximum_opening_m",
    )

    direction_raw = _plain_value(_located_parameter(hydraulic_sources, "allowed_flow_direction"))
    try:
        direction = StructureFlowDirection(direction_raw) if direction_raw is not None else None
    except ValueError:
        direction = None
    if direction is None:
        _add_issue(
            issues,
            "GATE_FLOW_DIRECTION_UNKNOWN",
            "allowed_flow_direction must be explicit; allow_reverse_flow is not equivalent",
            key,
            unified,
            "allowed_flow_direction",
        )

    velocity_raw = _plain_value(_located_parameter(hydraulic_sources, "use_velocity_height"))
    velocity = velocity_raw if isinstance(velocity_raw, bool) else None
    if velocity is None:
        _add_issue(
            issues,
            "GATE_VELOCITY_HEIGHT_UNKNOWN",
            "use_velocity_height must be an explicit boolean",
            key,
            unified,
            "use_velocity_height",
        )

    axis_raw = _plain_value(_located_parameter(hydraulic_sources, "maximum_opening_axis"))
    axis = axis_raw if axis_raw in {"vertical", "horizontal"} else None
    if axis is None:
        _add_issue(
            issues,
            "GATE_MAXIMUM_OPENING_AXIS_UNKNOWN",
            "maximum_opening_axis must be explicit",
            key,
            unified,
            "maximum_opening_axis",
        )

    correction = SourcedHydraulicScalar()
    geometry: GeneralOpeningGeometry | None = None
    coefficients: GeneralOpeningCoefficients | None = None
    if subtype == "vertical_underflow_gate":
        correction_location = _located_parameter(hydraulic_sources, "correction_coefficient")
        if correction_location is None:
            correction_location = _located_parameter(hydraulic_sources, "discharge_coefficient")
        if (
            correction_location is None
            and getattr(legacy, "discharge_coefficient", None) is not None
        ):
            correction_location = _database_value(
                legacy.discharge_coefficient,
                f"gate[{legacy.id}].discharge_coefficient",
            )
        correction = _scalar(
            correction_location,
            issues=issues,
            code="GATE_COEFFICIENT_UNKNOWN",
            message="vertical gate correction coefficient may not be defaulted",
            key=key,
            unified=unified,
            field_path="correction_coefficient",
        )
        if axis not in {None, "vertical"}:
            _add_issue(
                issues,
                "GATE_MAXIMUM_OPENING_AXIS_INVALID",
                "vertical_underflow_gate requires maximum_opening_axis='vertical'",
                key,
                unified,
                "maximum_opening_axis",
            )
    elif subtype == "general_opening":
        geometry_values = {
            field: _scalar(
                _located_parameter(hydraulic_sources, field),
                issues=issues,
                code="GENERAL_OPENING_FIELD_UNKNOWN",
                message=f"general_opening requires explicit {field}",
                key=key,
                unified=unified,
                field_path=f"general_geometry.{field}",
            )
            for field in _GENERAL_GEOMETRY_FIELDS
        }
        horizontal_raw = _plain_value(
            _located_parameter(hydraulic_sources, "horizontal_opening_direction")
        )
        try:
            horizontal = (
                GateOpeningHorizontalDirection(horizontal_raw)
                if horizontal_raw is not None
                else None
            )
        except ValueError:
            horizontal = None
        if horizontal is None:
            _add_issue(
                issues,
                "GENERAL_OPENING_FIELD_UNKNOWN",
                "general_opening requires explicit horizontal_opening_direction",
                key,
                unified,
                "general_geometry.horizontal_opening_direction",
            )
        geometry = GeneralOpeningGeometry(
            **geometry_values, horizontal_opening_direction=horizontal
        )
        coefficients = GeneralOpeningCoefficients(
            **{
                field: _scalar(
                    _located_parameter(hydraulic_sources, field),
                    issues=issues,
                    code="GATE_COEFFICIENT_UNKNOWN",
                    message=f"general_opening requires explicit {field}",
                    key=key,
                    unified=unified,
                    field_path=f"general_coefficients.{field}",
                )
                for field in _GENERAL_COEFFICIENT_FIELDS
            }
        )

    try:
        return GateHydraulicSpec(
            structure_id=unified.structure_code,
            name=unified.structure_name,
            branch_id=branch.branch_code,
            chainage_m=unified.chainage_m,
            gate_subtype=str(subtype),
            crest_level_m=crest,
            crest_width_m=width,
            opening_m=opening,
            maximum_opening_m=maximum,
            allowed_flow_direction=direction,
            use_velocity_height=velocity,
            correction_coefficient=correction,
            general_geometry=geometry,
            general_coefficients=coefficients,
            maximum_opening_axis=axis,
        )
    except Exception as exc:
        _add_issue(
            issues,
            "GATE_SPEC_INVALID",
            str(exc),
            key,
            unified,
            "gate",
        )
        return None


def _pump_spec(
    legacy: Gate | Pump,
    unified: HydraulicStructure,
    branch: HydraulicBranch,
    hydraulic_sources: tuple[_ParameterSource, ...],
    operation_sources: tuple[_ParameterSource, ...],
    issues: list[HydraulicAssetMappingIssue],
) -> PumpHydraulicSpec | None:
    key: AssetKey = ("pump", int(legacy.id))

    transfer_raw = _plain_value(_located_parameter(hydraulic_sources, "transfer_type"))
    if transfer_raw is None:
        transfer_raw = getattr(legacy, "transfer_type", None)
    transfer: PumpTransferType | None
    try:
        transfer = PumpTransferType(transfer_raw) if transfer_raw is not None else None
    except ValueError:
        transfer = None
    if transfer != PumpTransferType.INLINE_BRANCH:
        _add_issue(
            issues,
            "PUMP_TRANSFER_TYPE_UNSUPPORTED",
            "only an explicit inline_branch Pump has an audited native mapping",
            key,
            unified,
            "transfer_type",
        )
        return None

    intake_raw = _plain_value(_located_parameter(hydraulic_sources, "intake_id"))
    if intake_raw is None and getattr(legacy, "intake_node_id", None) is not None:
        intake_raw = f"legacy_node:{legacy.intake_node_id}"
    outlet_raw = _plain_value(_located_parameter(hydraulic_sources, "outlet_id"))
    if outlet_raw is None and getattr(legacy, "outlet_node_id", None) is not None:
        outlet_raw = f"legacy_node:{legacy.outlet_node_id}"
    if intake_raw is None:
        _add_issue(
            issues,
            "PUMP_ENDPOINT_UNKNOWN",
            "pump intake_id must be explicit",
            key,
            unified,
            "intake_id",
        )
    if outlet_raw is None:
        _add_issue(
            issues,
            "PUMP_ENDPOINT_UNKNOWN",
            "pump outlet_id must be explicit",
            key,
            unified,
            "outlet_id",
        )

    orientation_raw = _plain_value(_located_parameter(hydraulic_sources, "orientation"))
    try:
        orientation = PumpOrientation(orientation_raw) if orientation_raw is not None else None
    except ValueError:
        orientation = None
    if orientation is None:
        _add_issue(
            issues,
            "PUMP_ORIENTATION_UNKNOWN",
            "pump orientation relative to branch chainage must be explicit",
            key,
            unified,
            "orientation",
        )

    unit_raw = _plain_value(_located_parameter(operation_sources, "unit_count"))
    if unit_raw is None:
        unit_raw = getattr(legacy, "unit_count", None)
    unit_count = unit_raw if isinstance(unit_raw, int) and not isinstance(unit_raw, bool) else None
    if unit_count is None or unit_count < 1:
        _add_issue(
            issues,
            "PUMP_UNIT_COUNT_UNKNOWN",
            "pump unit_count must be an explicit positive integer",
            key,
            unified,
            "unit_count",
        )

    capacity_location = _located_parameter(hydraulic_sources, "aggregate_capacity_m3s")
    if capacity_location is None and getattr(legacy, "design_flow", None) is not None:
        # Legacy design_flow is documented as station capacity.  It is never
        # multiplied by unit_count and is not treated as actual discharge.
        capacity_location = _database_value(legacy.design_flow, f"pump[{legacy.id}].design_flow")
    capacity = _scalar(
        capacity_location,
        issues=issues,
        code="PUMP_CAPACITY_UNKNOWN",
        message="aggregate pump capacity must be explicitly sourced",
        key=key,
        unified=unified,
        field_path="aggregate_capacity_m3s",
    )

    availability_location = _located_parameter(hydraulic_sources, "availability")
    if availability_location is None and getattr(legacy, "status", None) in {
        "online",
        "offline",
        "maintenance",
        "fault",
    }:
        availability_location = _database_value(
            legacy.status == "online", f"pump[{legacy.id}].status"
        )
    availability = _boolean(
        availability_location,
        issues=issues,
        code="PUMP_AVAILABILITY_UNKNOWN",
        message="pump availability must be explicit",
        key=key,
        unified=unified,
        field_path="availability",
    )
    curve = _pump_curve(hydraulic_sources, key, unified, issues)

    if intake_raw is None or outlet_raw is None or orientation is None or unit_count is None:
        return None
    try:
        return PumpHydraulicSpec(
            structure_id=unified.structure_code,
            name=unified.structure_name,
            branch_id=branch.branch_code,
            chainage_m=unified.chainage_m,
            transfer_type=transfer,
            intake_id=str(intake_raw),
            outlet_id=str(outlet_raw),
            orientation=orientation,
            unit_count=unit_count,
            control_mode=PumpControlMode.AGGREGATE_CAPACITY,
            aggregate_capacity_m3s=capacity,
            availability=availability,
            head_reduction_curve=curve,
            native_num_stages=0,
            capacity_is_actual_discharge=False,
        )
    except Exception as exc:
        _add_issue(
            issues,
            "PUMP_SPEC_INVALID",
            str(exc),
            key,
            unified,
            "pump",
        )
        return None


def _pump_curve(
    hydraulic_sources: tuple[_ParameterSource, ...],
    key: AssetKey,
    unified: HydraulicStructure,
    issues: list[HydraulicAssetMappingIssue],
) -> PumpHeadReductionCurve:
    source: _ParameterSource | None = None
    raw: Any = None
    for candidate in hydraulic_sources:
        if "head_reduction_curve" in candidate.values:
            source = candidate
            raw = candidate.values["head_reduction_curve"]
            break
    if source is None:
        _add_issue(
            issues,
            "PUMP_HEAD_REDUCTION_CURVE_UNKNOWN",
            "legacy Q-H curves are not D-Flow reduction factors; provide named head_reduction_curve",
            key,
            unified,
            "head_reduction_curve",
        )
        return PumpHeadReductionCurve()
    evidence = f"{source.evidence_prefix}.head_reduction_curve"
    if not isinstance(raw, Mapping):
        _add_issue(
            issues,
            "PUMP_CURVE_PROVENANCE_REQUIRED",
            "head_reduction_curve requires explicit SOURCE_DATA or SYNTHETIC_ASSUMPTION provenance",
            key,
            unified,
            evidence,
        )
        return PumpHeadReductionCurve()
    declared = raw.get("provenance", raw.get("status"))
    try:
        status = HydraulicDataStatus(str(declared).upper())
    except (TypeError, ValueError):
        _add_issue(
            issues,
            "PUMP_CURVE_PROVENANCE_REQUIRED",
            "head_reduction_curve requires explicit SOURCE_DATA or SYNTHETIC_ASSUMPTION provenance",
            key,
            unified,
            evidence,
        )
        return PumpHeadReductionCurve()
    if status == HydraulicDataStatus.UNKNOWN:
        _add_issue(
            issues,
            "PUMP_HEAD_REDUCTION_CURVE_UNKNOWN",
            "head_reduction_curve is explicitly UNKNOWN",
            key,
            unified,
            evidence,
        )
        return PumpHeadReductionCurve()
    points_raw = raw.get("points")
    if points_raw is None and isinstance(raw.get("value"), Mapping):
        points_raw = raw["value"].get("points")
    elif points_raw is None:
        points_raw = raw.get("value")
    try:
        points = tuple(PumpHeadReductionPoint.model_validate(item) for item in points_raw)
        return PumpHeadReductionCurve(status=status, points=points, evidence=evidence)
    except Exception as exc:
        _add_issue(
            issues,
            "PUMP_HEAD_REDUCTION_CURVE_INVALID",
            str(exc),
            key,
            unified,
            evidence,
        )
        return PumpHeadReductionCurve()


def _gate_bindings(
    key: AssetKey,
    spec: GateHydraulicSpec,
    legacy: Gate | Pump,
    unified: HydraulicStructure,
    command_types: Iterable[str],
    issues: list[HydraulicAssetMappingIssue],
) -> list[ActuatorControlBinding]:
    values: list[ActuatorControlBinding] = []
    prefix = "orifices" if spec.gate_subtype == "vertical_underflow_gate" else "generalstructures"
    for command_type in command_types:
        if command_type not in {"gate_opening_m", "gate_opening_ratio"}:
            _add_issue(
                issues,
                "HYDRAULIC_COMMAND_SEMANTICS_UNSUPPORTED",
                f"{command_type} has no Gate BMI binding",
                key,
                field_path="command_type",
            )
            continue
        if spec.maximum_opening_axis != "vertical":
            _add_issue(
                issues,
                "HYDRAULIC_COMMAND_SEMANTICS_UNSUPPORTED",
                "gateLowerEdgeLevel cannot represent a horizontal opening command",
                key,
                unified,
                "maximum_opening_axis",
            )
            continue
        if spec.crest_level_m.value is None:
            _add_issue(
                issues,
                "GATE_CONTROL_REFERENCE_UNKNOWN",
                "gate control binding requires an explicit lower-edge datum",
                key,
                field_path="crest_level_m",
            )
            continue
        gate_height: float | None = None
        if command_type == "gate_opening_ratio":
            if spec.general_geometry is not None:
                gate_height = spec.general_geometry.gate_height_m.value
            elif unified.height_m is not None:
                gate_height = float(unified.height_m)
            elif getattr(legacy, "height", None) is not None:
                gate_height = float(legacy.height)
            if gate_height is None:
                _add_issue(
                    issues,
                    "GATE_CONTROL_HEIGHT_UNKNOWN",
                    "gate_opening_ratio requires explicit gate height",
                    key,
                    field_path="gate_height_m",
                )
                continue
        values.append(
            ActuatorControlBinding(
                structure_type="gate",
                structure_id=key[1],
                native_structure_id=spec.structure_id,
                supported_command_type=command_type,
                bmi_variable=f"{prefix}/{spec.structure_id}/gateLowerEdgeLevel",
                conversion="gate_lower_edge_level",
                reference_level_m=spec.crest_level_m.value,
                gate_height_m=gate_height,
            )
        )
    return values


def _pump_bindings(
    key: AssetKey,
    spec: PumpHydraulicSpec,
    command_types: Iterable[str],
    issues: list[HydraulicAssetMappingIssue],
) -> list[ActuatorControlBinding]:
    values: list[ActuatorControlBinding] = []
    for command_type in command_types:
        if command_type != "pump_target_flow":
            _add_issue(
                issues,
                "HYDRAULIC_COMMAND_SEMANTICS_UNSUPPORTED",
                (
                    f"{command_type} is not aggregate Capacity; pump_enabled and "
                    "pump_unit_count are intentionally unbound"
                ),
                key,
                field_path="command_type",
            )
            continue
        values.append(
            ActuatorControlBinding(
                structure_type="pump",
                structure_id=key[1],
                native_structure_id=spec.structure_id,
                supported_command_type="pump_target_flow",
                bmi_variable=f"pumps/{spec.structure_id}/capacity",
                conversion="identity_capacity",
            )
        )
    return values


def _add_issue(
    issues: list[HydraulicAssetMappingIssue],
    code: str,
    message: str,
    key: AssetKey,
    unified: HydraulicStructure | None = None,
    field_path: str | None = None,
) -> None:
    issues.append(
        HydraulicAssetMappingIssue(
            code=code,
            message=message[:512],
            structure_type=key[0],
            legacy_asset_id=key[1],
            hydraulic_structure_id=int(unified.id) if unified is not None else None,
            field_path=field_path,
        )
    )


__all__ = [
    "HydraulicAssetMappingIssue",
    "HydraulicAssetNormalization",
    "normalize_plan_hydraulic_assets",
]
