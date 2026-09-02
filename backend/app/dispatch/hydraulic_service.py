"""Compile and freeze development-only hydraulic dispatch plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from math import isclose
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.dispatch.assets import lock_plan_asset_rows
from app.dispatch.hydraulic_assets import (
    HydraulicAssetNormalization,
    HydraulicControlAsset,
    normalize_plan_hydraulic_assets,
)
from app.dispatch.hydraulic_schemas import (
    HydraulicCompileIssue,
    HydraulicPlanCompileReport,
    HydraulicPlanCompileRequest,
    HydraulicPlanFreezeResponse,
    HydraulicPreviewJobRecord,
)
from app.dispatch.hydraulic_snapshot import (
    CONTROL_COMPILER_BUNDLE_VERSION,
    build_hydraulic_plan_snapshot,
)
from app.dispatch.validator import validate_plan
from app.gis.models import (
    DatasetVersion,
    DispatchAction,
    DispatchEvent,
    DispatchPlan,
    DispatchRule,
    DispatchRun,
    HydraulicTaskSectionResult,
    SimulationTask,
    StructureResult,
)
from app.hydraulic.models import HydraulicCrossSection
from app.model_engine.hydraulic_1d_service import build_hydraulic_1d_model
from model.control.compiler import (
    HydraulicControlCompileReport,
    HydraulicControlCompiler,
)
from model.control.drtc import (
    DRTCCompileReport,
    DRTCCompiler,
    controlled_runtime_accepted,
)
from model.control.replay import ReplayAsset
from model.control.rules import ThresholdRule
from model.control.schedule import ScheduledAction
from model.hydraulic_1d.contracts import Hydraulic1DModel
from model.hydraulic_1d.controlled import (
    ControlRuntimeSelection,
    ControlledExecutionSettings,
    ControlledHydraulic1DRun,
    ControlledHydraulicResult,
    DispatchPlanSnapshot,
    EngineSelection,
)
from model.hydraulic_1d.capabilities import (
    CapabilityExecutionPolicy,
    capabilities_for,
    compatibility_report,
    required_capabilities,
)
from model.hydraulic_1d.dflow_fm.config import DFlowRuntimeConfig
from model.hydraulic_1d.dflow_fm.adapter import DFlowFMModelValidator
from model.hydraulic_1d.dflow_fm.runtime import create_dflow_runtime
from model.hydraulic_1d.dflow_fm.structures import DFlowFMStructureMapper
from model.hydraulic_1d.errors import Hydraulic1DError
from model.hydraulic_1d.registry import (
    CONTROLLED_HYDRAULIC_1D_RUN_SCHEMA,
    DFLOW_FM_ENGINE_ID,
    DFLOW_FM_ENGINE_VERSION,
    DFLOW_FM_SOLVER_ID,
    DFLOW_FM_UPSTREAM_COMMIT,
    controlled_task_engine_provenance,
    selected_engine_hash,
)
from model.hydraulic_1d.structures import GateHydraulicSpec, PumpHydraulicSpec
from model.provenance import canonical_json, snapshot_hash


class HydraulicDispatchNotFoundError(LookupError):
    """Raised when a hydraulic dispatch plan does not exist."""


class HydraulicDispatchStateError(RuntimeError):
    """Raised when compile/freeze violates the explicit v3 lifecycle."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "HYDRAULIC_DISPATCH_STATE_ERROR",
    ) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class _CompileContext:
    report: HydraulicPlanCompileReport
    model: Hydraulic1DModel | None
    normalization: HydraulicAssetNormalization
    manual_report: HydraulicControlCompileReport | None
    drtc_report: DRTCCompileReport


def _children(
    session: Session,
    plan_id: int,
) -> tuple[list[DispatchAction], list[DispatchRule]]:
    actions = list(
        session.scalars(
            select(DispatchAction)
            .where(DispatchAction.plan_id == plan_id)
            .order_by(
                DispatchAction.time_seconds,
                DispatchAction.sequence,
                DispatchAction.id,
            )
        ).all()
    )
    rules = list(
        session.scalars(
            select(DispatchRule)
            .where(DispatchRule.plan_id == plan_id)
            .order_by(DispatchRule.priority.desc(), DispatchRule.id)
        ).all()
    )
    return actions, rules


def _scheduled_actions(rows: list[DispatchAction]) -> tuple[ScheduledAction, ...]:
    return tuple(
        ScheduledAction(
            id=item.id,
            time_seconds=float(item.time_seconds),
            structure_type=item.structure_type,
            structure_id=int(item.gate_id if item.structure_type == "gate" else item.pump_id),
            command_type=item.command_type,
            target_value=float(item.target_value),
            interpolation=item.interpolation,
            priority=int(item.priority),
        )
        for item in rows
        if (item.gate_id if item.structure_type == "gate" else item.pump_id) is not None
    )


def _threshold_rules(rows: list[DispatchRule]) -> tuple[ThresholdRule, ...]:
    return tuple(
        ThresholdRule(
            id=item.id,
            name=item.name,
            enabled=item.enabled,
            observation_type=item.observation_type,
            observation_object_id=item.observation_object_id,
            operator=item.operator,
            threshold=float(item.threshold),
            hysteresis=float(item.hysteresis),
            minimum_hold_seconds=float(item.minimum_hold_seconds),
            cooldown_seconds=float(item.cooldown_seconds),
            action_template=dict(item.action_template),
            priority=int(item.priority),
        )
        for item in rows
    )


