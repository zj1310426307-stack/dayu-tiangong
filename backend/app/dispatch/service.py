"""调度计划状态、冻结、克隆、运行和比较的业务编排。"""

from __future__ import annotations

from datetime import UTC, datetime
import math
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dispatch import repository
from app.dispatch.assets import lock_plan_asset_rows
from app.dispatch.comparison import build_comparison
from app.dispatch.schemas import (
    DispatchActionCreate, DispatchActionRecord, DispatchActionUpdate,
    DispatchCapabilityFact, DispatchExecutionReadiness, DispatchReadinessIssue,
    DispatchComparison, DispatchPlanCreate, DispatchPlanRecord, DispatchPlanUpdate,
    DispatchRuleCreate, DispatchRuleRecord, DispatchRuleUpdate, DispatchRunRecord,
    DispatchSchedulePreview, DispatchSchedulePreviewRequest, ValidationReport,
)
from app.dispatch.snapshot import build_plan_snapshot
from app.dispatch.validator import validate_plan
from app.gis.models import (
    DispatchAction, DispatchEvent, DispatchPlan, DispatchRule, DispatchRun,
    JunctionResult, SimulationCase, SimulationTask, StructureResult,
)
from model.control.replay import (
    ReplayAsset,
    ReplayObservationFrame,
    SYNTHETIC_INITIAL_STATE_BASIS,
    SYNTHETIC_SCHEDULE_EVALUATOR_ID,
    SYNTHETIC_TIE_BREAK_POLICY,
    replay_schedule,
)
from model.control.rules import ThresholdRule
from model.control.schedule import ScheduledAction
from model.hydraulic_1d.capabilities import (
    CapabilityStatus,
    capabilities_for,
)
from model.hydraulic_1d.factory import create_hydraulic_1d_engine
from model.hydraulic_1d.registry import (
    DEFAULT_HYDRAULIC_1D_ENGINE_ID,
    DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
    MASCARET_ADAPTER_ID,
)
from model.provenance import snapshot_hash


class DispatchNotFoundError(LookupError):
    """请求的计划、动作、规则或运行不存在。"""


class DispatchStateError(RuntimeError):
    """操作与计划/运行状态不兼容。"""


class DispatchQueueError(RuntimeError):
    """基准/受控任务未能完整投递到计算队列。"""


