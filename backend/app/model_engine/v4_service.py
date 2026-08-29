"""Build, preflight, preview, and freeze native-v4 platform snapshots."""

from __future__ import annotations

from dataclasses import dataclass
import math
from re import fullmatch
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
from model.build_identity import RuntimeBuildIdentity, current_runtime_build_identity
from model.core.errors import HydraulicInputError
from model.provenance import CANONICALIZATION_ID, snapshot_hash
from model.solver.registry import (
    D1_CAPABILITY_ID,
    D1_RUNTIME_ADAPTER_ID,
    D1_SOLVER_ID,
    D3A_1_CAPABILITY_ID,
    D3A_2_CAPABILITY_ID,
    MODEL_INPUT_V4,
    registry_hash,
    resolve_capability,
    resolve_solver,
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


def _has_errors(issues: list[V4ReadinessIssue]) -> bool:
    """Return whether a mixed readiness finding list contains a blocking item."""

    return any(item.severity == "error" for item in issues)


def _is_sha256(value: object) -> bool:
    """Validate the canonical lowercase representation used by frozen identities."""

    return isinstance(value, str) and fullmatch(r"[0-9a-f]{64}", value) is not None


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
    selection = payload.get("solver_selection")
    capability_id = (
        selection.get("capability_id") if isinstance(selection, Mapping) else None
    )
    try:
        registration = resolve_solver(
            MODEL_INPUT_V4,
            solver_id=selection.get("solver_id") if isinstance(selection, Mapping) else None,
            capability_id=str(capability_id) if capability_id is not None else None,
            runtime_adapter_id=(
                selection.get("runtime_adapter_id")
                if isinstance(selection, Mapping)
                else None
            ),
        )
    except HydraulicInputError as exc:
        issues.append(
            _issue(
                "D3A_CAPABILITY_SELECTION_INVALID",
                str(exc),
                entity_type="solver_selection",
                field_path="solver_selection.capability_id",
            )
        )
        registration = None
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
        manning_n = section.get("default_manning_n")
        if capability_id == D1_CAPABILITY_ID and manning_n != 0.0:
            issues.append(
                _issue(
                    "D2_MANNING_NONZERO",
                    "D1 platform capability requires Manning n=0",
                    entity_type="cross_section",
                    entity_id=section.get("section_id"),
                    field_path="cross_sections.default_manning_n",
                )
            )
        if capability_id in {D3A_1_CAPABILITY_ID, D3A_2_CAPABILITY_ID} and (
            isinstance(manning_n, bool)
            or not isinstance(manning_n, (int, float))
            or not 0.0 < float(manning_n) <= 0.10
        ):
            issues.append(
                _issue(
                    "D3A_MANNING_OUT_OF_RANGE",
                    "D3A requires explicit effective Manning n in (0, 0.10]",
                    entity_type="cross_section",
                    entity_id=section.get("section_id"),
                    field_path="cross_sections.default_manning_n",
                )
            )
        if capability_id == D3A_2_CAPABILITY_ID:
            authority = (
                section.get("bed_elevation_m"),
                section.get("bed_elevation_source"),
                section.get("bed_elevation_confirmed_by"),
                section.get("bed_elevation_confirmed_at"),
            )
            if (
                isinstance(authority[0], bool)
                or not isinstance(authority[0], (int, float))
                or authority[1] not in {"surveyed", "design", "synthetic"}
                or not isinstance(authority[2], str)
                or not authority[2].strip()
                or authority[3] is None
            ):
                issues.append(
                    _issue(
                        "D3A_2_BED_AUTHORITY_UNCONFIRMED",
                        "D3A-2 requires explicit bed elevation with source, actor, and time",
                        entity_type="cross_section",
                        entity_id=section.get("section_id"),
                        field_path="cross_sections.bed_elevation_m",
                    )
                )
    if capability_id == D3A_2_CAPABILITY_ID:
        profile_signatures = {
            tuple(
                (
                    point.get("offset_m"),
                    round(
                        float(point.get("elevation_m"))
                        - float(section.get("bed_elevation_m")),
                        12,
                    ),
                )
                for point in section.get("points", [])
                if isinstance(point, Mapping)
                and isinstance(point.get("elevation_m"), (int, float))
                and not isinstance(point.get("elevation_m"), bool)
            )
            for section in sections
            if isinstance(section, Mapping)
            and isinstance(section.get("bed_elevation_m"), (int, float))
            and not isinstance(section.get("bed_elevation_m"), bool)
        }
    else:
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
                "selected platform capability requires identical absolute or local Profile geometry",
                entity_type="cross_section_profile",
                field_path="cross_sections.points",
            )
        )
    if capability_id == D3A_2_CAPABILITY_ID and all(
        isinstance(section, Mapping)
        and isinstance(section.get("bed_elevation_m"), (int, float))
        and not isinstance(section.get("bed_elevation_m"), bool)
        and isinstance(section.get("chainage_m"), (int, float))
        and not isinstance(section.get("chainage_m"), bool)
        for section in sections
    ):
        beds = tuple(float(section["bed_elevation_m"]) for section in sections)
        chainages = tuple(float(section["chainage_m"]) for section in sections)
        slopes = (
            tuple(
                (left_bed - right_bed) / (right_x - left_x)
                for left_bed, right_bed, left_x, right_x in zip(
                    beds, beds[1:], chainages, chainages[1:]
                )
            )
            if all(right > left for left, right in zip(chainages, chainages[1:]))
            else ()
        )
        if not slopes or any(value <= 0.0 for value in slopes) or any(
            not math.isclose(value, slopes[0], rel_tol=1.0e-10, abs_tol=1.0e-12)
            for value in slopes[1:]
        ):
            issues.append(
                _issue(
                    "D3A_2_BED_SLOPE_INVALID",
                    "D3A-2 requires one explicit strictly descending linear bed",
                    entity_type="cross_section",
                    field_path="cross_sections.bed_elevation_m",
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
    expected_validation_policy = (
        registration.runtime_adapter.validation_policy_version
        if registration is not None and registration.runtime_adapter is not None
        else None
    )
    if (
        not isinstance(validation, Mapping)
        or validation.get("validation_policy_version") != expected_validation_policy
        or validation.get("capability_id") != capability_id
    ):
        issues.append(
            _issue(
                "D2_VALIDATION_POLICY_UNREGISTERED",
                "native v4 validation policy must match the explicit capability",
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
    selection = payload.get("solver_selection")
    solver_id = (
        str(selection.get("solver_id"))
        if isinstance(selection, Mapping) and selection.get("solver_id") is not None
        else D1_SOLVER_ID
    )
    capability_id = (
        str(selection.get("capability_id"))
        if isinstance(selection, Mapping) and selection.get("capability_id") is not None
        else D1_CAPABILITY_ID
    )
    runtime_adapter_id = (
        str(selection.get("runtime_adapter_id"))
        if isinstance(selection, Mapping)
        and selection.get("runtime_adapter_id") is not None
        else D1_RUNTIME_ADAPTER_ID
    )
    readiness = V4ReadinessResponse(
        ready=not errors and projection is not None,
        solver_id=solver_id,
        capability_id=capability_id,
        runtime_adapter_id=runtime_adapter_id,
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


def dispatch_plan_hash_matches(snapshot: object, stored_hash: object) -> bool:
    """Recompute one frozen Dispatch Plan identity without trusting its metadata."""

    return (
        isinstance(snapshot, Mapping)
        and _is_sha256(stored_hash)
        and snapshot_hash(snapshot) == stored_hash
    )


def pump_curve_identity_payload(
    *,
    policy_id: object,
    unit: object,
    head_points: object,
    efficiency_points: object,
    source_revision: object,
) -> dict[str, object]:
    """Build the sole canonical Pump curve identity payload used by readiness."""

    return {
        "policy_id": policy_id,
        "unit": unit,
        "head_curve": {"points": head_points},
        "efficiency_curve": {"points": efficiency_points},
        "source_revision": source_revision,
    }


def _database_candidate(
    session: Session,
    case_id: int,
    dispatch_plan_id: int,
    *,
    build_identity: RuntimeBuildIdentity,
    capability_id: str,
) -> tuple[dict[str, Any] | None, list[V4ReadinessIssue]]:
    """Read only authoritative database rows and assemble one candidate snapshot."""

    issues: list[V4ReadinessIssue] = []
    capability = resolve_capability(capability_id)
    registration = resolve_solver(MODEL_INPUT_V4, capability_id=capability_id)
    if registration.runtime_adapter is None:
        raise ValueError("native-v4 capability has no registered runtime adapter")
    case = session.get(SimulationCase, case_id)
    if case is None:
        return None, [
            _issue("D2_CASE_NOT_FOUND", "simulation case does not exist", entity_id=case_id)
        ]
    dataset = session.get(DatasetVersion, case.dataset_version_id)
    if dataset is None or not _is_sha256(dataset.content_hash):
        issues.append(
            _issue(
                "D2_DATASET_IDENTITY_INCOMPLETE",
                "Dataset Version requires a canonical lowercase SHA-256 content hash",
                entity_type="dataset_version",
                entity_id=case.dataset_version_id,
                field_path="dataset_version.content_hash",
            )
        )
    elif dataset.status not in {"approved", "published"}:
        issues.append(
            _issue(
                "D2_DATASET_STATUS_NOT_AUTHORITATIVE",
                "native v4 requires an approved or published Dataset Version",
                entity_type="dataset_version",
                entity_id=dataset.id,
                field_path="dataset_version.status",
            )
        )
    else:
        issues.append(
            _issue(
                "D2_DATASET_HASH_PERSISTED_IDENTITY",
                "the approved GIS-core Dataset identity is trusted as persisted; RC1 does not claim a full D2 content recomputation",
                entity_type="dataset_version",
                entity_id=dataset.id,
                field_path="dataset_version.content_hash",
                severity="warning",
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
    plan_structurally_valid = (
        plan is not None
        and plan.status == "frozen"
        and plan.simulation_case_id == case.id
        and plan.dataset_version_id == case.dataset_version_id
        and isinstance(plan.frozen_snapshot, Mapping)
        and _is_sha256(plan.frozen_snapshot_hash)
    )
    if not plan_structurally_valid:
        issues.append(
            _issue(
                "D2_CONTROL_PLAN_NOT_FROZEN",
                "v4 requires one frozen Dispatch Plan for the same case and Dataset Version",
                entity_type="dispatch_plan",
                entity_id=dispatch_plan_id,
                field_path="control_plan",
            )
        )
    elif not dispatch_plan_hash_matches(
        plan.frozen_snapshot, plan.frozen_snapshot_hash
    ):
        issues.append(
            _issue(
                "D2_CONTROL_PLAN_HASH_MISMATCH",
                "stored Dispatch Plan snapshot does not match its frozen hash",
                entity_type="dispatch_plan",
                entity_id=dispatch_plan_id,
                field_path="control_plan.frozen_snapshot_hash",
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
    if _has_errors(issues):
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
    if capability_id == D1_CAPABILITY_ID and configured_manning != 0.0:
        issues.append(
            _issue(
                "D2_MANNING_NONZERO",
                "SimulationCase native-v4 configuration must explicitly set Manning n=0",
                field_path="simulation_case.v4_configuration.default_manning_n",
            )
        )
    if capability_id in {D3A_1_CAPABILITY_ID, D3A_2_CAPABILITY_ID} and (
        isinstance(configured_manning, bool)
        or not isinstance(configured_manning, (int, float))
        or not 0.0 < float(configured_manning) <= 0.10
    ):
        issues.append(
            _issue(
                "D3A_MANNING_OUT_OF_RANGE",
                "D3A native-v4 configuration requires Manning n in (0, 0.10]",
                field_path="simulation_case.v4_configuration.default_manning_n",
            )
        )
    for section in sections:
        profiles = list(
            session.scalars(
                select(HydraulicCrossSectionProfile)
                .where(
                    HydraulicCrossSectionProfile.cross_section_id == section.id,
                    HydraulicCrossSectionProfile.is_active.is_(True),
                )
                .order_by(HydraulicCrossSectionProfile.id)
            ).all()
        )
        if not profiles:
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
        if len(profiles) > 1:
            issues.append(
                _issue(
                    "D2_MULTIPLE_ACTIVE_PROFILES",
                    "cross section has more than one active Profile; selection is ambiguous",
                    entity_type="cross_section",
                    entity_id=section.id,
                    field_path="cross_sections.profile",
                )
            )
            continue
        profile = profiles[0]
        if not _is_sha256(profile.profile_hash):
            issues.append(
                _issue(
                    "D2_PROFILE_IDENTITY_INCOMPLETE",
                    "active Profile requires a canonical lowercase SHA-256 identity",
                    entity_type="cross_section_profile",
                    entity_id=profile.id,
                    field_path="cross_sections.profile.profile_hash",
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
        section_row = {
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
        if capability_id == D3A_2_CAPABILITY_ID:
            if (
                section.bed_elevation_m is None
                or section.bed_elevation_source
                not in {"surveyed", "design", "synthetic"}
                or not section.bed_elevation_confirmed_by
                or section.bed_elevation_confirmed_at is None
            ):
                issues.append(
                    _issue(
                        "D3A_2_BED_AUTHORITY_UNCONFIRMED",
                        "historical Cross Section has no confirmed authoritative bed elevation",
                        entity_type="cross_section",
                        entity_id=section.id,
                        field_path="cross_sections.bed_elevation_m",
                    )
                )
            else:
                section_row.update(
                    {
                        "bed_elevation_m": section.bed_elevation_m,
                        "bed_elevation_source": section.bed_elevation_source,
                        "bed_elevation_confirmed_by": (
                            section.bed_elevation_confirmed_by
                        ),
                        "bed_elevation_confirmed_at": (
                            section.bed_elevation_confirmed_at
                        ),
                    }
                )
        section_rows.append(section_row)
        profile_rows.append(
            {
                "id": profile.id,
                "cross_section_id": section.id,
                "profile_hash": profile.profile_hash,
                "profile_hash_trust": "persisted/import-validated",
            }
        )
    if profile_rows:
        issues.append(
            _issue(
                "D2_PROFILE_HASH_PERSISTED_IDENTITY",
                "Profile hashes are trusted as persisted/import-validated because historical import hash policies are not unambiguously reconstructable",
                entity_type="cross_section_profile",
                field_path="cross_section_profiles.profile_hash",
                severity="warning",
            )
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
    upstream_candidates = [
        item for item in boundaries if item.boundary_type == "upstream_flow"
    ]
    downstream_candidates = [
        item for item in boundaries if item.boundary_type == "downstream_water_level"
    ]
    if len(upstream_candidates) != 1 or len(downstream_candidates) != 1:
        issues.append(
            _issue(
                "D2_BOUNDARY_CARDINALITY_INVALID",
                "case requires exactly one upstream-flow and one downstream-water-level boundary",
                entity_type="boundary_condition",
                field_path="boundaries",
            )
        )
    upstream = upstream_candidates[0] if len(upstream_candidates) == 1 else None
    downstream = downstream_candidates[0] if len(downstream_candidates) == 1 else None
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
        or upstream.dataset_version_id != case.dataset_version_id
        or downstream.dataset_version_id != case.dataset_version_id
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
    gate_id = plan_config.get("gate_id")
    pump_id = plan_config.get("pump_id")
    if (
        isinstance(gate_id, bool)
        or not isinstance(gate_id, int)
        or gate_id <= 0
        or isinstance(pump_id, bool)
        or not isinstance(pump_id, int)
        or pump_id <= 0
    ):
        issues.append(
            _issue(
                "D2_STRUCTURE_SCOPE_MISSING",
                "frozen native_v4 controls must explicitly bind gate_id and pump_id",
                entity_type="dispatch_plan",
                entity_id=plan.id,
                field_path="control_plan.native_v4",
            )
        )
        return None, issues
    gate = session.scalar(
        select(Gate).where(
            Gate.id == gate_id,
            Gate.dataset_version_id == case.dataset_version_id,
        )
    )
    pump = session.scalar(
        select(Pump).where(
            Pump.id == pump_id,
            Pump.dataset_version_id == case.dataset_version_id,
        )
    )
    if gate is None or pump is None:
        issues.append(
            _issue(
                "D2_STRUCTURE_SCOPE_INVALID",
                "frozen Gate/Pump identity does not exist in the Case Dataset Version",
                entity_type="structure",
                field_path="control_plan.native_v4",
            )
        )
        return None, issues
    section_ids = {item.id for item in sections}
    if (
        gate.hydraulic_upstream_section_id not in section_ids
        or gate.hydraulic_downstream_section_id not in section_ids
        or pump.hydraulic_section_id not in section_ids
    ):
        issues.append(
            _issue(
                "D2_STRUCTURE_BRANCH_MISMATCH",
                "frozen Gate/Pump hydraulic bindings must belong to the selected Branch",
                entity_type="structure",
                field_path="structures",
            )
        )
    if _has_errors(issues):
        return None, issues
    gate_control = plan_config.get("gate_control")
    pump_control = plan_config.get("pump_control")
    head_points = _curve_points(pump.head_curve, ordinate="head_m")
    efficiency_points = _curve_points(pump.efficiency_curve, ordinate="efficiency")
    normalized_curve = pump_curve_identity_payload(
        policy_id=pump.curve_policy_id,
        unit=pump.curve_unit,
        head_points=head_points,
        efficiency_points=efficiency_points,
        source_revision=pump.curve_source_revision,
    )
    if (
        head_points is None
        or efficiency_points is None
        or pump.curve_policy_id != "d1-piecewise-linear-qh-qeta-si-v1"
        or pump.curve_unit != "SI"
        or not isinstance(pump.curve_source_revision, str)
        or not pump.curve_source_revision.strip()
        or not _is_sha256(pump.curve_hash)
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
            "solver_id": registration.solver_id,
            "capability_id": capability.capability_id,
            "runtime_adapter_id": registration.runtime_adapter.runtime_adapter_id,
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
            "policy_id": {
                D1_CAPABILITY_ID: "d1-gate-pump-control-v1",
                D3A_1_CAPABILITY_ID: "d3a-1-gate-pump-control-v1",
                D3A_2_CAPABILITY_ID: "d3a-2-gate-pump-control-v1",
            }[capability_id],
        },
        "numerical_policy": numerical,
        "validation": {
            "validation_policy_version": (
                registration.runtime_adapter.validation_policy_version
            ),
            "capability_id": capability.capability_id,
            "water_balance_tolerance": numerical.get("water_balance_tolerance")
            if isinstance(numerical, Mapping)
            else None,
        },
        "provenance": {
            **build_identity.provenance(),
            "canonicalization_id": CANONICALIZATION_ID,
            "registry_hash": registry_hash(),
        },
        "capability_scope": list(capability.scope),
        "capability_exclusions": list(capability.exclusions),
        "case_notes": list(case_config.get("case_notes", []))
        if isinstance(case_config.get("case_notes", []), list)
        else case_config.get("case_notes"),
        "known_limitations": list(capability.warnings),
    }
    return candidate, issues


def assess_database_case(
    session: Session,
    case_id: int,
    dispatch_plan_id: int,
    *,
    build_identity: RuntimeBuildIdentity | None = None,
    capability_id: str = D1_CAPABILITY_ID,
) -> NativeV4Assessment:
    """Build and preflight one database-backed candidate without persisting a task."""

    runtime_identity = build_identity or current_runtime_build_identity()
    candidate, database_issues = _database_candidate(
        session,
        case_id,
        dispatch_plan_id,
        build_identity=runtime_identity,
        capability_id=capability_id,
    )
    if candidate is None:
        errors = [item for item in database_issues if item.severity == "error"]
        warnings = [item for item in database_issues if item.severity == "warning"]
        try:
            registration = resolve_solver(MODEL_INPUT_V4, capability_id=capability_id)
            adapter_id = (
                registration.runtime_adapter.runtime_adapter_id
                if registration.runtime_adapter is not None
                else "unregistered"
            )
            solver_id = registration.solver_id
        except HydraulicInputError:
            solver_id = D1_SOLVER_ID
            adapter_id = "unregistered"
        readiness = V4ReadinessResponse(
            ready=False,
            solver_id=solver_id,
            capability_id=capability_id,
            runtime_adapter_id=adapter_id,
            errors=errors,
            warnings=warnings,
            snapshot_summary={"simulation_case_id": case_id},
            candidate_hashes={},
        )
        return NativeV4Assessment(readiness=readiness)
    assessment = assess_native_v4_snapshot(candidate)
    if not runtime_identity.verified:
        assessment.readiness.warnings.append(
            _issue(
                "D2_RUNTIME_BUILD_UNVERIFIED",
                "development runtime has no verified immutable Git build identity",
                entity_type="runtime_build",
                field_path="provenance.build_verified",
                severity="warning",
            )
        )
    if database_issues:
        assessment.readiness.errors.extend(
            item for item in database_issues if item.severity == "error"
        )
        assessment.readiness.warnings.extend(
            item for item in database_issues if item.severity == "warning"
        )
        assessment.readiness.ready = not assessment.readiness.errors
    return assessment


def freeze_v4_task_input(
    session: Session,
    case_id: int,
    dispatch_plan_id: int,
    *,
    build_identity: RuntimeBuildIdentity,
    capability_id: str,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Freeze one ready v4 source plus its independently recomputable projection manifest."""

    assessment = assess_database_case(
        session,
        case_id,
        dispatch_plan_id,
        build_identity=build_identity,
        capability_id=capability_id,
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
        solver_id=assessment.readiness.solver_id,
        capability_id=assessment.readiness.capability_id,
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
        capability_scope=[str(item) for item in snapshot.get("capability_scope", [])]
        if isinstance(snapshot.get("capability_scope"), list)
        else list(resolve_capability(assessment.readiness.capability_id).scope),
        capability_exclusions=[
            str(item) for item in snapshot.get("capability_exclusions", [])
        ]
        if isinstance(snapshot.get("capability_exclusions"), list)
        else list(resolve_capability(assessment.readiness.capability_id).exclusions),
        case_notes=[str(item) for item in snapshot.get("case_notes", [])]
        if isinstance(snapshot.get("case_notes"), list)
        else [],
        known_limitations=[str(item) for item in snapshot.get("known_limitations", [])]
        if isinstance(snapshot.get("known_limitations"), list)
        else list(resolve_capability(assessment.readiness.capability_id).warnings),
    )