def _runtime_readiness(
    requested_mode: str,
    requested_timeout_seconds: float,
) -> tuple[bool, str, dict[str, Any] | None]:
    try:
        config = DFlowRuntimeConfig.from_environment()
        expected_mode = "cli" if requested_mode == "external" else "container"
        if config.mode != expected_mode:
            return (
                False,
                (
                    "DFLOW_RUNTIME_BLOCKED: requested runtime mode "
                    f"{requested_mode!r} requires configured mode {expected_mode!r}, "
                    f"observed {config.mode!r}"
                ),
                None,
            )
        if not isclose(
            config.timeout_seconds,
            requested_timeout_seconds,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        ):
            return (
                False,
                (
                    "DFLOW_RUNTIME_BLOCKED: frozen timeout "
                    f"{requested_timeout_seconds:g}s does not match configured "
                    f"DFLOW_TIMEOUT {config.timeout_seconds:g}s"
                ),
                None,
            )
        runtime = create_dflow_runtime(config)
        available, detail, provenance = runtime.verified_provenance()
        return available, detail, provenance
    except (Hydraulic1DError, ValueError, OSError) as exc:
        return False, f"DFLOW_RUNTIME_BLOCKED: {exc}", None


def _issue_from_exception(
    stage: str,
    exc: Exception,
) -> HydraulicCompileIssue:
    return HydraulicCompileIssue(
        stage=stage,  # type: ignore[arg-type]
        code=str(getattr(exc, "code", type(exc).__name__.upper())),
        message=str(exc),
        field_path=getattr(exc, "field_path", None),
    )


def _observation_issues(
    rules: tuple[ThresholdRule, ...],
    request: HydraulicPlanCompileRequest,
) -> tuple[list[HydraulicCompileIssue], list[HydraulicCompileIssue]]:
    required = {
        (rule.observation_type, rule.observation_object_id)
        for rule in rules
        if rule.enabled and rule.observation_type != "elapsed_time"
    }
    provided = {
        (item.observation_type, item.observation_object_id) for item in request.observation_bindings
    }
    issues = [
        HydraulicCompileIssue(
            stage="observation",
            code="CONTROL_OBSERVATION_BINDING_MISSING",
            message="enabled hydraulic rule requires one exact D-Flow observation binding",
            field_path=f"{kind}:{object_id}",
        )
        for kind, object_id in sorted(required - provided)
    ]
    warnings = [
        HydraulicCompileIssue(
            stage="observation",
            code="CONTROL_OBSERVATION_BINDING_UNUSED",
            message="binding is explicit but no enabled rule consumes it",
            field_path=f"{kind}:{object_id}",
        )
        for kind, object_id in sorted(provided - required)
    ]
    return issues, warnings


def _observation_inventory_issues(
    model: Hydraulic1DModel,
    normalization: HydraulicAssetNormalization,
    request: HydraulicPlanCompileRequest,
) -> list[HydraulicCompileIssue]:
    """Bind every requested source to an observation the adapter actually emits."""

    sections = {item.id: item for item in model.cross_sections}
    controls = {
        (item.structure_type, item.structure_id): item for item in normalization.control_bindings
    }
    gates = {item.structure_id: item for item in normalization.gate_specs}
    pumps = {item.structure_id: item for item in normalization.pump_specs}
    issues: list[HydraulicCompileIssue] = []
    for binding in request.observation_bindings:
        source_ids = (
            (binding.upstream_source_id, binding.downstream_source_id)
            if binding.source_kind == "oriented_observation_pair"
            else (binding.source_id,)
        )
        missing = [
            str(source_id)
            for source_id in source_ids
            if source_id is None or source_id not in sections
        ]
        if missing:
            issues.append(
                HydraulicCompileIssue(
                    stage="observation",
                    code="CONTROL_OBSERVATION_SOURCE_NOT_EMITTED",
                    message=(
                        "D-Flow adapter emits observation points/cross sections only for "
                        "frozen HydraulicCrossSection IDs; missing " + ", ".join(missing)
                    ),
                    field_path=(f"{binding.observation_type}:{binding.observation_object_id}"),
                )
            )
            continue
        if binding.observation_type == "section_water_level" and binding.source_id != str(
            binding.observation_object_id
        ):
            issues.append(
                HydraulicCompileIssue(
                    stage="observation",
                    code="CONTROL_SECTION_OBSERVATION_ID_MISMATCH",
                    message="section_water_level must bind the exact requested Cross Section ID",
                    field_path=(f"{binding.observation_type}:{binding.observation_object_id}"),
                )
            )
            continue
        control = controls.get(
            (
                "gate" if binding.observation_type == "gate_head_difference" else "pump",
                binding.observation_object_id,
            )
        )
        if binding.observation_type == "gate_head_difference":
            spec = gates.get(control.native_structure_id) if control is not None else None
            upstream = sections[str(binding.upstream_source_id)]
            downstream = sections[str(binding.downstream_source_id)]
            if spec is None or not (
                upstream.branch_id == spec.branch_id == downstream.branch_id
                and upstream.chainage_m < downstream.chainage_m
                and upstream.chainage_m <= spec.chainage_m <= downstream.chainage_m
            ):
                issues.append(
                    HydraulicCompileIssue(
                        stage="observation",
                        code="GATE_HEAD_OBSERVATION_ORIENTATION_INVALID",
                        message=(
                            "gate head sources must be ordered upstream/downstream on the "
                            "Gate branch and straddle its frozen chainage"
                        ),
                        structure_type="gate",
                        structure_id=binding.observation_object_id,
                    )
                )
        elif binding.observation_type == "pump_intake_level":
            spec = pumps.get(control.native_structure_id) if control is not None else None
            source = sections[str(binding.source_id)]
            orientation_valid = spec is not None and source.branch_id == spec.branch_id
            if orientation_valid and spec is not None:
                orientation_valid = (
                    source.chainage_m <= spec.chainage_m
                    if spec.orientation.value == "positive"
                    else source.chainage_m >= spec.chainage_m
                )
            if not orientation_valid:
                issues.append(
                    HydraulicCompileIssue(
                        stage="observation",
                        code="PUMP_INTAKE_OBSERVATION_ORIENTATION_INVALID",
                        message=(
                            "pump intake source must lie on the frozen intake side of the "
                            "Pump branch orientation"
                        ),
                        structure_type="pump",
                        structure_id=binding.observation_object_id,
                    )
                )
    return issues


