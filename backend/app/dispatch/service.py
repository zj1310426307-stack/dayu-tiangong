"""调度计划状态、冻结、克隆、运行和比较的业务编排。"""

from __future__ import annotations

from datetime import UTC, datetime
from os import getenv
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dispatch import repository
from app.dispatch.comparison import build_comparison
from app.dispatch.schemas import (
    DispatchActionCreate, DispatchActionRecord, DispatchActionUpdate,
    DispatchComparison, DispatchPlanCreate, DispatchPlanRecord, DispatchPlanUpdate,
    DispatchRuleCreate, DispatchRuleRecord, DispatchRuleUpdate, DispatchRunRecord,
    ValidationReport,
)
from app.dispatch.snapshot import build_plan_snapshot
from app.dispatch.validator import validate_plan
from app.gis.models import (
    DispatchAction, DispatchEvent, DispatchPlan, DispatchRule, DispatchRun,
    JunctionResult, SimulationCase, SimulationTask, StructureResult,
)
from app.model_engine.provenance import ENGINE_VERSION, freeze_task_input
from app.worker.tasks import run_hydraulic_task


class DispatchNotFoundError(LookupError):
    """请求的计划、动作、规则或运行不存在。"""


class DispatchStateError(RuntimeError):
    """操作与计划/运行状态不兼容。"""


class DispatchQueueError(RuntimeError):
    """基准/受控任务未能完整投递到计算队列。"""


def _enqueue_run_tasks(
    session: Session,
    run: DispatchRun,
    baseline: SimulationTask,
    controlled: SimulationTask,
) -> None:
    """Durably record complete, failed, or partial two-task queue delivery."""

    try:
        baseline_job = run_hydraulic_task.delay(baseline.id)
    except Exception as exc:
        now = datetime.now(UTC)
        message = "dispatch queue broker unavailable; no tasks were enqueued"
        for task in (baseline, controlled):
            task.status = "failed"
            task.progress = 100
            task.error_message = message
            task.end_time = now
        run.status = "failed"
        run.progress = 100
        run.error_message = message
        run.end_time = now
        session.commit()
        raise DispatchQueueError(message) from exc

    baseline.queue_job_id = str(baseline_job.id)
    run.queue_job_id = str(baseline_job.id)
    # The first externally visible delivery must be durable before the second
    # broker call; otherwise a partial delivery would have no audit trail.
    session.commit()

    try:
        controlled_job = run_hydraulic_task.delay(controlled.id)
    except Exception as exc:
        now = datetime.now(UTC)
        message = (
            "dispatch queue broker unavailable after baseline enqueue; "
            f"baseline_job_id={baseline_job.id}, controlled task was not enqueued"
        )
        controlled.status = "failed"
        controlled.progress = 100
        controlled.error_message = message
        controlled.end_time = now
        run.status = "failed"
        run.error_message = message
        run.end_time = now
        session.commit()
        raise DispatchQueueError(message) from exc

    controlled.queue_job_id = str(controlled_job.id)
    run.queue_job_id = f"{baseline_job.id},{controlled_job.id}"
    session.commit()


def _freeze_run_snapshots(
    session: Session,
    plan: DispatchPlan,
    config: dict[str, Any],
    engine_commit: str,
) -> tuple[dict[str, Any], str, dict[str, Any], str]:
    """Freeze independent baseline/controlled v3 inputs through one identity boundary."""

    try:
        baseline_snapshot, baseline_hash = freeze_task_input(
            session,
            plan.simulation_case_id,
            config,
            schema_version="dayu.model-input.v3",
            engine_commit=engine_commit,
        )
        controlled_snapshot, controlled_hash = freeze_task_input(
            session,
            plan.simulation_case_id,
            config,
            schema_version="dayu.model-input.v3",
            engine_commit=engine_commit,
            dispatch_plan=plan.frozen_snapshot,
        )
    except (LookupError, ValueError) as exc:
        # The public router maps DispatchStateError to a stable 409.  A dataset
        # that is not v3-ready is an actionable plan state, not an HTTP 500.
        raise DispatchStateError(f"model-input.v3 is not ready: {exc}") from exc
    return baseline_snapshot, baseline_hash, controlled_snapshot, controlled_hash


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

    plan = session.get(DispatchPlan, plan_id)
    if plan is None:
        raise DispatchNotFoundError("dispatch plan does not exist")
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

    plan = session.get(DispatchPlan, plan_id)
    if plan is None:
        raise DispatchNotFoundError("dispatch plan does not exist")
    run_count = session.scalar(select(func.count(DispatchRun.id)).where(DispatchRun.plan_id == plan_id)) or 0
    if run_count or plan.status == "frozen":
        raise DispatchStateError("plan with runs or frozen state cannot be deleted")
    session.delete(plan)
    session.commit()