def _locked_plan(session: Session, plan_id: int) -> DispatchPlan:
    """Lock and refresh one plan so validation/freeze cannot race child edits."""

    plan = session.scalar(
        select(DispatchPlan)
        .where(DispatchPlan.id == plan_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if plan is None:
        raise DispatchNotFoundError("dispatch plan does not exist")
    return plan


def _plan_record(session: Session, plan: DispatchPlan) -> DispatchPlanRecord:
    """返回计划及实时动作/规则计数。"""

    action_count, rule_count = repository.counts(session, plan.id)
    record = DispatchPlanRecord.model_validate(plan)
    record.action_count = action_count
    record.rule_count = rule_count
    return record


def list_plans(
    session: Session, *, dataset_version_id: int | None, status: str | None,
    limit: int, offset: int,
) -> tuple[list[DispatchPlanRecord], int]:
    """返回筛选分页后的计划记录。"""

    items, total = repository.list_plans(
        session, dataset_version_id=dataset_version_id, status=status,
        limit=limit, offset=offset,
    )
    return [_plan_record(session, item) for item in items], total


def get_plan_record(session: Session, plan_id: int) -> DispatchPlanRecord:
    """读取计划或抛出稳定的不存在错误。"""

    plan = session.get(DispatchPlan, plan_id)
    if plan is None:
        raise DispatchNotFoundError("dispatch plan does not exist")
    return _plan_record(session, plan)


def create_plan(session: Session, payload: DispatchPlanCreate) -> DispatchPlanRecord:
    """创建草稿并阻止计算方案跨数据版本。"""

    case = session.get(SimulationCase, payload.simulation_case_id)
    if case is None or case.dataset_version_id != payload.dataset_version_id:
        raise DispatchStateError("simulation case must belong to the selected dataset version")
    plan = DispatchPlan(**payload.model_dump())
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return _plan_record(session, plan)


def update_plan(
    session: Session, plan_id: int, payload: DispatchPlanUpdate
) -> DispatchPlanRecord:
    """仅 draft/validated 可修改；frozen 只能克隆，archived 不可恢复。"""

    plan = _locked_plan(session, plan_id)
    changes = payload.model_dump(exclude_unset=True)
    # Archiving is the sole legal in-place transition for a frozen plan.  It
    # changes lifecycle visibility, never the frozen hydraulic contract.
    if plan.status == "frozen" and changes == {"status": "archived"}:
        plan.status = "archived"
        session.commit()
        session.refresh(plan)
        return _plan_record(session, plan)
    if plan.status in {"frozen", "archived"}:
        raise DispatchStateError("frozen or archived plan is immutable")
    for key, value in changes.items():
        setattr(plan, key, value)
    if payload.status != "archived":
        plan.status = "draft"
    session.commit()
    session.refresh(plan)
    return _plan_record(session, plan)


def delete_plan(session: Session, plan_id: int) -> None:
    """只有没有运行记录的未冻结计划可以删除。"""

    plan = _locked_plan(session, plan_id)
    if plan.status in {"frozen", "archived"}:
        raise DispatchStateError("frozen or archived plan cannot be deleted")
    run_count = session.scalar(select(func.count(DispatchRun.id)).where(DispatchRun.plan_id == plan_id)) or 0
    if run_count:
        raise DispatchStateError("plan with runs cannot be deleted")
    session.delete(plan)
    session.commit()


def validate_and_mark(session: Session, plan_id: int) -> ValidationReport:
    """执行校验；通过后把 draft 变为 validated。"""

    plan = _locked_plan(session, plan_id)
    if plan.status in {"frozen", "archived"}:
        raise DispatchStateError("frozen or archived plan cannot be revalidated")
    report = validate_plan(session, plan)
    plan.status = "validated" if report.valid else "draft"
    session.commit()
    return report


def freeze_plan(session: Session, plan_id: int) -> DispatchPlanRecord:
    """校验后冻结计划快照和哈希，冻结实体不可原地修改。"""

    plan = _locked_plan(session, plan_id)
    if plan.status != "validated":
        raise DispatchStateError("only a validated plan can be frozen")
    # Child mutations serialize on the plan row.  Asset services use their own
    # rows, so lock all referenced legacy/unified assets before the validation
    # and snapshot reads to remove that cross-domain TOCTOU window.
    lock_plan_asset_rows(session, plan)
    report = validate_plan(session, plan)
    if not report.valid:
        raise DispatchStateError("plan validation failed")
    try:
        snapshot, digest = build_plan_snapshot(session, plan)
    except ValueError as exc:
        raise DispatchStateError(str(exc)) from exc
    plan.status = "frozen"
    plan.frozen_time = datetime.now(UTC)
    plan.frozen_snapshot = snapshot
    plan.frozen_snapshot_hash = digest
    session.commit()
    session.refresh(plan)
    return _plan_record(session, plan)


def clone_plan(session: Session, plan_id: int) -> DispatchPlanRecord:
    """复制计划及动作规则为递增版本的可编辑草稿。"""

    source_name = session.scalar(
        select(DispatchPlan.name).where(DispatchPlan.id == plan_id)
    )
    if source_name is None:
        raise DispatchNotFoundError("dispatch plan does not exist")
    # Every clone of the same logical plan locks the complete version set in
    # one stable order.  Do not first lock an arbitrary source version, which
    # can deadlock two clones that start from different versions.
    locked_versions = list(
        session.scalars(
            select(DispatchPlan)
            .where(DispatchPlan.name == source_name)
            .order_by(DispatchPlan.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    source = next((item for item in locked_versions if item.id == plan_id), None)
    if source is None:
        raise DispatchNotFoundError("dispatch plan does not exist")
    # READ COMMITTED takes one snapshot per statement.  A concurrent clone can
    # have inserted a new version while this FOR UPDATE statement waited on an
    # older row, so allocate from a fresh statement snapshot after the stable
    # row lock set has been acquired.
    maximum = session.scalar(
        select(func.max(DispatchPlan.version)).where(
            DispatchPlan.name == source_name
        )
    )
    if maximum is None:  # pragma: no cover - protected by the locked source
        raise DispatchNotFoundError("dispatch plan does not exist")
    clone = DispatchPlan(
        dataset_version_id=source.dataset_version_id,
        simulation_case_id=source.simulation_case_id,
        name=source.name,
        version=int(maximum) + 1,
        status="draft",
        description=source.description,
        duration_seconds=source.duration_seconds,
        evaluation_config=source.evaluation_config,
        storage_level=source.storage_level,
        created_by=source.created_by,
    )
    session.add(clone)
    session.flush()
    for action in session.scalars(select(DispatchAction).where(DispatchAction.plan_id == source.id)).all():
        values = repository.dump(action)
        values.pop("id")
        values["plan_id"] = clone.id
        session.add(DispatchAction(**values))
    for rule in session.scalars(select(DispatchRule).where(DispatchRule.plan_id == source.id)).all():
        values = repository.dump(rule)
        values.pop("id")
        values["plan_id"] = clone.id
        session.add(DispatchRule(**values))
    session.commit()
    session.refresh(clone)
    return _plan_record(session, clone)


def _editable_plan(session: Session, plan_id: int) -> DispatchPlan:
    """读取可编辑计划；冻结/归档状态统一拒绝动作规则变更。"""

    plan = _locked_plan(session, plan_id)
    if plan.status in {"frozen", "archived"}:
        raise DispatchStateError("frozen or archived plan is immutable")
    return plan


def _locked_editable_action(
    session: Session, action_id: int
) -> tuple[DispatchPlan, DispatchAction]:
    """Lock plan first, then refresh/lock its action to avoid stale PATCH state."""

    plan_id = session.scalar(
        select(DispatchAction.plan_id).where(DispatchAction.id == action_id)
    )
    if plan_id is None:
        raise DispatchNotFoundError("dispatch action does not exist")
    plan = _editable_plan(session, int(plan_id))
    action = session.scalar(
        select(DispatchAction)
        .where(DispatchAction.id == action_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if action is None:
        raise DispatchNotFoundError("dispatch action does not exist")
    return plan, action


def _locked_editable_rule(
    session: Session, rule_id: int
) -> tuple[DispatchPlan, DispatchRule]:
    """Lock plan first, then refresh/lock its rule to avoid stale PATCH state."""

    plan_id = session.scalar(
        select(DispatchRule.plan_id).where(DispatchRule.id == rule_id)
    )
    if plan_id is None:
        raise DispatchNotFoundError("dispatch rule does not exist")
    plan = _editable_plan(session, int(plan_id))
    rule = session.scalar(
        select(DispatchRule)
        .where(DispatchRule.id == rule_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if rule is None:
        raise DispatchNotFoundError("dispatch rule does not exist")
    return plan, rule


def list_actions(session: Session, plan_id: int) -> list[DispatchActionRecord]:
    """按时间和序号返回人工计划动作。"""

    if session.get(DispatchPlan, plan_id) is None:
        raise DispatchNotFoundError("dispatch plan does not exist")
    return [
        DispatchActionRecord(**repository.dump(item))
        for item in session.scalars(
            select(DispatchAction).where(DispatchAction.plan_id == plan_id)
            .order_by(DispatchAction.time_seconds, DispatchAction.sequence)
        ).all()
    ]


def create_action(
    session: Session, plan_id: int, payload: DispatchActionCreate
) -> DispatchActionRecord:
    """向可编辑计划增加动作并限制动作时刻。"""

    plan = _editable_plan(session, plan_id)
    if payload.time_seconds > plan.duration_seconds:
        raise DispatchStateError("action time exceeds plan duration")
    asset_column = (
        DispatchAction.gate_id if payload.structure_type == "gate"
        else DispatchAction.pump_id
    )
    asset_id = payload.gate_id if payload.structure_type == "gate" else payload.pump_id
    conflict = session.scalar(
        select(DispatchAction.id).where(
            DispatchAction.plan_id == plan_id,
            DispatchAction.time_seconds == payload.time_seconds,
            asset_column == asset_id,
        )
    )
    if conflict is not None:
        raise DispatchStateError(
            "duplicate action for the same physical actuator and time is not allowed"
        )
    action = DispatchAction(plan_id=plan_id, **payload.model_dump())
    session.add(action)
    plan.status = "draft"
    session.commit()
    session.refresh(action)
    return DispatchActionRecord(**repository.dump(action))


def update_action(
    session: Session, action_id: int, payload: DispatchActionUpdate
) -> DispatchActionRecord:
    """局部更新动作且不允许改变设施身份。"""

    plan, action = _locked_editable_action(session, action_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(action, key, value)
    from model.control.constraints import (
        command_matches_structure,
        validate_command_value,
        validate_interpolation,
    )
    if not command_matches_structure(action.structure_type, action.command_type):
        session.rollback()
        raise DispatchStateError("command type does not match structure type")
    value_valid, reason = validate_command_value(action.command_type, action.target_value)
    if not value_valid:
        session.rollback()
        raise DispatchStateError(reason or "invalid action target value")
    interpolation_valid, reason = validate_interpolation(
        action.command_type, action.interpolation
    )
    if not interpolation_valid:
        session.rollback()
        raise DispatchStateError(reason or "invalid action interpolation")
    if action.time_seconds > plan.duration_seconds:
        session.rollback()
        raise DispatchStateError("action time exceeds plan duration")
    asset_column = (
        DispatchAction.gate_id if action.structure_type == "gate"
        else DispatchAction.pump_id
    )
    asset_id = action.gate_id if action.structure_type == "gate" else action.pump_id
    # The ORM row already carries the candidate PATCH values.  Suppress
    # autoflush so the partial unique index cannot turn this deliberate domain
    # check into an IntegrityError before we return the stable conflict reason.
    with session.no_autoflush:
        conflict = session.scalar(
            select(DispatchAction.id).where(
                DispatchAction.plan_id == action.plan_id,
                DispatchAction.id != action.id,
                DispatchAction.time_seconds == action.time_seconds,
                asset_column == asset_id,
            )
        )
    if conflict is not None:
        session.rollback()
        raise DispatchStateError(
            "duplicate action for the same physical actuator and time is not allowed"
        )
    plan.status = "draft"
    session.commit()
    session.refresh(action)
    return DispatchActionRecord(**repository.dump(action))


def delete_action(session: Session, action_id: int) -> None:
    """从可编辑计划删除动作。"""

    plan, action = _locked_editable_action(session, action_id)
    session.delete(action)
    plan.status = "draft"
    session.commit()


def list_rules(session: Session, plan_id: int) -> list[DispatchRuleRecord]:
    """按优先级返回阈值规则。"""

    if session.get(DispatchPlan, plan_id) is None:
        raise DispatchNotFoundError("dispatch plan does not exist")
    return [
        DispatchRuleRecord(**repository.dump(item))
        for item in session.scalars(
            select(DispatchRule).where(DispatchRule.plan_id == plan_id)
            .order_by(DispatchRule.priority.desc(), DispatchRule.id)
        ).all()
    ]


def create_rule(
    session: Session, plan_id: int, payload: DispatchRuleCreate
) -> DispatchRuleRecord:
    """向可编辑计划增加白名单规则。"""

    plan = _editable_plan(session, plan_id)
    rule = DispatchRule(plan_id=plan_id, **payload.model_dump())
    session.add(rule)
    plan.status = "draft"
    session.commit()
    session.refresh(rule)
    return DispatchRuleRecord(**repository.dump(rule))


def update_rule(
    session: Session, rule_id: int, payload: DispatchRuleUpdate
) -> DispatchRuleRecord:
    """局部更新规则且保持白名单类型和操作符不可篡改。"""

    plan, rule = _locked_editable_rule(session, rule_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, key, value)
    plan.status = "draft"
    session.commit()
    session.refresh(rule)
    return DispatchRuleRecord(**repository.dump(rule))


def delete_rule(session: Session, rule_id: int) -> None:
    """从可编辑计划删除规则。"""

    plan, rule = _locked_editable_rule(session, rule_id)
    session.delete(rule)
    plan.status = "draft"
    session.commit()


def create_run(session: Session, plan_id: int) -> DispatchRunRecord:
    """Fail closed until dispatch semantics have a verified MASCARET mapping."""

    plan = session.get(DispatchPlan, plan_id)
    if plan is None:
        raise DispatchNotFoundError("dispatch plan does not exist")
    raise DispatchStateError(
        "UNSUPPORTED_BY_MASCARET_ADAPTER: dispatch runs are disabled until "
        "Gate schedules and Pump controls have a verified external-engine mapping"
    )


def _snapshot_integrity(plan: DispatchPlan) -> tuple[bool, str | None]:
    """Verify that one frozen plan still matches its exact canonical snapshot."""

    if plan.frozen_snapshot is None or plan.frozen_snapshot_hash is None:
        return False, "frozen dispatch snapshot is missing"
    if plan.frozen_snapshot.get("schema_version") != "dayu.dispatch-plan.v2":
        return False, "legacy dispatch snapshot must be cloned and frozen as v2"
    expected_evaluator = {
        "version": SYNTHETIC_SCHEDULE_EVALUATOR_ID,
        "tie_break_policy": SYNTHETIC_TIE_BREAK_POLICY,
        "hydraulic_feedback": False,
        "initial_state_basis": SYNTHETIC_INITIAL_STATE_BASIS,
    }
    if plan.frozen_snapshot.get("control_evaluator") != expected_evaluator:
        return False, "frozen dispatch snapshot uses an unsupported evaluator contract"
    if snapshot_hash(plan.frozen_snapshot) != plan.frozen_snapshot_hash:
        return False, "frozen dispatch snapshot hash mismatch"
    return True, None


def execution_readiness(
    session: Session, plan_id: int
) -> DispatchExecutionReadiness:
    """Report plan, capability, runtime, and immutable-snapshot readiness separately."""

    plan = session.get(DispatchPlan, plan_id)
    if plan is None:
        raise DispatchNotFoundError("dispatch plan does not exist")
    report = validate_plan(session, plan)
    snapshot_valid, snapshot_reason = _snapshot_integrity(plan)
    required_features: set[str] = set()
    if snapshot_valid and plan.frozen_snapshot is not None:
        required_features.update(
            str(item.get("structure_type", "")).upper()
            for item in plan.frozen_snapshot.get("assets", [])
        )
    else:
        actions = session.scalars(
            select(DispatchAction).where(DispatchAction.plan_id == plan.id)
        ).all()
        rules = session.scalars(
            select(DispatchRule).where(DispatchRule.plan_id == plan.id)
        ).all()
        required_features.update(item.structure_type.upper() for item in actions)
        required_features.update(
            str(item.action_template.get("structure_type", "")).upper()
            for item in rules
            if isinstance(item.action_template, dict)
        )
    required_features.discard("")
    matrix = {
        item.feature: item
        for item in capabilities_for(
            DEFAULT_HYDRAULIC_1D_ENGINE_ID,
            DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
        )
    }
    capability_facts = [
        DispatchCapabilityFact.model_validate(matrix[feature].to_dict())
        for feature in sorted(required_features)
        if feature in matrix
    ]
    blockers: list[DispatchReadinessIssue] = []
    warnings: list[DispatchReadinessIssue] = [
        DispatchReadinessIssue(
            code="SYNTHETIC_PREVIEW_ONLY",
            message="静态预演没有水力反馈，不构成工程验证或设备下发依据",
        )
    ]
    if plan.status != "frozen":
        blockers.append(
            DispatchReadinessIssue(
                code="PLAN_NOT_FROZEN", message="只有冻结计划具有不可变执行合同"
            )
        )
    if not report.valid:
        blockers.extend(
            DispatchReadinessIssue(code="PLAN_VALIDATION_FAILED", message=message)
            for message in report.errors
        )
    warnings.extend(
        DispatchReadinessIssue(code="PLAN_VALIDATION_WARNING", message=message)
        for message in report.warnings
    )
    if not snapshot_valid:
        blockers.append(
            DispatchReadinessIssue(
                code="FROZEN_SNAPSHOT_INVALID",
                message=snapshot_reason or "frozen dispatch snapshot is invalid",
            )
        )
    compatible_statuses = {
        CapabilityStatus.VERIFIED_NATIVE,
        CapabilityStatus.VERIFIED_EQUIVALENT,
    }
    for feature in sorted(required_features):
        capability = matrix.get(feature)
        if capability is None:
            blockers.append(
                DispatchReadinessIssue(
                    code="CAPABILITY_ABSENT",
                    message="该能力不在版本化 Solver Capability Registry 中",
                    feature=feature,
                    status=CapabilityStatus.UNSUPPORTED.value,
                )
            )
        elif capability.status not in compatible_statuses:
            blockers.append(
                DispatchReadinessIssue(
                    code="CAPABILITY_NOT_VERIFIED",
                    message=capability.reason,
                    feature=feature,
                    status=capability.status.value,
                )
            )
    try:
        runtime_available, runtime_detail = create_hydraulic_1d_engine().availability()
    except Exception as exc:  # pragma: no cover - defensive environment boundary
        runtime_available = False
        runtime_detail = f"runtime availability check failed: {exc}"
    if not runtime_available:
        blockers.append(
            DispatchReadinessIssue(
                code="RUNTIME_UNAVAILABLE", message=runtime_detail
            )
        )
    blockers.append(
        DispatchReadinessIssue(
            code="HYDRAULIC_DISPATCH_RUNTIME_DISABLED",
            message=(
                "Gate/Pump 水力调度运行保持 fail closed；本阶段只开放合成静态预演"
            ),
        )
    )
    return DispatchExecutionReadiness(
        plan_id=plan.id,
        plan_status=plan.status,
        planning_valid=report.valid,
        frozen_snapshot_valid=snapshot_valid,
        static_preview_allowed=plan.status == "frozen" and snapshot_valid,
        hydraulic_runtime_supported=False,
        run_allowed=False,
        evidence_class="SYNTHETIC_DEVELOPMENT_ONLY",
        real_validation_status="SKIPPED_BY_USER",
        engine=DEFAULT_HYDRAULIC_1D_ENGINE_ID,
        engine_version=DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
        adapter_version=MASCARET_ADAPTER_ID,
        runtime_available=runtime_available,
        runtime_detail=runtime_detail,
        required_features=sorted(required_features),
        capabilities=capability_facts,
        blockers=blockers,
        warnings=warnings,
        frozen_snapshot_hash=plan.frozen_snapshot_hash,
    )


def preview_schedule(
    session: Session,
    plan_id: int,
    payload: DispatchSchedulePreviewRequest,
) -> DispatchSchedulePreview:
    """Replay one v2 frozen plan without creating tasks, runs, or hydraulic results."""

    plan = session.get(DispatchPlan, plan_id)
    if plan is None:
        raise DispatchNotFoundError("dispatch plan does not exist")
    if plan.status != "frozen":
        raise DispatchStateError("only a frozen dispatch plan can be replayed")
    snapshot_valid, snapshot_reason = _snapshot_integrity(plan)
    if not snapshot_valid or plan.frozen_snapshot is None or plan.frozen_snapshot_hash is None:
        raise DispatchStateError(snapshot_reason or "frozen dispatch snapshot is invalid")
    frozen = plan.frozen_snapshot
    duration_seconds = float(frozen["plan"]["duration_seconds"])
    observation_times = [item.time_seconds for item in payload.observations]
    if not math.isclose(
        observation_times[-1], duration_seconds, rel_tol=0.0, abs_tol=1.0e-9
    ):
        raise DispatchStateError(
            "synthetic observation replay must end at the frozen plan duration"
        )
    missing_action_times = [
        float(item["time_seconds"])
        for item in frozen.get("actions", [])
        if not any(
            math.isclose(
                float(item["time_seconds"]), value, rel_tol=0.0, abs_tol=1.0e-9
            )
            for value in observation_times
        )
    ]
    if missing_action_times:
        raise DispatchStateError(
            "synthetic replay must include every manual action time: "
            + ", ".join(str(value) for value in sorted(set(missing_action_times)))
        )
    required_observations = {
        (str(item["observation_type"]), int(item["observation_object_id"]))
        for item in frozen.get("rules", [])
        if item.get("enabled", True)
        and item.get("observation_type") != "elapsed_time"
    }
    replay_frames: list[ReplayObservationFrame] = []
    for frame in payload.observations:
        values = {
            (item.observation_type, item.observation_object_id): float(item.value)
            for item in frame.values
        }
        missing = sorted(required_observations - set(values))
        if missing:
            raise DispatchStateError(
                f"synthetic observation frame {frame.time_seconds} is missing {missing}"
            )
        replay_frames.append(
            ReplayObservationFrame(
                time_seconds=float(frame.time_seconds), values=values
            )
        )
    actions = tuple(
        ScheduledAction(
            id=int(item["id"]),
            time_seconds=float(item["time_seconds"]),
            structure_type=str(item["structure_type"]),
            structure_id=int(
                item["gate_id"]
                if item["structure_type"] == "gate"
                else item["pump_id"]
            ),
            command_type=str(item["command_type"]),
            target_value=float(item["target_value"]),
            interpolation=str(item["interpolation"]),
            priority=int(item["priority"]),
        )
        for item in frozen.get("actions", [])
    )
    rules = tuple(
        ThresholdRule(
            id=int(item["id"]),
            name=str(item["name"]),
            enabled=bool(item["enabled"]),
            observation_type=str(item["observation_type"]),
            observation_object_id=(
                int(item["observation_object_id"])
                if item.get("observation_object_id") is not None
                else None
            ),
            operator=str(item["operator"]),
            threshold=float(item["threshold"]),
            hysteresis=float(item["hysteresis"]),
            minimum_hold_seconds=float(item["minimum_hold_seconds"]),
            cooldown_seconds=float(item["cooldown_seconds"]),
            action_template=dict(item["action_template"]),
            priority=int(item["priority"]),
        )
        for item in frozen.get("rules", [])
    )
    assets = tuple(
        ReplayAsset(
            structure_type=str(item["structure_type"]),
            structure_id=int(item["legacy_asset_id"]),
            constraints=dict(item["constraints"]),
        )
        for item in frozen.get("assets", [])
    )
    replay = replay_schedule(
        actions=actions,
        rules=rules,
        assets=assets,
        observations=tuple(replay_frames),
    )
    observation_hash = snapshot_hash(payload.model_dump(mode="json"))
    response_payload: dict[str, Any] = {
        "plan_id": plan.id,
        "evidence_class": "SYNTHETIC_DEVELOPMENT_ONLY",
        "hydraulic_execution_supported": False,
        "no_hydraulic_feedback": True,
        "plan_snapshot_hash": plan.frozen_snapshot_hash,
        "observation_hash": observation_hash,
        **replay,
        "safety_notice": (
            "STATIC_DRY_RUN / SYNTHETIC / NO_HYDRAULIC_FEEDBACK / "
            "NO_REAL_EQUIPMENT_COMMAND"
        ),
    }
    response_payload["result_hash"] = snapshot_hash(response_payload)
    return DispatchSchedulePreview.model_validate(response_payload)


def _refresh_run(session: Session, run: DispatchRun) -> DispatchRun:
    """从两个权威任务状态派生调度运行状态和进度。"""

    baseline = session.get(SimulationTask, run.baseline_task_id)
    controlled = session.get(SimulationTask, run.controlled_task_id)
    tasks = [item for item in (baseline, controlled) if item is not None]
    if not tasks:
        return run
    run.progress = int(sum(item.progress for item in tasks) / len(tasks))
    statuses = {item.status for item in tasks}
    if statuses == {"success"}:
        run.status = "success"
        run.progress = 100
        run.end_time = run.end_time or datetime.now(UTC)
        comparison = build_comparison(
            session, run, session.get(DispatchPlan, run.plan_id).evaluation_config
        )
        run.metrics = comparison["metrics"]
    elif "failed" in statuses:
        run.status = "failed"
        run.error_message = "; ".join(item.error_message or "task failed" for item in tasks if item.status == "failed")
    elif statuses <= {"cancelled", "cancel_requested"}:
        run.status = "cancelled" if statuses == {"cancelled"} else "cancel_requested"
    elif "running" in statuses:
        run.status = "running"
    else:
        run.status = "queued"
    session.commit()
    return run


def list_runs(
    session: Session, *, dataset_version_id: int | None, plan_id: int | None,
    status: str | None,
    limit: int, offset: int,
) -> tuple[list[DispatchRunRecord], int]:
    """返回按 Dataset Version 筛选的分页运行并同步派生状态。"""

    items, total = repository.list_runs(
        session, dataset_version_id=dataset_version_id, plan_id=plan_id,
        status=status, limit=limit, offset=offset,
    )
    return [DispatchRunRecord.model_validate(_refresh_run(session, item)) for item in items], total


def get_run(session: Session, run_id: int) -> DispatchRunRecord:
    """读取并刷新一次调度运行。"""

    run = session.get(DispatchRun, run_id)
    if run is None:
        raise DispatchNotFoundError("dispatch run does not exist")
    return DispatchRunRecord.model_validate(_refresh_run(session, run))


def comparison(session: Session, run_id: int) -> DispatchComparison:
    """返回已完成运行的基准/受控曲线差值和指标。"""

    run = session.get(DispatchRun, run_id)
    if run is None:
        raise DispatchNotFoundError("dispatch run does not exist")
    run = _refresh_run(session, run)
    plan = session.get(DispatchPlan, run.plan_id)
    data = build_comparison(session, run, plan.evaluation_config)
    return DispatchComparison(
        run_id=run.id, status=run.status,
        baseline_task_id=run.baseline_task_id, controlled_task_id=run.controlled_task_id,
        **data,
    )


def related_rows(session: Session, run_id: int, kind: str) -> list[dict[str, Any]]:
    """返回事件、结构物或节点结果，供调度详情与 GIS 使用。"""

    run = session.get(DispatchRun, run_id)
    if run is None:
        raise DispatchNotFoundError("dispatch run does not exist")
    if kind == "events":
        rows = session.scalars(select(DispatchEvent).where(DispatchEvent.run_id == run_id).order_by(DispatchEvent.time_seconds)).all()
    elif kind == "structures":
        rows = session.scalars(select(StructureResult).where(StructureResult.task_id == run.controlled_task_id).order_by(StructureResult.time_seconds)).all()
    elif kind == "nodes":
        rows = session.scalars(select(JunctionResult).where(JunctionResult.task_id == run.controlled_task_id).order_by(JunctionResult.time_seconds)).all()
    else:
        raise ValueError("unsupported related row kind")
    return [repository.dump(item) for item in rows]