def _compile(
    session: Session,
    plan: DispatchPlan,
    request: HydraulicPlanCompileRequest,
) -> _CompileContext:
    issues: list[HydraulicCompileIssue] = []
    warnings: list[HydraulicCompileIssue] = [
        HydraulicCompileIssue(
            stage="plan",
            code="SYNTHETIC_NUMERICAL_ONLY",
            message=(
                "development hydraulic preview is not real engineering validation "
                "and cannot command equipment"
            ),
        )
    ]
    planning = validate_plan(session, plan)
    plan_valid = planning.valid and plan.status == "validated"
    if plan.snapshot_target != "hydraulic_v3" or plan.cloned_from_plan_id is None:
        issues.append(
            HydraulicCompileIssue(
                stage="plan",
                code="HYDRAULIC_V3_CLONE_REQUIRED",
                message="clone a frozen v2/v3 plan through hydraulic-clone before compile",
            )
        )
        plan_valid = False
    if plan.status != "validated":
        issues.append(
            HydraulicCompileIssue(
                stage="plan",
                code="PLAN_NOT_VALIDATED",
                message="hydraulic compile requires the explicit validated lifecycle state",
            )
        )
    issues.extend(
        HydraulicCompileIssue(
            stage="plan",
            code="PLAN_VALIDATION_FAILED",
            message=message,
        )
        for message in planning.errors
    )
    warnings.extend(
        HydraulicCompileIssue(
            stage="plan",
            code="PLAN_VALIDATION_WARNING",
            message=message,
        )
        for message in planning.warnings
    )

    actions, rule_rows = _children(session, plan.id)
    rules: tuple[ThresholdRule, ...]
    try:
        rules = _threshold_rules(rule_rows)
    except ValueError as exc:
        rules = ()
        issues.append(_issue_from_exception("drtc", exc))

    normalization = normalize_plan_hydraulic_assets(
        session,
        plan,
        request.initial_actuator_state,
    )
    issues.extend(
        HydraulicCompileIssue(
            stage=(
                "gate_mapping"
                if item.structure_type == "gate"
                else ("pump_mapping" if item.structure_type == "pump" else "asset_mapping")
            ),
            code=item.code,
            message=item.message,
            field_path=item.field_path,
            structure_type=item.structure_type,
            structure_id=item.legacy_asset_id,
        )
        for item in normalization.issues
        if item.blocking
    )

    structure_mapping_valid = normalization.ready
    if structure_mapping_valid:
        mapper = DFlowFMStructureMapper()
        for spec in normalization.gate_specs:
            try:
                mapper.map_gate(spec)
            except (Hydraulic1DError, ValueError) as exc:
                structure_mapping_valid = False
                issue = _issue_from_exception("gate_mapping", exc)
                issues.append(
                    issue.model_copy(
                        update={
                            "structure_type": "gate",
                        }
                    )
                )
        for spec in normalization.pump_specs:
            try:
                mapper.map_pump(spec)
            except (Hydraulic1DError, ValueError) as exc:
                structure_mapping_valid = False
                issue = _issue_from_exception("pump_mapping", exc)
                issues.append(
                    issue.model_copy(
                        update={
                            "structure_type": "pump",
                        }
                    )
                )

    model: Hydraulic1DModel | None = None
    hydraulic_model_hash: str | None = None
    capability_valid = False
    capability_facts = tuple(
        item.to_dict()
        for item in capabilities_for(DFLOW_FM_ENGINE_ID, DFLOW_FM_ENGINE_VERSION)
        if item.feature in {"GATE", "PUMP", "DYNAMIC_CONTROL", "D_RTC"}
    )
    try:
        candidate_model = build_hydraulic_1d_model(
            session,
            plan.simulation_case_id,
            {"duration_seconds": plan.duration_seconds},
            engine_id=DFLOW_FM_ENGINE_ID,
        )
        DFlowFMModelValidator().validate(
            candidate_model,
            gate_specs=normalization.gate_specs,
            pump_specs=normalization.pump_specs,
        )
        model = candidate_model
        hydraulic_model_hash = snapshot_hash(model.model_dump(mode="json"))
        physical_capability_report = compatibility_report(
            model,
            engine=DFLOW_FM_ENGINE_ID,
            engine_version=DFLOW_FM_ENGINE_VERSION,
            execution_policy=CapabilityExecutionPolicy.SYNTHETIC_NUMERICAL_ONLY,
            development_mode=True,
            production_mode=False,
        )
        capability_valid = bool(physical_capability_report["compatible"])
        physical_features = set(required_capabilities(model))
        capability_facts = tuple(
            item.to_dict()
            for item in capabilities_for(DFLOW_FM_ENGINE_ID, DFLOW_FM_ENGINE_VERSION)
            if item.feature in physical_features | {"DYNAMIC_CONTROL", "D_RTC"}
        )
        issues.extend(
            HydraulicCompileIssue(
                stage="capability",
                code="DFLOW_DEVELOPMENT_CAPABILITY_BLOCKED",
                message=str(item["reason"]),
                field_path=str(item["feature"]),
            )
            for item in physical_capability_report["issues"]
        )
    except (LookupError, Hydraulic1DError, ValueError) as exc:
        issues.append(_issue_from_exception("hydraulic_model", exc))

    manual_report: HydraulicControlCompileReport | None = None
    if normalization.ready:
        try:
            manual_report = HydraulicControlCompiler().compile(
                actions=_scheduled_actions(actions),
                assets=tuple(
                    ReplayAsset(
                        structure_type=item.structure_type,
                        structure_id=item.structure_id,
                        constraints=dict(item.constraints),
                    )
                    for item in normalization.control_assets
                ),
                initial_states=request.initial_actuator_state,
                bindings=normalization.control_bindings,
                duration_seconds=float(plan.duration_seconds),
            )
            issues.extend(
                HydraulicCompileIssue(
                    stage="manual_control",
                    code=item.code,
                    message=item.message,
                    structure_type=item.structure_type,
                    structure_id=item.structure_id,
                )
                for item in manual_report.issues
            )
        except (Hydraulic1DError, ValueError) as exc:
            issues.append(_issue_from_exception("manual_control", exc))
    manual_valid = manual_report is not None and manual_report.status == "COMPILED"

    manual_actuators = tuple(
        sorted({(item.structure_type, item.structure_id) for item in _scheduled_actions(actions)})
    )
    drtc_report = DRTCCompiler().compile(
        rules,
        manual_actuators=manual_actuators,
    )
    if drtc_report.status != "COMPILED":
        issues.extend(
            HydraulicCompileIssue(
                stage="drtc",
                code="DRTC_RULE_SEMANTICS_UNSUPPORTED",
                message=item.unsupported_reason or "D-RTC rule is unsupported",
                field_path=f"dispatch_rule:{item.rule_id}",
            )
            for item in drtc_report.rules
            if item.status == "UNSUPPORTED"
        )
    observation_issues, observation_warnings = _observation_issues(rules, request)
    inventory_issues = (
        _observation_inventory_issues(model, normalization, request) if model is not None else []
    )
    issues.extend(observation_issues)
    issues.extend(inventory_issues)
    warnings.extend(observation_warnings)

    runtime_available, runtime_detail, runtime_provenance = _runtime_readiness(
        request.runtime_mode,
        float(request.timeout_seconds),
    )
    if not runtime_available:
        issues.append(
            HydraulicCompileIssue(
                stage="runtime",
                code="DFLOW_RUNTIME_BLOCKED",
                message=runtime_detail,
            )
        )
    runtime_control_accepted = controlled_runtime_accepted()
    if not runtime_control_accepted:
        warnings.append(
            HydraulicCompileIssue(
                stage="drtc",
                code="DRTC_RUNTIME_ACCEPTANCE_BLOCKED",
                message=(
                    "the coupled DIMR/FBC execution path has no accepted synthetic "
                    "runtime benchmark and cannot create a preview job"
                ),
            )
        )

    hydraulic_model_valid = model is not None
    drtc_valid = drtc_report.status == "COMPILED"
    observation_valid = not observation_issues and not inventory_issues
    ready_to_freeze = all(
        (
            plan_valid,
            hydraulic_model_valid,
            capability_valid,
            structure_mapping_valid,
            manual_valid,
            drtc_valid,
            observation_valid,
        )
    )
    payload: dict[str, Any] = {
        "plan_id": plan.id,
        "plan_valid": plan_valid,
        "hydraulic_model_valid": hydraulic_model_valid,
        "capability_valid": capability_valid,
        "structure_mapping_valid": structure_mapping_valid,
        "manual_control_valid": manual_valid,
        "drtc_valid": drtc_valid,
        "observation_contract_valid": observation_valid,
        "ready_to_freeze": ready_to_freeze,
        "runtime_available": runtime_available,
        "controlled_runtime_accepted": runtime_control_accepted,
        "ready_to_run": (ready_to_freeze and runtime_available and runtime_control_accepted),
        "runtime_detail": runtime_detail,
        "runtime_provenance": runtime_provenance,
        "capabilities": list(capability_facts),
        "hydraulic_model_snapshot_hash": hydraulic_model_hash,
        "manual_control_report": (manual_report.model_dump(mode="json") if manual_report else None),
        "drtc_compile_report": drtc_report.model_dump(mode="json"),
        "issues": [item.model_dump(mode="json") for item in issues],
        "warnings": [item.model_dump(mode="json") for item in warnings],
    }
    report_without_hash = HydraulicPlanCompileReport(**payload, report_hash="")
    report_hash = snapshot_hash(
        report_without_hash.model_dump(mode="json", exclude={"report_hash"})
    )
    report = report_without_hash.model_copy(update={"report_hash": report_hash})
    return _CompileContext(report, model, normalization, manual_report, drtc_report)