def validate_and_mark(session: Session, plan_id: int) -> ValidationReport:
    """执行校验；通过后把 draft 变为 validated。"""

    plan = session.get(DispatchPlan, plan_id)
    if plan is None:
        raise DispatchNotFoundError("dispatch plan does not exist")
    if plan.status in {"frozen", "archived"}:
        raise DispatchStateError("frozen or archived plan cannot be revalidated")
    report = validate_plan(session, plan)
    plan.status = "validated" if report.valid else "draft"
    session.commit()
    return report


def freeze_plan(session: Session, plan_id: int) -> DispatchPlanRecord:
    """校验后冻结计划快照和哈希，冻结实体不可原地修改。"""

    plan = session.get(DispatchPlan, plan_id)
    if plan is None:
        raise DispatchNotFoundError("dispatch plan does not exist")
    if plan.status != "validated":
        raise DispatchStateError("only a validated plan can be frozen")
    report = validate_plan(session, plan)
    if not report.valid:
        raise DispatchStateError("plan validation failed")
    snapshot, digest = build_plan_snapshot(session, plan)
    plan.status = "frozen"
    plan.frozen_time = datetime.now(UTC)
    plan.frozen_snapshot = snapshot
    plan.frozen_snapshot_hash = digest
    session.commit()
    session.refresh(plan)
    return _plan_record(session, plan)


