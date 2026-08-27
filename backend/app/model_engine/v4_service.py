"""Build, preflight, preview, and freeze native-v4 platform snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from os import getenv
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.gis.models import (
    BoundaryCondition,
    DatasetVersion,
    DispatchPlan,
    Gate,
    Pump,
    SimulationCase,
    SimulationCaseBoundary,
)
from app.hydraulic.models import (
    HydraulicBranch,
    HydraulicCrossSection,
    HydraulicCrossSectionPoint,
    HydraulicCrossSectionProfile,
    HydraulicNetwork,
    HydraulicReach,
)
from app.model_engine.v4_schemas import (
    V4PreviewResponse,
    V4ReadinessIssue,
    V4ReadinessResponse,
)
from model.adapters import V4RuntimeProjection, project_v4_to_v4_lite
from model.core.errors import HydraulicInputError
from model.provenance import CANONICALIZATION_ID, snapshot_hash
from model.solver.registry import (
    D1_CAPABILITY_ID,
    D1_RUNTIME_ADAPTER_ID,
    D1_SOLVER_ID,
    registry_hash,
)


D1_KNOWN_LIMITATIONS = (
    "single Branch, fully wet, forward strictly subcritical validation only",
    "flat bed, identical Profile geometry, Manning n=0",
    "one completed-interface Gate and one external Q-H/Q-efficiency Pump",
    "not calibrated and not approved for production water decisions",
)


@dataclass(frozen=True, slots=True)
class NativeV4Assessment:
    """Carry one readiness result and any fully validated runtime projection."""

    readiness: V4ReadinessResponse
    snapshot: dict[str, Any] | None = None
    projection: V4RuntimeProjection | None = None


def _issue(
    code: str,
    message: str,
    *,
    entity_type: str = "simulation_case",
    entity_id: int | str | None = None,
    field_path: str = "",
    severity: str = "error",
) -> V4ReadinessIssue:
    """Create one stable readiness issue with a consistently populated path."""

    return V4ReadinessIssue(
        code=code,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        field_path=field_path or entity_type,
        message=message,
    )


def _collection(payload: Mapping[str, Any], key: str) -> list[Any]:
    """Return a JSON-array field or an empty collection for bounded preflight checks."""

    value = payload.get(key)
    return value if isinstance(value, list) else []


def _time_range(series: object) -> tuple[float | None, float | None]:
    """Read a finite time-series range without accepting malformed containers."""

    if not isinstance(series, Mapping):
        return None, None
    values = series.get("time_seconds")
    if not isinstance(values, list) or not values:
        return None, None
    try:
        return float(values[0]), float(values[-1])
    except (TypeError, ValueError):
        return None, None


def _native_preflight(payload: Mapping[str, Any]) -> list[V4ReadinessIssue]:
    """Check D2 scientific scope before invoking the strict platform/runtime parsers."""

    issues: list[V4ReadinessIssue] = []
    branches = _collection(payload, "branches")
    sections = _collection(payload, "cross_sections")
    structures = payload.get("structures")
    gates = (
        structures.get("gates", [])
        if isinstance(structures, Mapping) and isinstance(structures.get("gates"), list)
        else []
    )
    pumps = (
        structures.get("pumps", [])
        if isinstance(structures, Mapping) and isinstance(structures.get("pumps"), list)
        else []
    )
    if len(branches) != 1:
        issues.append(
            _issue(
                "D2_BRANCH_COUNT_UNSUPPORTED",
                "native D1 v4 requires exactly one hydraulic Branch",
                entity_type="network",
                field_path="branches",
            )
        )
    if not 3 <= len(sections) <= 200:
        issues.append(
            _issue(
                "D2_SECTION_COUNT_UNSUPPORTED",
                "native D1 v4 requires between 3 and 200 ordered cross sections",
                entity_type="cross_section",
                field_path="cross_sections",
            )
        )
    for section in sections:
        if not isinstance(section, Mapping):
            continue
        if section.get("default_manning_n") != 0.0:
            issues.append(
                _issue(
                    "D2_MANNING_NONZERO",
                    "D1 platform capability requires Manning n=0",
                    entity_type="cross_section",
                    entity_id=section.get("section_id"),
                    field_path="cross_sections.default_manning_n",
                )
            )
    profile_signatures = {
        tuple(
            (point.get("offset_m"), point.get("elevation_m"))
            for point in section.get("points", [])
            if isinstance(point, Mapping)
        )
        for section in sections
        if isinstance(section, Mapping)
    }
    if sections and len(profile_signatures) != 1:
        issues.append(
            _issue(
                "D2_PROFILE_MISMATCH",
                "D1 platform capability requires identical Profile geometry",
                entity_type="cross_section_profile",
                field_path="cross_sections.points",
            )
        )
    if len(gates) != 1:
        issues.append(
            _issue(
                "D2_GATE_COUNT_UNSUPPORTED",
                "native D1 v4 requires exactly one Gate",
                entity_type="gate",
                field_path="structures.gates",
            )
        )
    if len(pumps) != 1:
        issues.append(
            _issue(
                "D2_PUMP_COUNT_UNSUPPORTED",
                "native D1 v4 requires exactly one external Pump",
                entity_type="pump",
                field_path="structures.pumps",
            )
        )
    elif isinstance(pumps[0], Mapping):
        pump = pumps[0]
        if pump.get("pump_model") != "hydraulic-qh-external-sink-v1" or pump.get(
            "outlet"
        ) != "external":
            issues.append(
                _issue(
                    "D2_INTERNAL_OR_NONHYDRAULIC_PUMP",
                    "D1 requires an external hydraulic Q-H Pump",
                    entity_type="pump",
                    entity_id=(pump.get("identity") or {}).get("id")
                    if isinstance(pump.get("identity"), Mapping)
                    else None,
                    field_path="structures.pumps[0]",
                )
            )
        for field in ("head_curve", "efficiency_curve", "outlet_stage", "system_loss"):
            if not isinstance(pump.get(field), Mapping):
                issues.append(
                    _issue(
                        "D2_PUMP_CONTRACT_INCOMPLETE",
                        f"Pump {field} is required and must be explicit",
                        entity_type="pump",
                        field_path=f"structures.pumps[0].{field}",
                    )
                )
    if len(gates) == 1 and len(pumps) == 1:
        gate = gates[0]
        pump = pumps[0]
        if isinstance(gate, Mapping) and isinstance(pump, Mapping):
            interface = gate.get("interface")
            pump_section = pump.get("section_id")
            if isinstance(interface, Mapping) and pump_section in {
                interface.get("upstream_section_id"),
                interface.get("downstream_section_id"),
            }:
                issues.append(
                    _issue(
                        "D2_GATE_PUMP_PLACEMENT_CONFLICT",
                        "Gate interface and external Pump source section must not overlap",
                        entity_type="structure",
                        field_path="structures",
                    )
                )
    numerical = payload.get("numerical_policy")
    validation = payload.get("validation")
    if not isinstance(numerical, Mapping) or numerical.get(
        "pump_curve_policy"
    ) != "piecewise-linear-qh-v1":
        issues.append(
            _issue(
                "D2_NUMERICAL_POLICY_UNREGISTERED",
                "native D1 v4 requires the registered Pump curve policy",
                entity_type="numerical_policy",
                field_path="numerical_policy.pump_curve_policy",
            )
        )
    if not isinstance(validation, Mapping) or validation.get(
        "validation_policy_version"
    ) != "v4-lite-7":
        issues.append(
            _issue(
                "D2_VALIDATION_POLICY_UNREGISTERED",
                "native D1 v4 requires validation policy v4-lite-7",
                entity_type="validation_policy",
                field_path="validation.validation_policy_version",
            )
        )
    duration = (
        float(numerical.get("duration_seconds"))
        if isinstance(numerical, Mapping)
        and isinstance(numerical.get("duration_seconds"), (int, float))
        else None
    )
    boundaries = payload.get("boundaries")
    if isinstance(boundaries, Mapping) and duration is not None:
        for role in ("upstream", "downstream"):
            start, end = _time_range(boundaries.get(role))
            if start != 0.0 or end is None or end < duration:
                issues.append(
                    _issue(
                        "D2_BOUNDARY_COVERAGE_INCOMPLETE",
                        f"{role} boundary must explicitly cover 0..duration",
                        entity_type="boundary_condition",
                        field_path=f"boundaries.{role}.time_seconds",
                    )
                )
    return issues


def assess_native_v4_snapshot(payload: Mapping[str, Any]) -> NativeV4Assessment:
    """Return structured preflight and independent candidate hashes for one snapshot."""

    issues = _native_preflight(payload)
    projection: V4RuntimeProjection | None = None
    if not issues:
        try:
            projection = project_v4_to_v4_lite(payload)
        except HydraulicInputError as exc:
            issues.append(
                _issue(
                    "D2_CONTRACT_VALIDATION_FAILED",
                    str(exc),
                    field_path="dayu.model-input.v4",
                )
            )
    errors = [item for item in issues if item.severity == "error"]
    warnings = [item for item in issues if item.severity == "warning"]
    sections = _collection(payload, "cross_sections")
    structures = payload.get("structures")
    hashes = dict(projection.manifest) if projection is not None else {}
    candidate_hashes = {
        key: str(value)
        for key, value in hashes.items()
        if key.endswith("_hash")
    }
    summary = {
        "schema_version": payload.get("schema_version"),
        "dataset_version_id": (payload.get("dataset_version") or {}).get("id")
        if isinstance(payload.get("dataset_version"), Mapping)
        else None,
        "simulation_case_id": (payload.get("simulation_case") or {}).get("id")
        if isinstance(payload.get("simulation_case"), Mapping)
        else None,
        "branch_count": len(_collection(payload, "branches")),
        "section_count": len(sections),
        "gate_count": len(structures.get("gates", []))
        if isinstance(structures, Mapping) and isinstance(structures.get("gates"), list)
        else 0,
        "pump_count": len(structures.get("pumps", []))
        if isinstance(structures, Mapping) and isinstance(structures.get("pumps"), list)
        else 0,
    }
    readiness = V4ReadinessResponse(
        ready=not errors and projection is not None,
        solver_id=D1_SOLVER_ID,
        capability_id=D1_CAPABILITY_ID,
        runtime_adapter_id=D1_RUNTIME_ADAPTER_ID,
        errors=errors,
        warnings=warnings,
        snapshot_summary=summary,
        candidate_hashes=candidate_hashes,
    )
    return NativeV4Assessment(
        readiness=readiness,
        snapshot=projection.source_snapshot if projection is not None else dict(payload),
        projection=projection,
    )


def _series_values(
    boundary: BoundaryCondition,
    *,
    value_key: str,
    duration_seconds: float,
) -> tuple[list[float], list[float]] | None:
    """Normalize an explicit series or declared constant without interpolating data."""

    values = boundary.values
    if not isinstance(values, Mapping):
        return None
    times = values.get("time_seconds")
    samples = values.get(value_key)
    if isinstance(times, list) and isinstance(samples, list):
        return [float(item) for item in times], [float(item) for item in samples]
    constant = values.get("value")
    if isinstance(constant, (int, float)) and not isinstance(constant, bool):
        return [0.0, duration_seconds], [float(constant), float(constant)]
    return None


def _curve_points(raw: object, *, ordinate: str) -> list[dict[str, float]] | None:
    """Normalize one explicitly ordered legacy curve JSON without sorting or defaults."""

    if not isinstance(raw, Mapping) or not isinstance(raw.get("points"), list):
        return None
    result: list[dict[str, float]] = []
    for row in raw["points"]:
        if isinstance(row, Mapping):
            flow = row.get("flow_m3s")
            value = row.get(ordinate)
        elif isinstance(row, (list, tuple)) and len(row) == 2:
            flow, value = row
        else:
            return None
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in (flow, value)):
            return None
        result.append({"flow_m3s": float(flow), ordinate: float(value)})
    return result


def _database_candidate(
    session: Session,
    case_id: int,
    dispatch_plan_id: int,
    *,
    engine_commit: str,
) -> tuple[dict[str, Any] | None, list[V4ReadinessIssue]]:
    """Read only authoritative database rows and assemble one candidate snapshot."""

    issues: list[V4ReadinessIssue] = []
    case = session.get(SimulationCase, case_id)
    if case is None:
        return None, [
            _issue("D2_CASE_NOT_FOUND", "simulation case does not exist", entity_id=case_id)
        ]
    dataset = session.get(DatasetVersion, case.dataset_version_id)
    if dataset is None or not isinstance(dataset.content_hash, str) or len(dataset.content_hash) != 64:
        issues.append(
            _issue(
                "D2_DATASET_IDENTITY_INCOMPLETE",
                "Dataset Version requires a 64-character content hash",
                entity_type="dataset_version",
                entity_id=case.dataset_version_id,
                field_path="dataset_version.content_hash",
            )
        )
    case_config = case.v4_configuration
    if not isinstance(case_config, Mapping):
        issues.append(
            _issue(
                "D2_CASE_CONFIGURATION_MISSING",
                "SimulationCase has no typed native-v4 configuration",
                entity_id=case.id,
                field_path="simulation_case.v4_configuration",
            )
        )
    plan = session.get(DispatchPlan, dispatch_plan_id)
    if (
        plan is None
        or plan.status != "frozen"
        or plan.simulation_case_id != case.id
        or plan.dataset_version_id != case.dataset_version_id
        or not isinstance(plan.frozen_snapshot, Mapping)
        or not isinstance(plan.frozen_snapshot_hash, str)
        or len(plan.frozen_snapshot_hash) != 64
    ):
        issues.append(
            _issue(
                "D2_CONTROL_PLAN_NOT_FROZEN",
                "v4 requires one frozen Dispatch Plan for the same case and Dataset Version",
                entity_type="dispatch_plan",
                entity_id=dispatch_plan_id,
                field_path="control_plan",
            )
        )
    networks = list(
        session.scalars(
            select(HydraulicNetwork)
            .where(HydraulicNetwork.dataset_version_id == case.dataset_version_id)
            .order_by(HydraulicNetwork.id)
        ).all()
    )
    if len(networks) != 1:
        issues.append(
            _issue(
                "D2_NETWORK_COUNT_UNSUPPORTED",
                "v4 requires exactly one hydraulic Network in the Dataset Version",
                entity_type="network",
                field_path="network",
            )
        )
    if issues:
        return None, issues
    assert dataset is not None and isinstance(case_config, Mapping) and plan is not None
    network = networks[0]
    if not network.engineering_crs:
        return None, [
            _issue(
                "D2_ENGINEERING_CRS_MISSING",
                "hydraulic Network requires a confirmed engineering CRS",
                entity_type="network",
                entity_id=network.id,
                field_path="network.engineering_crs",
            )
        ]
    branches = list(
        session.scalars(
            select(HydraulicBranch)
            .where(HydraulicBranch.network_id == network.id)
            .order_by(HydraulicBranch.id)
        ).all()
    )
    if len(branches) != 1:
        return None, _native_preflight({"branches": [None] * len(branches)})
    branch = branches[0]
    reaches = list(
        session.scalars(
            select(HydraulicReach)
            .where(HydraulicReach.branch_id == branch.id)
            .order_by(HydraulicReach.start_chainage_m, HydraulicReach.id)
        ).all()
    )
    sections = list(
        session.scalars(
            select(HydraulicCrossSection)
            .where(HydraulicCrossSection.branch_id == branch.id)
            .order_by(HydraulicCrossSection.chainage, HydraulicCrossSection.id)
        ).all()
    )
    section_rows: list[dict[str, Any]] = []
    profile_rows: list[dict[str, Any]] = []
    configured_manning = case_config.get("default_manning_n")
    if configured_manning != 0.0:
        issues.append(
            _issue(
                "D2_MANNING_NONZERO",
                "SimulationCase native-v4 configuration must explicitly set Manning n=0",
                field_path="simulation_case.v4_configuration.default_manning_n",
            )
        )
    for section in sections:
        profile = session.scalar(
            select(HydraulicCrossSectionProfile)
            .where(
                HydraulicCrossSectionProfile.cross_section_id == section.id,
                HydraulicCrossSectionProfile.is_active.is_(True),
            )
            .order_by(HydraulicCrossSectionProfile.id.desc())
        )
        if profile is None:
            issues.append(
                _issue(
                    "D2_PROFILE_MISSING",
                    "cross section has no active Profile",
                    entity_type="cross_section",
                    entity_id=section.id,
                    field_path="cross_sections.profile",
                )
            )
            continue
        points = list(
            session.scalars(
                select(HydraulicCrossSectionPoint)
                .where(HydraulicCrossSectionPoint.profile_id == profile.id)
                .order_by(HydraulicCrossSectionPoint.sequence)
            ).all()
        )
        section_rows.append(
            {
                "section_id": section.id,
                "section_code": section.section_code,
                "branch_id": branch.id,
                "chainage_m": section.chainage,
                "profile_id": profile.id,
                "profile_hash": profile.profile_hash,
                "default_manning_n": configured_manning,
                "points": [
                    {"offset_m": point.distance, "elevation_m": point.elevation}
                    for point in points
                ],
            }
        )
        profile_rows.append(
            {
                "id": profile.id,
                "cross_section_id": section.id,
                "profile_hash": profile.profile_hash,
            }
        )
    boundaries = list(
        session.scalars(
            select(BoundaryCondition)
            .join(
                SimulationCaseBoundary,
                SimulationCaseBoundary.boundary_condition_id == BoundaryCondition.id,
            )
            .where(SimulationCaseBoundary.case_id == case.id)
            .order_by(BoundaryCondition.id)
        ).all()
    )
    upstream = next((item for item in boundaries if item.boundary_type == "upstream_flow"), None)
    downstream = next(
        (item for item in boundaries if item.boundary_type == "downstream_water_level"),
        None,
    )
    numerical = case_config.get("numerical_policy")
    duration = (
        float(numerical.get("duration_seconds"))
        if isinstance(numerical, Mapping)
        and isinstance(numerical.get("duration_seconds"), (int, float))
        else 0.0
    )
    upstream_values = (
        _series_values(upstream, value_key="flow_m3_s", duration_seconds=duration)
        if upstream is not None
        else None
    )
    downstream_values = (
        _series_values(
            downstream, value_key="water_level_m", duration_seconds=duration
        )
        if downstream is not None
        else None
    )
    if (
        upstream is None
        or downstream is None
        or upstream.hydraulic_node_id != branch.upstream_node_id
        or downstream.hydraulic_node_id != branch.downstream_node_id
        or upstream_values is None
        or downstream_values is None
    ):
        issues.append(
            _issue(
                "D2_BOUNDARY_BINDING_INCOMPLETE",
                "case requires explicit hydraulic-node Q(t)/H(t) boundaries",
                entity_type="boundary_condition",
                field_path="boundaries",
            )
        )
    gates = list(
        session.scalars(
            select(Gate)
            .where(Gate.dataset_version_id == case.dataset_version_id)
            .order_by(Gate.id)
        ).all()
    )
    pumps = list(
        session.scalars(
            select(Pump)
            .where(Pump.dataset_version_id == case.dataset_version_id)
            .order_by(Pump.id)
        ).all()
    )
    if len(gates) != 1 or len(pumps) != 1:
        issues.extend(
            _native_preflight(
                {
                    "branches": [{}],
                    "cross_sections": section_rows,
                    "structures": {
                        "gates": [{} for _ in gates],
                        "pumps": [{} for _ in pumps],
                    },
                }
            )
        )
    if issues:
        return None, issues
    gate, pump = gates[0], pumps[0]
    plan_config = (
        plan.frozen_snapshot.get("plan", {}).get("evaluation_config", {}).get("native_v4")
        if isinstance(plan.frozen_snapshot.get("plan"), Mapping)
        else None
    )
    if not isinstance(plan_config, Mapping):
        return None, [
            _issue(
                "D2_CONTROL_POLICY_MISSING",
                "frozen Dispatch Plan lacks evaluation_config.native_v4",
                entity_type="dispatch_plan",
                entity_id=plan.id,
                field_path="control_plan.native_v4",
            )
        ]
    gate_control = plan_config.get("gate_control")
    pump_control = plan_config.get("pump_control")
    head_points = _curve_points(pump.head_curve, ordinate="head_m")
    efficiency_points = _curve_points(pump.efficiency_curve, ordinate="efficiency")
    normalized_curve = {
        "policy_id": pump.curve_policy_id,
        "unit": pump.curve_unit,
        "head_curve": {"points": head_points},
        "efficiency_curve": {"points": efficiency_points},
        "source_revision": pump.curve_source_revision,
    }
    if (
        head_points is None
        or efficiency_points is None
        or pump.curve_policy_id != "d1-piecewise-linear-qh-qeta-si-v1"
        or pump.curve_unit != "SI"
        or not isinstance(pump.curve_hash, str)
        or pump.curve_hash != snapshot_hash(normalized_curve)
        or not isinstance(pump.system_loss, Mapping)
        or not isinstance(pump.outlet_stage, Mapping)
    ):
        return None, [
            _issue(
                "D2_PUMP_CURVE_IDENTITY_INVALID",
                "Pump curves require explicit SI policy/source/hash/system-loss/outlet-stage",
                entity_type="pump",
                entity_id=pump.id,
                field_path="pump.curve_hash",
            )
        ]
    if (
        gate.hydraulic_upstream_section_id is None
        or gate.hydraulic_downstream_section_id is None
        or pump.hydraulic_section_id is None
        or not isinstance(gate_control, Mapping)
        or not isinstance(pump_control, Mapping)
    ):
        return None, [
            _issue(
                "D2_STRUCTURE_BINDING_INCOMPLETE",
                "Gate face, Pump section, and both frozen controls are required",
                entity_type="structure",
                field_path="structures",
            )
        ]
    upstream_times, upstream_samples = upstream_values
    downstream_times, downstream_samples = downstream_values
    candidate = {
        "schema_version": "dayu.model-input.v4",
        "solver_selection": {
            "solver_id": D1_SOLVER_ID,
            "capability_id": D1_CAPABILITY_ID,
            "runtime_adapter_id": D1_RUNTIME_ADAPTER_ID,
        },
        "dataset_version": {"id": dataset.id, "content_hash": dataset.content_hash},
        "simulation_case": {"id": case.id, "name": case.name},
        "coordinate_reference": {
            "engineering_crs": network.engineering_crs,
            "horizontal_unit": "m",
            "vertical_datum": network.vertical_datum,
            "vertical_unit": "m",
        },
        "network": {"id": network.id, "code": network.code},
        "branches": [
            {
                "network_id": network.id,
                "branch_id": branch.id,
                "branch_code": branch.branch_code,
                "upstream_node_id": branch.upstream_node_id,
                "downstream_node_id": branch.downstream_node_id,
                "start_chainage_m": branch.start_chainage,
                "end_chainage_m": branch.end_chainage,
                "direction_status": branch.direction_status,
            }
        ],
        "reaches": [
            {
                "id": item.id,
                "branch_id": item.branch_id,
                "reach_code": item.reach_code,
                "start_chainage_m": item.start_chainage_m,
                "end_chainage_m": item.end_chainage_m,
            }
            for item in reaches
        ],
        "cross_sections": section_rows,
        "cross_section_profiles": profile_rows,
        "initial_state": case_config.get("initial_state"),
        "boundaries": {
            "upstream": {
                "identity": {"namespace": "public.boundary_condition", "id": upstream.id},
                "type": "discharge-series",
                "target_node_id": upstream.hydraulic_node_id,
                "time_seconds": upstream_times,
                "flow_m3_s": upstream_samples,
                "interpolation": "linear",
                "extrapolation": "error",
            },
            "downstream": {
                "identity": {"namespace": "public.boundary_condition", "id": downstream.id},
                "type": "stage-series",
                "target_node_id": downstream.hydraulic_node_id,
                "time_seconds": downstream_times,
                "water_level_m": downstream_samples,
                "interpolation": "linear",
                "extrapolation": "error",
            },
        },
        "structures": {
            "gates": [
                {
                    "identity": {"namespace": "public.gate", "id": gate.id},
                    "branch_id": branch.id,
                    "interface": {
                        "upstream_section_id": gate.hydraulic_upstream_section_id,
                        "downstream_section_id": gate.hydraulic_downstream_section_id,
                    },
                    "opening_m": gate_control.get("opening_m"),
                    "width_m": gate.width,
                    "height_m": gate.height,
                    "discharge_coefficient": gate.discharge_coefficient,
                    "allow_reverse_flow": gate.allow_reverse_flow,
                    "control": {
                        "type": "one-shot-stage-above-bracketed-v1",
                        "threshold_water_level_m": gate_control.get(
                            "threshold_water_level_m"
                        ),
                    },
                    "sill_elevation_m": gate.bottom_elevation,
                }
            ],
            "pumps": [
                {
                    "pump_model": "hydraulic-qh-external-sink-v1",
                    "identity": {"namespace": "public.pump", "id": pump.id},
                    "branch_id": branch.id,
                    "section_id": pump.hydraulic_section_id,
                    "outlet": "external",
                    "status": "off",
                    "head_curve": {"points": head_points},
                    "efficiency_curve": {"points": efficiency_points},
                    "unit_configuration": {
                        "total_units": pump.unit_count,
                        "running_units": pump.minimum_running_units,
                        "minimum_running_units": pump.minimum_running_units,
                        "maximum_running_units": pump.maximum_running_units,
                    },
                    "system_loss": dict(pump.system_loss),
                    "outlet_stage": dict(pump.outlet_stage),
                    "control": {
                        "type": "stage-hysteresis-min-runtime-v1",
                        **dict(pump_control),
                    },
                }
            ],
        },
        "control_plan": {
            "id": plan.id,
            "frozen_snapshot_hash": plan.frozen_snapshot_hash,
            "policy_id": "d1-gate-pump-control-v1",
        },
        "numerical_policy": numerical,
        "validation": {
            "validation_policy_version": "v4-lite-7",
            "capability_id": D1_CAPABILITY_ID,
            "water_balance_tolerance": numerical.get("water_balance_tolerance")
            if isinstance(numerical, Mapping)
            else None,
        },
        "provenance": {
            "engine_version": getenv("HYDRAULIC_ENGINE_VERSION", "dayu-hydraulic-4.0.0"),
            "engine_commit": engine_commit,
            "canonicalization_id": CANONICALIZATION_ID,
            "registry_hash": registry_hash(),
        },
        "known_limitations": list(
            case_config.get("known_limitations", D1_KNOWN_LIMITATIONS)
        ),
    }
    return candidate, []


def assess_database_case(
    session: Session,
    case_id: int,
    dispatch_plan_id: int,
    *,
    engine_commit: str | None = None,
) -> NativeV4Assessment:
    """Build and preflight one database-backed candidate without persisting a task."""

    candidate, database_issues = _database_candidate(
        session,
        case_id,
        dispatch_plan_id,
        engine_commit=engine_commit or getenv("ENGINE_COMMIT", "uncommitted"),
    )
    if candidate is None:
        readiness = V4ReadinessResponse(
            ready=False,
            solver_id=D1_SOLVER_ID,
            capability_id=D1_CAPABILITY_ID,
            runtime_adapter_id=D1_RUNTIME_ADAPTER_ID,
            errors=database_issues,
            warnings=[],
            snapshot_summary={"simulation_case_id": case_id},
            candidate_hashes={},
        )
        return NativeV4Assessment(readiness=readiness)
    assessment = assess_native_v4_snapshot(candidate)
    if database_issues:
        assessment.readiness.errors.extend(database_issues)
        assessment.readiness.ready = False
    return assessment


def freeze_v4_task_input(
    session: Session,
    case_id: int,
    dispatch_plan_id: int,
    *,
    engine_commit: str,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Freeze one ready v4 source plus its independently recomputable projection manifest."""

    assessment = assess_database_case(
        session,
        case_id,
        dispatch_plan_id,
        engine_commit=engine_commit,
    )
    if not assessment.readiness.ready or assessment.projection is None:
        details = "; ".join(
            f"{item.code}: {item.message}" for item in assessment.readiness.errors
        )
        raise ValueError(f"native v4 input is not ready: {details}")
    snapshot = assessment.projection.source_snapshot
    digest = snapshot_hash(snapshot)
    if digest != assessment.projection.manifest["source_input_hash"]:
        raise ValueError("native v4 authoritative input hash is not reproducible")
    return snapshot, digest, dict(assessment.projection.manifest)