def compile_hydraulic_plan(
    session: Session,
    plan_id: int,
    request: HydraulicPlanCompileRequest,
) -> HydraulicPlanCompileReport:
    """Return a full report without mutating plan, task, run, or workspace state."""

    plan = session.get(DispatchPlan, plan_id)
    if plan is None:
        raise HydraulicDispatchNotFoundError("dispatch plan does not exist")
    return _compile(session, plan, request).report


def freeze_hydraulic_plan(
    session: Session,
    plan_id: int,
    request: HydraulicPlanCompileRequest,
) -> HydraulicPlanFreezeResponse:
    """Recompile under a plan/asset lock and persist one immutable v3 snapshot."""

    # Discover the snapshot domain without taking a conflicting plan-first lock.
    # Dataset content writers lock DatasetVersion before mutating children, so
    # freeze uses the same ordering to prevent a mixed READ COMMITTED snapshot.
    candidate = session.get(DispatchPlan, plan_id)
    if candidate is None:
        raise HydraulicDispatchNotFoundError("dispatch plan does not exist")
    dataset_version_id = candidate.dataset_version_id
    dataset_version = session.scalar(
        select(DatasetVersion)
        .where(DatasetVersion.id == dataset_version_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if dataset_version is None:
        raise HydraulicDispatchStateError(
            "hydraulic plan dataset version does not exist"
        )
    plan = session.scalar(
        select(DispatchPlan)
        .where(DispatchPlan.id == plan_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if plan is None:
        raise HydraulicDispatchNotFoundError("dispatch plan does not exist")
    if plan.dataset_version_id != dataset_version_id:
        raise HydraulicDispatchStateError(
            "hydraulic plan dataset version changed while acquiring snapshot locks"
        )
    if plan.status != "validated":
        raise HydraulicDispatchStateError("only a validated hydraulic_v3 clone can be frozen")
    lock_plan_asset_rows(session, plan)
    context = _compile(session, plan, request)
    if not context.report.ready_to_freeze:
        raise HydraulicDispatchStateError(
            "hydraulic compile is not freeze-ready: "
            + "; ".join(
                f"{item.code}: {item.message}"
                for item in context.report.issues
                if item.stage != "runtime"
            )
        )
    if (
        context.model is None
        or context.manual_report is None
        or context.report.hydraulic_model_snapshot_hash is None
    ):
        raise HydraulicDispatchStateError("hydraulic compile context is incomplete")
    try:
        frozen, digest, control_contract_hash = build_hydraulic_plan_snapshot(
            session,
            plan,
            request=request,
            hydraulic_model=context.model,
            hydraulic_model_snapshot_hash=(context.report.hydraulic_model_snapshot_hash),
            capability_facts=context.report.capabilities,
            gate_specs=context.normalization.gate_specs,
            pump_specs=context.normalization.pump_specs,
            control_assets=context.normalization.control_assets,
            control_bindings=context.normalization.control_bindings,
            manual_report=context.manual_report,
            drtc_report=context.drtc_report,
        )
    except ValueError as exc:
        raise HydraulicDispatchStateError(str(exc)) from exc
    plan.status = "frozen"
    plan.frozen_time = datetime.now(UTC)
    plan.frozen_snapshot = frozen
    plan.frozen_snapshot_hash = digest
    session.commit()
    return HydraulicPlanFreezeResponse(
        plan_id=plan.id,
        snapshot_hash=digest,
        hydraulic_model_snapshot_hash=context.report.hydraulic_model_snapshot_hash,
        control_contract_hash=control_contract_hash,
        runtime_available=context.report.runtime_available,
    )


def hydraulic_snapshot_integrity(plan: DispatchPlan) -> tuple[bool, str | None]:
    """Verify a self-hashed v3 envelope independently of the legacy v2 digest."""

    if plan.snapshot_target != "hydraulic_v3":
        return False, "plan is not a hydraulic_v3 clone"
    if not isinstance(plan.frozen_snapshot, dict) or not isinstance(
        plan.frozen_snapshot_hash,
        str,
    ):
        return False, "frozen hydraulic snapshot or digest is missing"
    frozen = plan.frozen_snapshot
    if frozen.get("schema_version") != "dayu.dispatch-plan.v3":
        return False, "frozen hydraulic snapshot schema is unsupported"
    try:
        envelope = DispatchPlanSnapshot.model_validate(frozen)
        payload = json.loads(envelope.plan_payload_json)
        hydraulic_model = Hydraulic1DModel.model_validate(payload.get("hydraulic_model_snapshot"))
        gate_specs = {
            item.structure_id: item
            for item in (
                GateHydraulicSpec.model_validate(value)
                for value in payload.get("gate_hydraulic_specs", [])
            )
        }
        pump_specs = {
            item.structure_id: item
            for item in (
                PumpHydraulicSpec.model_validate(value)
                for value in payload.get("pump_hydraulic_specs", [])
            )
        }
        manual_report = HydraulicControlCompileReport.model_validate(
            payload.get("manual_control_report")
        )
        drtc_report = DRTCCompileReport.model_validate(payload.get("drtc_compile_report"))
        manual_payload = manual_report.model_dump(mode="json", exclude={"artifact_hash"})
        drtc_payload = drtc_report.model_dump(mode="json", exclude={"artifact_hash"})
        if manual_report.artifact_hash != snapshot_hash(manual_payload):
            raise ValueError("manual control report artifact hash mismatch")
        if drtc_report.artifact_hash != snapshot_hash(drtc_payload):
            raise ValueError("D-RTC compile report artifact hash mismatch")
        controlled_assets = payload.get("assets")
        if not isinstance(controlled_assets, list):
            raise ValueError("frozen hydraulic asset list is missing")
        for asset in controlled_assets:
            if not isinstance(asset, dict):
                raise ValueError("frozen hydraulic asset must be an object")
            control_asset = HydraulicControlAsset(
                structure_type=asset.get("structure_type"),
                structure_id=asset.get("legacy_asset_id"),
                constraints=asset.get("constraints"),
                provenance=asset.get("constraint_provenance"),
            )
            structure = asset.get("hydraulic_structure")
            native_id = structure.get("structure_code") if isinstance(structure, dict) else None
            capability = asset.get("capability")
            if (
                asset.get("initial_state_authority") != "initial_actuator_state"
                or not isinstance(capability, dict)
                or capability.get("engine") != DFLOW_FM_ENGINE_ID
            ):
                raise ValueError("frozen actuator authority or D-Flow capability is invalid")
            if control_asset.structure_type == "gate":
                spec = gate_specs.get(str(native_id))
                maximum = control_asset.constraints["maximum_opening_m"]
                if (
                    spec is None
                    or spec.maximum_opening_m.value is None
                    or not isclose(
                        float(maximum),
                        float(spec.maximum_opening_m.value),
                        rel_tol=0.0,
                        abs_tol=1.0e-12,
                    )
                ):
                    raise ValueError("Gate control and hydraulic limits drifted")
            else:
                spec = pump_specs.get(str(native_id))
                capacity = control_asset.constraints["design_flow_capacity_m3s"]
                expected_availability = (
                    "online" if spec is not None and spec.availability.value is True else "offline"
                )
                if (
                    spec is None
                    or spec.aggregate_capacity_m3s.value is None
                    or int(control_asset.constraints["unit_count"]) != spec.unit_count
                    or control_asset.constraints["availability"] != expected_availability
                    or not isclose(
                        float(capacity),
                        float(spec.aggregate_capacity_m3s.value),
                        rel_tol=0.0,
                        abs_tol=1.0e-12,
                    )
                ):
                    raise ValueError("Pump control and hydraulic limits drifted")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return False, f"frozen hydraulic snapshot contract is invalid: {exc}"
    if (
        payload.get("engine_id") != DFLOW_FM_ENGINE_ID
        or payload.get("engine_version") != DFLOW_FM_ENGINE_VERSION
        or payload.get("evidence_class") != "SYNTHETIC_NUMERICAL_ONLY"
        or payload.get("real_engineering_validation") is not False
        or payload.get("real_equipment_command") is not False
        or payload.get("plc_scada_connected") is not False
        or payload.get("hydraulic_model_snapshot_hash") != envelope.hydraulic_model_snapshot_hash
        or payload.get("engine_registry_hash") != envelope.engine_registry_hash
        or payload.get("control_compiler_version") != envelope.control_compiler_version
    ):
        return False, "frozen hydraulic snapshot evidence or engine identity drifted"
    envelope_initial_state = [
        item.model_dump(mode="json") for item in envelope.initial_actuator_state
    ]
    envelope_observations = envelope.control_observation_contract.model_dump(mode="json")
    envelope_provenance = [
        item.model_dump(mode="json") for item in envelope.runtime_provenance_requirements
    ]
    if (
        payload.get("initial_actuator_state") != envelope_initial_state
        or payload.get("control_observation_contract") != envelope_observations
        or payload.get("runtime_provenance_requirements") != envelope_provenance
        or payload.get("control_runtime") != envelope.control_runtime
        or payload.get("hydraulic_feedback") is not envelope.hydraulic_feedback
    ):
        return False, "frozen hydraulic snapshot envelope and payload drifted"
    if (
        envelope.engine_registry_hash != selected_engine_hash(DFLOW_FM_ENGINE_ID)
        or envelope.control_compiler_version != CONTROL_COMPILER_BUNDLE_VERSION
    ):
        return False, "frozen hydraulic snapshot registry or compiler is obsolete"
    control_contract = {
        "manual": payload.get("manual_control_report"),
        "drtc": payload.get("drtc_compile_report"),
        "bindings": payload.get("control_bindings"),
        "initial_actuator_state": payload.get("initial_actuator_state"),
        "observation_contract": payload.get("control_observation_contract"),
        "execution_settings": payload.get("execution_settings"),
    }
    if payload.get("control_contract_hash") != snapshot_hash(control_contract):
        return False, "frozen hydraulic control contract hash mismatch"
    observed_model_hash = snapshot_hash(hydraulic_model.model_dump(mode="json"))
    if observed_model_hash != envelope.hydraulic_model_snapshot_hash:
        return False, "frozen hydraulic model snapshot hash mismatch"
    internal = envelope.snapshot_hash
    computed = snapshot_hash(
        {key: value for key, value in frozen.items() if key != "snapshot_hash"}
    )
    if internal != computed or plan.frozen_snapshot_hash != computed:
        return False, "frozen hydraulic snapshot hash mismatch"
    return True, None


def _request_matches_frozen_snapshot(
    request: HydraulicPlanCompileRequest,
    envelope: DispatchPlanSnapshot,
) -> bool:
    """Require preview input to repeat the exact user-approved frozen contract."""

    payload = json.loads(envelope.plan_payload_json)
    observed = {
        "initial_actuator_state": [
            item.model_dump(mode="json") for item in request.initial_actuator_state
        ],
        "control_observation_contract": {
            "schema_version": "dayu.control-observation-contract.v1",
            "sampling_interval_seconds": (request.observation_sampling_interval_seconds),
            "elapsed_time_enabled": True,
            "bindings": [item.model_dump(mode="json") for item in request.observation_bindings],
        },
        "runtime_mode": request.runtime_mode,
        "timeout_seconds": request.timeout_seconds,
    }
    expected = {
        "initial_actuator_state": payload.get("initial_actuator_state"),
        "control_observation_contract": payload.get("control_observation_contract"),
        "runtime_mode": (payload.get("execution_settings") or {}).get("runtime_mode"),
        "timeout_seconds": (payload.get("execution_settings") or {}).get("timeout_seconds"),
    }
    return canonical_json(observed) == canonical_json(expected)


def start_hydraulic_preview(
    session: Session,
    plan_id: int,
    request: HydraulicPlanCompileRequest,
) -> HydraulicPreviewJobRecord:
    """Create and enqueue one immutable synthetic controlled D-Flow task."""

    plan = session.get(DispatchPlan, plan_id)
    if plan is None:
        raise HydraulicDispatchNotFoundError("dispatch plan does not exist")
    if plan.status != "frozen":
        raise HydraulicDispatchStateError(
            "hydraulic preview requires a frozen DispatchPlan v3",
            code="HYDRAULIC_V3_NOT_FROZEN",
        )
    valid, reason = hydraulic_snapshot_integrity(plan)
    if not valid:
        raise HydraulicDispatchStateError(
            reason or "frozen hydraulic snapshot is invalid",
            code="HYDRAULIC_V3_SNAPSHOT_INVALID",
        )
    assert isinstance(plan.frozen_snapshot, dict)
    envelope = DispatchPlanSnapshot.model_validate(plan.frozen_snapshot)
    if not _request_matches_frozen_snapshot(request, envelope):
        raise HydraulicDispatchStateError(
            "preview request does not match the immutable v3 execution contract",
            code="HYDRAULIC_PREVIEW_REQUEST_DRIFT",
        )
    runtime_available, detail, runtime_provenance = _runtime_readiness(
        request.runtime_mode,
        float(request.timeout_seconds),
    )
    if not runtime_available:
        raise HydraulicDispatchStateError(detail, code="DFLOW_RUNTIME_BLOCKED")
    if not controlled_runtime_accepted():
        raise HydraulicDispatchStateError(
            "controlled runtime acceptance registry is missing or drifted",
            code="DRTC_COMPILER_BLOCKED",
        )
    payload = json.loads(envelope.plan_payload_json)
    hydraulic_model = Hydraulic1DModel.model_validate(
        payload.get("hydraulic_model_snapshot")
    )
    selection = EngineSelection.from_current_registry(
        runtime_mode=request.runtime_mode
    )
    control_selection = ControlRuntimeSelection(
        runtime_version="1.6.1",
        coupling_runtime_version="2.00",
        compiler_id="dayu-drtc-fbc-artifact-writer",
        compiler_version=CONTROL_COMPILER_BUNDLE_VERSION,
    )
    controlled_run = ControlledHydraulic1DRun(
        hydraulic_model=hydraulic_model,
        hydraulic_model_snapshot_hash=envelope.hydraulic_model_snapshot_hash,
        dispatch_plan_snapshot=envelope,
        engine_selection=selection,
        control_runtime_selection=control_selection,
        execution_settings=ControlledExecutionSettings(
            timeout_seconds=float(request.timeout_seconds)
        ),
    )
    frozen_run = controlled_run.model_dump(mode="json")
    provenance = controlled_task_engine_provenance()
    task = SimulationTask(
        case_id=plan.simulation_case_id,
        dataset_version_id=plan.dataset_version_id,
        status="queued",
        progress=0,
        config={
            "runtime_mode": request.runtime_mode,
            "timeout_seconds": float(request.timeout_seconds),
            "synthetic_fixture": True,
            "production_mode": False,
        },
        task_kind="controlled_hydraulic_preview",
        evidence_class="SYNTHETIC_NUMERICAL_ONLY",
        input_schema_version=CONTROLLED_HYDRAULIC_1D_RUN_SCHEMA,
        input_snapshot=frozen_run,
        input_snapshot_hash=snapshot_hash(frozen_run),
        engine_version=DFLOW_FM_ENGINE_VERSION,
        engine_commit=DFLOW_FM_UPSTREAM_COMMIT,
        solver_build_id=DFLOW_FM_SOLVER_ID,
        build_mode="development",
        build_verified=True,
        execution_phase="queued",
        artifact_status="none",
        queued_time=datetime.now(UTC),
        delivery_attempt_count=1,
        last_delivery_time=datetime.now(UTC),
        **provenance,
    )
    session.add(task)
    session.flush()
    run = DispatchRun(
        plan_id=plan.id,
        controlled_task_id=task.id,
        status="queued",
        run_mode="hydraulic_preview",
        evidence_class="SYNTHETIC_NUMERICAL_ONLY",
        engine_id=DFLOW_FM_ENGINE_ID,
        control_runtime="d-rtc/fbc",
        compiled_artifact_hash=str(payload.get("control_contract_hash") or ""),
        runtime_provenance=runtime_provenance,
        result_contract={
            "schema_version": "dayu.controlled-hydraulic-result.v1",
            "real_engineering_validation": False,
            "real_equipment_command": False,
            "plc_scada_connected": False,
        },
    )
    session.add(run)
    session.commit()
    from app.worker.tasks import HYDRAULIC_1D_QUEUE, run_hydraulic_task

    try:
        queued = run_hydraulic_task.apply_async(
            args=[task.id], queue=HYDRAULIC_1D_QUEUE
        )
    except Exception as exc:
        task.last_infrastructure_error = "queue broker unavailable; recovery pending"
        session.commit()
        raise HydraulicDispatchStateError(
            "controlled hydraulic task was persisted but queue delivery failed",
            code="HYDRAULIC_PREVIEW_QUEUE_UNAVAILABLE",
        ) from exc
    task.queue_job_id = str(queued.id)
    run.queue_job_id = str(queued.id)
    session.commit()
    return HydraulicPreviewJobRecord(
        job_id=task.id,
        run_id=run.id,
        status="QUEUED",
    )


def persist_controlled_result(
    session: Session,
    task: SimulationTask,
    result: ControlledHydraulicResult,
) -> None:
    """Persist H/Q, Gate state, events and evidence for one attempt atomically."""

    if task.task_kind != "controlled_hydraulic_preview":
        raise ValueError("controlled result cannot be stored on a standard task")
    if not isinstance(task.input_snapshot, dict):
        raise ValueError("controlled task snapshot is missing")
    frozen_run = ControlledHydraulic1DRun.model_validate(task.input_snapshot)
    if result.run_snapshot_hash != frozen_run.snapshot_hash:
        raise ValueError("controlled result does not match its frozen run")
    run = session.scalar(
        select(DispatchRun).where(DispatchRun.controlled_task_id == task.id)
    )
    if run is None:
        raise ValueError("controlled task has no DispatchRun owner")
    sections = {
        str(item.id): item
        for item in session.scalars(
            select(HydraulicCrossSection).where(
                HydraulicCrossSection.dataset_version_id == task.dataset_version_id
            )
        ).all()
    }
    session.execute(
        delete(HydraulicTaskSectionResult).where(
            HydraulicTaskSectionResult.task_id == task.id
        )
    )
    session.execute(delete(StructureResult).where(StructureResult.task_id == task.id))
    session.execute(delete(DispatchEvent).where(DispatchEvent.run_id == run.id))
    for record in result.hydraulic_result.records:
        section = sections.get(record.cross_section_id)
        if section is None or str(section.branch_id) != record.branch_id:
            raise ValueError("controlled result Section is absent from the Dataset Version")
        if isinstance(record.timestamp, datetime):
            raise ValueError("controlled D-Flow result must use simulation seconds")
        session.add(
            HydraulicTaskSectionResult(
                task_id=task.id,
                dataset_version_id=task.dataset_version_id,
                hydraulic_cross_section_id=section.id,
                section_code=section.section_code,
                branch_id=section.branch_id,
                chainage_m=float(record.chainage_m),
                time_seconds=float(record.timestamp),
                water_level_m=float(record.water_level_m),
                depth_m=float(record.depth_m),
                flow_m3s=float(record.discharge_m3s),
                velocity_m_s=float(record.velocity_m_s),
                flow_area_m2=float(record.flow_area_m2),
                wet_area_m2=record.wet_area_m2,
                hydraulic_radius_m=record.hydraulic_radius_m,
                top_width_m=record.top_width_m,
                froude_number=record.froude_number,
                control_volume_m3=None,
            )
        )
    for item in result.structure_results:
        if item.discharge_m3s is None:
            continue
        session.add(
            StructureResult(
                task_id=task.id,
                dispatch_run_id=run.id,
                time_seconds=float(item.time_seconds),
                structure_type=item.structure_type,
                structure_id=item.asset_id,
                requested_value=item.requested_value,
                actual_value=item.applied_value,
                flow=float(item.discharge_m3s),
                upstream_level=item.upstream_water_level_m,
                downstream_level=item.downstream_water_level_m,
                head_difference=(
                    float(item.upstream_water_level_m - item.downstream_water_level_m)
                    if item.upstream_water_level_m is not None
                    and item.downstream_water_level_m is not None
                    else None
                ),
                transfer_type="internal_transfer",
                constraint_flags=[],
            )
        )
    traces = {item.time_seconds: item for item in result.dispatch_trace}
    for item in result.control_events:
        trace = traces.get(item.time_seconds)
        session.add(
            DispatchEvent(
                run_id=run.id,
                time_seconds=float(item.time_seconds),
                source_type=(trace.source_type if trace else "safety"),
                source_id=(trace.source_id if trace else None),
                structure_type=str(item.structure_type),
                structure_id=int(item.asset_id),
                requested_command=(
                    {
                        "command_type": trace.command_type,
                        "requested_value": trace.requested_value,
                        "resolved_value": trace.resolved_value,
                    }
                    if trace
                    else {}
                ),
                applied_command=(
                    {"applied_value": trace.applied_value, "unit": trace.unit}
                    if trace
                    else None
                ),
                outcome=item.outcome,
                reason=item.reason_code,
            )
        )
    task.status = "success"
    task.progress = 100
    task.execution_phase = "complete"
    task.error_message = None
    task.end_time = datetime.now(UTC)
    task.heartbeat_time = task.end_time
    task.result_path = f"database://controlled-hydraulic-result/{task.id}"
    task.diagnostics = {
        **result.hydraulic_result.diagnostics,
        "controlled_result_hash": result.result_hash,
        "dispatch_trace_count": len(result.dispatch_trace),
        "structure_result_count": len(result.structure_results),
        "evidence_class": result.evidence_class,
        "real_engineering_validation": False,
        "real_equipment_command": False,
        "plc_scada_connected": False,
    }
    run.status = "success"
    run.progress = 100
    run.end_time = task.end_time
    run.runtime_provenance = {
        "components": [item.model_dump(mode="json") for item in result.runtime_provenance]
    }
    run.result_contract = {
        "schema_version": result.schema_version,
        "result_hash": result.result_hash,
        "hydraulic_record_count": len(result.hydraulic_result.records),
        "structure_result_count": len(result.structure_results),
        "control_event_count": len(result.control_events),
        "evidence_class": result.evidence_class,
        "real_engineering_validation": False,
        "real_equipment_command": False,
        "plc_scada_connected": False,
    }
    session.commit()


__all__ = [
    "HydraulicDispatchNotFoundError",
    "HydraulicDispatchStateError",
    "compile_hydraulic_plan",
    "freeze_hydraulic_plan",
    "hydraulic_snapshot_integrity",
    "persist_controlled_result",
    "start_hydraulic_preview",
]