def clone_plan(session: Session, plan_id: int) -> DispatchPlanRecord:
    """复制计划及动作规则为递增版本的可编辑草稿。"""

    source = session.get(DispatchPlan, plan_id)
    if source is None:
        raise DispatchNotFoundError("dispatch plan does not exist")
    maximum = session.scalar(
        select(func.max(DispatchPlan.version)).where(DispatchPlan.name == source.name)
    ) or source.version
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

    plan = session.get(DispatchPlan, plan_id)
    if plan is None:
        raise DispatchNotFoundError("dispatch plan does not exist")
    if plan.status in {"frozen", "archived"}:
        raise DispatchStateError("frozen or archived plan is immutable")
    return plan


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
            DispatchAction.command_type == payload.command_type,
            asset_column == asset_id,
        )
    )
    if conflict is not None:
        raise DispatchStateError(
            "duplicate action for the same structure, command and time is not allowed"
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

    action = session.get(DispatchAction, action_id)
    if action is None:
        raise DispatchNotFoundError("dispatch action does not exist")
    plan = _editable_plan(session, action.plan_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(action, key, value)
    from model.control.constraints import command_matches_structure, validate_command_value
    if not command_matches_structure(action.structure_type, action.command_type):
        session.rollback()
        raise DispatchStateError("command type does not match structure type")
    value_valid, reason = validate_command_value(action.command_type, action.target_value)
    if not value_valid:
        session.rollback()
        raise DispatchStateError(reason or "invalid action target value")
    if action.time_seconds > plan.duration_seconds:
        raise DispatchStateError("action time exceeds plan duration")
    asset_column = (
        DispatchAction.gate_id if action.structure_type == "gate"
        else DispatchAction.pump_id
    )
    asset_id = action.gate_id if action.structure_type == "gate" else action.pump_id
    conflict = session.scalar(
        select(DispatchAction.id).where(
            DispatchAction.plan_id == action.plan_id,
            DispatchAction.id != action.id,
            DispatchAction.time_seconds == action.time_seconds,
            DispatchAction.command_type == action.command_type,
            asset_column == asset_id,
        )
    )
    if conflict is not None:
        session.rollback()
        raise DispatchStateError(
            "duplicate action for the same structure, command and time is not allowed"
        )
    plan.status = "draft"
    session.commit()
    session.refresh(action)
    return DispatchActionRecord(**repository.dump(action))


def delete_action(session: Session, action_id: int) -> None:
    """从可编辑计划删除动作。"""

    action = session.get(DispatchAction, action_id)
    if action is None:
        raise DispatchNotFoundError("dispatch action does not exist")
    plan = _editable_plan(session, action.plan_id)
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

    rule = session.get(DispatchRule, rule_id)
    if rule is None:
        raise DispatchNotFoundError("dispatch rule does not exist")
    plan = _editable_plan(session, rule.plan_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, key, value)
    plan.status = "draft"
    session.commit()
    session.refresh(rule)
    return DispatchRuleRecord(**repository.dump(rule))


def delete_rule(session: Session, rule_id: int) -> None:
    """从可编辑计划删除规则。"""

    rule = session.get(DispatchRule, rule_id)
    if rule is None:
        raise DispatchNotFoundError("dispatch rule does not exist")
    plan = _editable_plan(session, rule.plan_id)
    session.delete(rule)
    plan.status = "draft"
    session.commit()


def create_run(session: Session, plan_id: int) -> DispatchRunRecord:
    """基于冻结计划创建基准/受控冻结任务并异步投递。"""

    plan = session.get(DispatchPlan, plan_id)
    if plan is None:
        raise DispatchNotFoundError("dispatch plan does not exist")
    if plan.status != "frozen" or plan.frozen_snapshot is None:
        raise DispatchStateError("only a frozen plan can run")
    config = {
        "duration_seconds": plan.duration_seconds,
        "output_interval_seconds": 60.0,
        "storage_level": plan.storage_level,
        "allow_fallback_boundary": False,
        "section_geometry": "tabulated",
    }
    commit = getenv("ENGINE_COMMIT", "uncommitted")
    (
        baseline_snapshot,
        baseline_hash,
        controlled_snapshot,
        controlled_hash,
    ) = _freeze_run_snapshots(
        session, plan, config, commit
    )
    baseline = SimulationTask(
        case_id=plan.simulation_case_id, status="queued", progress=0, config=config,
        input_schema_version="dayu.model-input.v3", input_snapshot=baseline_snapshot,
        input_snapshot_hash=baseline_hash, engine_version=ENGINE_VERSION,
        engine_commit=commit, queued_time=datetime.now(UTC),
    )
    controlled = SimulationTask(
        case_id=plan.simulation_case_id, status="queued", progress=0, config=config,
        input_schema_version="dayu.model-input.v3", input_snapshot=controlled_snapshot,
        input_snapshot_hash=controlled_hash, engine_version=ENGINE_VERSION,
        engine_commit=commit, queued_time=datetime.now(UTC),
    )
    session.add_all((baseline, controlled))
    session.flush()
    run = DispatchRun(
        plan_id=plan.id, baseline_task_id=baseline.id, controlled_task_id=controlled.id,
        status="queued", progress=0, start_time=datetime.now(UTC),
    )
    session.add(run)
    session.commit()
    _enqueue_run_tasks(session, run, baseline, controlled)
    session.refresh(run)
    return DispatchRunRecord.model_validate(run)


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
    session: Session, *, plan_id: int | None, status: str | None,
    limit: int, offset: int,
) -> tuple[list[DispatchRunRecord], int]:
    """返回分页运行并同步派生状态。"""

    items, total = repository.list_runs(
        session, plan_id=plan_id, status=status, limit=limit, offset=offset
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