def preview_from_assessment(assessment: NativeV4Assessment) -> V4PreviewResponse:
    """Create a bounded preview from an assessment without exposing the full snapshot."""

    snapshot = assessment.snapshot or {}
    branches = _collection(snapshot, "branches")
    structures = snapshot.get("structures")
    gates = structures.get("gates", []) if isinstance(structures, Mapping) else []
    pumps = structures.get("pumps", []) if isinstance(structures, Mapping) else []
    boundaries = snapshot.get("boundaries")
    upstream_range = _time_range(boundaries.get("upstream")) if isinstance(boundaries, Mapping) else (None, None)
    downstream_range = _time_range(boundaries.get("downstream")) if isinstance(boundaries, Mapping) else (None, None)
    numerical = snapshot.get("numerical_policy")
    return V4PreviewResponse(
        schema_version=str(snapshot.get("schema_version", "dayu.model-input.v4")),
        solver_id=D1_SOLVER_ID,
        capability_id=D1_CAPABILITY_ID,
        dataset_version_id=assessment.readiness.snapshot_summary.get("dataset_version_id"),
        simulation_case_id=assessment.readiness.snapshot_summary.get("simulation_case_id"),
        branch=dict(branches[0]) if branches and isinstance(branches[0], Mapping) else None,
        section_count=len(_collection(snapshot, "cross_sections")),
        gate={
            "id": (gates[0].get("identity") or {}).get("id"),
            "interface": gates[0].get("interface"),
        }
        if gates and isinstance(gates[0], Mapping)
        else None,
        pump={
            "id": (pumps[0].get("identity") or {}).get("id"),
            "section_id": pumps[0].get("section_id"),
            "outlet": pumps[0].get("outlet"),
        }
        if pumps and isinstance(pumps[0], Mapping)
        else None,
        boundary_time_range={
            "upstream_start": upstream_range[0],
            "upstream_end": upstream_range[1],
            "downstream_start": downstream_range[0],
            "downstream_end": downstream_range[1],
        },
        simulation_duration_seconds=float(numerical.get("duration_seconds"))
        if isinstance(numerical, Mapping)
        and isinstance(numerical.get("duration_seconds"), (int, float))
        else None,
        hashes=assessment.readiness.candidate_hashes,
        readiness=assessment.readiness,
        known_limitations=[str(item) for item in snapshot.get("known_limitations", [])]
        if isinstance(snapshot.get("known_limitations"), list)
        else list(D1_KNOWN_LIMITATIONS),
    )

